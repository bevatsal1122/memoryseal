package core

import (
	"bytes"
	"testing"
)

func TestMemorySealBoundedResponse(t *testing.T) {
	exact := bytes.NewReader(make([]byte, memorySealMaxSealedResponse))
	data, err := memorySealReadResponse(exact)
	if err != nil || len(data) != memorySealMaxSealedResponse {
		t.Fatal("response at limit should succeed")
	}
	oversized := bytes.NewReader(make([]byte, memorySealMaxSealedResponse+1000))
	data, err = memorySealReadResponse(oversized)
	if err == nil || data != nil || oversized.Len() != 999 {
		t.Fatal("oversized response must fail after at most limit plus one bytes")
	}
}
