// Injected into the pinned upstream core for the experimental MemorySeal bridge.
package core

import (
	"fmt"
	"io"
)

// This bounds the sealed HTTP response before upstream JSON decoding or decryption.
const memorySealMaxSealedResponse = 4 * 1024 * 1024

func memorySealReadResponse(body io.Reader) ([]byte, error) {
	data, err := io.ReadAll(io.LimitReader(body, memorySealMaxSealedResponse+1))
	if err != nil {
		return nil, err
	}
	if len(data) > memorySealMaxSealedResponse {
		return nil, fmt.Errorf("sealed response exceeds MemorySeal limit")
	}
	return data, nil
}
