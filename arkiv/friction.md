# Arkiv feedback

These observations come from our implementation and dated [build record](../docs/BUILD_RECORD.md), not invented benchmark results.

## An uncertain submission needs better recovery ergonomics

Expected: after sending an entity creation, obtain its transaction hash and entity key. Observed: lost/ambiguous responses can leave the outbox uncertain even if the chain accepted a submission. A missing immediate query cannot distinguish rejection from indexing delay. We built explicit read-only reconciliation rather than blindly submitting another write.

Reproduce the application behavior with the outbox tests: simulate a transport failure after submission, then return missing, matching and conflicting entities from the read adapter. The tests cover the state transitions; they are not a claim to reproduce an Arkiv node defect. See `tests/` files containing `uncertain` and `reconcile`, and `integrations/arkiv/publish.mjs`.

Request: a documented end-to-end recovery recipe, durable request identifiers, and clear distinctions between submission, receipt and indexed availability.

## Schema evolution and query expectations

We retain multiple event versions. Readers must choose the schema and trusted creator, not just match a memory UUID. A cross-version query example with pagination and explicit ownership semantics would reduce integration work. Our standalone query intentionally reports that a single page is incomplete.

## Public endpoint limits

The SDK warns that the unauthenticated endpoint is heavily rate limited. Our read-only live query succeeded on 7 November, but a judge may encounter limits. A free access key can be supplied through MEMORYSEAL_ARKIV_ACCESS_KEY. Clear retry guidance and a predictable demo allowance would help hackathon teams.
