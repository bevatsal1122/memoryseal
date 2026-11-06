# MemorySeal local runbook

This guide starts the development prototype on one machine. Use dedicated test accounts. The gateway holds the encryption key and is not hardened or audited for real assets or private data. The [P0 status](P0_STATUS.md) separates local evidence from the live workflow that still needs verification.

New memory records store their commitment salts encrypted under the namespace key; older records with plaintext salts remain readable but are not automatically upgraded. An isolated key-rotation snapshot re-encrypts those salts while retaining the original commitments. Old database and backup copies can still expose legacy salts, and a salt plus public commitment permits guessing predictable content. Older MemorySeal versions cannot read newly protected salts, so preserve a tested backup and plan rollback before upgrading. Snapshot rotation is experimental and requires the documented quiescent cutover process; it does not erase old copies or implement client-side key management.

For an isolated salt-only upgrade without changing the encryption key, first stop all gateway and outbox writers, back up the source, and ensure it is already at the current schema version 8. Set `MEMORYSEAL_SNAPSHOT_KEY` in the local process environment to the same base64 master key used by the source; do not put the key on the command line or in chat. Then run:

```sh
.venv/bin/python -m memoryseal.demo.protect_salts prepare /path/to/source.db /path/to/new-snapshot.db
.venv/bin/python -m memoryseal.demo.protect_salts verify /path/to/source.db /path/to/new-snapshot.db
```

The first command refuses to overwrite a destination, checks each encrypted memory and retry digest, and protects legacy salts in a separate snapshot. The second compares the source and snapshot, checks every commitment and requires protected salts in the snapshot. Both report whether at least one memory was available for key checking; zero memories do not verify the key. Keep writers stopped through both operations and any separately coordinated cutover: these commands neither stop processes nor switch databases, and a successful comparison is only point-in-time. Keep the backup and account for old database copies, WAL files and backups that may retain plaintext salts; no secure deletion is provided. Do not use this experimental procedure as a substitute for reviewed key management.

To protect legacy plaintext source-reference fields with the same key, follow the same stopped-writer and backup procedure, then run:

```sh
.venv/bin/python -m memoryseal.demo.protect_sources prepare /path/to/source.db /path/to/new-snapshot.db
.venv/bin/python -m memoryseal.demo.protect_sources verify /path/to/source.db /path/to/new-snapshot.db
```

The commands check each memory and retry digest, encrypt legacy source-reference fields in a new snapshot, and compare recovered values and other records. A zero-memory result does not verify the key. No cutover is performed. SQLite pages, old copies, WAL files and backups may still contain plaintext, and this procedure makes no secure-deletion guarantee. Continue protecting both source and snapshot files and coordinate any cutover separately.

## 1. Prepare the workspace

From the project root, install Python 3.11 or newer and Node.js, then run:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev,contract-test]'
(cd contracts && npm ci && node scripts/compile.mjs --with-test-token)
(cd integrations/ens && npm ci)
(cd integrations/arkiv && npm ci)
(cd web && npm ci)
```

Create a new `.env` with a random encryption key:

```bash
.venv/bin/python scripts/init_local.py
```

The command creates the file with owner-only permissions, prints no key, and refuses to overwrite an existing file. If `.env` already exists, retain its encryption key: replacing it makes existing encrypted memories inaccessible. Back up the key and SQLite database together before migrations or changes. Set optional integration values locally in `.env`; do not put secrets in chat or commit the file.

To create separate test-only owner, browser, research and finance signing keys, run `.venv/bin/python scripts/init_demo_wallets.py`. It writes `.demo.env` with owner-only permissions, prints public addresses only, and refuses to overwrite an existing file. The file contains private keys: keep it local, never commit or share it, and back it up securely if the accounts will be reused. These keys are not funded or linked to an ENS parent automatically. For demo commands that explicitly read these keys from the shell, load the file in a trusted local shell:

```bash
set -a
. ./.demo.env
set +a
```

Only source a file you trust. The gateway does not read `.demo.env`; its Arkiv and 0G settings belong in the separate root `.env`. Public testnet funding and ENS ownership still need to be established separately.

## 2. Start the gateway and dashboard

In the project root, start the gateway. Its settings load `.env` from the current directory:

```bash
.venv/bin/uvicorn memoryseal.api:app --host 127.0.0.1 --port 8000
```

In another terminal, start the dashboard:

```bash
cd web
npm run dev
```

Visit `http://localhost:3000` with an EVM wallet. The dashboard defaults to `http://localhost:8000` and audience `memoryseal-local`; its optional `NEXT_PUBLIC_GATEWAY_URL`, `NEXT_PUBLIC_GATEWAY_AUDIENCE`, `NEXT_PUBLIC_REGISTRY_ADDRESS`, and `NEXT_PUBLIC_CHAIN_ID` are frontend build settings, not secrets. The gateway allows `http://localhost:3000` by default. To authorize other dashboard origins, set `MEMORYSEAL_DASHBOARD_ORIGINS` to a comma-separated list of exact origins, such as `https://dashboard.example`, without trailing slashes, paths or wildcards, then restart the gateway. Remote origins require HTTPS. Invalid configuration prevents startup. CORS controls browser access; signed request authentication and authorization are still required, and CORS does not restrict non-browser clients.

