package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/0gfoundation/0g-pc-e2ee/client/core"
	"github.com/0gfoundation/0g-pc-e2ee/client/openaiproxy"
	"github.com/0gfoundation/0g-pc-e2ee/client/sig"
	"github.com/0gfoundation/0g-pc-e2ee/protocol/crypto"
	"github.com/0gfoundation/0g-pc-e2ee/protocol/proof"
	"github.com/0gfoundation/0g-pc-e2ee/protocol/wire"
	"github.com/decred/dcrd/dcrec/secp256k1/v4"
	"github.com/decred/dcrd/dcrec/secp256k1/v4/ecdsa"
	"golang.org/x/crypto/sha3"
)

type fixtureFetcher struct {
	receipt proof.ChatSignature
	calls   int
}

// Test the upstream protocol option independently of the production bridge wiring.
func TestRequestModelBindingOption(t *testing.T) {
	providerPriv, providerPub, err := crypto.GenerateRecipientKey()
	if err != nil {
		t.Fatal(err)
	}
	_, clientPub, err := crypto.GenerateRecipientKey()
	if err != nil {
		t.Fatal(err)
	}
	request := wire.Request{
		"model":    json.RawMessage(`"original-model"`),
		"messages": json.RawMessage(`[{"role":"user","content":"private"}]`),
	}
	for _, tc := range []struct {
		name             string
		unbound          []string
		mutationAccepted bool
	}{
		{"upstream_default", wire.DefaultUnboundFields(), true},
		{"bind_all_fields", []string{}, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			envelope, err := wire.SealRequest(providerPub, request, nil,
				"0x1111111111111111111111111111111111111111", clientPub, tc.unbound...)
			if err != nil {
				t.Fatal(err)
			}
			if _, err := wire.OpenRequest(providerPriv, envelope); err != nil {
				t.Fatalf("original request failed to decrypt: %v", err)
			}
			envelope["model"] = json.RawMessage(`"changed-model"`)
			_, err = wire.OpenRequest(providerPriv, envelope)
			if (err == nil) != tc.mutationAccepted {
				t.Fatalf("model mutation accepted = %v, want %v", err == nil, tc.mutationAccepted)
			}
		})
	}
}

