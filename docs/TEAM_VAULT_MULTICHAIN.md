# Organizations, TypeScript SDK, client encryption, rotation and multi-chain policies

Implemented for the current development gateway and dashboard on 6 November 2026. These features extend the existing owner/agent model. They do not turn the temporary non-private 0G route into private inference, add cross-chain bridges, or deploy/fund additional networks automatically.

## What is available

| Feature | Backend / SDK | Website |
| --- | --- | --- |
| Organization policies | Owner, admin and auditor roles; versioned membership; existing capability enforcement and audit trail | Organizations tab: create, list, membership, agent registration, grants and revocation |
| TypeScript SDK | Typed ESM package with wallet signing, memory operations, teams, chain observations and client crypto | Used by the new team/vault controls |
| Client-held encryption | Opaque encrypted records, recipient key envelopes, signed key manifests, local commitment verification | Encrypted vault tab: encrypted backups, public identity registration, creation, writing, reading and release |
| Online namespace-key rotation | Atomic key-version changes, stale-write rejection, resumable per-record compare-and-swap migration | Rotate, migrate next batch, check remaining records |
| Multiple EVM chains | Validated per-chain RPC/registry/executor configuration; request-scoped receipt checks; agent memory-policy chain binding | Configured deployment selectors in Integrations and Agent console |
| Vault provenance | Separate outbox using existing conservative publication/reconciliation; public metadata whitelist | Per-record lifecycle events and publish/reconcile/query controls |

## Upgrade and run

Keep the current `.env`, `.demo.env`, SQLite data and encryption key. Stop old gateway/outbox processes and take a consistent backup before upgrade. Schema **10** adds tables for organizations, client encryption identities, namespace key epochs, encrypted records and their outbox; it adds `agents.policy_chain_id`. No historical plaintext is automatically downloaded/re-encrypted, no wallet keys change, and no existing grant is silently converted into a team role.

```sh
npm ci --prefix sdk/typescript
npm run build --prefix sdk/typescript
.venv/bin/uvicorn memoryseal.api:app --host 127.0.0.1 --port 8000
```

Run `cd web && npm run dev` separately. The frontend's `predev`/`prebuild` scripts build the local SDK. The SDK's generated `dist/` is intentionally ignored by Git; build it after cloning. There is no npm publication or external deployment in this change.

## Organization walkthrough

1. Connect the owner wallet. In **Organizations**, give the team a name and choose **Create organization**. One organization is allowed per owner wallet, and it encompasses that wallet's existing gateway agents/capabilities.
2. Load/select the organization. Add a dedicated teammate address as **admin** or **auditor**. Every membership update signs the current organization version; stale versions return 409.
3. Connect the admin wallet. Load the team. Register an agent, grant exact `read`/`write` namespaces or a per-action transfer limit, and revoke a grant. These are the same `Agent` and `Capability` rows that ordinary memory operations enforce.
4. Connect the auditor. It can see team metadata but must be denied registration, grants, revocations and membership changes.
5. Only the owner can add/remove/promote members. Neither admin nor auditor can replace or remove the owner. Removing an admin prevents future team-management calls; it does not retrospectively revoke legitimate agent grants they created. Review/revoke those grants explicitly as needed.

Admin actions are attributed to the actual admin address in Activity. Membership authorization and mutations run under the same SQLite write lock, so membership cannot change between role checking and mutation. A reduced capability replaces previous grants for the same exact agent/operation/resource.

**Custody:** this organization is a wallet-owned gateway team, not a multisig or an independent contract account. An admin cannot sign the owner's token approvals, ENS transactions or protected-action grants. Existing owner-signed public memory reviews still require the owner wallet. Organization admins can manage encrypted-vault review/migration when given the required decryption keys, but new namespace key manifests require an owner signature. Auditors get no plaintext access through team membership.

## Client-encrypted vault walkthrough

Use a new namespace such as `private-research`. The existing **Memories** screen is the gateway-encrypted/inference workflow; **Encrypted vault** is a separate client-encrypted mode. Choosing the mode explicitly prevents silent loss of classification or decryption capability.

### A. Prepare encryption identities and capabilities

