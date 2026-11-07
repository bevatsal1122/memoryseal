# How MemorySeal uses Arkiv

1. The gateway commits a memory lifecycle change and an outbox event together.
2. The worker validates a strict public-field projection and checks for an existing event by trusted creator plus event ID.
3. It creates a readonly entity on Rabdi with @arkiv-network/sdk and 30-day retention.
4. The memory view exposes publication status and a transaction link. Its provenance observation reads Arkiv and compares the record against the expected local event.
5. An ambiguous result is reconciled through reads rather than automatically creating another entity.

The [adapter](../integrations/arkiv/provenance.mjs) implements publication and filters; [publisher](../integrations/arkiv/publish.mjs) handles lookup-before-write; [query CLI](../integrations/arkiv/query.mjs) allows independent reads. The interface is therefore backed by both writes and reads, not an installed-but-unused SDK.

## What each feature changes for users

| Feature | User consequence |
| --- | --- |
| creator + memory_id filter | Inspect the configured publisher's events for one memory |
| creator + event_id filter | Reconcile a specific uncertain event without blind resubmission |
| readonly attributes | Keep separate lifecycle events rather than silently editing their attributes |
| wallet ownership | Identify the platform publisher independently of agent metadata |
| explicit expiry | Bound retention; missing expired data is not described as never having existed |
| public query | Review provenance without a MemorySeal account or private database access |

The current query returns a single page and handles each schema separately. It is not an exhaustive graph index or permanent archive. The 30-day default fits the prototype review window; retention configuration and renewal UX are future work.

Run the exact query and view the example transaction in the [README](../README.md#query-real-arkiv-data). Automated adapter checks: `npm test --prefix integrations/arkiv`.
