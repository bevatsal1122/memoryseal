# Arkiv adapter

Publishes bounded MemorySeal lifecycle metadata to Rabdi and reads it back with exact schema, creator and memory/event filters. Private memory content, salts and encryption keys are not part of the public projection.

## Install and check

```bash
npm ci --prefix integrations/arkiv
npm test --prefix integrations/arkiv
node integrations/arkiv/query.mjs 0x80ce7202b4dab0653a410605f307ee5cd796db64 40f9c87a-1942-4d8d-9c6c-e9e41d848cf0 memoryseal.memory-event.v3
```

Run from the repository root. The query is read-only and needs no private key. An optional `MEMORYSEAL_ARKIV_ACCESS_KEY` selects an authenticated endpoint. Results are one page; records expire, so absence is not proof that publication never occurred.

## Entry points

- `provenance.mjs`: versioned schemas, strict public projection, proof checks and SDK helpers.
- `publish.mjs`: one-event stdin boundary; checks existing creator/event records before writing. Lookup mode never publishes.
- `query.mjs`: independent creator + memory ID query.
- `src/memoryseal/outbox_worker.py`: durable application publication and reconciliation.

The gateway stores publication work with the local state change. Automatic publication is controlled by `MEMORYSEAL_AUTO_PUBLISH`; Railway startup enables it by default. Ambiguous writes enter reconciliation rather than being blindly duplicated.

[Schema and retention](../../arkiv/schema.md) · [User-facing behavior](../../arkiv/how-you-use-arkiv.md) · [Design choices](../../arkiv/why-arkiv.md) · [Documentation](../../docs/README.md)
