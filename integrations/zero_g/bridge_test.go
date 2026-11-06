package main

import (
	"encoding/json"
	"net/http"
	"strings"
	"testing"
)

func TestClassifierRequestShape(t *testing.T) {
	accepted := `{"model":"model","temperature":0,"verify_tee":true,"messages":[{"role":"system","content":"rules"},{"role":"user","content":"private"}]}`
	if !validClassifierRequest(json.RawMessage(accepted)) {
		t.Fatal("valid classifier request rejected")
	}
	rejected := []string{
		`{"model":"model","temperature":0,"verify_tee":true,"messages":[{"role":"system","content":"rules"},{"role":"user","content":"private"}],"extra":"private"}`,
		`{"model":"model","temperature":0,"verify_tee":true,"messages":[{"role":"system","content":"rules"},{"role":"user","content":"private","extra":"secret"}]}`,
		`{"model":"model","temperature":0,"verify_tee":true,"stream":true,"messages":[{"role":"system","content":"rules"},{"role":"user","content":"private"}]}`,
		`{"model":"model","temperature":0,"verify_tee":false,"messages":[{"role":"system","content":"rules"},{"role":"user","content":"private"}]}`,
	}
	for _, value := range rejected {
		if validClassifierRequest(json.RawMessage(value)) {
			t.Error("unsafe request accepted")
		}
	}
}

func TestClassifierRequestUsesPrivateRouting(t *testing.T) {
	req := classifierHTTPReq(request{APIKey: "key", Body: json.RawMessage(`{}`)})
	if got := req.Header.Get("X-0G-Provider-Trust-Mode"); got != "private" {
		t.Fatalf("trust mode = %q, want private", got)
	}
	if got := req.Header.Get("Authorization"); got != "Bearer key" {
		t.Fatalf("authorization header was not forwarded")
	}
}

func TestRequiredProviderPins(t *testing.T) {
	in := request{Provider: "0x1111111111111111111111111111111111111111", Signer: "0x2222222222222222222222222222222222222222", Endpoint: "https://provider.example"}
	if !validPins(in) {
		t.Fatal("valid pins rejected")
	}
	in.RecipientKey = strings.Repeat("1", 64)
	if !validPins(in) {
		t.Fatal("valid recipient key rejected")
	}
	in.RecipientKey = ""
	for _, bad := range []request{
		{},
		{Provider: in.Provider, Signer: in.Signer, Endpoint: "http://provider.example"},
		{Provider: in.Provider, Signer: in.Signer, Endpoint: "https://user@provider.example"},
		{Provider: in.Provider, Signer: in.Signer, Endpoint: "https://provider.example?x=y"},
		{Provider: "0x0000000000000000000000000000000000000000", Signer: in.Signer, Endpoint: in.Endpoint},
		{Provider: in.Provider, Signer: in.Signer, Endpoint: in.Endpoint, RecipientKey: strings.Repeat("0", 64)},
		{Provider: in.Provider, Signer: in.Signer, Endpoint: in.Endpoint, RecipientKey: "not-a-key"},
	} {
		if validPins(bad) {
			t.Fatal("invalid pins accepted")
		}
	}
}

func TestOnlySuccessfulResponsesWithKeyAreReturned(t *testing.T) {
	response := &boundedResponse{header: make(http.Header)}
	response.WriteHeader(http.StatusOK)
	_, _ = response.Write([]byte(`{"choices":[]}`))
	if validResponse(response) {
		t.Fatal("missing key accepted")
	}
	response.header.Set("ZG-Res-Key", "key-1")
	if !validResponse(response) {
		t.Fatal("valid response rejected")
	}
	response.status = http.StatusBadGateway
	if validResponse(response) {
		t.Fatal("error response accepted")
	}
	response.status = http.StatusOK
	response.header.Set("ZG-Res-Key", "../bad")
	if validResponse(response) {
		t.Fatal("invalid key accepted")
	}
	response.header.Set("ZG-Res-Key", "key-1")
	response.overflow = true
	if validResponse(response) {
		t.Fatal("oversized response accepted")
	}
}

func TestPinnedResponseRequiresBridgeSelectedProvider(t *testing.T) {
	provider := "0x1111111111111111111111111111111111111111"
	response := &boundedResponse{header: make(http.Header), status: http.StatusOK}
	response.header.Set("ZG-Res-Key", "key-1")
	_, _ = response.Write([]byte(`{"choices":[]}`))
	if validPinnedResponse(response, provider) {
		t.Fatal("missing provider accepted")
	}
	response.header.Set("X-Provider", "0x2222222222222222222222222222222222222222")
	if validPinnedResponse(response, provider) {
		t.Fatal("different provider accepted")
	}
	response.header.Set("X-Provider", provider)
	if !validPinnedResponse(response, provider) {
		t.Fatal("matching provider rejected")
	}
}