The Python SDK requires HTTPS for remote gateways, allowing HTTP only for localhost/loopback development or a caller-supplied custom transport. A custom transport is a trust boundary and can bypass this safeguard. The dashboard requires HTTPS outside local development and allows an HTTP gateway only when the dashboard and gateway are both local. It rejects redirects on signed gateway requests. Direct API callers must separately use trusted HTTPS for remote gateways; local HTTP is intended for local development only. The local hostname exception depends on the host's name resolution.

The dashboard asks the wallet to sign separately for each gateway request. It shows local grants separately from onchain grants. Changing the wallet account or network resets the dashboard session. A transaction already submitted can still complete.

## 3. Run the local demos

With the gateway running, run the deterministic three-agent scenario:

```bash
.venv/bin/python -m memoryseal.demo.run
```

It uses temporary keys and reports a quarantined forged claim, a denied simulation and an allowed simulation after the owner changes the local limit. It does not send tokens. The generated owner key is discarded. To inspect this demo through a wallet, set `MEMORYSEAL_DEMO_OWNER_KEY` **in the demo process environment** to a dedicated unfunded wallet's private key and connect that wallet to the dashboard. Never use a funded or real-asset wallet for this option.

For a contract-enforced transfer on a fresh local EVM:

```bash
.venv/bin/python -m memoryseal.demo.onchain
```

This uses ephemeral accounts and an in-memory PyEVM, deploys a test token, registry and executor, verifies an over-limit revert, updates the policy and verifies the recipient's balance after a successful transaction. The chain and keys disappear at exit; its hashes are not testnet transactions. Run this with `MEMORYSEAL_REQUIRE_ONCHAIN_MEMORY=false` unless the gateway is configured for the demo's temporary registry. Partner integrations enabled on the gateway can still make network calls.

### Verify a private memory commitment

An owner-signed `inspect_memory` call returns the plaintext and a private base64 commitment salt. In Python, call `verify_memory_commitment(content, commitment_salt, commitment)` from `memoryseal.client`; the dashboard can also perform the calculation locally after inspection. Compare the commitment with a separately observed Arkiv event to check that the disclosed content and salt match that event. A match does not prove truth, authorship or that the published event is permanent. Treat the salt as private: disclosing it permits others to test guesses against the public commitment. The gateway and browser still receive plaintext during owner inspection.

To compare against a specific result from `integrations/arkiv/query.mjs`, save the public query output as `arkiv-page.json` and obtain the owner inspection JSON using a trusted client. Pass the private inspection JSON on standard input, not as command-line arguments:

```bash
.venv/bin/python -m memoryseal.provenance_verify arkiv-page.json \
  --publisher PUBLISHER_ADDRESS --memory-id MEMORY_UUID --entity-key ENTITY_KEY < private-inspection.json
```

The inspection JSON includes plaintext and salt and must be stored and handled as a secret. The command prints only public identifiers and the comparison result. It verifies the selected event’s identifiers and commitment against the supplied content and salt; it does not authenticate the report file, prove the RPC’s response, or establish truth or authorship.

### LangGraph memory nodes

The optional adapter binds an existing signed SDK client, agent ID, namespace and source type outside graph state. Install and test it with the optional dependency. A separate environment keeps framework dependencies isolated:

```bash
python3 -m venv .venv-langgraph
.venv-langgraph/bin/pip install -e '.[dev,langgraph]'
.venv-langgraph/bin/pytest -q tests/test_langgraph_adapter.py
```

Use `MemoryNodes(client, agent_id, namespace, "external")` for externally sourced data, then add `nodes.write` and `nodes.read` as LangGraph nodes. The write node reads `memory_content` and a stable `memory_request_id` UUID from state and returns `memory_write`; optional `memory_source_reference` and `memory_parent_id` are forwarded. The read node returns one `memory_page`, with optional `memory_offset` and `memory_limit` inputs. Follow `next_offset` even after an empty page. Reuse the same request ID only for the same write after an uncertain result; the graph or its caller must persist that ID across retries. The SDK client and graph checkpoint may handle sensitive data; configure their storage and tracing accordingly. Gateway permission errors propagate to the graph. These nodes do not secure tools or storage that bypass the gateway and do not grant action authority.

### Reading agent memories in pages

`POST /memory/read` returns `memories` and `next_offset`, with optional `offset` (default 0) and `limit` (1–100, default 100). Follow `next_offset` until it is null, even if a page is empty: candidates with unsafe recorded ancestry are withheld after paging. This changes the raw HTTP response from the earlier unbounded behavior, so direct HTTP integrations must follow the cursor to avoid incomplete results. The Python SDK's `read_memory` follows every page for compatibility; use `read_memory_page(agent_id, namespace, offset=..., limit=...)` for bounded client memory. Each page rechecks authorization. Pages are separate observations, not a snapshot; concurrent changes can shift offset-based pagination. The compatibility method still accumulates all returned content in the client.

## 4. Configure live testnet integrations separately

