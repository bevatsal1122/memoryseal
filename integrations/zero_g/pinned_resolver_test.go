package main

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"

	"github.com/0gfoundation/0g-pc-e2ee/client/core"
	"github.com/0gfoundation/0g-pc-e2ee/client/endpoint"
	"github.com/0gfoundation/0g-pc-e2ee/protocol/wire"
)

type fixtureResolver struct{ candidates core.Candidates }

func (f fixtureResolver) Resolve(context.Context, endpoint.Endpoint, wire.Request) (core.Candidates, error) {
	return f.candidates, nil
}

func TestMismatchedProviderIsNotSentPrompt(t *testing.T) {
	var requests atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()
	candidate := core.Provider{URL: server.URL, Address: "other", SignerAddr: "signer", Endpoint: server.URL}
	resolver := pinnedResolver{fixtureResolver{fixtureCandidates{candidate}}, "expected", "signer", server.URL, nil}
	client := core.NewWithResolver(resolver, core.WithEndpoint(endpoint.Chat))
	_, err := client.Complete(context.Background(), wire.Request{
		"model":    []byte(`"model"`),
		"messages": []byte(`[{"role":"user","content":"private marker"}]`),
	})
	if err == nil {
		t.Fatal("mismatched candidate unexpectedly succeeded")
	}
	if requests.Load() != 0 {
		t.Fatal("prompt was sent to mismatched provider")
	}
}

func TestMismatchedRecipientKeyIsNotSentPrompt(t *testing.T) {
	var requests atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
	}))
	defer server.Close()
	candidate := core.Provider{URL: server.URL, Address: "expected", SignerAddr: "signer", Endpoint: server.URL, EncPubKey: make([]byte, 32)}
	expectedKey := make([]byte, 32)
	expectedKey[0] = 1
	resolver := pinnedResolver{fixtureResolver{fixtureCandidates{candidate}}, "expected", "signer", server.URL, expectedKey}
	client := core.NewWithResolver(resolver, core.WithEndpoint(endpoint.Chat))
	_, err := client.Complete(context.Background(), wire.Request{
		"model": []byte(`"model"`), "messages": []byte(`[{"role":"user","content":"private marker"}]`),
	})
	if err == nil || requests.Load() != 0 {
		t.Fatal("mismatched encryption key was not blocked before sending")
	}
}

func TestBridgeBuilderInstallsResolverBeforeCompletion(t *testing.T) {
	var requests atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
	}))
	defer server.Close()
	candidate := core.Provider{URL: server.URL, Address: "other", SignerAddr: "signer", Endpoint: server.URL}
	wrapped := false
	client := buildClassifierClient(request{Network: "testnet"}, func(upstream core.Resolver) core.Resolver {
		if upstream == nil {
			t.Fatal("missing upstream resolver")
		}
		wrapped = true
		return pinnedResolver{fixtureResolver{fixtureCandidates{candidate}}, "expected", "signer", server.URL, nil}
	})
	if !wrapped || client == nil {
		t.Fatal("builder did not install wrapper")
	}
	_, err := client.Complete(context.Background(), wire.Request{
		"model":    []byte(`"model"`),
		"messages": []byte(`[{"role":"user","content":"private marker"}]`),
	})
	if err == nil || requests.Load() != 0 {
		t.Fatal("mismatched candidate was not blocked")
	}
}

type fixtureCandidates []core.Provider

type failingCandidates struct{ err error }

func (f failingCandidates) Len() int { return 1 }
func (f failingCandidates) Provider(context.Context, int) (core.Provider, error) {
	return core.Provider{}, f.err
}

func TestProviderEnforcementDiagnosticIsOnlyACategory(t *testing.T) {
	for _, tc := range []struct {
		message string
		want    bool
	}{
		{"provider refused (provider enforce): private upstream detail", true},
		{"unrelated failure with private upstream detail", false},
	} {
		resolverDiagnostic.providerEnforceRefused.Store(false)
		c := pinnedCandidates{failingCandidates{errors.New(tc.message)}, "address", "signer", "https://example.test", nil}
		if _, err := c.Provider(context.Background(), 0); err == nil {
			t.Fatal("upstream failure must remain a failure")
		}
		if got := resolverDiagnostic.providerEnforceRefused.Load(); got != tc.want {
			t.Fatalf("unexpected provider enforcement category: got %t, want %t", got, tc.want)
		}
	}
}

func (f fixtureCandidates) Len() int { return len(f) }
func (f fixtureCandidates) Provider(_ context.Context, i int) (core.Provider, error) {
	if i < 0 || i >= len(f) {
		return core.Provider{}, errors.New("bad index")
	}
	return f[i], nil
}

func TestPinRejectsMismatchedCandidatesAndFallback(t *testing.T) {
	good := core.Provider{Address: "0xABC", SignerAddr: "0xDEF", Endpoint: "https://provider.example"}
	badAddress := good
	badAddress.Address = "0xother"
	badSigner := good
	badSigner.SignerAddr = "0xother"
	badEndpoint := good
	badEndpoint.Endpoint = "https://other.example"
	for _, candidate := range []core.Provider{badAddress, badSigner, badEndpoint} {
		resolver := pinnedResolver{fixtureResolver{fixtureCandidates{candidate, good}}, "0xabc", "0xdef", "https://provider.example", nil}
		candidates, err := resolver.Resolve(context.Background(), endpoint.Chat, nil)
		if err != nil {
			t.Fatal(err)
		}
		if candidates.Len() != 1 {
			t.Fatal("fallback must be disabled")
		}
		if _, err := candidates.Provider(context.Background(), 0); err == nil {
			t.Fatal("mismatched candidate accepted")
		}
		if _, err := candidates.Provider(context.Background(), 1); err == nil {
			t.Fatal("fallback accepted")
		}
	}
	resolver := pinnedResolver{fixtureResolver{fixtureCandidates{good}}, "0xabc", "0xdef", "https://provider.example", nil}
	candidates, err := resolver.Resolve(context.Background(), endpoint.Chat, nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = candidates.Provider(context.Background(), 0); err != nil {
		t.Fatal(err)
	}
}

func TestPinRejectsEmptyConfigurationAndCandidates(t *testing.T) {
	resolver := pinnedResolver{upstream: fixtureResolver{fixtureCandidates{{Address: "x"}}}}
	candidates, err := resolver.Resolve(context.Background(), endpoint.Chat, nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = candidates.Provider(context.Background(), 0); err == nil {
		t.Fatal("empty pins accepted")
	}
	resolver.upstream = fixtureResolver{fixtureCandidates{}}
	if _, err = resolver.Resolve(context.Background(), endpoint.Chat, nil); err == nil {
		t.Fatal("empty candidates accepted")
	}
}
