# Deploy the MemorySeal gateway on Railway

The public frontend is `https://www.memoryseal.work` (hosted on Vercel). Railway runs the Python gateway. This repository now contains a backend `Dockerfile`, `railway.toml`, a restricted Docker build context, and a startup script.

## 1. Publish the deployment files

Commit and push the changes to the GitHub branch Railway will deploy. These instructions do not themselves publish changes or create a Railway service.

In Railway, create a project/service from this repository. Use the **repository root**, not `web/` or `src/`. The root Dockerfile builds the gateway, Node ENS/Arkiv adapters and local contract artifacts. Leave custom Build Command and Start Command unset; the image starts the gateway itself on `0.0.0.0:$PORT` with one worker. `railway.toml` selects the Dockerfile and `/health` readiness check.

## 2. Attach persistent storage

Attach a volume to this service at **`/data`**, then keep the service at **one replica in one region**. Do not add PostgreSQL as a drop-in replacement: current gateway queries and migrations are SQLite-specific.

The startup script refuses Railway startup without a volume or with a database outside it. Database migrations run during gateway startup, after Railway mounts the volume; do not add a separate pre-deploy migration command. Back up the volume before importing a database or deploying schema changes.

## 3. Set Railway service variables

```text
MEMORYSEAL_DATABASE_URL=sqlite:////data/memoryseal.db
MEMORYSEAL_REQUEST_AUDIENCE=memoryseal-local
MEMORYSEAL_DASHBOARD_ORIGINS=https://memoryseal.work,https://www.memoryseal.work
MEMORYSEAL_ENCRYPTION_KEY=<your base64-encoded 32-byte encryption key>
```

There are **four slashes** after `sqlite:`. Railway supplies `PORT` and volume metadata; do not manually invent `RAILWAY_VOLUME_MOUNT_PATH`. Keep the existing audience unless changing both backend and frontend together.

For an existing database, use its existing `MEMORYSEAL_ENCRYPTION_KEY` from your local configuration. Copy that value directly into Railway Variables, never into chat or a Git commit. Preserve this key across deployments. A new key cannot decrypt old ordinary memories.

For a brand-new database, generate a new key locally. On your Mac, this copies a new random key to your clipboard without printing it:

```sh
openssl rand -base64 32 | pbcopy
```

Paste it into Railway's `MEMORYSEAL_ENCRYPTION_KEY` value and retain a secure backup. Do not regenerate it on each restart. Client-held vault identity backups are separate and remain the recipients' responsibility.

## 4. Configure the integrations you intend to use

A healthy gateway can serve wallet authentication, registrations, team policies and encrypted-vault APIs without funded external integrations. External features require their backend configuration:

| Integration | Variables to transfer deliberately from your local configuration |
| --- | --- |
| ENS observations | `MEMORYSEAL_ENS_RPC_URL`, `MEMORYSEAL_ENS_NETWORK` |
| EVM observations | `MEMORYSEAL_ONCHAIN_RPC_URL`, `MEMORYSEAL_ONCHAIN_CHAIN_ID`, `MEMORYSEAL_ONCHAIN_REGISTRY`, `MEMORYSEAL_ONCHAIN_EXECUTOR`, or configured `MEMORYSEAL_CHAINS` |
| Arkiv publishing | Dedicated test publisher `MEMORYSEAL_ARKIV_PRIVATE_KEY`, `MEMORYSEAL_ARKIV_CREATOR_ADDRESS`, and access key if used |
| 0G inference | `MEMORYSEAL_ZERO_G_API_KEY`, `MEMORYSEAL_ZERO_G_MODEL`, network/trust-mode settings and any corresponding provider pins |

Keep private keys, encryption keys and provider credentials **only in backend variables**, never in `NEXT_PUBLIC_*` settings. Do not upload the entire local `.env`: it may include deployment/owner keys that the server does not need.

The Docker image includes ENS/Arkiv Node adapters and freshly compiled policy/executor artifacts. It does **not** include the operator-reviewed 0G bridge or `pcverify` binaries. macOS executable paths will not work inside Linux. Strict inference remains fail-closed unless its required Linux verifier is separately provided. Hosting does not fix the previously discussed provider baseline/attestation limitation. If retaining the temporary non-private test route, deliberately reproduce its existing trust-mode settings and use synthetic content; do not weaken production verification merely to make a healthcheck pass.