The experimental gateway-connection check is required by default. Set an absolute executable path in `MEMORYSEAL_CONNECTION_ATTESTATION_VERIFIER`; the operator must build and review a compatible 0G pcverify binary and its trust roots. Set `MEMORYSEAL_CONNECTION_ATTESTATION_VERIFIER_SHA256` to its reviewed lowercase SHA-256 digest. Protect the executable and its parent directories from replacement; the digest check is not atomic and does not cover baselines or trust roots. The gateway checks the digest, runs it in strict mode, extracts its verified certificate fingerprint, then verifies the certificate on the actual inference TLS connection before sending the API key or content. Missing, incompatible or failing verifier output, or a different certificate, fails closed and quarantines the write. This path bypasses HTTP proxies, trusts the verifier and system CA roots, and has not been validated against a live successful 0G inference. It does not independently establish provider execution, request/response binding, or finality. Explicitly setting `MEMORYSEAL_REQUIRE_CONNECTION_ATTESTATION=false` disables the pre-send check; use that weaker mode only with non-sensitive test data. The experimental bridge currently requires it and remains unverified.

No current inference path verifies the complete chain from the original request through an attested provider to its response. By default all new results remain quarantined and existing accepted memories are withheld from agent reads. The live memory stage now refuses to start either write unless the gateway reports request-binding support and the unbound-inference override is disabled; the current gateway reports no support, so the stage cannot run until implementation changes. This avoids paid writes that cannot satisfy its stated checks. `MEMORYSEAL_ALLOW_UNBOUND_INFERENCE=true` is a weaker compatibility mode for controlled tests only; it cannot satisfy P0 acceptance. Readiness is a gateway assertion and can change after the check, not independent proof. Owners can still inspect quarantined or withheld memories.

Before the live workflow, `.venv/bin/python -m memoryseal.demo.preflight` reports whether the expected local configuration is present and syntactically plausible without printing keys. Demo keys and the demo RPC must be in the process environment; gateway settings are read from `.env` or environment variables. The command does not connect to services or verify balances, ENS ownership, deployment, permissions, or attestation. It exits nonzero if a listed item is missing, including optional provider pins used for the stronger signature-check path, or if the gateway connection check is disabled. The preflight reads its own process configuration, which must match the running gateway; it does not verify that they match.

With the dedicated demo keys in the process environment and `MEMORYSEAL_ENS_RPC_URL` configured for Sepolia, run `.venv/bin/python -m memoryseal.demo.wallet_balances` to observe all four native-token balances at one rechecked block. Only public wallet addresses are sent to the RPC; keys are not sent or printed. Balances are RPC observations and do not establish finality or guarantee enough funds for the workflow.




These are not proven by the local demos. The current implementation still needs the complete live workflow and real-wallet testing.

1. **Contracts:** compile in `contracts` as above. Supply `MEMORYSEAL_RPC_URL`, `MEMORYSEAL_CHAIN_ID`, and a dedicated funded testnet `MEMORYSEAL_DEPLOYER_KEY` in the deployment process environment, then run `(cd contracts && npm run deploy)`. The script checks the chain ID and prints the locally derived transaction hash and predicted contract address before each broadcast. Preserve that output: if submission or receipt observation fails, inspect the hash and nonce before considering a retry. A printed hash or predicted address alone does not prove broadcast, inclusion, or successful deployment. To resume with `MEMORYSEAL_REGISTRY_ADDRESS`, the script requires the registry runtime to match the local artifact at a rechecked RPC block. This trusts the RPC and artifact, does not establish finality, and does not verify the registry owner or later state. For a dedicated demo token, compile with `--with-test-token` and run `(cd contracts && node scripts/deploy.mjs --with-test-token)`. This optional path accepts only chain ID 11155111 or 1337, deploys a new 18-decimal TUSD test token and mints 1,000,000 tokens to the deployer; it is not USDC and it costs network gas. Use the dedicated demo owner as deployer if that owner will approve and fund the transfer. The option creates a fresh token each time, so inspect uncertain transaction hashes before any retry. To deploy only a test token after the registry and executor are already available, use `(cd contracts && node scripts/deploy.mjs --test-token-only)`; it still creates a new token and incurs gas. It does not load the root `.env` automatically. Configure `MEMORYSEAL_ONCHAIN_RPC_URL`, `MEMORYSEAL_ONCHAIN_CHAIN_ID`, `MEMORYSEAL_ONCHAIN_REGISTRY`, and `MEMORYSEAL_ONCHAIN_EXECUTOR` in the gateway's root `.env`, then restart the gateway. Use the dashboard’s “Check executor registry” observation to compare the configured pair, then use a test token and approve the executor before testing transfers. The dashboard can simulate and request an exact ERC-20 allowance or set it to zero, and can read the allowance separately. Before a nonzero approval it requests a fresh gateway observation and requires the configured chain, executor, registry and local runtime comparisons to match; revocation remains available if that observation fails. An approval lets the spender use tokens under that token’s rules; verify the executor address and code and avoid real assets. The observation compares runtime code with the locally compiled artifacts and trusts both those artifacts and the RPC; it does not establish finality or prove the code is safe. Compile contracts first; missing or older artifacts produce an unavailable comparison. A capability is a per-transfer limit, not a total budget.
2. **ENS:** configure `MEMORYSEAL_ENS_RPC_URL` and `MEMORYSEAL_ENS_NETWORK=sepolia`, install ENS dependencies, and restart the gateway. The dashboard can inspect an existing parent subregistry and offers experimental Sepolia owned-subname registration and resolver-record transactions. These require a user-controlled parent and appropriate roles. Subname ownership, resolver permissions and MemorySeal authorization are separate. No live registration has been verified yet.
   An agent can update its public identity configuration reference after the owner grants the `memoryseal.config` setter role. From a Node application with viem clients, use `writeAgentConfig` and `verifyAgentConfig` from `integrations/ens/agent-config.mjs`. Supply the normalized agent name, expected dedicated resolver, public reference string, Sepolia public client, and an agent wallet client. The write simulates the resolver call and returns a transaction hash; verify after inclusion. For example:

   ```js
   import { writeAgentConfig, verifyAgentConfig } from "./integrations/ens/agent-config.mjs";
   // publicClient and agentWalletClient are viem Sepolia clients configured by your app.
   const write = await writeAgentConfig({
     publicClient, walletClient: agentWalletClient, name: "browser.example.eth",
     resolver: dedicatedResolverAddress, value: "ipfs://public-config-reference",
   });
   // Wait for inclusion using your client before verification.
   await publicClient.waitForTransactionReceipt({ hash: write.transactionHash });
   const observation = await verifyAgentConfig({ publicClient, ...write });
   ```

   ENS records are public. Do not put secrets or private configuration in the reference. Resolver checks before submission can race, and a resolver or record can later change or be shared. This write grants no gateway or action permissions. The helper and flow have not been tested on live Sepolia.
