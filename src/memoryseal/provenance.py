"""Public provenance projection. Never add memory text or source URLs here."""

import json
from uuid import uuid4

from memoryseal.models import Memory, ProvenanceOutbox


def memory_created(memory: Memory, *, agent_address: str) -> ProvenanceOutbox:
    event_id = str(uuid4())
    # Only explicitly chosen fields are public. Namespace and source references
    # can contain private information and stay in the local database.
    payload = {
        "schema": "memoryseal.memory-event.v3",
        "event_id": event_id,
        "event_type": "memory_created",
        "memory_id": memory.id,
        "owner": memory.owner_address,
        "agent_id": memory.agent_id,
        "agent_address": agent_address.lower(),
        "source_type": memory.source_type,
        "commitment": memory.commitment,
        "parent_id": memory.parent_id,
        "trust_class": memory.trust_class,
        "status": memory.status,
        "policy_version": memory.policy_version,
    }
    return ProvenanceOutbox(
        id=event_id,
        memory_id=memory.id,
        event_type="memory_created",
        payload=json.dumps(payload, separators=(",", ":")),
        state="pending",
    )


def memory_quarantined(
    memory: Memory,
    *,
    agent_address: str,
    policy_version: int,
    request_proof: dict,
    event_id: str | None = None,
) -> ProvenanceOutbox:
    entry = memory_created(memory, agent_address=agent_address)
    if event_id is not None:
        entry.id = event_id
    payload = json.loads(entry.payload)
    payload.update(
        schema="memoryseal.memory-event.v6"
        if event_id is not None
        else "memoryseal.memory-event.v5",
        event_id=entry.id,
        event_type="memory_quarantined",
        actor_address=memory.owner_address,
        status="quarantined",
        policy_version=policy_version,
        **request_proof,
    )
    entry.event_type = "memory_quarantined"
    entry.payload = json.dumps(payload, separators=(",", ":"))
    return entry


def memory_origin_attested(
    memory: Memory, *, agent_address: str, event_id: str, request_proof: dict
) -> ProvenanceOutbox:
    entry = memory_created(memory, agent_address=agent_address)
    entry.id = event_id
    payload = json.loads(entry.payload)
    payload.update(
        schema="memoryseal.memory-event.v7",
        event_id=event_id,
        event_type="memory_origin_attested",
        actor_address=agent_address.lower(),
        **request_proof,
    )
    entry.event_type = "memory_origin_attested"
    entry.payload = json.dumps(payload, separators=(",", ":"))
    return entry


def memory_reviewed(
    memory: Memory, *, agent_address: str, policy_version: int, request_proof: dict, event_id: str
) -> ProvenanceOutbox:
    entry = memory_created(memory, agent_address=agent_address)
    entry.id = event_id
    payload = json.loads(entry.payload)
    payload.update(
        schema="memoryseal.memory-event.v8",
        event_id=event_id,
        event_type="memory_reviewed",
        actor_address=memory.owner_address,
        status="accepted",
        policy_version=policy_version,
        **request_proof,
    )
    entry.event_type = "memory_reviewed"
    entry.payload = json.dumps(payload, separators=(",", ":"))
    return entry
