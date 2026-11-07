# Sepolia ENS during agent creation

The Agents form now registers an ENSv2 subname before saving the agent and its permissions. Mainnet registration has been removed. The default parent is `memoryseal.eth`; a deployment can override it with `NEXT_PUBLIC_ENS_PARENT` at frontend build time.

## One-time parent setup

`memoryseal.eth` is a real ENS name, not a cosmetic suffix. The workspace owner must first register it on the **same Sepolia ENSv2 deployment** used by MemorySeal and attach a canonical subregistry with the registrar role assigned to that wallet. The app checks the actual owner, bidirectional canonical registry and registrar role before any transaction. Another wallet cannot create names under this parent just by signing into MemorySeal.

On November 7, 2026, a read-only query to the configured Sepolia UniversalHelper returned zero owner and zero canonical subregistry for `memoryseal.eth`. Zero owner alone is not proof of registrar availability: reserved or expired names can also return zero. No parent registration or other transaction was sent by this change.

Use https://sepolia.app.ens.domains/ to register the parent with your workspace-owner wallet. The testnet app may display a dollar-denominated price; it uses test-network assets. Gas uses Sepolia ETH. The earlier demo parent registration used mintable MockUSDC, documented in `sepolia-ens.log`. Do not buy or bridge mainnet funds for this test workflow. Verify the wallet network and token before confirming.

The subregistry must have its parent pointer configured correctly, in addition to being attached to the parent. The current adapter requires `findCanonicalRegistry(parent)` to return a nonzero address. Mere resolver-only naming is not sufficient for owned subname registration.

## Agent flow

1. Select Sepolia in the owner wallet and connect to MemorySeal.
2. Fill the agent name, agent wallet, collection, permissions and an ENS label such as `research`.
3. Click **Register ENS and add agent**. The resulting name is `research.memoryseal.eth`.
4. Confirm each wallet transaction. The app registers the owned subname, deploys a dedicated resolver, attaches it and sets the agent's address. These are four onchain transactions with automatic receipt checks between them, followed by the signed gateway operation to add the agent and permissions. The subname remains owner-held; its address record points to the agent.
5. Each transaction has a Sepolia Etherscan link. The gateway setup runs only after the final forward lookup matches the agent address. ENS naming does not itself grant MemorySeal capabilities.

The requested subname expiry is one year from setup start. Parent expiration or removal of its registry can stop child resolution earlier. No parent ownership, delegation or permissions are silently changed.

## Recovery

Public setup metadata and transaction checkpoints are stored in localStorage, scoped to the connected owner wallet. They contain no private keys or memory content. Browser storage must be available before submission. After a refresh, **Resume agent setup** verifies saved transactions and continues at the next missing step. A known transaction is never blindly resubmitted after a receipt timeout. Explicit wallet rejection can be retried. An ambiguous submission without a hash stops for manual recovery via wallet history; a reverted transaction also stops rather than being automatically retried.

Gateway retries reuse their original request ID and payload. Before the first gateway submission, the current policy version is fetched. Direct SDK/API agent creation remains its existing metadata-based operation: this change applies to the website's guided creation flow, not a new server-side ENS requirement.

Existing agents and historical names are unchanged. The advanced ENS settings retain resolver management and inspection, while the separate manual subname-registration action has been removed in favor of guided agent creation.

## Verification

Tests cover ordered execution, ownership/role prerequisites, receipt-timeout recovery, wallet rejection, uncertain submission handling and verification failures. Existing ENS tests verify exact transaction calldata, resolver factory deployment, attachment and record writes. A production frontend build is checked independently of the user's running dev server.

Actual end-to-end registration under `memoryseal.eth` is pending parent provisioning and wallet confirmations; passing local tests is not evidence of a successful live registration.