1. For each participating wallet—owner and relevant agents—open **Encrypted vault**.
2. Enter a strong backup passphrase (at least 12 characters), generate an encryption identity, and download its encrypted JSON backup. Confirm the download is safely stored. The UI enables public registration after the download is requested; it cannot prove your backup was saved or remains recoverable.
3. Choose **Register public identity**. Only the public key reaches the gateway. Keep the encrypted backup and passphrase separately. A reload, wallet/account change, or **Lock encryption identity** clears in-memory access; restore from the file to unlock again.
4. Share each identity's **public fingerprint** through an independently trusted channel. Never share private keys, namespace keys, passphrases or decrypted content in chat.
5. As owner or team admin, grant the writer `write` and reader `read` on the exact new namespace. Writers receive the namespace encryption key too; cryptographic key possession is broader than the API's read/write distinction. Use separate namespaces where writers must not possess the same secret as readers.

### B. Create the encrypted namespace

1. Connect the owner and unlock its encryption identity.
2. Expand **Create a namespace or prepare rotation recipients**. Enter the owner address and new namespace.
3. Enter one line per recipient: `wallet_address verified_fingerprint`. Include the owner, writer and reader. Recipient public identities and current access must exist.
4. Create the namespace. The browser generates a random key, encrypts a separate key envelope for each recipient, asks the owner to sign the manifest, then signs the API request. Raw keys remain local.

A namespace containing existing ordinary memories cannot be converted in place. Use a new namespace, explicitly inspect/export/re-encrypt selected historical content if needed, and preserve the old data/keys until the migration is verified. Old server-held copies remain server-held; creating a vault does not erase them.

### C. Write, inspect and share

1. Connect the agent wallet and restore its encryption identity. Load accessible namespaces, select the namespace and enter the agent registration UUID from **Agent console**.
2. Write a test observation. The browser encrypts it before the signed vault request. It starts quarantined. An uncertain submission retains the same record ID and ciphertext for retry while the page stays open.
3. Connect the owner, restore its identity, fetch/decrypt records locally and review the exact displayed content. Check the review box and sign release. Revision and ciphertext digest checks reject stale review attempts.
4. Connect the reader, restore its identity and fetch/decrypt. Only released records are returned, and current namespace grants are checked. Without a matching private key/envelope, the ciphertext remains unreadable.
5. Quarantine the record again and verify it is absent from subsequent agent reads. Revoking namespace access blocks subsequent record/key-envelope retrieval; it cannot erase already downloaded data.

**Inference distinction:** the gateway cannot classify this hidden plaintext, so vault writes never invoke 0G. Release is explicit human authorization to share, not the ordinary server classifier's verdict and not independent attestation. The server cannot prove the reviewer decrypted/read the record or that the content is safe. Treat all decrypted content as untrusted data; spending remains protected by separate capabilities and contracts. If you need model classification of client-encrypted data, a separately designed client-to-attested-provider channel is still required.

## Online rotation and recovery

1. Revoke removed agents' local grants first. If required onchain namespace checks are enabled, revoke the corresponding onchain access separately. Remove former recipients from the new key recipient list.
2. Unlock the owner's encryption identity. Prepare verified recipient fingerprints, including the owner, and click **Rotate to a fresh key**. The signed manifest contains the namespace identity and new version. The gateway atomically increments the active version with an expected-version check.
3. New writes use the new version immediately; old-version writes are rejected. Existing readable records remain accessible with the appropriate old keys during migration.
4. Click **Migrate next batch** repeatedly. Each batch reads at most 50 old-version records, decrypts/authenticates locally, checks the unchanged salted commitment, encrypts with the active key, and uploads with the expected record revision. IDs, commitments, release status and original write retry identity are preserved.
5. Check **rotation progress** until `remaining = 0`. Re-read samples with the new key and test intended recipient access before retiring any old identities or backups. The SDK returns remaining counts and can resume after interruption. If another rotation/review changes a revision, refresh and retry the batch; it does not overwrite concurrent changes blindly.

This is online **client-held namespace data-key rotation**. Legacy gateway-held encryption still uses the existing offline snapshot procedure. It is not global master-key rotation or online migration of every historical storage mode. Removed recipients retain old downloaded keys/plaintext; previously captured ciphertext remains decryptable with the corresponding old key. Old databases, WAL pages, Arkiv commitments and backups are not securely erased. If the owner's old private encryption identity is lost, the server cannot recover old namespace keys; preserve backups or another explicitly authorized recovery recipient.

