# Simpler MemorySeal workflows

Implemented November 7, 2026. These changes preserve owner-signed authority and scoped access while removing routine diagnostic steps from everyday use.

## Everyday flow

1. Connect a wallet and sign in once. The 30-minute session survives page refreshes in the same tab through sessionStorage, without extending its expiry. The app restores it only for the wallet’s currently connected account, gateway and audience. Sign out, account changes and chain changes clear it. Expired or revoked sessions require reconnecting. Storage-blocked browsers fall back to in-memory sessions. The short-lived browser session permits workspace reads and the exact agent memory-read endpoint. Mutations still require a signature.
2. In **Agents**, enter a friendly name, the agent's public wallet address, and a collection. Select read/write access and an acceptance policy. **Add agent and permissions** signs one atomic request. Registration, permissions, and acceptance policy succeed together or roll back together. Retries retain the request ID and cannot create duplicate grants.
3. Use the agent wallet in **Playground**. Its registrations and collections load automatically. Enter content and choose **Save memory**, then confirm one wallet signature. Success resets the editor. An uncertain response retains the original request for retry.
4. **Read memories** uses the existing login session; it does not request another wallet signature. Current permissions are checked server-side, including revocation.
5. In **Memories**, see compact cards with collection, friendly agent name, date, availability, and publication status. Filters update automatically. Inspecting verifies the content commitment automatically. Detailed IDs, provider evidence, related memories, and manual recovery are under expandable details.

## Acceptance and review

Strict remains the default. Standard is an explicit owner choice for an agent and collection: eligible low-risk observations can be accepted without individual owner review. Instructions, conflicts, failed analysis, and unsafe ancestry remain withheld. An unverified result is still labeled unverified. Acceptance never grants spending authority.

The review UI uses server-computed eligibility and does not offer an approval that the backend would reject. Existing quarantined memories are not silently released when a rule changes. Current read eligibility continues to enforce revocation and ancestry.

Optional origin acknowledgement remains available under **Additional proof**. It is not required for ordinary saving and still needs its separate signatures. It does not independently prove the content true.

## Automatic public receipts

The deployed startup script defaults `MEMORYSEAL_AUTO_PUBLISH=true`. With the dedicated Arkiv publisher configured, the gateway handles both ordinary-memory and vault outboxes in the background. Only event metadata is published, never plaintext memory content.

- Pending events are submitted through the existing atomic claim mechanism.
- Uncertain events are looked up, not blindly submitted again.
- Retries use persisted backoff, capped at an hour.
- Interrupted publishing claims get a grace period before reconciliation.
- A filesystem lock permits one scheduler per database on the host. Keep one Railway replica and the persistent volume.
- Existing pending events are eligible too. Configure `MEMORYSEAL_AUTO_PUBLISH=false` to retain manual publication.
- Missing credentials leave manual recovery available. Configured does not mean the provider is reachable or the wallet funded.

The memory list refreshes publication metadata periodically when no inspection is open. **View transaction** links remain available. Event history and manual reconciliation live under proof details; an uncertain receipt is never labeled published merely to simplify the interface.

## Other pages

- **Overview:** accurate workspace counts and a shorter getting-started guide; only recent activity is shown.
- **Agents:** friendly labels; addresses, ENS observations and chain settings in identity details. ENS observation is a read operation; naming transactions still require wallet confirmation.
- **Permissions:** grouped by agent. Signed grants and revocation retain their original checks.
- **Organizations:** automatic loading, automatic selection when there is one team, and separate member/agent/permission tasks.
- **Encrypted vault:** combined identity generation, encrypted backup download and registration; separate restore and lock controls. Public recipient fingerprints still require independent checking. Private writers use an agent picker. Keys remain in memory, not browser storage.
- **Vault rotation:** client-side decryption/rewrapping with a signed batch of at most five records, rather than one signature per record. The backend applies the batch atomically and checks scope, owner access, active key version and revisions. Lost-response exact retries are idempotent. Progress is refreshed after each batch.
- **Playground transfers:** human-readable token amounts, token decimal lookup, fresh policy version, simulation before execution, and receipt polling. Technical parameters and recovery tools remain available. Distinct onchain approvals are not silently combined.
- **Settings:** compact connection summary, with diagnostic and advanced ENS/onchain controls collapsed.

