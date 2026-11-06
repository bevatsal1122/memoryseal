# MemorySeal 0G verification blockers

Checked 6 November 2026, approximately 14:23 UTC. **Both blockers remain.** We want private inference with independently verified evidence; a successful model response alone is insufficient.

## 1. Gateway manifest unavailable

- Gateway: `router-api.0g.ai`
- App ID: `cc35d11bf6d0405242a4e2cb83bb9b0338247225`
- Authenticated quote compose hash: `eaa354ebe95ce1649fd280ba53532c6d0b0c56ecf5abd65d5eccee87c35dda7b`
- Quote and TLS certificate checks passed, but the exact `app-compose.json` could not be retrieved. Phala returned **401**; the guest-agent fallback failed with **TLS EOF**. Strict verification failed.

Reproduce the 401:

```sh
curl -i 'https://cloud-api.phala.com/api/v1/apps/cc35d11bf6d0405242a4e2cb83bb9b0338247225/attestations'
```

**Ask 0G:** Please provide the exact `app-compose.json` matching the app ID and quote hash above, or a public endpoint for it. Should the Phala endpoint require authentication, and should the guest-agent endpoint be publicly accessible?

## 2. Provider reviewed baseline missing

- Model: `0gm-1.0-35b-a3b`
- Provider: `0xf4fb8d2bd856e672b5f9848b0ed235a20079b250`
- Current observed signer: `0xddaeaac4d8525d72dfd20cc6de0f28eb3d320bfb`
- Provider compose hash: `6a0ea081469664b56b33fbd010ea707dfef67ae2ac8613420acf207e4bc9a0f4`
- Quote, OS, onchain signer match and manifest integrity checks passed. **Strict verification failed because no reviewed per-service baseline was available.** The router identity endpoint also reported `compose_baseline: no_baseline` and `runtime_release: not_checked`.

A baseline is an approved reference configuration: we can verify what is running, but cannot establish that it matches an approved deployment. Missing approval does not mean the provider is compromised.

**Ask 0G:** Is there a reviewed baseline for this provider and compose hash, with an independently verifiable source? Otherwise, which supported provider/model currently passes full strict verification? The signer has changed from our earlier observation; what evidence should we use to independently validate the rotation?

## Until resolved

Keep unverified inference quarantined. Even successful standalone gateway/provider checks do not prove that a particular inference request and response used that verified connection.

Full commands and evidence: [0G team verification report](0G_TEAM_VERIFICATION_REPORT.md). IDs, signers and hashes above are observations from this check and may change after deployment updates.
