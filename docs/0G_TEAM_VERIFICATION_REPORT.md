# 0G verification: current reproducible results

Checked 6 November 2026 at approximately 14:23 UTC. Read-only diagnostics used upstream `0gfoundation/0g-pc-e2ee` commit `c0e7d23f03adea19cbac36223bbeabe05cc8eaad`, built locally in a temporary checkout. No API keys, wallet private keys, memory content or paid inference were used for these diagnostics. Values are point-in-time observations, not permanent pins.

## 1. Gateway app-compose is still unavailable

Gateway: `router-api.0g.ai` (mainnet). DNS TXT `_dstack-app-address.router-api.0g.ai` resolved app ID `cc35d11bf6d0405242a4e2cb83bb9b0338247225`. The gateway quote identified the compose hash `eaa354ebe95ce1649fd280ba53532c6d0b0c56ecf5abd65d5eccee87c35dda7b`.

- Direct GET to `https://cloud-api.phala.com/api/v1/apps/cc35d11bf6d0405242a4e2cb83bb9b0338247225/attestations` returned HTTP 401.
- The derived guest-agent fallback `https://cc35d11bf6d0405242a4e2cb83bb9b0338247225-8090.dstack-pha-prod5.phala.network/prpc/Info` failed with TLS EOF.
- The verifier authenticated the TDX quote, evidence bundle and served TLS certificate, validated the OS image and observed the mainnet registry settings, but could not establish gateway code identity without the matching manifest. With `-strict` it exited 1. One run hit a Phala request deadline; a separate direct request returned 401. An automatic release lookup also hit GitHub's rate limit, so we supplied the official release asset `release-2026.11.05.1` (SHA-256 `59807a4ca8f702415325ad6ed01e3dbd98ea6232b9804e76557934440efa52a7`) explicitly. That bypasses our local release-list rate limit; it cannot replace the gateway's own app-compose.

**Question:** Can you provide the exact `app-compose.json` bytes for the running gateway app ID and quote hash above, or a publicly accessible endpoint that returns them? If an endpoint returns multiple instances, we will hash each manifest and select the one matching the verified quote. Can you confirm whether the Cloud endpoint is expected to require authentication and whether guest-agent access is intended to be public?

## 2. Provider per-service baseline remains missing

Model: `0gm-1.0-35b-a3b`; provider: `0xf4fb8d2bd856e672b5f9848b0ed235a20079b250`; registry: `0x47340d900bdFec2BD393c626E12ea0656F938d84`; endpoint: `https://compute-network-20.integratenetwork.work`.

Current registry signer was `0xddaeaac4d8525d72dfd20cc6de0f28eb3d320bfb`. This differs from the historical signer `0x6c94321bb38e764ed266db6e3eee7503f754a23a`; a diagnostic with the old pin correctly failed the expected-signer check. We reran with the currently observed signer, not an assumed trusted replacement.

The fresh strict provider diagnostic passed acknowledgement, quote DCAP verification, allowlisted OS `dstack-nvidia-0.5.12`, onchain/quote signer match, and authenticated provider manifest. Provider compose hash: `6a0ea081469664b56b33fbd010ea707dfef67ae2ac8613420acf207e4bc9a0f4`. It then exited 1 because the verifier contained no per-service baseline for this provider. The review output flagged items needing justification, including shared mounts and guest-agent socket access. The gateway's own public provider identity endpoint independently reports its **own** verdicts as `quote_dcap: pass`, `onchain_signer: pass`, `measurement: pass`, `compose_baseline: no_baseline`, and `runtime_release: not_checked`; these are gateway reports, not independent proof of request binding.

**Question:** Is there a reviewed per-service deployment baseline for this provider/compose hash, and an independently verifiable source for it? If not, is another provider/model currently supported with a reviewed baseline and full strict pass? Can you also confirm the intended independent signer-rotation process and what evidence should establish the new pin?

## Reproduction

Build from the repository at the recorded commit. This checkout has a nested Go module at `client/cmd/pcverify`:

```sh
git clone https://github.com/0gfoundation/0g-pc-e2ee.git
cd 0g-pc-e2ee
git checkout c0e7d23f03adea19cbac36223bbeabe05cc8eaad
(cd client/cmd/pcverify && go build -o /tmp/pcverify .)

dig +short TXT _dstack-app-address.router-api.0g.ai
curl -i 'https://cloud-api.phala.com/api/v1/apps/cc35d11bf6d0405242a4e2cb83bb9b0338247225/attestations'
curl -v 'https://cc35d11bf6d0405242a4e2cb83bb9b0338247225-8090.dstack-pha-prod5.phala.network/prpc/Info'

curl -fL -o /tmp/0g-release.yml 'https://github.com/0gfoundation/0g-pc-e2ee/releases/download/release-2026.11.05.1/docker-compose.release.yml'
shasum -a 256 /tmp/0g-release.yml

env -u SSL_CERT_FILE /tmp/pcverify \
  -gateway router-api.0g.ai -expect-network mainnet -strict \
  -expect-compose-file /tmp/0g-release.yml \
  -app-id cc35d11bf6d0405242a4e2cb83bb9b0338247225 \
  -base-domain dstack-pha-prod5.phala.network -no-dns-discovery -timeout 45s

env -u SSL_CERT_FILE /tmp/pcverify \
  -provider 0xf4fb8d2bd856e672b5f9848b0ed235a20079b250 \
  -chain-rpc-url https://evmrpc.0g.ai \
  -serving-contract 0x47340d900bdFec2BD393c626E12ea0656F938d84 \
  -endpoint https://compute-network-20.integratenetwork.work \
  -expect-signer 0xddaeaac4d8525d72dfd20cc6de0f28eb3d320bfb \
  -strict -timeout 30s

curl -s 'https://router-api.0g.ai/v1/providers/0xf4fb8d2bd856e672b5f9848b0ed235a20079b250/identity'
```

`env -u SSL_CERT_FILE` used the local system certificate store for this diagnostic; it is not a trust-policy recommendation. Compare the release asset hash with the one published on the official release page. Repeat discovery before relying on any ID, signer or deployment hash: deployments can change. The standalone provider and gateway checks are not bound to MemorySeal's inference connection, request or response. MemorySeal currently quarantines unverified inference, and the report does not claim that either party is compromised.
