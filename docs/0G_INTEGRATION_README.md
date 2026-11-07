# 0G integration

0G provides structured analysis in MemorySeal's ordinary-memory write path. Identity checks and owner permissions remain deterministic gateway responsibilities; a classifier never grants a capability or changes a spending limit.

## Request flow

1. Check the agent's signed write, current collection permission and relevant parent state.
2. Build classifier input from the proposed content and policy context.
3. Send the configured router request and parse category, risk, suspicious-instruction flag, conflicts and recommendation.
4. Record available inference request/provider/response references and their observed verification status.
5. Recheck current policy before applying Strict or owner-authorized Standard acceptance.

Malformed/missing analysis does not qualify for Standard acceptance. The encrypted vault bypasses classification because its plaintext never reaches the gateway.

## Configuration

| Variable | Purpose |
| --- | --- |
| MEMORYSEAL_ZERO_G_API_KEY | Server-side router credential |
| MEMORYSEAL_ZERO_G_MODEL | Model identifier selected by the operator |
| MEMORYSEAL_ZERO_G_NETWORK | mainnet or testnet; must match credentials/router |
| MEMORYSEAL_ZERO_G_TRUST_MODE | private sends the explicit routing directive; router_default omits it |
| MEMORYSEAL_REQUIRE_CONNECTION_ATTESTATION | Requires the configured connection verifier before sending content; true by default |
| MEMORYSEAL_CONNECTION_ATTESTATION_VERIFIER / SHA256 | Reviewed verifier executable and digest when connection checks are enabled |
| MEMORYSEAL_ALLOW_UNBOUND_INFERENCE | Legacy operator compatibility choice; false by default |

The project has exercised `0gm-1.0-35b-a3b` through the mainnet router. Availability and routing are external service properties; model names in earlier logs are dated observations, not a fallback list. `router_default` does not itself establish private or independently attested execution.

Optional provider address, signer and signature-service pins are configured together. Incomplete or invalid pins prevent the intended checked path. Registry observations and signed-response checks have narrower meanings than complete independent attestation. See `src/memoryseal/config.py` and `src/memoryseal/memory_service.py` for the current gates. Do not copy development verification exceptions into another deployment without understanding their effect.

## Acceptance is a separate decision

Strict retains the configured verification requirements. Standard is a signed owner rule for one agent and exact collection; eligible low-risk observations can be accepted with their original unverified status. Failed verification, suspicious instructions, conflicts and failed analysis do not qualify. Standard does not bypass a separately enabled pre-send connection check.

Existing quarantined records are not retroactively accepted. Readers still need current grants and eligible ancestry. See [memory acceptance](MEMORY_ACCEPTANCE.md).

## Evidence and limits

Live structured classifications and gateway writes have been observed, with dated results in [BUILD_RECORD.md](BUILD_RECORD.md). The deployed router path and the experimental bridge are separate implementations. Successful inference does not prove independent binding between a specific submitted request and an attested model execution.

The [verification report](0G_TEAM_VERIFICATION_REPORT.md) and [investigation notes](0G_BLOCKERS_SHORT.md) preserve earlier provider/baseline findings. They are historical investigation artifacts, not claims that all integration work remains undone. No complete independent request-bound verification pass is claimed here.

For a reproducible integration check, submit synthetic content through the agent workflow, inspect the classification and record the actual nonempty inference request ID returned by the service. A memory UUID, completion identifier or transaction hash is not interchangeable with the provider's request/signature reference. When a field is absent, report it as absent.

## Code map

- `src/memoryseal/inference.py`: router transport and structured response parsing.
- `src/memoryseal/memory_service.py`: permission checks, verification evidence and acceptance.
- `src/memoryseal/config.py`: configuration defaults.
- `integrations/zero_g/README.md`: optional experimental bridge and local verification tooling.

Configuration alone is not a successful inference check. Automated tests use controlled responses; they do not certify a live provider or cryptographic execution guarantee.