## Wallet confirmations that remain

| Action | Expected confirmations after login |
| --- | --- |
| Add personal agent + initial collection permissions + acceptance | 1 signature |
| Save ordinary memory | 1 signature |
| Read ordinary memory | 0 signatures during a valid browser session |
| Explicit owner review or permission change | 1 signature |
| Optional origin acknowledgement | Separate proof signatures remain |
| Register encryption identity | 1 signature; local backup download is also required |
| Create/rotate a vault epoch | Signed manifest plus signed API request remain |
| Rewrap existing vault records | 1 signature per batch of up to 5 |
| Onchain grant, allowance or transfer | Wallet confirmation for each required transaction |

A cancelled or expired login can require a new signature. Switching accounts or chains clears the browser session. No wallet confirmation is bypassed.

## Implementation map

- `web/components/AgentSetup.jsx`: guided atomic setup form and retry state.
- `web/components/MemoryProof.jsx`: compact proof summary and advanced recovery.
- `web/components/AgentWorkbench.jsx`: simplified write/read, optional proof and transfer flow.
- `web/components/TeamVaultPanel.jsx`: team navigation, vault setup and migration.
- `web/app/page.jsx`, `web/components/design/WorkspaceGuide.jsx`, `web/app/neobrutal.css`: workspace layout, summaries and progressive disclosure.
- `web/lib/browser-session.mjs`, `web/lib/gateway.mjs`, `src/memoryseal/auth.py`: exact read-only session allowance for `POST /memory/read`.
- `src/memoryseal/api.py`: atomic `/agents/setup`, workspace summary, GET ENS observation and scheduler lifecycle.
- `src/memoryseal/memory_service.py`: review eligibility.
- `src/memoryseal/publication_loop.py`, `outbox_worker.py`: persistent publication scheduling and safe reconciliation.
- `src/memoryseal/models.py`, `migrations.py`: schema 13, labels, setup receipts and outbox scheduling fields.
- `src/memoryseal/vault.py`: bounded atomic rewrap batches.
- `sdk/typescript/src/index.ts`, `src/memoryseal/client.py`: setup helpers; TypeScript batched migration.

## Deployment and validation

Deploy backend and frontend together, backend first. Back up the database volume before the schema 13 migration. Preserve the encryption key, publisher key, domain origins and existing provider configuration. Older gateways reject the newer schema; restore a backup for a deliberate rollback rather than running old code against it.

Validation performed locally: 266 Python tests passed, 6 skipped; 12 browser-transport tests passed; 4 TypeScript SDK tests passed, including live HTTP team isolation, encrypted sharing, rotation, rollback and exact batch retry. Production Next build passed. Browser QA used an isolated local database, synthetic inference and disposable wallet signing accounts: agent setup took one signature; saving took one signature; reading added none. These tests do not represent new production-chain transactions or a real MetaMask confirmation run.

## Memory relationship map

The Memories page includes an interactive bubble map of the current filtered results (up to 100 records per page). Arrows represent explicit parent-to-child relationships only. Green means available, peach means needs review, and lavender means currently withheld. Dashed bubbles mark parent IDs outside the current page or filters; **Find parent** performs the existing owner-scoped search. Bubble size reflects visible link count, not truth, confidence or importance.

Select a bubble to highlight its immediate connections and open the existing memory inspection flow. Pan by dragging the canvas; use zoom controls and Reset view. Bubbles support keyboard selection with Enter or Space. The original list and review controls remain available. No additional wallet signature or backend migration is introduced by the map.
