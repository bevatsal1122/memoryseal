# MemorySeal — ETHGlobal Mumbai submission

Prepared 7 November 2026. This is a submission pack, not confirmation of prize eligibility or an entry submitted to ETHGlobal.

## Links

- Live app: https://www.memoryseal.work
- Direct demo: https://www.memoryseal.work/#demo
- Repository: https://github.com/bevatsal1122/memoryseal
- Video: **TO ADD BY AUTHOR — under three minutes for the 0G submission**
- Team name: **MemorySeal**.
- Contact email: **bevatsal1122@gmail.com**.
- GitHub maintainer: bevatsal1122. Individual team member names and a Telegram/X contact are not yet supplied; do not infer them from the team name or email.

## Short description

MemorySeal gives AI agents shared memory without allowing remembered text to become permission. Agents receive ENSv2 identities, 0G analyzes incoming observations for risky instructions and conflicts, and Arkiv exposes a queryable public provenance trail while memory content stays encrypted. Owners define access and review exceptions; model recommendations never grant spending authority.

## Partner submission text

### 0G: Build with 0G Private Computer

0G is used in the ordinary memory-write path to classify proposed context, suspicious instructions and policy conflicts. Its structured output informs the owner's configured admission/review policy. The recurring use case is safely collecting and reusing context across agents. Without 0G, MemorySeal loses its implemented AI analysis step and must fall back to conservative handling; deterministic permissions still apply.

Show an actual write, its classification and inference request reference. Do not use a local memory UUID or transaction hash as a substitute for the inference request ID. The UI exposes inference details and the classifier extracts router request_id and response_key when supplied. Capture a fresh nonempty reference in the video; if the provider omits it, that evidence item remains outstanding.

We do not claim independently verified request-bound private execution. See the dated [0G investigation](0G_INTEGRATION_README.md). The simulated payment screen does not qualify as autonomous compute earnings. No iAI-credit bonus, Physical AI or pay-for-itself claim is made.

### Arkiv: Build on Arkiv

Memory lifecycle metadata is published as real Rabdi entities. A user-facing provenance observation reads those records back, and anyone can run the standalone creator-filtered query. Private memory text, salts and keys stay offchain. Arkiv gives reviewers an independently accessible data path rather than requiring access to our private database.