The deployment startup script defaults `MEMORYSEAL_AUTO_PUBLISH=true`. With an Arkiv publisher configured, a background worker publishes queued public event metadata and checks uncertain submissions without resending them. It uses durable backoff and an OS lock on the database volume. Set `MEMORYSEAL_AUTO_PUBLISH=false` to retain manual publication. This also processes existing pending events; it never publishes plaintext memory content. Keep one replica. The current schema is version 14, including scheduling, setup receipts and ENS registration jobs; back up the volume before migrations.

## 5. Deploy and obtain the gateway URL

Deploy the service after configuring its volume and variables. Generate a public Railway domain for the gateway using the service's networking settings. Open:

```text
https://YOUR-RAILWAY-DOMAIN/health
```

Expected response:

```json
{"status":"ok"}
```

Health confirms startup/migrations completed; it does not prove external provider availability, wallet authorization, balances, attestation or finality. Do not disable authentication on `/agents` to make a browser check pass.

## 6. Connect Vercel

Set these **frontend build environment variables** in the Vercel environment used by the website:

```text
NEXT_PUBLIC_GATEWAY_URL=https://YOUR-RAILWAY-DOMAIN
NEXT_PUBLIC_GATEWAY_AUDIENCE=memoryseal-local
```

Use the HTTPS origin only, without `/health`, `/api`, credentials or query strings. Redeploy the frontend so Next.js embeds the new values. A hosted frontend pointing at localhost requires a build-time gateway URL correction.

Return to `https://www.memoryseal.work`, connect the wallet, and sign the login message. Subsequent supported reads reuse that session. Wallet connection itself does not require a token payment. If you see a CORS error, verify the backend's exact allowed origin. If signatures are rejected, verify both audience settings and the client clock.

## Existing laptop data

A fresh Railway volume starts an **empty workspace**, even with the same owner wallet. This is expected; local registrations, capabilities, memories and audit records are not automatically copied. For an existing-data migration, first create a consistent SQLite backup (using SQLite's backup API or stopping all writers), keep the matching encryption key, and import it into the volume while the Railway gateway is stopped. Do not overwrite a live database or upload private backups to GitHub. Handle any outbox rows left in `publishing` using the documented recovery/reconciliation process, not a blind retry. Client identity backups must still be restored separately in the browser.

## Validation and limits

`tests/test_railway_start.py` checks invalid key/volume/database rejection, actual gateway startup, `/health`, the Vercel CORS origin, rejection of unsigned reads, and database persistence across restart using an isolated temporary directory. It does not test Railway's volume infrastructure or build the Linux Docker image.

The existing Railway service has been deployed and exercised. The live observations below are dated checks; use `/health` and authenticated integration observations to assess a current deployment.

Sources: [Railway Dockerfiles](https://docs.railway.com/builds/dockerfiles), [volumes](https://docs.railway.com/volumes), [configuration as code](https://docs.railway.com/config-as-code/reference), [health checks](https://docs.railway.com/deployments/healthchecks).


## November 6 live integration setup

The missing ENS, Sepolia observer and Arkiv publisher variables were transferred using the local, gitignored `.env.railway-integrations` file. This file contains a private publisher key: do not commit, share or paste it into chat. Import only its integration entries into Railway; preserve the deployed database URL, encryption key, dashboard origin, audience and 0G configuration.

The deployed readiness endpoint confirmed all integration configuration flags. Live 0GM classification, quarantine, denied reads and revoked writes passed. Arkiv publication and independent record observation passed. The existing Thirdweb Sepolia endpoint worked locally but the Railway contract and ENS observations failed; PublicNode was checked locally as a replacement at `https://ethereum-sepolia-rpc.publicnode.com`. After changing both Railway RPC variables, the live ENS and contract observations passed; both runtime bytecodes matched the local artifacts. Configuration presence alone is not service readiness.

The ENS parent and deployed contracts are shared testnet infrastructure; the owner's local registrations and permissions are not automatically imported into Railway. Users still register agents and grant their own capabilities in their connected-wallet workspace. Onchain transactions require the appropriate wallet, chain, gas and token allowance. No new chain or real-money deployment is implied by configuring the Sepolia observer.

The apex domain redirects to `https://www.memoryseal.work/`. Both origins must be listed explicitly in `MEMORYSEAL_DASHBOARD_ORIGINS`; allowing the apex alone does not allow the redirected website.

### Sponsored Sepolia ENS

See [ENS_AGENT_SETUP.md](ENS_AGENT_SETUP.md) for the dedicated registrar variables, one-time parent authorization, persistent transaction queue and user flow. Do not use the parent-owner or Arkiv publisher key as the ENS signer. Deploy schema 14 with the existing persistent volume and one replica.
