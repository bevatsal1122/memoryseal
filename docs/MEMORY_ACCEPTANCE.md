# Owner-controlled memory acceptance

Memory acceptance is separate from capability grants and transfer authority. Strict remains the default. No deployment environment flag needs changing to use Standard.

## Website

1. Open **Permissions → Memory acceptance** as the workspace owner.
2. Choose an agent and an exact namespace (for example `research`).
3. Select **Standard** and sign the policy update once.
4. Ensure the agent separately has a write capability for that namespace.
5. Submit a new low-risk observation from the agent. Eligible observations are accepted automatically, retaining their original inference status and untrusted source classification.
6. Readers still need their own read capabilities. All configured onchain memory checks continue to apply.

Standard requires valid structured analysis with category `observation`, risk `low`, recommendation `accept`, no suspicious instruction, and no reported conflicts. Only agent-source memories qualify. Unverified, router-verified, or pinned-signature-verified responses can qualify; failed verification, failed/missing analysis, and stale policy context cannot. Deterministic authorization-claim checks and ancestry checks still apply. Model classification can be wrong: Standard explicitly trades independent inference verification for owner-authorized automatic processing, not a guarantee of safety or truth.

Rules are scoped to an owner-owned agent and exact namespace, with no wildcard. A rule does not grant write/read access or authorize financial actions. Encrypted vault records and organization permissions are unchanged.

## Existing records and revocation

Existing quarantined memories are not retroactively accepted. Review them individually or submit a new observation with a new request ID. Idempotent retries retain their original outcome.

Switching a rule back to Strict withholds unreviewed Standard-accepted memories from agent reads (including their dependent descendants), without rewriting historical stored status. Revoking the writer also withholds these automatically accepted records. Explicit owner review remains a separate decision. Restoring Standard can make previously automatically accepted records eligible again when all checks pass.

Strict retains the deployment's existing verification policy; the older operator `allow_unbound_inference` setting is unchanged. On the current deployment it is false. Standard does not bypass a separately enabled requirement for connection attestation.

## API and SDKs

`GET /capabilities` returns `acceptance_rules` alongside the current policy version.

Owner-signed `POST /acceptance-rules`:

```json
{"agent_id":"AGENT_UUID","namespace":"research","mode":"standard","policy_version":6}
```

A stale policy version returns 409. Successful updates advance the owner policy version and append an `acceptance_policy_changed` audit event. Browser read-session tokens cannot authorize this mutation.

Python: `owner.set_acceptance_rule(agent_id, "research", "standard", policy_version=version)`.

TypeScript: `owner.setAcceptanceRule({ agent_id, namespace: "research", mode: "standard", policy_version: version })`.

Memory metadata exposes `auto_accepted`, and the website labels records accepted under Standard. Inference status is not upgraded to verified. Arkiv publication remains the separate provenance workflow.

## Deployment

Deploy backend and frontend. Backend startup migrates SQLite to schema 12, adding the rule table and an automatic-acceptance marker that defaults false for existing records. Back up the persistent database before deployment; older gateways reject this newer schema. No existing workspace is opted into Standard automatically.

## Implementation

- `src/memoryseal/models.py`, `migrations.py`: scoped rules and migration.
- `src/memoryseal/api.py`: signed policy updates, audit events, rule listing.
- `src/memoryseal/memory_service.py`: write eligibility and current-policy ancestry checks.
- `src/memoryseal/client.py`, `sdk/typescript/src/index.ts`: SDK helpers.
- `web/app/page.jsx`: owner settings and acceptance labels.
- `tests/test_acceptance_policy.py`: owner isolation, stale versions, exact scopes, risky analysis, ancestry, strict rollback and revocation.
