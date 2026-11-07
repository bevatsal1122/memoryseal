# Why Arkiv

MemorySeal keeps private memory encrypted in its application storage and publishes a narrow public event projection to Arkiv. Anyone can query those records by creator and memory/event ID without access to our SQLite database or an owner session.

Replacing this with a private Postgres table would remove that independent public query path and wallet-owned external record. A public Postgres API could expose similar filters, but readers would depend on our API availability and access policy. Arkiv provides the shared data layer and explicit entity retention.

We intentionally keep content, collection names, source references, salts and keys off Arkiv. The product does not need all data onchain: it needs independently accessible lifecycle metadata without making private notes public.

Arkiv does not establish that a memory is true, that all events were published, or that a publisher is honest. Records can expire; application authorization still comes from owner policy. The user-visible benefit is inspecting an external provenance record and its transaction, not delegating permissions to a database.
