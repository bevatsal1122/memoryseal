# Automatic sponsored ENS registration (Sepolia)

Updated 7 November 2026. This guide covers the deployed Sepolia naming flow and setup for a new operator.

Users create an agent with the normal signed MemorySeal request. The gateway atomically creates the agent, its permissions and an ENS registration job. Users do not need the parent wallet, Sepolia ETH or ENS transaction confirmations. The service assigns a unique name such as `research-48271.memoryseal.eth` and pays Sepolia gas using a dedicated registrar. New names use five random digits, with database collision checks and onchain availability checks before signing. If the label is already used onchain, the unsubmitted job picks another suffix. Existing registered names are unchanged.

## Activate once

1. Deploy the backend and frontend changes.
2. Configure the backend variables below with a dedicated registrar key. For this existing deployment, preserve its configured key and other service variables. For a new deployment, create a separate registrar wallet; do not use the parent-owner key.
3. Fund registrar `0x10001C3e369DDA564Ff7d0d2C5e0fFfE267271B5` with Sepolia ETH. A small test balance, for example 0.02, is a starting point; monitor its balance and actual gas use.
4. Connect parent-owner wallet `0x0b0a492D98671d187036766a55016Bf4b80e873B` on Sepolia. Open `https://www.memoryseal.work/?devmode=true#settings`, select **Agent names → ENS operator setup → Configure sponsored registration**. The owner confirms three one-time transactions: deploy a UserRegistry with the owner's administration roles and the sponsor's registrar-only root role; set its canonical parent pointer; attach it to `memoryseal.eth`.
5. The setup verifies the factory implementation, exact transaction calldata, canonical registry and sponsor role. It refuses to replace an existing unrelated subregistry. If the parent already has a registry, grant its registrar root role to the sponsor through the existing registry's owner tools instead.
6. Create an agent from another wallet. Its card should advance from queued to registering to registered and show Sepolia transaction links. The gateway assigns `ens_name` only after the final address lookup matches the agent signing address.

The existing memoryseal.eth setup has completed. Its canonical subregistry is `0x828AfCc3D80C65C1620495e1E0EAF5c980D8F1C8`. The owner completed setup and subsequently observed successful sponsored registration and matching address resolution for an agent. Do not repeat initialization for this already-configured registry. These observations do not guarantee future RPC availability, gas balance or parent renewal. All transactions here are on Sepolia.

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

Public API responses include name, state, step and transaction hashes. They exclude signer secrets and raw signed transaction storage. Error logs do not print subprocess output or credentials. Agent cards poll using the existing read session without wallet prompts. A four-stage progress bar advances only after verified stages: register name, create resolver, connect name, verify address. The completed state is compact, with expandable transaction links.

## Validation and operational checks

Tests cover quotas, public-status filtering, persistence-before-broadcast, reuse of identical transaction bytes after retries, stage progression, revert handling, collision replacement and cancellation after revocation. Source tests live in `tests/test_ens_registration.py` and the ENS adapter test directory.

The user observed a completed live registration for `yoyo-d5547cb29f324332a56ced9dac29dc43.memoryseal.eth` resolving to `0x3f0bfca263b79737864fb891400680c767234e78`. That older name retains its original suffix; new names use five digits. See the [submission evidence](SUBMISSION.md#public-deployment-evidence).

For a new installation, verify the canonical parent/subregistry, delegated registrar role, available Sepolia gas, all four receipts and final forward resolution. A configured service or successful unit test is not a substitute for those checks.