func (f *fixtureFetcher) FetchSignature(_ context.Context, _ core.Provider, key string) (proof.ChatSignature, error) {
	f.calls++
	if key != "ck-1" {
		return proof.ChatSignature{}, fmt.Errorf("unexpected key")
	}
	return f.receipt, nil
}
func TestBridgeHandlerRequiresValidProviderSignature(t *testing.T) {
	selectedProvider := "0x1111111111111111111111111111111111111111"
	spoofedProvider := "0x2222222222222222222222222222222222222222"
	signer, err := secp256k1.GeneratePrivateKey()
	if err != nil {
		t.Fatal(err)
	}
	digest := sha3.NewLegacyKeccak256()
	digest.Write(signer.PubKey().SerializeUncompressed()[1:])
	address := "0x" + hex.EncodeToString(digest.Sum(nil)[12:])
	fetcher := &fixtureFetcher{}
	replayReceipt := false
	oversized := false
	boundResponse := false
	providerPriv, encPub, err := crypto.GenerateRecipientKey()
	if err != nil {
		t.Fatal(err)
	}
	challenge := "memoryseal-" + strings.Repeat("a", 64)
	var openedRequests atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-0G-Provider-Trust-Mode") != "private" {
			t.Error("private routing directive was not forwarded")
		}
		if r.Header.Get("X-0G-Provider-Address") != selectedProvider {
			t.Error("request was not pinned to selected provider")
		}
		if oversized {
			w.Header().Set("ZG-Res-Key", "ck-1")
			_, _ = w.Write(bytes.Repeat([]byte("x"), 4*1024*1024+1024))
			return
		}
		raw, _ := io.ReadAll(r.Body)
		if bytes.Contains(raw, []byte("sensitive marker")) {
			t.Error("provider request was not sealed")
		}
		var envelope map[string]json.RawMessage
		if json.Unmarshal(raw, &envelope) != nil {
			t.Error("invalid envelope")
			return
		}
		opened, err := wire.OpenRequest(providerPriv, envelope)
		if err != nil {
			t.Error("provider could not authenticate sealed request")
			return
		}
		var messages []struct {
			Role    string `json:"role"`
			Content string `json:"content"`
		}
		if json.Unmarshal(opened["messages"], &messages) != nil ||
			len(messages) != 2 || messages[0].Role != "system" || messages[0].Content != "rules" ||
			messages[1].Role != "user" || messages[1].Content != "sensitive marker" ||
			string(opened["model"]) != `"model"` || string(opened["user"]) != `"`+challenge+`"` {
			t.Error("opened request does not match the original classifier request")
			return
		}
		openedRequests.Add(1)
		bind, _, err := wire.TakeResponseBind(wire.ProfileChat, opened)
		if err != nil {
			t.Error("invalid response binding")
			return
		}
		var inner struct {
			ClientPub string `json:"client_eph_pub"`
		}
		if json.Unmarshal(envelope["_e2ee"], &inner) != nil {
			t.Error("missing key")
			return
		}
		pub, err := base64.RawURLEncoding.DecodeString(inner.ClientPub)
		if err != nil {
			t.Error(err)
			return
		}
		response := wire.Response{"model": json.RawMessage(`"model"`), "choices": json.RawMessage(`[{"index":0,"message":{"role":"assistant","content":"result"}}]`)}
		var sealed wire.Response
		if bind == nil {
			sealed, err = wire.SealResponse(crypto.PublicKey(pub), response, nil)
		} else {
			sealed, err = wire.SealBoundResponseFor(wire.ProfileChat, crypto.PublicKey(pub), bind, response, nil)
		}
		if err != nil {
			t.Error(err)
			return
		}
		text, err := proof.SignedTextE2EE(envelope, sealed)
		if err != nil {
			t.Error(err)
			return
		}
		hash := sha3.NewLegacyKeccak256()
		hash.Write([]byte("\x19Ethereum Signed Message:\n" + strconv.Itoa(len(text))))
		hash.Write([]byte(text))
		compact := ecdsa.SignCompact(signer, hash.Sum(nil), false)
		rawsig := append(append([]byte{}, compact[1:]...), compact[0])
		if !replayReceipt {
			fetcher.receipt = proof.ChatSignature{Text: text, Signature: "0x" + hex.EncodeToString(rawsig)}
		}
		w.Header().Set("ZG-Res-Key", "ck-1")
		w.Header().Set("X-Provider", spoofedProvider)
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(sealed)
	}))
	defer server.Close()
	body := `{"model":"model","temperature":0,"verify_tee":true,"user":"` + challenge + `","messages":[{"role":"system","content":"rules"},{"role":"user","content":"sensitive marker"}]}`
	run := func(expectedSigner string) *boundedResponse {
		client := core.New(core.Provider{URL: server.URL, Endpoint: server.URL, EncPubKey: encPub, SignerAddr: expectedSigner, Address: selectedProvider, BindResponse: boundResponse}, core.WithUnboundFields([]string{}), core.WithResponseVerification(fetcher, sig.Recover))
		req := classifierHTTPReq(request{APIKey: "dummy", Body: json.RawMessage(body), Provider: selectedProvider})
		result := &boundedResponse{header: make(http.Header)}
		openaiproxy.Handler(client).ServeHTTP(result, req)
		return result
	}
	good := run(address)
	if openedRequests.Load() != 1 {
		t.Fatal("fake provider did not open the signed request")
	}
	receipt := core.MemorySealTakeReceipt()
	if receipt == nil || !strings.HasPrefix(receipt.Text, "zg-sig-v1/e2ee-ct:") || receipt.Signature == "" {
		t.Fatal("verified receipt missing")
	}
	if receipt.Artifacts == nil {
		t.Fatal("binding artifacts missing")
	}
	var requestAAD map[string]json.RawMessage
	if json.Unmarshal(receipt.Artifacts.RequestAAD, &requestAAD) != nil || string(requestAAD["user"]) != `"`+challenge+`"` {
		t.Fatal("fresh challenge not bound in request AAD")
	}
	reqH := proof.BindingHash(receipt.Artifacts.RequestAAD, receipt.Artifacts.RequestCiphertext)
	respH := proof.BindingHash(receipt.Artifacts.ResponseAAD, receipt.Artifacts.ResponseCiphertext)
	if proof.SignedTextE2EEFromHashes(reqH, respH) != receipt.Text {
		t.Fatal("binding artifacts did not match the verified receipt")
	}
	// Optional cross-language fixture contains only synthetic test data and keys.
	if path := os.Getenv("MEMORYSEAL_TEST_BINDING_FIXTURE"); path != "" {
		fixture, err := json.Marshal(struct {
			Receipt   *core.MemorySealReceipt `json:"receipt"`
			Signer    string                  `json:"signer"`
			Challenge string                  `json:"challenge"`
			Body      json.RawMessage         `json:"body"`
		}{receipt, address, challenge, good.body.Bytes()})
		if err != nil || os.WriteFile(path, fixture, 0o600) != nil {
			t.Fatal("could not write synthetic binding fixture")
		}
	}
	if !validPinnedResponse(good, selectedProvider) || !strings.Contains(good.body.String(), "result") {
		t.Fatalf("valid signed response rejected: status %d", good.status)
	}
	if good.Header().Get("X-Provider") != selectedProvider {
		t.Fatal("upstream spoofed provider identity propagated")
	}
	boundResponse = true
	bound := run(address)
	boundReceipt := core.MemorySealTakeReceipt()
	if !validPinnedResponse(bound, selectedProvider) || boundReceipt == nil || boundReceipt.Artifacts == nil {
		t.Fatal("bound response or receipt missing")
	}
	if path := os.Getenv("MEMORYSEAL_TEST_BINDING_FIXTURE"); path != "" {
		fixture, err := json.Marshal(struct {
			Receipt   *core.MemorySealReceipt `json:"receipt"`
			Signer    string                  `json:"signer"`
			Challenge string                  `json:"challenge"`
			Body      json.RawMessage         `json:"body"`
		}{boundReceipt, address, challenge, bound.body.Bytes()})
		if err != nil || os.WriteFile(path+".bound", fixture, 0o600) != nil {
			t.Fatal("could not write synthetic bound response fixture")
		}
	}
	boundResponse = false
	replayReceipt = true
	replayed := run(address)
	if validResponse(replayed) {
		t.Fatal("signature from a prior sealed request was accepted")
	}
	if core.MemorySealTakeReceipt() != nil {
		t.Fatal("replayed receipt was recorded as verified")
	}
	oversized = true
	before := fetcher.calls
	large := run(address)
	if validResponse(large) || fetcher.calls != before {
		t.Fatal("oversized sealed response reached receipt verification or was accepted")
	}
	oversized = false
	replayReceipt = false
	bad := run("0x0000000000000000000000000000000000000009")
	if validResponse(bad) {
		t.Fatal("wrong signer response accepted")
	}
	if core.MemorySealTakeReceipt() != nil {
		t.Fatal("wrong signer receipt was recorded as verified")
	}
}
