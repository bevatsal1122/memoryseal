# MemorySeal and 0G Private Computer: integration and verification

**Status: in progress.** This document records the implementation and the point-in-time observations made on 6 November 2026. MemorySeal can reach the 0G mainnet router and obtain a structured classification for synthetic data, but the complete private inference path has **not** passed independent end-to-end verification. The gateway keeps unverified inference quarantined. This is a development prototype, not a security audit.

### Temporary low-cost routing (6 November 2026)

At the owner's request, the local development configuration uses `glm-5.3-flash` and `MEMORYSEAL_ZERO_G_TRUST_MODE=router_default`. This sends ordinary HTTPS requests to the 0G router without requiring its Private routing mode or TEE verification. The router chooses the provider; this is **not private or independently attested inference**. Memory content and policy context submitted for classification can be visible to the router and its chosen provider, so use synthetic inputs only until private inference is restored. Local connection-attestation enforcement is disabled for this temporary path, while unverified inference remains quarantined and does not grant permissions.

The live catalog listed $0.09015 per million input tokens and $0.3153 per million output tokens; prices and availability can change. A bounded synthetic request using the actual classifier returned a valid high-risk result. The router identified provider `0x000000003f486c7198d6203568a98d02b91f8044`; this was an observation, not a security pin. The router rejected `response_format=json_object`, and the model sometimes wraps JSON in a code fence; the temporary adapter accepts one fenced JSON object and still validates the strict schema. A 1,200-token limit produced empty answers in gateway tests with policy context; the temporary cap was increased to 4,096 tokens, including model reasoning. Success is not guaranteed for all inputs.

To return to Private inference, set `MEMORYSEAL_ZERO_G_TRUST_MODE=private`, select the desired compatible chat model, restore `MEMORYSEAL_REQUIRE_CONNECTION_ATTESTATION=true`, and configure and independently verify the current provider, signer, endpoint, baseline and request binding as needed. Vela requires a different decisions API adapter. Restart the service after changing settings. The full verified P0 demo remains blocked by the attestation and binding issues described below.

This is a guide to the 0G work, including the code, commands, tests, observed failures and questions for the 0G team. For the whole product see [P0 status](P0_STATUS.md), the [local runbook](LOCAL_RUNBOOK.md), and the detailed [build record](BUILD_RECORD.md). Paths and line numbers below refer to this repository snapshot; line numbers can move as files change.

## 1. What MemorySeal is trying to do

MemorySeal lets AI agents share memories while enforcing separate permissions for reading, writing and taking actions. A memory is information, not a permission. An AI model can suggest how to classify it, but cannot grant a capability, approve a transfer or change an owner's spending policy.

Example:

1. The owner permits the finance agent to transfer at most 100 test USDC per action.
2. A browser agent reads a malicious page claiming the owner approved 5,000 USDC.
3. The browser agent submits that claim as a memory. MemorySeal verifies the agent and checks its write permission.
4. 0G Private Computer analyzes the synthetic claim and relevant policy context. A suitable result may identify an authorization claim and a conflict and recommend quarantine or rejection.
5. MemorySeal applies its own deterministic rules. An unverified or suspicious memory is quarantined; its provenance can be recorded in Arkiv without publishing its private text.
6. If finance attempts a 2,000-token transfer, the protected contract checks the current owner-granted capability independently of the memory and model result.

The desired security property is that sensitive memory analysis uses 0G **Private** inference, with independently checked evidence tying the intended request and response to the expected execution. A model classification can be wrong, and attestation does not prove that a classification is correct.

## 2. What has and has not been demonstrated