Identity replacement is separate: `registerEncryptionIdentity(newPublicKey, expectedOldFingerprint)` uses compare-and-swap. Replacing the identity pointer does not rewrite old envelopes. Keep the old identity to migrate its records, create fresh key-version envelopes for the new identity, and verify recovery before retiring it. The website deliberately does not silently overwrite an existing identity.

## Cryptographic protocol and trust boundaries

- Payload encryption: AES-256-GCM with independent random 96-bit nonces. The private payload contains UTF-8 content and a random 32-byte commitment salt.
- Commitment: SHA-256 of `memoryseal:commitment:v1\0 || salt || content`. The salt is inside the encrypted payload. Rotation preserves it and the commitment.
- Payload additional authenticated data: JSON array of protocol version, namespace UUID, owner address, namespace name, record UUID, key version and content commitment. Swapping records/scopes/versions fails local authentication.
- Key envelopes: ephemeral P-256 ECDH, HKDF-SHA-256 and AES-256-GCM. Wrapping context includes namespace UUID, version, recipient wallet and pinned recipient public-key fingerprint. Each envelope names the recipient fingerprint.
- Key-version manifest: owner EIP-191 signature over canonical JSON binding namespace identity, version, namespace key fingerprint and the hash of every recipient envelope. SDK unwrapping checks the signature, selected envelope hash and key fingerprint. The same wallet also signs the API request, binding its method/path/body/nonce/time.
- Identity backups: PBKDF2-HMAC-SHA-256, 600,000 iterations, random 16-byte salt and AES-256-GCM; backup format `memoryseal.identity.v1`.

The server observes metadata, sizes and timing. Pin the owner, namespace ID and recipient fingerprints independently; discovery from one server is not an independent identity proof. Keep a trusted latest key version across application restarts: the SDK's in-memory high-water mark cannot establish global freshness for a new device. Server-side authorization still assumes an honest gateway, while payload confidentiality depends on uncompromised client-held keys and authentic client code. This is custom application code with automated tests, not an external cryptographic security audit.

## Multiple EVM chains

Set `MEMORYSEAL_CHAINS` in the local gateway environment to a JSON array. Each entry requires `chain_id`, `name`, `rpc_url`, `registry`, and `executor`. Example structure (replace addresses with actual deployments):

```json
[
  {"chain_id":31337,"name":"Local A","rpc_url":"http://127.0.0.1:8545","registry":"0x1111111111111111111111111111111111111111","executor":"0x2222222222222222222222222222222222222222"},
  {"chain_id":31338,"name":"Local B","rpc_url":"http://127.0.0.1:8546","registry":"0x3333333333333333333333333333333333333333","executor":"0x4444444444444444444444444444444444444444"}
]
```

The addresses above are examples, not deployments. Duplicate IDs, invalid addresses and insecure non-loopback HTTP RPC URLs are rejected. RPC credentials remain server-side; `GET /chains` exposes only chain IDs, display names and contract addresses. Existing single-chain environment settings remain the default. An explicit entry for the same ID takes precedence for explicitly selected requests.

Use the existing `contracts/scripts/deploy.mjs` with `MEMORYSEAL_RPC_URL`, `MEMORYSEAL_CHAIN_ID` and a local deployer key to deploy registry/executor contracts on the chosen EVM network. It verifies the RPC's chain ID before signing. Its optional test-token deployment remains restricted to the original approved test chains. Deployment and gas funding on additional live chains are separate operator actions; none were performed here.

In **Integrations**, check configuration and choose the configured deployment before grants or allowances. In **Agent console**, load configured contracts and choose the same chain for execution. The wallet must also be on that chain. Deployment observations, grant/transfer receipts and token-balance observations use the explicitly selected chain, without changing global settings. Contract code comparisons, agent identity and policy-version checks remain in place.

For optional onchain memory enforcement (`MEMORYSEAL_REQUIRE_ONCHAIN_MEMORY=true`), register an agent with `policy_chain_id` to bind its namespace checks to a configured chain; omitted bindings use the legacy default. Both ordinary and vault memory operations honor this setting and fail closed on unavailable chain policy. Existing agents are not silently rebound.