3. **0G:** set `MEMORYSEAL_ZERO_G_API_KEY`, `MEMORYSEAL_ZERO_G_MODEL`, and the matching `MEMORYSEAL_ZERO_G_NETWORK` in the gateway's `.env`. If using pinned verification, set all three provider, signer and signature URL pins and optionally the registry RPC. Verify those pins independently. The router's report, pinned signature, onchain record observation, and attestation are different claims; the gateway does not verify TEE attestation or request binding. To inspect one page of public testnet provider records without credentials, run `.venv/bin/python -m memoryseal.demo.discover_0g https://evmrpc-testnet.0g.ai --network testnet`. Use `--offset` and `--limit` for additional pages. The command reports contract fields and compatibility with the current pinned-signature check; it does not select or endorse a provider, verify attestation, establish model availability or validate pricing. Verify any chosen provider and pins independently before configuring them.

For a separate, strict gateway attestation check, build 0G’s `pcverify` from a reviewed checkout of [0g-pc-e2ee](https://github.com/0gfoundation/0g-pc-e2ee/blob/main/docs/verifying-the-gateway.md), then run `.venv/bin/python -m memoryseal.demo.verify_0g_gateway /absolute/path/to/pcverify --network testnet`. The wrapper uses fixed router domains, does not pass MemorySeal environment credentials, and stops after a bounded wait. It treats incomplete, failed or timed-out results as failures. The binary and its trust roots must be independently reviewed. This standalone command is not tied to the inference connection. The separate experimental gate described above compares the verified certificate with the actual connection before sending; it still does not independently attest the downstream provider execution.
The optional pinned provider signature adapter supports a legacy signature over response text only. It rejects 0G PC E2EE's versioned `zg-sig-v1/e2ee-ct` receipts because the hosted gateway does not expose the sealed request and response artifacts that MemorySeal would need to recompute their bindings. See the [0G protocol specification, section 8](https://github.com/0gfoundation/0g-pc-e2ee/blob/c0e7d23f03adea19cbac36223bbeabe05cc8eaad/protocol/SPEC.md#8-response-signature). A rejected receipt fails closed; a legacy signature match does not prove request binding.

4. **Arkiv:** set a dedicated funded `MEMORYSEAL_ARKIV_PRIVATE_KEY` and, optionally, `MEMORYSEAL_ARKIV_ACCESS_KEY`. After a memory is written, run `.venv/bin/python -m memoryseal.outbox_worker --memory-id MEMORY_ID` from the root to process that memory’s pending event, or omit the option to process the oldest pending event. The owner memory listing and dashboard show the event ID needed for reconciliation. Use the dashboard or SDK to observe a published record. For interrupted writes, use the recovery and reconciliation instructions in [README](../README.md); never assume a timeout means a write did not occur. Arkiv metadata is public and entities can expire or be changed or removed by their creator.
5. **Verify end to end:** use the same test owner and appropriate agent identities across the gateway, ENS, Arkiv and executor; capture the claim's status, inference reference, provenance query, failed action, owner policy update and successful test-token transfer. Record network, contract addresses and public transaction identifiers, but not keys or private memory. The provided local onchain demo does not automatically perform this live scenario.

Once the three agent subnames exist and resolve to the dedicated agent addresses, the gateway bootstrap can register them and add four exact local memory grants. Prepare a JSON context containing public names, two stable UUIDs, and the planned local transfer details:

```json
{
  "names": {"browser": "browser.example.eth", "research": "research.example.eth", "finance": "finance.example.eth"},
  "request_ids": {"research": "RESEARCH_WRITE_UUID", "claim": "CLAIM_WRITE_UUID"},
  "local_transfer": {"asset": "0xTEST_TOKEN_ADDRESS", "max_amount": "100000000000000000000", "claim_amount": "5000000000000000000000"}
}
```

With the four demo keys in the process environment, run `.venv/bin/python -m memoryseal.demo.bootstrap bootstrap.json`. It checks each name through the configured Sepolia observer before creating identities, then grants browser write, research read/write, and finance read for both research and browser observations. Output contains agent IDs, request IDs and the supplied local transfer details usable as the memory-stage context. Bootstrap validates and normalizes these transfer details before creating agents; the memory stage checks them again and requires the owner to grant the corresponding local transfer capability separately. It does not register ENS names or grant onchain permissions. Existing matching grants are preserved; an expired unrevoked grant causes an error rather than being replaced. Concurrent policy changes are not coordinated. If setup stops partway through, inspect gateway state and rerun with the same context; matching identities and grants are reused. ENS address observations do not establish name ownership or exclusive resolver control.

Older bootstrapped scenarios may lack the finance research grant. Adding it advances the local policy version; do this before recording the memory-stage policy snapshot and keep the local and onchain policies distinct.

To write the memory stage with existing agents, first register the three agent signing addresses and ENS names with the owner, grant the browser `write` on `browser-observations` and the research agent `write` on `research`, and configure the gateway integrations. Set the dedicated `MEMORYSEAL_DEMO_OWNER_KEY`, `MEMORYSEAL_DEMO_BROWSER_KEY`, and `MEMORYSEAL_DEMO_RESEARCH_KEY` in the process environment. Create a JSON file containing the public gateway agent IDs and two distinct UUIDs generated once and retained for retries:

```json
{
  "agents": {"browser": "BROWSER_AGENT_ID", "research": "RESEARCH_AGENT_ID", "finance": "FINANCE_AGENT_ID"},
  "request_ids": {"research": "RESEARCH_WRITE_UUID", "claim": "CLAIM_WRITE_UUID"},
  "local_transfer": {"asset": "0xTEST_TOKEN_ADDRESS", "max_amount": "100000000000000000000", "claim_amount": "5000000000000000000000"}
}
```

Before running the memory stage, use the owner dashboard or SDK to grant the finance agent the specified local transfer capability (the example is 100 tokens and a 5,000-token claim, using an 18-decimal test token). Provide the stage limit as a decimal string to preserve precision; the gateway stores positive uint256 limits exactly as decimal text. Local limits are separate from, and do not enforce or automatically mirror, registry limits. Verify the units and onchain policy independently.

Run `.venv/bin/python -m memoryseal.demo.live_memory stage.json`. It checks the matching local finance capability before either write and records the observed local version and capability ID. The stage compares the pre-write version and capability ID with gateway-recorded inference snapshot metadata, and fails if they do not match or inference was stale. This metadata is a gateway assertion, not cryptographic proof binding the request to an attested execution. It also checks the running gateway reports Sepolia ENS and 0G configuration, then checks agent records, all three agent keys, ENS address observations, and the required active local read/write grants before writing a research memory and malicious browser claim. Finance must read the exact research memory, and the stage checks that its browser-namespace read withholds the claim. Local policy and readiness can change after these checks; the gateway enforces each actual request separately. The readiness response does not verify service access or attestation. It can invoke paid inference. It prints IDs and inference/provenance status without the private memory text. If a request times out or its outcome is uncertain, retain the same UUIDs and inspect the gateway before retrying; do not assume the write failed. If a completed write has failed or unverified inference, reusing its UUID returns the original result; after resolving the cause and confirming the old outcome, use new UUIDs for a new scenario. The runner exits nonzero when the claim lacks router-reported verification or is not quarantined. This step does not verify the finance key, publish Arkiv, update onchain policy, or submit transfers. Complete those steps separately and use the claim ID in the evidence context below.

For each test-token action, prepare a JSON file with `registry`, `executor`, `owner`, `token`, `recipient`, `amount` (base units) and `policy_version`, and set `MEMORYSEAL_DEMO_RPC_URL` and the dedicated `MEMORYSEAL_DEMO_FINANCE_KEY` in the process environment. Run:

```bash
.venv/bin/python -m memoryseal.demo.submit_action action.json --max-gas-price-wei YOUR_CAP
```

The command requires Sepolia, checks the executor’s registry pointer and compares both contract runtimes with the locally compiled artifacts at a rechecked RPC block, and normally estimates gas. Missing or mismatched artifacts prevent submission. The check trusts the RPC and local build and does not prevent later changes or prove the code is safe. For a deliberately over-limit demonstration, add `--gas-limit 300000`: estimation normally rejects a reverting call before submission. **An explicit gas limit does not force a revert**; if the policy permits the call when included, it can transfer the approved tokens. Use only a dedicated test token and test account, review the current policy and approval, and expect a network fee even on a revert. A submitted hash does not establish inclusion or success. If submission is uncertain, the command prints the locally derived transaction hash; inspect that hash before considering any retry. Update the owner policy separately, then submit the allowed action using the new version. Record both hashes and verify them with the evidence collector.

Anyone with a public Arkiv creator address and memory UUID can query one page without the gateway or a private key: `node integrations/arkiv/query.mjs CREATOR_ADDRESS MEMORY_UUID`. The optional third argument selects schemas v1 through v7; v3 is the default, v4-v6 contain owner-triggered quarantine events, and v7 contains agent-signed commitment acknowledgements. V5 and v6 carry owner-signed requests; v7 carries an agent-signed request. The command reports the observed block and skipped rows and deliberately labels its result incomplete. A record can expire, be unavailable, or change, and a match does not prove its contents are true. `MEMORYSEAL_ARKIV_ACCESS_KEY` may be supplied in the process environment for the query.

To compare a selected v4, v5 or v6 quarantine event to private memory material using the command in section 2, query the appropriate schema and add `--event-type memory_quarantined --expected-owner OWNER_ADDRESS` to `memoryseal.provenance_verify`. The comparison requires the report's owner and actor to match that address and the event status to be quarantined; private content and salt still go through stdin. For v5 and v6 it verifies the owner's signature over the original quarantine request. V6 binds the event ID, commitment and policy version; v5 does not. Neither signature establishes publication time, authenticates the supplied query page, or binds the agent, source type or parent metadata.

An agent can call `attest_memory_origin_verified` with the original content, a new event UUID, and the memory ID, commitment and creation policy version returned by `write_memory`. The SDK privately retrieves the salt and checks the content locally before signing. The gateway only discloses the salt to the original agent with current write permission, records an audit event without the salt, and sets `Cache-Control: no-store`. Use a trusted TLS connection outside local development and keep the salt private; a salt and public commitment enable guesses of predictable content. The standard local demos use this helper, and do not include the salt in their output. The separate v7 event neither changes quarantine nor grants authority. To compare it, query the v7 schema and use `--event-type memory_origin_attested --expected-owner OWNER_ADDRESS --expected-agent AGENT_ADDRESS`; supply private content and salt on stdin. The signature binds the event ID, memory ID, commitment and creation policy version. It cannot prove that the agent used the verified helper, authored the source, or that the metadata and query page are truthful. The audience, request timestamp, nonce and signature are public.

After running the live scenario, collect its existing evidence with `python -m memoryseal.demo.evidence scenario.json`, using the owner, research and finance keys in `MEMORYSEAL_DEMO_OWNER_KEY`, `MEMORYSEAL_DEMO_RESEARCH_KEY` and `MEMORYSEAL_DEMO_FINANCE_KEY`, and the gateway URL and audience in the process environment. The context file contains scenario identifiers, including a local capability ID; protect it as operational metadata:

```json
{
  "agents": {"browser": "BROWSER_AGENT_ID", "research": "RESEARCH_AGENT_ID", "finance": "FINANCE_AGENT_ID"},
  "claim_id": "CLAIM_MEMORY_ID",
  "local_transfer": {"asset": "0xTEST_TOKEN_ADDRESS", "max_amount": "100000000000000000000", "claim_amount": "5000000000000000000000"},
  "local_policy_version": 5,
  "local_finance_capability_id": "LOCAL_FINANCE_CAPABILITY_ID",
  "initial_grant": {"transaction_hash": "0xINITIAL_GRANT_HASH", "max_amount": "100000000000000000000", "expires_at": 0},
  "grant_transaction_hash": "0xOWNER_GRANT_HASH",
  "grant_expires_at": 0,
  "research_memory_id": "RESEARCH_MEMORY_ID",
  "token": "0xTEST_TOKEN_ADDRESS",
  "recipient": "0xRECIPIENT_ADDRESS",
  "amount": "2000000000000000000000",
  "denied": {"transaction_hash": "0xDENIED_HASH", "policy_version": 1},
  "allowed": {"transaction_hash": "0xALLOWED_HASH", "policy_version": 2}
}
```

Take the local transfer parameters, version and capability ID from the memory-stage output. The local asset must be the same token address and its limit must equal the observed initial onchain grant. The forged claim names the asset and amount in base units so the local policy context uses comparable units; its claimed amount must cover the attempted action for the evidence check to pass. Replace the placeholders with actual IDs, addresses and transaction hashes; versions and amount must match the signed calls. The collector checks both the registered research and finance agents can read the exact research observation and the registered finance agent cannot retrieve the quarantined claim and privately inspects the demo claim (recording an owner audit event), checks the same token, recipient, amount and executor for both actions and requires both the executor event and matching ERC-20 Transfer event for the successful action, and requires matching Sepolia ENS observations, an initial direct owner grant below the requested amount before the rejected action, and a matching updated grant in a block between the reverted and successful actions. The grant amount must equal the action amount and its expiry must match the transaction. The grant versions must be consecutive; if the observed registry runtime remained unchanged throughout and the RPC is truthful, that excludes intervening version-incrementing registry updates, but does not establish why the earlier action reverted. Same-block order is treated as unproven. It exits nonzero when a listed observation does not match. A zero exit means only those observation checks passed; the report explicitly marks P0 acceptance unverified because attestation, request binding and other requirements are not established. It separately requires a gateway-reported connection-attestation result and certificate fingerprint, and checks whether the model labels the content an authorization claim and reports the expected finance capability ID as a conflict. The connection result is a gateway assertion that trusts the configured verifier; it is not an independently verifiable attestation artifact. A reported conflict is advisory, reflects the gateway policy context supplied at inference time, and is not independently tied to the onchain policy. The collector also requests recipient balances at the ends of the block before and the block containing the successful transfer, requiring their difference to equal the action amount and the block hash to match the receipt. This requires historical state from the RPC; if it is unavailable, the report retains other observations, marks the balance check unsuccessful and exits nonzero. Other transactions in the same block may affect the difference, and both token events and balance responses are assertions by the token contract, not independent proofs. It reports configured-RPC observations and router claims, not TEE attestation, policy-change causality, transaction finality or proof of exclusive resolver use. It does not perform the scenario; ENS and action observations can add audit events. The report contains public identifiers and inference metadata, so review it before sharing.

Deployment scripts read their configuration from the process environment, whereas the gateway reads its root `.env`. If exporting local settings into a shell, avoid printing them and ensure the correct dedicated testnet keys and network are selected.

## 5. Run local checks

```bash
.venv/bin/ruff check src scripts tests contracts/test
.venv/bin/pytest -q tests contracts/test/test_evm.py
(cd contracts && npm test)
node --test integrations/ens/test/*.test.mjs integrations/arkiv/test/*.test.mjs
.venv/bin/python scripts/test_web.py
(cd web && npm run build)
```

The dashboard test command starts a temporary gateway with its own ephemeral configuration and database, runs the Node tests, and shuts it down. It requires the Python package and Node dependencies installed above.

The test results cover local behavior and mocks as described in [P0 status](P0_STATUS.md); they do not demonstrate live service availability, attestation, finalized chain state, or visual wallet behavior.

The experimental 0G bridge mode currently quarantines all inference results. The live memory-stage command refuses this mode before writing, and preflight reports `demo_memory_path_supported` as false; the complete demo requires a research memory that the research agent can read. Configuration can change after preflight, and the later evidence collector checks actual readability.

For local experiments, `MEMORYSEAL_ZERO_G_PROVIDER_VERIFIER` optionally supplies an operator-reviewed strict verifier executable. Set its lowercase SHA-256 digest in `MEMORYSEAL_ZERO_G_PROVIDER_VERIFIER_SHA256`; the registry RPC and provider pins are also required. A failed check prevents the bridge call. Rebuild and re-pin the bridge before using this setting. Readiness reports configuration only, not a digest match or successful live verifier check. The verifier and its baseline, RPC and bridge are trusted inputs; RPC and endpoint arguments can be visible to local processes. Keep credentials out of those URLs and use only non-sensitive test data. See `integrations/zero_g/README.md` for the limitations.

The memory-stage command additionally requires the running gateway to report that its connection check is required and a verifier is configured before either write. After the research write, it requires recorded gateway-reported connection evidence before sending the claim; it also requires such evidence for the claim before reporting the stage successful. Each writing agent privately checks its submitted content against the commitment before signing a separate origin event; event IDs are stable across retries and returned in `origin_event_ids`. These events are queued, not automatically published, and the public signature cannot prove the local check ran or authenticate the source. Use a trusted TLS connection and protect commitment salts. The connection results are gateway assertions, not independent attestation evidence, and configuration may change between checks. A previously completed write without that evidence cannot be upgraded by retrying the same request ID; inspect the existing result and use a new scenario ID only after resolving the configuration.

Grant the research agent both read and write access to the `research` namespace before running the memory stage. The stage writes the research memory and checks that the agent can read the expected content before submitting the malicious claim. If that check fails after the write, retain the stable request IDs and inspect the memory and permissions before retrying.

To inspect a possibly completed write, use the owner SDK's `list_memories(agent_id=AGENT_ID, request_id=WRITE_UUID)`. The filter is owner-scoped; include the agent because request IDs are scoped to an agent. An empty result is only a point-in-time observation and does not prove an in-flight write will not commit. For an uncertain outcome, retry the identical write with the same UUID; do not create a new UUID until the earlier outcome is understood.

The live memory stage and evidence collector scan at most 50 pages per agent and namespace. If more pages remain they fail instead of reporting that a memory is absent. Reads across pages are not a snapshot; an observed absence does not prove a claim was never accessible or copied. If a scan fails after a write, preserve the stable request IDs and reconcile before retrying.

The dashboard memory explorer also supports the write request UUID filter. Select the agent as well when checking an uncertain write; the same UUID can be used by different agents. An empty search does not prove that a request still in progress will not commit.

The local simulation and isolated onchain demos grant the finance agent read access to the research and browser-observations namespaces. They verify that finance cannot retrieve the quarantined forged claim despite that browser namespace grant; the output reports `finance_read_claim`. The default request-binding policy also quarantines the research memory and withholds it from agent reads. Output includes `research_write_status`, `research_memories`, `finance_research_memories`, and `finance_read_research_write`, which checks the finance agent received the exact demo write. A router-reported verification is not independent proof of provider attestation or request binding. A separate automated test uses mocked inference and the unsafe test-only override to exercise the readable cross-agent path; that test is not evidence of live 0G verification.

After the fail-closed inference change, older memories may still show stored status `accepted` while being withheld from agent reads because their own or an ancestor's inference status is not eligible. Owner inspection remains available. The read-time guard does not rewrite old provenance records, and it cannot revoke plaintext already retrieved by an agent.

A memory write response includes the stored `status` and a point-in-time `lineage_eligible` flag. A retry can return an older `accepted` status with `lineage_eligible: false`; the agent must not assume that record is readable. Actual reads also require current namespace permission and can change as policy or ancestry changes.

Use the SDK and gateway from the same version. The SDK treats a write response missing the UUID, known status, or boolean `lineage_eligible` as an uncertain outcome, including responses from older gateways without that field. Preserve the exception's request ID and retry the identical request after resolving the version mismatch.

The Python SDK rejects malformed read-page envelopes and cursors that do not follow the current gateway's offset-plus-limit contract. A filtered page may contain no memories and still have a next cursor. This validation does not make separate page reads a consistent snapshot.

For the action JSON, provide `amount` in token base units and `policy_version` as exact integers or ASCII decimal strings. Fractions, booleans and signed strings are rejected; the command does not round token amounts. Inspect transaction hashes after uncertain submissions as described above.

Agent-supplied memories classified as instructions or authorization claims are quarantined even when the model recommends acceptance. Older accepted records in those categories, and their descendants, are withheld by the read-time ancestry gate. Classification can be wrong; this does not make memory an authorization credential or establish who actually authored an instruction.

After changing the Arkiv publisher, an event already bound to a different creator remains pending for that creator and is not republished under the new key. Untargeted publishing skips it to process eligible events; if only creator-mismatched events remain, the worker reports `creator_mismatch`. Reconcile or manage those events with the original creator rather than changing their attribution.

The gateway upgrades SQLite to schema version 8 for encrypted source references; version 7 added distinct memory lifecycle provenance events, version 6 signals the encrypted-salt format and version 5 introduced Arkiv publication attempt IDs. Back up the database before upgrading and stop old gateway and worker processes first. Older versions that honor the schema guard will refuse to start against version 8, but a process already running is not stopped by this check. New references are encrypted; existing plaintext references remain readable and are encrypted in a rotated snapshot, but the salt-only snapshot leaves them unchanged. Upgrading the version does not encrypt old salts or erase old data, WAL files, or backups. A late publisher cannot complete a newer claim with a different attempt ID, but this does not prove the old process stopped or prevent duplicate external publication if an uncertain event is reset prematurely. Follow the stopped-worker and reconciliation procedure before any retry.

An owner can quarantine a previously accepted memory in the dashboard or with `quarantine_memory_signed(memory_id, event_id=..., commitment=..., policy_version=...)`. The SDK caller supplies a new UUID, the memory's current commitment and the current local policy version; a changed commitment or policy is rejected. The dashboard fetches the policy version immediately before signing. The gateway queues a `memoryseal.memory-event.v6` event containing the owner signature over these fields and the quarantine request, while leaving the creation event unchanged. The legacy `quarantine_memory(memory_id)` continues to produce v5. Both formats publish the signed request's audience, timestamp, nonce, body hash and signature. Use a public, non-secret gateway audience and a random nonce; the SDK and dashboard generate the supported nonce format. The signed timestamp is an assertion, not proof of wall-clock or publication time. Future agent reads withhold the memory and descendants, while owner inspection remains available. The dashboard can show event publication states and query an individual published event; the SDK exposes `memory_provenance_events(memory_id)` and `observe_memory_provenance_event(memory_id, event_id)`. Results are point-in-time observations from the configured Arkiv RPC, not proof of permanence, truth or finality. Publishing and live observation still require a configured Arkiv worker and testnet credentials. Quarantine cannot retract content an agent already obtained.

The standalone Arkiv worker applies database migrations on startup, just like the gateway. Back up the SQLite database before first running either command after an upgrade. The worker refuses a database schema newer than it understands.

### Experimental encryption snapshot preparation

A preparation command can create a separate re-encrypted SQLite copy; it does not switch the running gateway or its key. This is a development tool and has not been independently audited. Before any cutover, stop the gateway, publisher and all other writers, preserve a tested backup of the original database and old key, and keep them stopped until the selected database and key are coordinated. A copy taken while writers continue can omit later writes. Resolve any in-flight publication first.

Place the existing and new base64-encoded 32-byte keys in the process environment as `MEMORYSEAL_ROTATION_OLD_KEY` and `MEMORYSEAL_ROTATION_NEW_KEY`, keeping them out of shell history, logs and chat. Then run `.venv/bin/python -m memoryseal.demo.prepare_rotation SOURCE_DB NEW_SNAPSHOT_DB`. The destination must not exist. The command retains memory commitments and retry identities, creates an owner-only file, and never changes the source or gateway configuration. It does not prove that writers were stopped, verify a future cutover, remove old backups or SQLite free-page ciphertext, or revoke plaintext already accessed by an agent. Verify the prepared copy with the new key in an isolated environment before planning any switch. Clear the temporary environment variables afterward.

With the same rotation environment variables, run `.venv/bin/python -m memoryseal.demo.verify_rotation SOURCE_DB NEW_SNAPSHOT_DB` to compare the prepared copy with the source. The verifier checks schema and table contents, verifies every memory under both keys, and checks the retry digests without printing plaintext or keys. It reports a point-in-time match only; keep every writer stopped through verification and any subsequent cutover, because it cannot detect changes after its read. It does not switch the database or keys or establish secure deletion of old ciphertext.

If the database has no encrypted memory rows, snapshot comparison reports `matched_no_encrypted_memories` and `keys_verified_against_memory: false`: there is no ciphertext against which to check either supplied key. This status is not confirmation that the old or new key is the intended one.