| Area | Evidence observed | What it does not establish |
| --- | --- | --- |
| Mainnet access | A configured 0G key reached the model catalog and a small synthetic inference returned HTTP 200. | A successful response alone does not prove private execution, code identity or request binding. |
| Classification | Direct classifier call returned `authorization_claim`, high risk, a policy conflict and `reject` for synthetic content. Request, provider and response-signature references were present; the router-reported TEE flag was absent. | This was not a verified request through the production gateway. The reported references do not independently attest the provider or the model. |
| Gateway attestation | A separate diagnostic verified a TDX quote, evidence-bundle binding, served certificate and allowlisted OS image. | Strict verification failed because the application manifest could not be obtained, so gateway code identity was not established. It was not bound to the actual inference connection. |
| Provider attestation | A separate provider diagnostic verified a TDX quote, allowlisted boot chain, signer match and provider manifest hash binding. | Strict verification failed because there was no reviewed per-service baseline for that provider. This is not evidence that the provider is compromised, nor approval of it. |
| Experimental bridge | Local Go and Python tests cover synthetic signatures, ciphertext binding, challenge and pin checks. A live synthetic diagnostic reached provider selection but the upstream provider-enforcement gate refused the candidate. | No successful live receipt, actual wire-traffic proof or independently verified model execution. All bridge results remain unverified and quarantined. |
| Product demonstration | ENS identities, an Arkiv synthetic creation event and a Sepolia protected action have separate tests; a quarantined browser claim was withheld from finance. | They are not yet one complete attack scenario with verified live 0G inference. |

