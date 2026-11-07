# Automatic sponsored ENS registration (Sepolia)

Users create an agent with the normal signed MemorySeal request. The gateway atomically creates the agent, its permissions and an ENS registration job. Users do not need the parent wallet, Sepolia ETH or ENS transaction confirmations. The service assigns a unique name such as `research-48271.memoryseal.eth` and pays Sepolia gas using a dedicated registrar. New names use five random digits, with database collision checks and onchain availability checks before signing. If the label is already used onchain, the unsubmitted job picks another suffix. Existing registered names are unchanged.

## Activate once

1. Deploy the backend and frontend changes.
2. Add the entries from the ignored, mode-0600 local `.env.railway-ens` file to Railway, preserving existing variables. Never paste the key into chat or commit it. This file was generated for this deployment and contains a dedicated key, not the parent-owner key.
3. Fund registrar `0x10001C3e369DDA564Ff7d0d2C5e0fFfE267271B5` with Sepolia ETH. A small test balance, for example 0.02, is a starting point; monitor its balance and actual gas use.
4. Connect parent-owner wallet `0x0b0a492D98671d187036766a55016Bf4b80e873B` on Sepolia. Open **Integrations → ENS → ENS operator setup → Configure sponsored registration**. The owner confirms three one-time transactions: deploy a UserRegistry with the owner's administration roles and the sponsor's registrar-only root role; set its canonical parent pointer; attach it to `memoryseal.eth`.
5. The setup verifies the factory implementation, exact transaction calldata, canonical registry and sponsor role. It refuses to replace an existing unrelated subregistry. If the parent already has a registry, grant its registrar root role to the sponsor through the existing registry's owner tools instead.
6. Create an agent from another wallet. Its card should advance from queued to registering to registered and show Sepolia transaction links. The gateway assigns `ens_name` only after the final address lookup matches the agent signing address.

The ENS app's testnet dollar display is not a requirement to buy real assets. All transactions described here are on Sepolia. The parent `memoryseal.eth` has been observed owned by the wallet above; its subregistry was still absent at implementation time. Operator setup and live end-to-end registration must be confirmed after deployment, not inferred from test success.

## Railway variables

```dotenv
MEMORYSEAL_ENS_AUTO_REGISTER=true
MEMORYSEAL_ENS_PARENT=memoryseal.eth
MEMORYSEAL_ENS_NETWORK=sepolia
MEMORYSEAL_ENS_RPC_URL=https://ethereum-sepolia-rpc.publicnode.com
MEMORYSEAL_ENS_REGISTRAR_PRIVATE_KEY=<dedicated registrar key>
MEMORYSEAL_ENS_REGISTRATION_PER_OWNER_DAY=5
MEMORYSEAL_ENS_REGISTRATION_GLOBAL_DAY=50
MEMORYSEAL_ENS_REGISTRATION_MAX_FEE_GWEI=20
```

Keep one Railway replica with the persistent `/data` volume. No frontend private key or `NEXT_PUBLIC` signer setting is needed. The backend is the source of truth for naming. Use this signer exclusively for this worker; unrelated transactions from the same signer can disrupt nonce recovery. Preserve the key across deployments and drain/reconcile jobs before replacing it.

## Registration and ownership

Each job registers a new subname, deploys a dedicated resolver, attaches it and writes the agent address. Four ENS transactions run in the backend, not four user approvals. The sponsor retains the subname and resolver administration; these are **platform-managed names**, not independently owned user domains. The parent's administrator retains its own powers. Names are not proof of agent trust or memory authorization.

The expiry requested is one year from creation. Parent expiry or removal of its registry can invalidate child resolution sooner. Automatic renewal is not implemented. Revoking an agent cancels an unsubmitted job; it does not remove already-published ENS records. Gateway revocation continues to prevent access regardless of ENS state.

## Durability and limits

SQLite schema 14 adds `ens_registration_jobs`. Jobs are queued within the same transaction as agent creation. `/agents/setup` remains idempotent: repeating the same request ID does not create a second agent or ENS job. `/agents/register` also queues ENS when sponsorship is enabled. The guided website requests sponsorship explicitly and returns a configuration error instead of silently promising registration when the service is disabled.

The worker uses a process lock and serializes the dedicated signer's queue. A Node adapter prepares and signs one transaction **without broadcasting**. The gateway commits its exact signed bytes, hash and expected context before broadcasting. If submission or receipt lookup times out, the worker broadcasts only the same bytes and checks the same hash. A restart does not prepare a replacement transaction with a fresh nonce. Successful receipts are verified against expected calldata and ENS state before advancing. A revert stops the job for operator review; verification failures and transient errors back off without claiming success. An unresolved job blocks later nonce allocation.

Authenticated owners are limited to 5 jobs per rolling 24 hours by default, with a global 50-job ceiling and 20 gwei maximum fee. Failed and cancelled attempts still count. The global ceiling bounds multi-wallet abuse; per-wallet limits are not a Sybil-proof identity system. Successful agent creation and memory permissions do not depend on the ENS network finishing immediately.

Public API responses include name, state, step and transaction hashes. They exclude signer secrets and raw signed transaction storage. Error logs do not print subprocess output or credentials. Agent cards poll using the existing read session without wallet prompts.

## Validation

The full Python suite passed: 270 passed, 6 skipped. ENS Node adapter tests passed, and an isolated production frontend build passed. Added tests cover quotas, public-status filtering, persistence-before-broadcast, crash/retry reuse of identical transaction bytes, stage progression, revert handling and revocation cancellation. A read-only Sepolia simulation successfully deployed the planned UserRegistry initialization for the actual owner and dedicated sponsor; no transaction was broadcast by that simulation.

Live operator setup, registrar funding and another-wallet agent registration remain deployment checks. Never describe them as completed until receipts and forward resolution have been observed.
