# Website acceptance checks

Use dedicated test wallets and synthetic content. These are reproducible checks for the current interface, not a statement that every check was rerun on the hosted deployment today.

## 1. Session and navigation

- Connect the owner wallet and sign in. Refresh the same tab: a valid session should restore without another login signature.
- Check direct links such as `#agents`, `#memories` and `#vault`, plus browser Back/Forward.
- Switch account, change network or sign out: the old session must clear. An expired session must not continue authorizing reads.
- Verify Settings is linked only with `?devmode=true`; hiding navigation must not replace endpoint authorization.
- Confirm errors are readable, dismissible and do not leave buttons permanently busy.

## 2. Agent setup and ENS

- Create a labeled agent with initial collection access and Strict acceptance. The setup is one signed application request.
- Retry the identical request after a simulated lost response: it must not create duplicate agents or grants.
- With sponsored ENS enabled, observe the registration stages and completed name. Check transaction links and forward resolution against the public signing address.
- A failed/queued registration must not be displayed as ready. Existing long names should remain unchanged; new names use a five-digit suffix.

## 3. Ordinary memory and acceptance

- Connect the agent wallet and open Playground. Save a synthetic observation; verify one write signature and retained recovery state if the result is uncertain.
- Read using the active session. Current permissions must be checked without an extra wallet signature for each supported read.
- As owner, enable Standard for that agent and exact collection, then submit a new eligible observation. It may be accepted automatically while retaining its original inference status.
- Submit a suspicious authorization claim or conflicting instruction. It must not acquire new permissions through its content.
- Existing held records must not be automatically approved when Standard is enabled. Test explicit owner review only where the gateway marks the record eligible.

## 4. Memory list and graph

- Exercise collection/status filters and empty results.
- Inspect a memory and its content commitment. Test a parent–child pair and a parent outside the current page.
- Select graph nodes with mouse and keyboard, pan/zoom, and use Find parent. The graph must represent explicit parent links only.
- Quarantine a source and verify dependent reads remain subject to ancestry checks. Revoke access and check subsequent reads are denied.

## 5. Arkiv

- With automatic publication configured, wait for a queued event to publish without a manual publish step.
- Open its explorer transaction and run its record observation; distinguish publication state from a current matched query.
- Run the independent read-only command from the root README.
- Test uncertain-event recovery through controlled failures. Missing/indexing-delayed records must not trigger blind duplicate publication.

## 6. Organizations and vault

- Create a team, add admin and auditor members, and verify their different permissions. Only the owner changes membership.
- Generate and back up encryption identities, verify recipient fingerprints and create a vault collection.
- Write encrypted content, explicitly release an eligible record, and decrypt as an intended recipient.
- Reload: login may survive, but vault private keys must require unlocking again.
- Rotate the collection key, migrate in batches of up to five, and verify revised records and exact retries. Check unauthorized recipients cannot retrieve newly authorized access through stale team membership.

## 7. Configured onchain actions

- Select the intended network and deployment under Settings → Onchain policies, then the same network in Playground.
- Compare local permission results with separate onchain grants. Neither local acceptance nor ENS registration should create a token allowance.
- On a funded test setup, verify policy-version checks, an over-limit refusal, and receipt/balance observations for a separately signed permitted transaction.
- Keep transaction hashes and distinguish RPC observations from a guarantee of finality.

## 8. Layout and recovery

Check desktop and narrow screens, long addresses/names, delayed RPCs, rejected wallet signatures, storage-blocked sessions and interrupted writes. Keep unresolved request IDs/payloads intact. Production builds should run in an isolated checkout when a development server is active.

See [frontend behavior](FRONTEND_DESIGN.md), [local setup](LOCAL_RUNBOOK.md) and [integration evidence](SUBMISSION.md#public-deployment-evidence).
