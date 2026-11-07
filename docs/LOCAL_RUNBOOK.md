# Local setup and first memory

Run commands from the repository root. You need Python 3.11+, Node.js 20+, npm and an EVM wallet for browser signing.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
npm ci --prefix integrations/arkiv
npm ci --prefix integrations/ens
npm ci --prefix sdk/typescript
npm run build --prefix sdk/typescript
npm ci --prefix web
.venv/bin/python scripts/init_local.py
```

The last command creates a private `.env` with a random encryption key and refuses to overwrite an existing file. Preserve the key for an existing database. The gateway loads `.env` from the current directory; keep secrets out of frontend variables and version control.

## Configure

| Setting | Purpose |
| --- | --- |
| MEMORYSEAL_DATABASE_URL | SQLite database location; default local file |
| MEMORYSEAL_ENCRYPTION_KEY | Ordinary-memory encryption key generated at initialization |
| MEMORYSEAL_REQUEST_AUDIENCE | Request signature audience; default memoryseal-local |
| MEMORYSEAL_DASHBOARD_ORIGINS | Exact browser origins; default http://localhost:3000 |
| MEMORYSEAL_ZERO_G_API_KEY / MODEL / NETWORK | Real inference configuration |
| MEMORYSEAL_ARKIV_PRIVATE_KEY | Dedicated public-event publisher |
| MEMORYSEAL_AUTO_PUBLISH | Enable background Arkiv publication locally |
| MEMORYSEAL_ENS_AUTO_REGISTER | Enable sponsored agent names after operator setup |

For provider routing and verification options, follow the [0G guide](0G_INTEGRATION_README.md). For names and registrar secrets, follow [ENS setup](ENS_AGENT_SETUP.md). A configured key does not establish funds, provider availability or verification. Without usable inference, ordinary writes can be held for review. The guided website requests ENS sponsorship and reports a configuration error if it is disabled; SDK registration can be used independently of the website's sponsored onboarding flow.

## Start

Terminal one:

```bash
umask 077
.venv/bin/uvicorn memoryseal.api:app --host 127.0.0.1 --port 8000
```

Terminal two:

```bash
NEXT_PUBLIC_GATEWAY_URL=http://localhost:8000 NEXT_PUBLIC_GATEWAY_AUDIENCE=memoryseal-local npm run dev --prefix web
```

Open http://localhost:3000. Both audience values must match. Remote gateways require HTTPS; use exact allowed origins without paths or wildcards. `/health` confirms startup, not external integration readiness.

## Create and use an agent

1. Connect the owner wallet and sign the readable login message.
2. In Agents, enter a label, the agent's public signing address and a collection. Choose initial read/write permissions and Strict or Standard acceptance. Sign the setup request.
3. If sponsorship is configured, the ENS job runs in the background. Its progress and transaction links appear on the agent card.
4. Switch to the agent wallet. Open Playground; registrations and collections load automatically.
5. Write a synthetic observation such as “The supplier lists delivery on Friday.” Choose Save memory and sign once.
6. Read eligible records using the valid session. If the observation is held, the owner can inspect it in Memories and review it when eligible.
7. Inspect its public provenance after the background publisher runs. A published transaction and a matched read observation are separate pieces of evidence.

A refresh preserves the unexpired login in the same tab. It does not preserve unlocked vault keys. A lost write response retains its request ID and exact payload; retry that payload rather than creating a new memory request.

## Teams and client encryption

Follow [organizations and vault](TEAM_VAULT_MULTICHAIN.md) for roles, identity backups, independently checked recipient fingerprints and key rotation. Ordinary memories and vault records have different trust paths: the vault never sends plaintext to the classifier.

## Onchain policy configuration

Use Settings at `/?devmode=true#settings` for Connections, Agent names and Onchain policies. A configured Sepolia deployment needs its RPC, chain ID, registry and executor. Multiple deployments use `MEMORYSEAL_CHAINS`. Registering an agent locally does not grant a contract permission or token allowance. See [the chain guide](TEAM_VAULT_MULTICHAIN.md#multiple-evm-chains).

## Checks

```bash
.venv/bin/python -m pytest
npm test --prefix integrations/arkiv
node --test integrations/ens/test/*.test.mjs
.venv/bin/python scripts/test_typescript_sdk.py
```

The SDK runner starts an isolated gateway; network/contract tests may require optional configuration. For contract tests, install `.[dev,contract-test]` and compile artifacts with `npm ci --prefix contracts` followed by `(cd contracts && node scripts/compile.mjs --with-test-token)`. Use an isolated checkout for `npm run build --prefix web` if a development server is active.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Empty workspace after deployment | Hosted SQLite is separate from the laptop database; account selection also changes the workspace |
| CORS error | Match the actual browser origin, including www, in the gateway allowlist |
| Signature rejected | Account, audience, exact payload, clock and current policy version |
| Memory held for review | Analysis, acceptance rule, current grants and parent eligibility |
| ENS waiting | Registrar balance, delegated role, RPC, quota and unresolved earlier jobs |
| Arkiv uncertain | Query/reconcile the existing event; do not blindly republish |
| Vault cannot decrypt | Correct identity backup, passphrase, recipient envelope and key version |

For deployment, storage and migrations use the [Railway guide](RAILWAY_DEPLOYMENT.md). Historical investigations remain in the build record; they are not prerequisite steps for a normal installation.
