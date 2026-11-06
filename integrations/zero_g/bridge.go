// Experimental one-request bridge for a pinned 0G client checkout.
// Build inside client/cmd/memorysealbridge so Go's internal-package rule applies.
package main

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"regexp"
	"strings"

	"github.com/0gfoundation/0g-pc-e2ee/client/cmd/internal/proxycli"
	"github.com/0gfoundation/0g-pc-e2ee/client/core"
	"github.com/0gfoundation/0g-pc-e2ee/client/endpoint"
	"github.com/0gfoundation/0g-pc-e2ee/client/openaiproxy"
)

type request struct {
	Network      string          `json:"network"`
	APIKey       string          `json:"api_key"`
	Body         json.RawMessage `json:"body"`
	Provider     string          `json:"provider"`
	Signer       string          `json:"signer"`
	Endpoint     string          `json:"endpoint"`
	RecipientKey string          `json:"recipient_key,omitempty"`
}

var addressPattern = regexp.MustCompile(`^0x[0-9a-fA-F]{40}$`)
var recipientKeyPattern = regexp.MustCompile(`^[0-9a-f]{64}$`)

func validPins(in request) bool {
	if !addressPattern.MatchString(in.Provider) || !addressPattern.MatchString(in.Signer) ||
		strings.EqualFold(in.Provider, "0x0000000000000000000000000000000000000000") ||
		strings.EqualFold(in.Signer, "0x0000000000000000000000000000000000000000") {
		return false
	}
	if in.RecipientKey != "" && (!recipientKeyPattern.MatchString(in.RecipientKey) || in.RecipientKey == strings.Repeat("0", 64)) {
		return false
	}
	u, err := url.Parse(in.Endpoint)
	return err == nil && u.Scheme == "https" && u.Hostname() != "" && u.User == nil &&
		u.RawQuery == "" && u.Fragment == "" && !u.ForceQuery
}

type message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}
type classifierRequest struct {
	Model       string    `json:"model"`
	Temperature *float64  `json:"temperature"`
	VerifyTEE   *bool     `json:"verify_tee"`
	Stream      *bool     `json:"stream"`
	Messages    []message `json:"messages"`
	User        string    `json:"user,omitempty"`
}

var challengePattern = regexp.MustCompile(`^memoryseal-[0-9a-f]{64}$`)

func validClassifierRequest(raw json.RawMessage) bool {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	var request classifierRequest
	if decoder.Decode(&request) != nil {
		return false
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF {
		return false
	}
	if len(request.Model) == 0 || len(request.Model) > 256 || request.Temperature == nil || *request.Temperature != 0 || request.VerifyTEE == nil || !*request.VerifyTEE || (request.Stream != nil && *request.Stream) {
		return false
	}
	if len(request.Messages) != 2 || request.Messages[0].Role != "system" || request.Messages[1].Role != "user" {
		return false
	}
	if request.User != "" && !challengePattern.MatchString(request.User) {
		return false
	}
	return request.Messages[0].Content != "" && request.Messages[1].Content != ""
}

type boundedResponse struct {
	header   http.Header
	status   int
	body     bytes.Buffer
	overflow bool
}

func (r *boundedResponse) Header() http.Header { return r.header }
func (r *boundedResponse) WriteHeader(status int) {
	if r.status == 0 {
		r.status = status
	}
}
func (r *boundedResponse) Write(p []byte) (int, error) {
	if r.status == 0 {
		r.status = 200
	}
	if r.body.Len()+len(p) > 1_048_576 {
		r.overflow = true
		return 0, io.ErrShortWrite
	}
	return r.body.Write(p)
}

var responseKeyPattern = regexp.MustCompile(`^[A-Za-z0-9_-]{1,256}$`)

func validResponse(response *boundedResponse) bool {
	return !response.overflow && response.status == http.StatusOK &&
		responseKeyPattern.MatchString(response.Header().Get("ZG-Res-Key")) &&
		json.Valid(response.body.Bytes())
}

func validPinnedResponse(response *boundedResponse, provider string) bool {
	return validResponse(response) && addressPattern.MatchString(provider) &&
		strings.EqualFold(response.Header().Get("X-Provider"), provider)
}

func fail() { fmt.Fprintln(os.Stderr, "bridge request failed"); os.Exit(1) }

func classifierHTTPReq(in request) *http.Request {
	req := httptest.NewRequest("POST", endpoint.Chat.Path, bytes.NewReader(in.Body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+in.APIKey)
	req.Header.Set("X-0G-Provider-Trust-Mode", "private")
	req.Header.Set("X-0G-Provider-Address", in.Provider)
	req.Header.Set("X-0G-Provider-Allow-Fallbacks", "false")
	return req
}

func buildClassifierClient(in request, wrap func(core.Resolver) core.Resolver) *core.Client {
	hosts := map[string]string{"testnet": "https://router-api-testnet.integratenetwork.work", "mainnet": "https://router-api.0g.ai"}
	flags := flag.NewFlagSet("memorysealbridge", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	f := proxycli.RegisterFlags(flags, "MS_BRIDGE", "127.0.0.1:0", hosts[in.Network])
	if flags.Parse([]string{"-network", in.Network, "-router-url", hosts[in.Network], "-attest", "-attest-enforce", "-onchain", "-onchain-enforce", "-verify-responses", "-provider-enforce"}) != nil {
		return nil
	}
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	built := f.Build("memorysealbridge", logger, proxycli.MemorySealResolverWrapper(wrap))
	return built.Clients[endpoint.Chat.Path]
}

func main() {
	// No values from command-line flags or ambient ZG_SIDECAR_* configuration are accepted.
	for _, key := range os.Environ() {
		if len(key) >= 10 && key[:10] == "MS_BRIDGE_" {
			fail()
		}
	}
	raw, err := io.ReadAll(io.LimitReader(os.Stdin, 1_048_577))
	if err != nil || len(raw) > 1_048_576 {
		fail()
	}
	var in request
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&in) != nil || (in.Network != "testnet" && in.Network != "mainnet") || in.APIKey == "" || !json.Valid(in.Body) {
		fail()
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF {
		fail()
	}
	if len(in.APIKey) > 4096 || strings.ContainsAny(in.APIKey, "\r\n") || !validClassifierRequest(in.Body) || !validPins(in) {
		fail()
	}
	client := buildClassifierClient(in, func(upstream core.Resolver) core.Resolver {
		var recipient []byte
		if in.RecipientKey != "" {
			recipient, _ = hex.DecodeString(in.RecipientKey)
		}
		return pinnedResolver{upstream: upstream, address: in.Provider, signer: in.Signer, endpoint: in.Endpoint, recipientKey: recipient}
	})
	if client == nil {
		fail()
	}
	req := classifierHTTPReq(in)
	rec := &boundedResponse{header: make(http.Header)}
	openaiproxy.Handler(client).ServeHTTP(rec, req)
	receipt := core.MemorySealTakeReceipt()
	if !validPinnedResponse(rec, in.Provider) || receipt == nil {
		fail()
	}
	output := struct {
		Status      int                     `json:"status"`
		ResponseKey string                  `json:"response_key,omitempty"`
		Provider    string                  `json:"provider"`
		Receipt     *core.MemorySealReceipt `json:"receipt"`
		Body        json.RawMessage         `json:"body"`
	}{rec.status, rec.Header().Get("ZG-Res-Key"), rec.Header().Get("X-Provider"), receipt, rec.body.Bytes()}
	if !json.Valid(output.Body) || json.NewEncoder(os.Stdout).Encode(output) != nil {
		fail()
	}
}
