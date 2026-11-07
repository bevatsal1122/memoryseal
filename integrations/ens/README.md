# ENSv2 adapter

MemorySeal assigns sponsored Sepolia subnames under `memoryseal.eth` and resolves them to agent signing addresses. Names are registered onchain rather than stored only as display labels.

## Registration flow

The gateway creates a durable job with agent setup. A dedicated registrar registers the name, deploys a resolver, attaches it and sets the agent address. Signed transaction bytes are persisted before broadcast; retries inspect or rebroadcast the same transaction rather than allocating another nonce blindly. Final address resolution must match before the agent receives its completed ENS name.

New labels include five random digits with database and onchain collision handling. Existing registered names are retained. The sponsor manages these names and resolvers; application access remains controlled by separate capabilities.

## Setup and tests

```bash
npm ci --prefix integrations/ens
node --test integrations/ens/test/*.test.mjs
```

Run from the repository root. [Operator setup](../../docs/ENS_AGENT_SETUP.md) documents the dedicated signer, one-time parent authorization, quotas, progress states and renewal limits. No signer key belongs in frontend build variables.

The parent setup UI is under Settings → Agent names at `/?devmode=true#settings`. Ordinary agent owners do not need that setup or ENS wallet confirmations.

[Current documentation](../../docs/README.md) · [Public deployment evidence](../../docs/SUBMISSION.md#public-deployment-evidence)
