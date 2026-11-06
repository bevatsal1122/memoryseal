// Injected into the pinned protocol crypto package for the one-request bridge.
package crypto

import (
	"bytes"
	"crypto/rand"
	"io"
	"sync"

	"github.com/cloudflare/circl/hpke"
)

var memorySealRequestState struct {
	sync.Mutex
	seed, recipient, plaintext []byte
}

// These values are private request-opening material. Never log or persist them.
func MemorySealRecordRequestPlaintext(plaintext []byte) {
	memorySealRequestState.Lock()
	defer memorySealRequestState.Unlock()
	memorySealRequestState.seed = nil
	memorySealRequestState.recipient = nil
	memorySealRequestState.plaintext = nil
	if len(plaintext) <= 200_000 {
		memorySealRequestState.plaintext = append([]byte(nil), plaintext...)
	}
}

func memorySealSetupSender(sender *hpke.Sender, pub PublicKey, info []byte) ([]byte, hpke.Sealer, error) {
	if string(info) != "0g-pc/v1/seal" {
		return sender.Setup(rand.Reader)
	}
	var random bytes.Buffer
	enc, sealer, err := sender.Setup(io.TeeReader(rand.Reader, &random))
	memorySealRequestState.Lock()
	defer memorySealRequestState.Unlock()
	if err == nil && random.Len() == 32 && len(pub) == 32 && memorySealRequestState.plaintext != nil {
		memorySealRequestState.seed = append([]byte(nil), random.Bytes()...)
		memorySealRequestState.recipient = append([]byte(nil), pub...)
	}
	return enc, sealer, err
}

func MemorySealTakeRequestSeal() (seed, recipient, plaintext []byte) {
	memorySealRequestState.Lock()
	defer memorySealRequestState.Unlock()
	seed, recipient, plaintext = memorySealRequestState.seed, memorySealRequestState.recipient, memorySealRequestState.plaintext
	memorySealRequestState.seed, memorySealRequestState.recipient, memorySealRequestState.plaintext = nil, nil, nil
	return
}
