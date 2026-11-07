# Frontend and interaction guide

The workspace uses warm paper backgrounds, dark borders, hard shadows, lime primary actions, lavender detail panels and peach attention states. The goal is a short everyday path with technical evidence available on demand.

## Screens

| Screen | Main task | Details available when needed |
| --- | --- | --- |
| Overview | See agents, active permissions, review counts and recent activity | Activity categories and links to relevant tasks |
| Agents | Add a friendly name, signing address and initial collection access | Identity, permissions, ENS registration progress and transaction links |
| Permissions | Manage scoped grants and acceptance rules | Exact resources, expiry and policy version |
| Memories | Find, inspect and review memories | Parent relationships, classifier evidence, commitments and publication recovery |
| Organizations | Create/select a team and manage members, agents and access | Owner/admin/auditor roles and signed membership changes |
| Encrypted vault | Unlock identity, manage encrypted collections and share records | Recipient fingerprints, key versions and batch migration |
| Activity | Understand actions and decisions | Context-specific memory, agent and explorer links |
| Playground | Use an agent's write/read and configured action tools | Proof and transaction recovery controls |

Settings contains Connections, Agent names and Onchain policies. Its sidebar entry appears only when the URL includes `?devmode=true`, for example `/?devmode=true#settings`. Backend authorization still applies regardless of navigation visibility.

## Agents and ENS progress

Agent cards group the label, public signing address, permission count and collection count. The registration component advances through Register name, Create resolver, Connect name and Verify address. Progress reflects completed stages, not an elapsed-time animation. Once registered it becomes a compact ready state. Transaction links remain expandable. Failed, cancelled and retrying jobs are distinct states.

The service assigns names such as `research-48271.memoryseal.eth`; existing names are retained. Ordinary users do not manage the parent registry or approve its backend transactions.

## Memories and relationship map

The map represents the current filtered page, up to 100 records. Arrows show explicit parent-to-child references; they do not infer semantic relationships. Dashed placeholders identify parents outside the current result set. Users can pan, zoom, select a bubble and inspect its immediate connections, or find a missing parent through the existing owner-scoped search.

Bubble size reflects visible links. Availability colors are accompanied by text and are not confidence scores. The record list remains available for browsing and review. Detailed IDs, raw evidence and recovery actions belong in collapsed details rather than dominating the page.

## Session and feedback

The compact header combines refresh with the wallet address, alongside Switch account and Sign out. Same-tab refresh restores an unexpired session for the matching account, gateway and audience. Account/network changes and sign-out clear it. Vault private keys remain in memory and require unlocking again after reload.

Routine reads reuse the session. Writes and policy changes keep their request-bound signatures. Errors appear in a dismissible modal with a clear next action; errors do not change operation success or pending transaction state.

## Accessibility and responsive behavior

Use visible keyboard focus, labels, text alongside color, wrapping identifiers and reduced-motion support. Graph nodes support keyboard selection. Keep native validation and meaningful disabled states. Narrow navigation remains labeled and scrollable; do not replace all navigation with unexplained icons.

Check empty/populated states, long ENS names, delayed registration, rejected signatures, expired sessions and blocked storage. Test desktop and narrow widths, browser Back/Forward and direct fragment navigation. Switching tasks must preserve unresolved write recovery state.

## Implementation map

- `web/app/page.jsx`: workspace composition, header and navigation.
- `web/lib/workspace-navigation.js`: fragment/history handling.
- `web/lib/browser-session.mjs`: session persistence.
- `web/components/AgentSetup.jsx`, `AgentCard.jsx`, `EnsRegistrationProgress.jsx`: onboarding and identity.
- `web/components/MemoryProof.jsx`, `AgentWorkbench.jsx`, `TeamVaultPanel.jsx`: memory evidence, agent tools and vault workflows.
- `web/app/neobrutal.css`: visual system and responsive rules.

## Build

The frontend imports sibling packages. Keep `sdk/typescript` and `integrations/ens` available in the checkout. `npm ci --prefix web` installs its sibling dependencies through lifecycle scripts; `npm run build --prefix web` builds the SDK before Next.js. Use a separate checkout for production builds while a development server is running.
