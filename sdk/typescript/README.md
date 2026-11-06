# @memoryseal/sdk

Typed ESM SDK for Node 20+ and browsers with Web Crypto. It signs the same exact HTTP request format as the Python SDK, and provides organization, chain-observation and client-encrypted vault operations. This package is local to this repository; it has not been published to npm.

## Install and build

```sh
npm ci --prefix sdk/typescript
npm run build --prefix sdk/typescript
# From another project, install the local package directory:
npm install /absolute/path/to/memoryseal/sdk/typescript
```

The package exports `dist/index.js` and TypeScript declarations. No signing key is stored by the SDK. Supply a signer or use an EIP-1193 browser wallet:

```ts
import { MemorySealClient, walletSigner, chainAsset } from '@memoryseal/sdk';
const [address] = await window.ethereum.request({method: 'eth_requestAccounts'});
const client = new MemorySealClient(walletSigner(window.ethereum, address),
  'http://localhost:8000', 'memoryseal-local');
const agent = await client.registerAgent('0xYOUR_AGENT_ADDRESS', undefined, 11155111);
await client.grant({agent_id: agent.id, operation: 'read', resource: 'research'});
const asset = chainAsset(11155111, '0xYOUR_TEST_TOKEN_ADDRESS');
await client.grant({agent_id: agent.id, operation: 'transfer', resource: asset, max_amount: '100'});
```

An agent uses its own signer for `writeMemory`, `readMemory` and `simulateTransfer`. Addresses above are placeholders. `max_amount` and action amounts are decimal **strings**, avoiding JavaScript integer precision loss. A local simulation never sends tokens. Chain-qualified assets are exact strings; use the same `chainAsset` value for grant and simulation. Legacy raw-address grants remain supported and are not chain-qualified.

## Organizations

`createOrganization`, `organizations`, `organization`, `setMember`, `registerOrganizationAgent`, `grantOrganization` and `revokeOrganization` implement the team flow. Only the owner changes membership; the current membership version is required. Admins manage gateway agents/grants. Auditors read metadata. Organization custody remains with its owner wallet; team roles are not multisig signatures or contract delegation.

## Client-held encryption

1. `generateIdentity()` creates a P-256 encryption keypair. `exportIdentity(identity, passphrase)` produces an encrypted JSON backup; `importIdentity` restores it. Keep backups separately from their passphrase. Keys are independent of Ethereum signing keys.
2. Register only the public key with `registerEncryptionIdentity`. Verify recipient fingerprints independently before distributing namespace keys.
3. Generate a 32-byte namespace key with `newKey`. Wrap it separately for each authorized recipient using `wrapKey`; include the owner. Pass the independently verified fingerprint, not a value blindly trusted from the same gateway response.
4. Call `createVault(scope, fingerprint, envelopes)`. The SDK asks the **owner** to sign the complete key-version manifest, then signs the HTTP request. Agent read/write grants use the existing namespace capability system.
5. `vaultKey(scope, identity)` verifies the owner signature and recipient envelope hash before unwrapping locally. The SDK maintains a key-version high-water mark during its lifetime. Persist trusted scope IDs, owner addresses and latest versions in your application to detect rollback across restarts; server-provided discovery is not an independent identity proof.
6. `writeVault` encrypts content locally and submits ciphertext. `vaultRecords` returns encrypted records; use `openRecord` to authenticate, decrypt and check the salted content commitment. Managers can inspect quarantine; agents receive released records only.
7. `reviewVault` approves the exact ciphertext revision. This is human approval, not a claim that the server classified or independently verified the hidden content. Treat decrypted memories as untrusted data, never as authority.

```ts
import { newKey, keyFingerprint, wrapKey, type WrappedKey } from '@memoryseal/sdk';
const scope = {id: crypto.randomUUID(), owner_address: ownerAddress.toLowerCase(),
  namespace: 'private-research', active_version: 1};
const key = newKey();
const envelopes: Record<string, WrappedKey> = {};
for (const recipient of independentlyVerifiedRecipients) {
  const identity = await client.encryptionIdentity(recipient.address);
  envelopes[recipient.address.toLowerCase()] = await wrapKey(key, identity.public_key,
    recipient.pinnedFingerprint, scope.id, 1, recipient.address);
}
await client.createVault(scope, await keyFingerprint(key), envelopes);
```

The gateway sees owner, namespace, participants, record IDs, sizes, commitments, versions and timing. It never receives vault plaintext or raw namespace/private keys through the vault API. A compromised endpoint/browser or malicious delivered JavaScript can access an unlocked client; use a trusted client build. This is not a cryptographic guarantee of policy enforcement by a malicious gateway. Epoch signatures prevent undetected key substitution relative to the pinned owner and scope; they do not provide a global freshness oracle.

## Online rotation

Create new recipient envelopes for `scope.active_version + 1` using a **fresh** key and call `rotateVault(scope, fingerprint, envelopes)`. Fetch the latest scope. New writes must use the new version. Call `migrateVaultBatch(scope, identity)` repeatedly until `rotationStatus(scope).remaining` is zero. Each batch processes at most 50 records, checks the original commitment locally and updates ciphertext using a revision compare-and-swap. The owner must retain the old encryption identities needed to unwrap old versions.

Migration preserves IDs, content commitments, release status and the original write retry identity. A stale write or conflicting migration returns 409; refresh before proceeding. Do not delete old backups merely because the count is zero—verify the current data with the new keys and retain a tested recovery plan. Rotation cannot revoke previously downloaded plaintext or keys and does not securely erase old database/backup copies.

`vaultEvents` and `vaultEventAction` publish/query lifecycle metadata through Arkiv. Public vault events are gateway assertions; owner key-version signatures are verified separately. No plaintext, namespace name, ciphertext or key envelope is published by this projection.

## Error handling and tests

`GatewayError.status` distinguishes policy/conflict errors. `WriteOutcomeUnknown` retains the request ID **and exact payload**: preserve it and retry `writeMemory(payload)` or `submitVault(scope, payload)`. Never create a new ID after an uncertain submission. Signed requests reject redirects, require HTTPS outside loopback and use fresh nonces; no write is automatically retried. Network requests have a three-minute timeout and a bounded response reader. `request` also accepts an AbortSignal.

```sh
npm test --prefix sdk/typescript          # crypto test; HTTP test needs isolated gateway
.venv/bin/python scripts/test_typescript_sdk.py  # starts/stops unfunded gateway; runs all SDK + browser tests
```

See [the full system guide](../../docs/TEAM_VAULT_MULTICHAIN.md) for the browser walkthrough and deployment configuration.