Keep local transfer resources chain-qualified using SDK `chainAsset(chainId, token)` (for example `eip155:31337/erc20:0x...`) in both grants and simulation. Legacy raw-address grants remain chain-agnostic strings. Real spending is always subject to the selected chain's own registry, allowance and executor. Policies/budgets are not automatically synchronized or bridged between chains. ENS and Arkiv remain their configured services; this feature adds EVM policy/action deployments, not non-EVM or cross-chain consensus.

## Public provenance

Vault writes, releases, quarantine and rewraps queue separate `memoryseal.vault-event.v1` events. The public projection includes event/record/agent IDs, wallet addresses, commitment, key version, revision and status. It excludes plaintext, namespace names, ciphertext and wrapped keys. Vault events are publisher/gateway assertions, not publicly verified reviewer signatures or model attestations. Signed key-version manifests are verified separately by the client.

Owners/admins use the record's event controls to publish pending metadata, reconcile uncertain outcomes without republishing, and query published records. Existing creator pinning, publication attempt IDs and conservative state transitions are reused. A `publishing` event left by a stopped worker needs operator recovery after establishing that the process stopped; no timeout is treated as permission to blindly republish. Public RPC observations do not establish finality, completeness or truth. The worker CLI accepts `--vault`; after proving an interrupted publisher has stopped, use `--vault --recover-interrupted EVENT_ID`, then `--vault --reconcile EVENT_ID`. Neither recovery nor reconciliation republishes the event.

## API / implementation map

| Area | Key endpoints | Files |
| --- | --- | --- |
| Team roles | `/organizations`, `/{id}/members`, `/{id}/agents`, `/{id}/capabilities`, `/{id}/revoke/{kind}/{id}` | `src/memoryseal/organizations.py`, `models.py` |
| Encryption identities | `/vault/identity`, `/vault/identity/{address}` | `src/memoryseal/vault.py`, `sdk/typescript/src/crypto.ts` |
| Key versions | `/vault/namespaces`, `/{id}/epochs/{version}`, `/{id}/rotate`, `/{id}/rotation` | `vault.py`, `sdk/typescript/src/index.ts` |
| Encrypted records | `/vault/namespaces/{id}/records`, `/{record}/review`, `/{record}/rewrap` | `vault.py`, `crypto.ts` |
| Vault provenance | `.../records/{record}/events`, `.../events/{event}/{action}` | `outbox_worker.py`, `integrations/arkiv/provenance.mjs` |
| Chains | `/chains`; existing `/onchain/observe-deployment` and `/actions/observe-*` accept signed `?chain_id=` | `networks.py`, `config.py`, `api.py` |
| Website | Organizations, Encrypted vault, chain selectors | `web/components/TeamVaultPanel.jsx`, `AgentWorkbench.jsx`, `web/app/page.jsx` |

The [TypeScript SDK README](../sdk/typescript/README.md) lists usage, types, retry handling and packaging. The Python SDK gains organization discovery/management, encrypted-record queries, rotation status and chain selection; client cryptographic operations in this release are implemented in the TypeScript SDK used by the browser.

## Validation and what you still supply

Automated verification covers signed HTTP interoperability, role isolation, encrypted writes and release, manifest tampering, wrong keys/passphrases, context substitution, online rotation, stale revisions, exact write retries and revocation. The runner checks that plaintext markers do not appear in the test database. Two independent local EVMs test different limits at identical contract addresses, successful transfer on one chain, failure on the other and wrong-chain refusal. Legacy tests remain part of regression validation.

```sh
.venv/bin/pytest -q
.venv/bin/python scripts/test_typescript_sdk.py
npm test --prefix integrations/arkiv
npm run build --prefix web
```

Use the private/default verification environment for legacy tests if your development `.env` intentionally relaxes 0G connection checks. No live compute credits or additional deployment funds are required by the isolated SDK runner. Live MetaMask acceptance, identity backup retention and independently checked recipient fingerprints are your remaining test/setup actions. For another live chain, supply its RPC and verified deployed contract addresses and fund only the intended test wallets. The 0G private-inference blocker remains separate.
