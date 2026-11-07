# Arkiv entity schema

Source of truth: [provenance.mjs](../integrations/arkiv/provenance.mjs).

| Schema | Meaning | Fields added |
| --- | --- | --- |
| memoryseal.memory-event.v1 | Legacy creation | event_id, memory_id, owner, agent_id, event_type, commitment, parent_id, trust_class, status, policy_version |
| v2 | Creation | source_type |
| v3 | Current creation | agent_address |
| v4 | Legacy quarantine | actor_address |
| v5/v6 | Signed quarantine variants | request_audience, request_timestamp, request_nonce, request_body_sha256, request_signature |
| v7 | Agent origin acknowledgement | Same signed-event fields; agent is the signer |
| v8 | Owner review | Same signed-event fields; owner is the signer |
| memoryseal.vault-event.v1 | Encrypted vault lifecycle | event_id, memory_id, owner, agent_id, agent_address, actor_address, event_type, commitment, key_version, revision, status |

The abbreviated v2–v8 labels above use the `memoryseal.memory-event.` prefix. Fields are strings. Memory event_id, memory_id and owner are indexed; agent_address is indexed from v3, actor_address from v4. Vault event_id, memory_id, owner and agent_address are indexed.

Reads combine the exact schema with a trusted creator and memory_id or event_id. Filtering by creator prevents an unrelated wallet's same-schema record being treated as this publisher's record. Owner inside the payload is application identity, not entity ownership.

## Ownership and retention

The deployed publisher/initial entity owner is `0x80ce7202b4dab0653a410605f307ee5cd796db64`. End users do not hold the Arkiv publisher key. Entities are created with readonly attributes and a default expiration of 30 days; the helper accepts 1–365 days but the current publisher uses the default. No automatic renewal is promised. Expiry is appropriate for a bounded prototype audit window, not permanent archival retention. Owners retain the chain's supported ownership/lifecycle powers; readonly is not a permanence guarantee.

Memory text, collection names, source URLs, commitment salts, encryption keys and bearer credentials are excluded. Public owner/agent addresses and IDs are linkable. Signed lifecycle events carry request proofs; unsigned creation metadata is a publisher assertion, not proof that its content is true.

[Runnable query and live example](../README.md#query-real-arkiv-data).
