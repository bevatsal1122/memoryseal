// Injected into the pinned upstream core for the one-request MemorySeal bridge.
package core

import (
	"encoding/json"
	"sync"

	"github.com/0gfoundation/0g-pc-e2ee/protocol/crypto"
	"github.com/0gfoundation/0g-pc-e2ee/protocol/proof"
	"github.com/0gfoundation/0g-pc-e2ee/protocol/wire"
)

// The artifacts are bridge-reported AAD and ciphertext, not plaintext or keys.
type MemorySealBindingArtifacts struct {
	RequestAAD         []byte `json:"request_aad"`
	RequestCiphertext  []byte `json:"request_ciphertext"`
	ResponseAAD        []byte `json:"response_aad"`
	ResponseCiphertext []byte `json:"response_ciphertext"`
}

type MemorySealReceipt struct {
	Text                string                      `json:"text"`
	Signature           string                      `json:"signature"`
	Artifacts           *MemorySealBindingArtifacts `json:"artifacts,omitempty"`
	ResponsePrivateKey  []byte                      `json:"response_private_key,omitempty"`
	RequestSeed         []byte                      `json:"request_seed,omitempty"`
	RequestRecipientKey []byte                      `json:"request_recipient_key,omitempty"`
	RequestPlaintext    []byte                      `json:"request_plaintext,omitempty"`
}

// The one-request bridge passes this ephemeral key only to its local parent.
// It must never be written to logs, public provenance, or persistent evidence.
func memorySealRecordResponseKey(key []byte) {
	memorySealReceiptState.Lock()
	defer memorySealReceiptState.Unlock()
	if memorySealReceiptState.receipt != nil && memorySealReceiptState.receipt.Artifacts != nil {
		memorySealReceiptState.receipt.ResponsePrivateKey = append([]byte(nil), key...)
	}
}

var memorySealReceiptState struct {
	sync.Mutex
	receipt *MemorySealReceipt
}

func memorySealRecordReceipt(sig proof.ChatSignature, req, resp map[string]json.RawMessage) {
	seed, recipient, plaintext := crypto.MemorySealTakeRequestSeal()
	requestAAD, requestCT, reqErr := wire.FrameBinding(req)
	responseAAD, responseCT, respErr := wire.FrameBinding(resp)
	var artifacts *MemorySealBindingArtifacts
	// Bound extra pipe output; larger otherwise-valid responses retain only the receipt.
	if reqErr == nil && respErr == nil && len(requestAAD)+len(requestCT)+len(responseAAD)+len(responseCT) <= 200_000 {
		artifacts = &MemorySealBindingArtifacts{requestAAD, requestCT, responseAAD, responseCT}
	}
	memorySealReceiptState.Lock()
	defer memorySealReceiptState.Unlock()
	receipt := &MemorySealReceipt{Text: sig.Text, Signature: sig.Signature, Artifacts: artifacts}
	if artifacts != nil && len(seed) == 32 && len(recipient) == 32 && len(plaintext) > 0 {
		receipt.RequestSeed, receipt.RequestRecipientKey, receipt.RequestPlaintext = seed, recipient, plaintext
	}
	memorySealReceiptState.receipt = receipt
}

// MemorySealTakeReceipt consumes the last successful non-stream verification.
func MemorySealTakeReceipt() *MemorySealReceipt {
	memorySealReceiptState.Lock()
	defer memorySealReceiptState.Unlock()
	receipt := memorySealReceiptState.receipt
	memorySealReceiptState.receipt = nil
	return receipt
}
