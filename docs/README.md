# MemorySeal documentation

MemorySeal connects agent identity, scoped permissions and shared memory. Start with the product guide, then choose the setup or integration guide for your task.

## Start here

| Guide | Purpose |
| --- | --- |
| [Project README](../README.md) | Features, architecture, installation and public integration evidence |
| [Product explained](pitch.md) | Plain-language walkthrough, examples and design choices |
| [Local setup](LOCAL_RUNBOOK.md) | Install, configure, sign in and create your first agent and memory |
| [Everyday workflows](WORKFLOW_SIMPLIFICATION.md) | Signatures, sessions, background publication and navigation |
| [Memory acceptance](MEMORY_ACCEPTANCE.md) | Strict/Standard rules, review and current read eligibility |
| [Organizations and encrypted vault](TEAM_VAULT_MULTICHAIN.md) | Roles, client encryption, key rotation and chain selection |

## Integrations and operations

- [ENSv2 sponsored registration](ENS_AGENT_SETUP.md): parent setup, registrar configuration, progress and recovery.
- [0G integration](0G_INTEGRATION_README.md): classifier flow, routing choices and verification boundaries.
- [Arkiv schema](../arkiv/schema.md), [integration behavior](../arkiv/how-you-use-arkiv.md), [design rationale](../arkiv/why-arkiv.md), [feedback](../arkiv/friction.md), and [intended users](../arkiv/reach.md).
- [Railway deployment](RAILWAY_DEPLOYMENT.md): persistence, secrets, CORS and frontend configuration.
- [TypeScript SDK](../sdk/typescript/README.md): signed API calls and client-held cryptography.
- [Experimental 0G bridge](../integrations/zero_g/README.md): optional research tooling, separate from normal router inference.

## Interface and verification

- [Frontend guide](FRONTEND_DESIGN.md): screens, interaction patterns and accessibility checks.
- [Website acceptance checks](WEBSITE_E2E_TEST.md): current wallet-driven workflows.
- [Submission pack](SUBMISSION.md): partner descriptions, public addresses and author checklist.

## Historical records

[Build record](BUILD_RECORD.md), [P0 checklist](P0_STATUS.md), [earlier implementation notes](LEGACY_IMPLEMENTATION_NOTES.md), [0G verification report](0G_TEAM_VERIFICATION_REPORT.md), and [0G investigation blockers](0G_BLOCKERS_SHORT.md) preserve dated engineering observations. They can describe earlier states that no longer match the interface. Use the guides above for current setup; historical test results are not a live health report.