0G distinguishes **Private** from **Verified** routing. The current classifier explicitly asks for `private`; the request header is a routing request, not independent proof that every desired security property was achieved. See [0G Private Computer](https://pc.0g.ai/) and [0G trusted privacy](https://pc.0g.ai/trusted-privacy).

## 3. Architecture and implementation files

```text
Signed agent request
        |
MemorySeal gateway: identity + namespace authorization
        |
Classifier input: proposed memory + source + policy/agent context
        |
0G mainnet router / selected provider (Private mode)
        |
Structured advisory result + verification evidence
        |
Deterministic firewall: accept / quarantine / reject
        |
Encrypted local payload + Arkiv provenance event

Protected token action -> separate owner-controlled on-chain policy check
```

The goal above is the intended flow. In particular, the live request-binding and attestation chain is **not** completed simply because the diagram contains it.

| File and approximate line | Responsibility |
| --- | --- |
| [`src/memoryseal/inference.py:18`](../src/memoryseal/inference.py#L18) | Strict structured analysis schema. `ZeroGClassifier` starts at line 42; `analyze` starts at line 73. It requests Private mode and structured JSON. |
| [`src/memoryseal/memory_service.py:143`](../src/memoryseal/memory_service.py#L143) | Memory-write flow, permission checks and classification. Around lines 252–345 it checks integration configuration and constructs the transport; around lines 431 and 514 it applies unverified/fail-closed handling. |
| [`src/memoryseal/api.py:79`](../src/memoryseal/api.py#L79) | Authenticated integration-readiness endpoint. Line 123 currently reports `request_binding_verification_supported: false`. This is intentional; the live evidence and acceptance policy are not complete. |
| [`src/memoryseal/attested_transport.py`](../src/memoryseal/attested_transport.py) | Experimental separate gateway-verifier and connection-certificate check. This is not independent provider execution or request binding. |
| [`src/memoryseal/gateway_verifier.py:15`](../src/memoryseal/gateway_verifier.py#L15) | Runs a pinned, operator-trusted strict gateway verifier with bounded execution. |
| [`src/memoryseal/demo/verify_0g_gateway.py:12`](../src/memoryseal/demo/verify_0g_gateway.py#L12) | Standalone strict gateway diagnostic. It excludes MemorySeal credentials from the child environment. Its separate run is not tied to the later inference connection. |
| [`src/memoryseal/zero_g_registry.py:24`](../src/memoryseal/zero_g_registry.py#L24) and [`src/memoryseal/demo/discover_0g.py:15`](../src/memoryseal/demo/discover_0g.py#L15) | Observe provider registry records and compare configured pins. An RPC observation is not attestation or provider approval. |
| [`src/memoryseal/zero_g_provider_verifier.py:29`](../src/memoryseal/zero_g_provider_verifier.py#L29) | Experimental strict provider-verifier adapter; on an unambiguous pass it extracts quote-reported public keys. The executable, baseline, roots and RPC are operator trust inputs. |
| [`integrations/zero_g/bridge.go:140`](../integrations/zero_g/bridge.go#L140) and [`integrations/zero_g/pinned_resolver.go:31`](../integrations/zero_g/pinned_resolver.go#L31) | Experimental one-request Go bridge and pre-sealing provider/signer/endpoint/key pin checks. The upstream handler is invoked locally. |
| [`src/memoryseal/bridge_transport.py:40`](../src/memoryseal/bridge_transport.py#L40) | Adapts the bridge to the classifier and checks optional reported receipts. Its result is not promoted to verified inference. |
| [`src/memoryseal/zero_g_verification.py:26`](../src/memoryseal/zero_g_verification.py#L26) | Signature, artifact-hash, challenge and legacy response checks. These operate on reported evidence, not independently observed network traffic. |
| [`src/memoryseal/bridge_response.py:36`](../src/memoryseal/bridge_response.py#L36) | Experimental independent opening of bridge-reported response ciphertext; request ciphertext comparison starts at line 118. Sealing material and ephemeral keys are sensitive. |
| [`scripts/build_0g_bridge.py`](../scripts/build_0g_bridge.py), [`scripts/test_0g_bridge.py`](../scripts/test_0g_bridge.py) | Build from a pinned upstream archive and run isolated synthetic bridge/receipt tests. Build success is not an audit. |
| [`integrations/zero_g/README.md`](../integrations/zero_g/README.md) | More detailed bridge configuration, tests and limitations. |

## 4. Mainnet configuration and API request

The local configuration has a 0G mainnet API key and temporarily uses `glm-5.3-flash` with router-default routing, as described above. Earlier tests below used `glm-5.3`, `0gm-1.0-35b-a3b` and `deepseek-v4.1-flash`. Settings belong in the private root `.env`, not in source control or chat:

```text
MEMORYSEAL_ZERO_G_NETWORK=mainnet
MEMORYSEAL_ZERO_G_MODEL=glm-5.3-flash
MEMORYSEAL_ZERO_G_TRUST_MODE=router_default
MEMORYSEAL_ZERO_G_API_KEY=<secret stored locally>
```

The mainnet router is `https://router-api.0g.ai/v1/`. The testnet router is separate and uses separate accounts, balances and keys. The classifier calls `POST /v1/chat/completions` with `Authorization: Bearer <API_KEY>` and `X-0G-Provider-Trust-Mode: private`. If provider pins are supplied, it also sends `X-0G-Provider-Address` and `X-0G-Provider-Allow-Fallbacks: false`.

The body contains `model`, `temperature: 0`, `verify_tee: true` and two messages: a system instruction asking for JSON classification, and a user message containing JSON with `content`, `source_type`, `policy_context` and `agent_context`. Do not log these messages, API keys, bridge pipe data, ephemeral keys or sealing seeds. The router and provider may see fields outside the encrypted payload; consult the upstream protocol before deciding which information is safe to send.

For the actual gateway, `MEMORYSEAL_REQUIRE_CONNECTION_ATTESTATION` defaults to true. The verifier path and reviewed binary digest must be configured before that check can run. The **experimental bridge currently cannot be combined with that separate gateway-connection check** and requires the check disabled; bridge output remains quarantined. Do not disable a check to present a demo as verified or send real sensitive data through an unreviewed experimental path. The local key and model being present is configuration, not proof that inference or attestation is ready.

## 5. What was tried: gateway verification

The read-only diagnostics used 0G's [`pcverify` gateway procedure](https://github.com/0gfoundation/0g-pc-e2ee/blob/main/docs/verifying-the-gateway.md) and a locally built verifier from upstream commit `c0e7d23f03adea19cbac36223bbeabe05cc8eaad`. No MemorySeal credentials or private memory were supplied to these verifier runs.

1. `GET https://router-api.0g.ai/v1/gateway/identity` and `/evidences/sha256sum.txt` were reachable. The identity endpoint is self-report; it is not proof by itself.
2. The initial strict verifier runs timed out. A stack trace showed it waiting in the TDX library's retrying collateral retrieval. A diagnostic build that failed on the first collateral error exposed a TLS unknown-authority error at the Intel TCB endpoint. This diagnostic build was not used as an authorization gate.
3. Running the original verifier with `SSL_CERT_FILE` omitted for the diagnostic allowed the TDX quote, bundle binding, served certificate and allowlisted `dstack-0.6.1` OS-image checks to pass. This used the system trust store for that run; it was **not** installed as a runtime trust policy.
4. Strict verification still exited nonzero because it could not obtain the authenticated application manifest. The Phala app-attestations endpoint returned **401** and the guest-agent fallback returned EOF / TLS connection failure. Consequently, code identity and a strict pass were not established.
5. The previously reported app ID was `cc35d11bf6d0405242a4e2cb83bb9b0338247225`. A later DNS TXT check resolved to the same ID, and the CNAME chain led to `dstack-pha-prod5.phala.network`. IDs and deployments can change; always discover and verify the current ones rather than hardcoding them as authority.

Representative read-only diagnostic, with an independently obtained published release file:

```bash
env -u SSL_CERT_FILE /path/to/reviewed/pcverify \
  -gateway router-api.0g.ai \
  -expect-network mainnet \
  -strict \
  -expect-compose-file /path/to/docker-compose.release.yml \
  -timeout 20s
```

The `-expect-compose-file` is a release manifest used for comparison; it is **not** the missing `app-compose.json`. For a supplied app manifest, `pcverify` supports `-app-compose /path/to/app-compose.json`. Verify the exact bytes against the compose hash extracted from the **verified gateway quote**, then compare its embedded deployment compose with a reviewed published release. If the Cloud API returns multiple instances, hash and compare **each candidate**; do not assume the first is correct. A separately run verifier does not by itself prove that the later API request used the same TLS connection or provider.

At the latest documented check, the DNS-resolved app ID's Cloud endpoint still returned 401 and the derived guest-agent HTTPS endpoint failed. No manifest bytes were available to hash. A `401`, EOF or `no_baseline` is not a finding that the provider is compromised; it means the requested verification could not be completed.

## 6. What was tried: provider verification

At 0G mainnet block `49432102`, a public registry page reported the following point-in-time record:

| Field | Observed value |
| --- | --- |
| Model | `0GM-1.0-35B-A3B` |
| Provider | `0xf4fb8d2bd856e672b5f9848b0ed235a20079b250` |
| Provider endpoint | `https://compute-network-20.integratenetwork.work` |
| Registry | `0x47340d900bdFec2BD393c626E12ea0656F938d84` |
| Reported signer | `0x6c94321bb38e764ed266db6e3eee7503f754a23a` |
| Reported mode / acknowledgement | `TeeML` / acknowledged |

These are RPC observations, not a trust decision. Provider registration, endpoint, model availability and pins can change.

The strict diagnostic used the original pinned verifier, the system trust store for this particular run, and no API key:

```bash
env -u SSL_CERT_FILE /path/to/reviewed/pcverify \
  -provider 0xf4fb8d2bd856e672b5f9848b0ed235a20079b250 \
  -chain-rpc-url https://evmrpc.0g.ai \
  -serving-contract 0x47340d900bdFec2BD393c626E12ea0656F938d84 \
  -endpoint https://compute-network-20.integratenetwork.work \
  -expect-signer 0x6c94321bb38e764ed266db6e3eee7503f754a23a \
  -strict -timeout 20s
```

It reported a genuine TDX quote, an allowlisted boot chain, matching quote and registry signer, and an authenticated provider app-compose. It **failed strict mode** because no deployment baseline was recorded for this provider. The authenticated manifest also contained shared mounts and guest-agent socket access that require human review. Those findings do not prove maliciousness; they identify what a meaningful review must account for.

The upstream baseline file had an older `compute-network-20` entry for provider `0x4870cbc4d07d6ac2ee5aa865588e5985fe77a4e9`, with a different deployment hash. A temporary, deliberately remapped copy was used only to compare differences: the verifier reported 14 mismatches across services and top-level volumes/networks. The temporary file was deleted and was never trusted or used by the gateway. A later registry lookup of the older provider did not return a usable service record.

**Verdicts:** `pass` means a check ran and succeeded; `no_match` means it ran and found a mismatch; `no_baseline` means the required reference was absent; `unavailable` means a required check could not complete. `no_baseline` is not a pass or a compromise finding. See [0G's verification procedure](https://github.com/0gfoundation/0g-pc-e2ee/blob/main/docs/verifying-the-gateway.md).

## 7. What was tried: experimental request binding

The bridge is built from the pinned upstream archive with local hooks. Its client construction uses `-attest`, `-attest-enforce`, `-onchain`, `-onchain-enforce`, `-verify-responses` and `-provider-enforce`. It pins the selected provider, signer, endpoint and optionally the quote-reported encryption key. It sends one request through a local process pipe; that pipe is sensitive and the executable remains a trusted component.

The Python side can check a bridge-reported provider signature, hashes of request/response artifacts, a random request challenge, a reconstructed request ciphertext and the opened response choices. These checks use evidence and one-use material reported by the bridge. They do not by themselves prove the actual wire traffic, independently attest the provider, prove which model ran or make the bridge trustworthy. The gateway does **not** promote these observations into verified inference.

Synthetic local tests exercised this path, including changed ciphertext, signer, request and response. The isolated Go suites passed with the race detector and the cross-language synthetic receipt fixture passed. Tests are local and do not prove real service behavior.

A separate synthetic mainnet bridge diagnostic, with the observed provider and quote-reported key pinned, returned **502** and no usable receipt. Fixed boolean diagnostics reported that candidate resolution started but provider materialization failed; the error matched the upstream provider-enforcement refusal category. Upstream enforcement can refuse missing/failing baseline or runtime-release checks. The boolean does not prove which subcheck failed, whether any inference reached a provider, or whether it was billed. No enforcement was relaxed and no private content was used. The normal gateway runner discards child stderr.

## 8. How to reproduce safe local checks

The following use synthetic fixtures and do not send a live inference request:

```bash
.venv/bin/pytest -q tests/test_zero_g_verification.py \
  tests/test_bridge_transport.py tests/test_zero_g_provider_verifier.py

.venv/bin/python -m scripts.test_0g_bridge \
  /path/to/reviewed/0g-pc-e2ee-checkout \
  /absolute/path/to/go --race
```

The test runner requires the pinned upstream checkout and appropriate Go/Python dependencies; see the [bridge README](../integrations/zero_g/README.md). A successful local test verifies its fixtures and assertions, not live attestation or provider behavior. The most recent broader Python run recorded in the build record was **243 passed, 6 skipped**; it predates some later bridge-only diagnostics.

Provider discovery is read-only, but its output must be treated as an RPC observation, not a provider recommendation:

```bash
.venv/bin/python -m memoryseal.demo.discover_0g \
  https://evmrpc.0g.ai --network mainnet --limit 30
```

Live inference can consume the account's credits. Use synthetic data for diagnostics, keep keys local, and never assume a timeout means no request was processed or billed.

### DeepSeek model switch and routing checks

After the 0G team suggested DeepSeek-V4.1-Flash as a temporary alternative, the locally configured model was changed to `deepseek-v4.1-flash`; no provider pins or gateway security settings were changed. At the time of the check, the mainnet model catalog returned the model, but its record did not include TEE-attestation metadata. A synthetic Private-mode request and a separate synthetic Verified-mode request both returned HTTP 503 with `no_provider_for_trust_mode`. A third synthetic request with no explicit trust-mode header returned HTTP 200; that request used the key's configured default, which was not independently established in the diagnostic. It is evidence of general availability only, not evidence that Private mode works or that execution was attested. The ordinary MemorySeal classifier continues to require Private mode and the gateway's fail-closed behavior remains enabled. The earlier 0GM provider address and baseline findings are historical and must not be applied to DeepSeek without a fresh provider observation and verification.

### Temporary GLM-5.3 selection

A bounded synthetic `glm-5.3` Private-mode request returned HTTP 200 with the expected structured high-risk authorization-claim classification. An earlier 600-token request returned 200 but did not produce output compatible with the strict schema. A separate invocation of MemorySeal's existing classifier failed with a schema `ValidationError`; its exact invalid field was not captured. A later bounded synthetic request using the exact classifier system prompt returned valid structured output. These mixed observations do not establish reliable classifier compatibility, privacy or attested execution. At that point the local model was set to `glm-5.3`; it was later changed to the temporary option described above.

The router reported provider `0xd179f4526064846de9a9e9d93683af75cb72e503` on the bounded test, matching a point-in-time acknowledged mainnet registry record for `glm-5.3`. A separate strict provider diagnostic verified its TDX quote, allowlisted boot chain, signer match and provider manifest binding, but exited nonzero because no per-service baseline was recorded. That separate diagnostic is not tied to the inference request. The gateway remains fail-closed, and the full verified demo is not ready.

When switching models, the model setting can be changed independently while routing is unpinned. When provider pinning is enabled, update and independently verify the provider address, signer, endpoint and, where used, recipient encryption key and provider baseline together; an old provider's evidence or baseline cannot establish the new provider's identity. The gateway's code-identity and request-binding requirements remain separate.

### Vela 2.0 9B Private-mode test

At the user's request, inspected the live mainnet catalog for `vela-2.0-9b`. The catalog described a `decisions` model, 16,384-token context, TeeML/TDX metadata, one provider, and input-only pricing of $0.04 per million input tokens at the time. These are router-reported fields and prices, not independent attestation or a guarantee of current availability. Unlike GLM, Vela uses `POST /v1/decisions` with `state` and `questions` and returns decision answers; the existing classifier and experimental bridge use chat completions and cannot use it by changing the model ID alone. [Vela's model usage](https://huggingface.co/vllm-sr/Vela-2.0-9B/blob/main/USAGE.md) describes its decision question types.

Two small synthetic Private-mode requests to `/v1/decisions`, one with explicit yes/no criteria and one with default criteria, both returned HTTP 502 `provider_error` with the router message that the upstream provider request failed. This is not sufficient to identify whether the failure was request compatibility, provider availability or another upstream problem, and does not prove the model cannot work privately. No private memory was sent. Switching to Vela without a decisions adapter would break the current chat classifier. To use Vela, first confirm Private-mode API behavior and then implement and test a decisions adapter and explicit deterministic mapping from returned answers to `ThreatAnalysis`; the existing verification and quarantine gates must remain enforced.

## 9. Questions for the 0G team

1. Can you provide the exact public gateway `app-compose.json` for the currently DNS-resolved app ID, or a working public retrieval endpoint? The documented Phala endpoint returned 401 and the guest-agent fallback failed. We will compare the exact bytes with the verified quote's compose hash, including checking all instances.
2. Is there a reviewed per-service baseline for mainnet provider `0xf4fb8d2bd856e672b5f9848b0ed235a20079b250`, or another currently supported model/provider with one? The strict verifier reported no baseline and the bridge reported provider-enforcement refusal.
3. What supported procedure should an integrating client use to bind its actual Private-mode request and response to the independently verified gateway/provider, and how can it verify the model execution claim?
4. Does the mainnet router intentionally omit the router-reported TEE flag for this response format, and which documented receipt fields should we expect?

These questions require no API key, wallet private key, recovery phrase or private memory. The public addresses, model and endpoint above are historical observations; recheck current values before relying on them.

## 10. Remaining steps

1. Obtain and validate the gateway app manifest; independently review the provider baseline and verifier trust inputs. A supplied file or an upstream claim alone is not a pass.
2. Establish a reviewed policy for provider attestation and request/response binding, and exercise the **actual** gateway connection and inference with synthetic input first. Preserve fail-closed behavior until the required evidence is present.
3. Reconcile the uncertain Arkiv acknowledgement without blindly republishing it. Publish and independently query provenance for the eventual integrated scenario.
4. Recheck Sepolia owner/agent identities, policy and test-token allowance; run the malicious claim, denied action, owner-signed policy change and permitted test-token action. Local and on-chain policy versions are separate. Confirm receipts and state using the configured RPC, while documenting finality limits.
5. Verify the dashboard and wallet interactions, run the relevant regression and security tests, and audit every P0 requirement against the actual results.

The complete P0 workflow is not finished until those requirements are met and verified. See [P0 status](P0_STATUS.md) for the current checklist.
