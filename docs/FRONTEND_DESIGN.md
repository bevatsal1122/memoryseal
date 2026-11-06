# MemorySeal frontend

The frontend uses a neobrutalist visual system: warm paper backgrounds, near-black borders, hard shadows, lime actions, lavender context panels and peach review states. It retains the development-preview label and does not imply that incomplete provider verification is solved.

## Screen structure

- **Landing:** product explanation, illustrated memory flow, six feature cards, three-step setup and wallet entry points. Wallet connection errors appear with retry guidance.
- **Overview:** next steps, memory/vault shortcuts, live workspace counts and recent agent/activity summaries. Counts reflect the gateway snapshot; quarantine counts cover the latest 100 records.
- **Agents:** identity list followed by a vertically ordered registration form.
- **Permissions:** current grants and a separate grant form. Local permissions retain their existing meaning.
- **Memories:** filters, results, inspection, owner review and expandable provenance. Trust and attestation limitations remain visible at the relevant action.
- **Organizations:** owner/admin/auditor workflows using the existing signed gateway requests.
- **Encrypted vault:** identity/backup/namespace progress, expandable setup, encrypted writes, review and rotation. Switching views retains component state; reloading still clears in-memory keys.
- **Activity:** the gateway decision trail.
- **Agent console:** separate Write, Read, Simulate and Onchain transfer tasks. Task switches hide rather than unmount pending operations; the read task exposes its namespace field.
- **Integrations:** Connections, Agent names and Onchain policies. Each section keeps its own state while navigating.

## Navigation and accessibility

Workspace locations use URL fragments such as `#vault` and `#permissions`; browser back/forward restores the selected view after connection. Only the view name appears in the URL. No wallet secrets, memory content or encryption keys are persisted by navigation.

The interface has keyboard focus outlines, skip links, accessible navigation labels, text alongside status colors, reduced-motion support, wrapping long identifiers and responsive layouts. Phone navigation uses a horizontally scrollable labeled menu instead of unlabeled icons. Controls retain native form validation and existing disabled-state checks.

## Files

- `web/components/design/Landing.jsx`: landing sections and brand.
- `web/components/design/WorkspaceGuide.jsx`: overview actions.
- `web/app/style.css`: structural layout and view visibility.
- `web/app/neobrutal.css`: visual tokens, component styling and responsive rules.
- `web/lib/workspace-navigation.js`: view navigation and history.
- `web/app/page.jsx`: existing signed owner workflows and integrations.
- `web/components/AgentWorkbench.jsx`: signed agent workflows and task selection.
- `web/components/TeamVaultPanel.jsx`: team and encrypted-vault workflows.

No external font request is required. The system font stack keeps the initial render independent of font services.

## Acceptance checks

1. Open the landing page at desktop, tablet and phone widths. Check navigation anchors, connection failure and keyboard focus.
2. Connect a test wallet to the configured gateway. Verify counts and each of the nine views.
3. Navigate through workspace sections; check browser back/forward and a reload with a view fragment.
4. Check empty and populated agents, permissions, memories and activity.
5. Switch among all integration sections. Ensure unrelated forms are hidden and entered values remain.
6. Load agent access. Switch among the four tasks; confirm a pending write survives task switches and namespace remains locked until resolved.
7. Check vault progress before/after unlocking a disposable identity. Preserve actual backup and recipient-verification requirements.
8. Test keyboard navigation, narrow layouts, long identifiers and errors. Use a real test wallet for signed transactions; simulated-wallet visual checks are not live transaction evidence.

## Verified in this change

- Production compilation and static generation passed; the existing viem/ox dynamic-import warning remains.
- SDK cryptographic and signed-HTTP groups: 2 passed. Browser/helper suite: 10 passed, including two local EVM deployments.
- Browser checks covered all nine views at 1280, 768, 390 and 320px with synthetic populated data; document width matched viewport width in all 36 checks. Empty-state screens were checked separately at desktop and phone widths.
- All four agent task selectors and all three integration selectors showed only their corresponding forms. Browser Back restored the previous workspace view.
- Landing, overview and vault screenshots were inspected. Visual workflow checks used an intercepted gateway and simulated wallet; they did not submit real wallet transactions or consume compute credits.
- The isolated SDK test runner now waits for a successful health check or fails with the temporary server log, instead of starting tests after an exhausted readiness loop.
- Branded 404 recovery was rendered and inspected; its home link points to `/`. A simulated rejected wallet connection showed retry guidance and re-enabled the connection button at 320px without page overflow.
- The temporary preview server was stopped after verification. No additional frontend process is required; run `npm run dev --prefix web` when ready.
