package main

import (
	"bytes"
	"context"
	"errors"
	"strings"
	"sync/atomic"

	"github.com/0gfoundation/0g-pc-e2ee/client/core"
	"github.com/0gfoundation/0g-pc-e2ee/client/endpoint"
	"github.com/0gfoundation/0g-pc-e2ee/protocol/wire"
)

// The bridge handles exactly one request. Diagnostics never include the
// candidate, key, request or error text.
var resolverDiagnostic struct {
	resolveStarted, resolveReturned, providerRequested, providerReturned, pinsMatched, providerEnforceRefused atomic.Bool
}

// pinnedResolver checks the materialized candidate before core seals the prompt.
// Its upstream resolver is still responsible for attestation and grounding.
type pinnedResolver struct {
	upstream     core.Resolver
	address      string
	signer       string
	endpoint     string
	recipientKey []byte
}

func (p pinnedResolver) Resolve(ctx context.Context, ep endpoint.Endpoint, req wire.Request) (core.Candidates, error) {
	resolverDiagnostic.resolveStarted.Store(true)
	candidates, err := p.upstream.Resolve(ctx, ep, req)
	if err != nil {
		return nil, err
	}
	resolverDiagnostic.resolveReturned.Store(true)
	if candidates == nil || candidates.Len() < 1 {
		return nil, errors.New("provider selection unavailable")
	}
	return pinnedCandidates{candidates, p.address, p.signer, p.endpoint, p.recipientKey}, nil
}

type pinnedCandidates struct {
	upstream     core.Candidates
	address      string
	signer       string
	endpoint     string
	recipientKey []byte
}

// Exposing one candidate prevents fallback to another provider.
func (p pinnedCandidates) Len() int { return 1 }

func (p pinnedCandidates) Provider(ctx context.Context, i int) (core.Provider, error) {
	resolverDiagnostic.providerRequested.Store(true)
	if i != 0 || p.address == "" || p.signer == "" || p.endpoint == "" {
		return core.Provider{}, errors.New("invalid provider pin")
	}
	candidate, err := p.upstream.Provider(ctx, 0)
	if err != nil {
		// Report only a fixed category; never expose the upstream error text.
		resolverDiagnostic.providerEnforceRefused.Store(strings.Contains(err.Error(), "refused (provider enforce)"))
		return core.Provider{}, err
	}
	resolverDiagnostic.providerReturned.Store(true)
	if !strings.EqualFold(candidate.Address, p.address) ||
		!strings.EqualFold(candidate.SignerAddr, p.signer) || candidate.Endpoint != p.endpoint ||
		(p.recipientKey != nil && !bytes.Equal(candidate.EncPubKey, p.recipientKey)) {
		return core.Provider{}, errors.New("provider does not match configured pins")
	}
	resolverDiagnostic.pinsMatched.Store(true)
	return candidate, nil
}