Required documents: [schema](../arkiv/schema.md), [friction](../arkiv/friction.md), [reach](../arkiv/reach.md), [why Arkiv](../arkiv/why-arkiv.md), [how we use Arkiv](../arkiv/how-you-use-arkiv.md). Publisher and runnable query are in the [README](../README.md#query-real-arkiv-data). No Swarm bonus is claimed.

### ENS: Best Use of ENSv2

Agent onboarding creates real Sepolia ENSv2 subnames under memoryseal.eth. The parent owner delegates the registrar role once; the backend subsequently registers names, deploys dedicated resolvers, attaches them and sets the agent address without requiring each user to pay or sign ENS transactions. Resolution connects a readable identity to the registered signing address. Application permissions remain separate.

These are platform-managed names and resolvers, not a claim that each agent controls its resolver. The implementation uses ENSv2 hierarchy and delegated access rather than hard-coded display labels. The standard Best Use track permits Sepolia; the existing-project ENS track requires mainnet and is not the track demonstrated here.

## Judge walkthrough / video outline (about 2 minutes 45 seconds)

1. **0:00–0:20 — Problem.** Open the direct demo. Explain how malicious source text can be mistaken for permission; label payment decisions as simulations.
2. **0:20–0:55 — ENS.** Register an agent using a dedicated test signing address. Show the completed subname, resolution match and real Sepolia transaction. Registration may take longer than the video: record it beforehand and disclose any edit/time compression.
3. **0:55–1:35 — 0G.** Give the agent collection write permission, connect its wallet, and submit synthetic content claiming an unauthorized spending approval. Show the actual classifier result and request ID. Explain that owner policy, not AI confidence, decides authority.
4. **1:35–2:10 — Arkiv.** Open that memory's provenance. Wait for publication, open the transaction and perform the record observation. Show the independent CLI query as well. Uncertain events must be reconciled, not described as confirmed.
5. **2:10–2:35 — Boundary.** Show the memory withheld or reviewed and a denied simulated transfer above the current allowance. Do not describe this simulation as an executed transaction.
6. **2:35–2:45 — Close.** Show the live URL and repo. Explain recurring value: the next agent can reuse eligible context without inheriting authority from it.

The owner and agent signing accounts can be different. A new owner workspace initially has no agents or permissions. Public viewers can inspect chain evidence and run the Arkiv query without being granted access to another owner's private workspace.

## Public deployment evidence

| Item | Network / address |
| --- | --- |
| ENS parent | memoryseal.eth, Sepolia (11155111) |
| Parent subregistry | 0x828AfCc3D80C65C1620495e1E0EAF5c980D8F1C8 |
| Backend registrar | 0x10001C3e369DDA564Ff7d0d2C5e0fFfE267271B5 |
| Successful user-observed agent name | yoyo-d5547cb29f324332a56ced9dac29dc43.memoryseal.eth |
| That agent's signing address | 0x3f0bfca263b79737864fb891400680c767234e78 |
| MemoryPolicyRegistry | Sepolia: 0xcC79334441497eA501CaB95E2D3B2F7c52c74437 |
| ProtectedTransfer | Sepolia: 0x46065CA936c7813bD2D560F0CE7C7a25A38d05Ec |
| Demo test token | Sepolia: 0x6988ec52814125689586C8f2C62F93993CE82E3B |
| Arkiv publisher | Rabdi (7794095): 0x80ce7202b4dab0653a410605f307ee5cd796db64 |

[ENS registry explorer](https://sepolia.etherscan.io/address/0x828AfCc3D80C65C1620495e1E0EAF5c980D8F1C8) · [Policy registry](https://sepolia.etherscan.io/address/0xcC79334441497eA501CaB95E2D3B2F7c52c74437) · [Protected executor](https://sepolia.etherscan.io/address/0x46065CA936c7813bD2D560F0CE7C7a25A38d05Ec).

Historical Sepolia transaction observations are in [sepolia-action.log](sepolia-action.log) and [sepolia-ens.log](sepolia-ens.log). They are point-in-time evidence, not assertions that old permissions remain active. The old ENS log concerns an earlier parent; the current parent is memoryseal.eth.

Arkiv transaction: [0xa200…403a](https://rabdi.explorer.arkiv.network/tx/0xa200b274a66cb79867c59c1b9a8967af11a2231ad0935c3209ffd1dcc17a403a). Entity: `0xddcdae1867fa7e9619c890ae683c365337dc05e8d2581b859f4a14fc29967359`. The README query was rerun on 7 November at observed Rabdi block 315799 and returned this entity with event `8298136f-1471-442c-9205-babdfc22a913`, memory `40f9c87a-1942-4d8d-9c6c-e9e41d848cf0`, status quarantined and zero skipped rows. This was a read-only public check, not a new paid publication. Entities expire.

## Build provenance and final author tasks

The earliest commit in this checkout is dated 6 November 2026. Commit dates alone do not prove that all work began at the event. **The author must confirm from-scratch versus Continuity registration and disclose any pre-event work.** Do not select an existing-project track merely because the repository already exists today.

Before submitting:

- Add the video URL and a fresh visible 0G inference request ID.
- Supply individual team member names and a Telegram/X contact where required by the submission form or sponsor. Team name and email are recorded above.
- Confirm event participation category and pre-event work disclosure.
- Submit through your ETHGlobal account and select the appropriate sponsor tracks.

The app, docs, source availability and test evidence can be prepared independently; the private ETHGlobal application and unknown team details cannot be completed by inventing values.

## Rules checked

[0G requirements](https://ethglobal.com/events/mumbai/prizes/0g), [Arkiv requirements](https://ethglobal.com/events/mumbai/prizes/arkiv), [ENS requirements](https://ethglobal.com/events/mumbai/prizes/ens). Consult the current pages at submission time. Meeting technical conditions does not guarantee an award; judging and participant eligibility remain with the organizers.
