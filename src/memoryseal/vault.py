"""Opaque client-encrypted namespaces. No plaintext or decryption key enters this API."""

import base64
import hashlib
import json
from typing import Annotated
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, EllipticCurvePublicKey
from cryptography.hazmat.primitives.serialization import load_der_public_key
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from memoryseal.auth import authenticate
from memoryseal.chain_memory import ChainPolicyError
from memoryseal.chain_memory import is_allowed as chain_allowed
from memoryseal.config import settings
from memoryseal.db import get_session
from memoryseal.models import (
    Agent,
    AuditEvent,
    Capability,
    EncryptionIdentity,
    Memory,
    Organization,
    PolicyState,
    VaultEpoch,
    VaultNamespace,
    VaultOutbox,
    VaultRecord,
)
from memoryseal.networks import network
from memoryseal.organizations import role_for
from memoryseal.outbox_worker import observe_published, publish_one, reconcile_one
from memoryseal.policy import evaluate

router = APIRouter(prefix="/vault", tags=["client encrypted memory"])
Signer = Annotated[str, Depends(authenticate)]
Database = Annotated[Session, Depends(get_session)]


def canonical(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def decode(value, minimum, maximum):
    try:
        raw = base64.b64decode(value, validate=True)
        if not minimum <= len(raw) <= maximum:
            raise ValueError()
        return raw
    except ValueError:
        raise HTTPException(422, "invalid encrypted envelope encoding") from None


def public_key(value):
    raw = decode(value, 80, 150)
    try:
        key = load_der_public_key(raw)
        if not isinstance(key, EllipticCurvePublicKey) or not isinstance(key.curve, SECP256R1):
            raise TypeError()
    except (ValueError, TypeError):
        raise HTTPException(422, "P-256 SPKI encryption public key required") from None
    return hashlib.sha256(raw).hexdigest()


def manager(session, owner, signer):
    if owner == signer:
        return True
    org = session.scalar(select(Organization).where(Organization.owner_address == owner))
    return bool(org and role_for(session, org, signer) == "admin")


def allowed_agents(session, scope, signer, operation):
    state = session.get(PolicyState, scope.owner_address)
    if not state:
        return []
    agents = session.scalars(
        select(Agent).where(
            Agent.owner_address == scope.owner_address, Agent.signing_address == signer
        )
    ).all()
    candidates = [
        a
        for a in agents
        if evaluate(
            a,
            session.scalars(select(Capability).where(Capability.agent_id == a.id)),
            operation=operation,
            resource=scope.namespace,
            policy_version=state.version,
        ).allowed
    ]

    if not settings.require_onchain_memory:
        return candidates
    result = []
    for agent in candidates:
        selected = network(agent.policy_chain_id)
        if not all(
            (selected.onchain_rpc_url, selected.onchain_chain_id, selected.onchain_registry)
        ):
            continue
        try:
            if chain_allowed(
                rpc_url=selected.onchain_rpc_url,
                chain_id=selected.onchain_chain_id,
                registry=selected.onchain_registry,
                owner=scope.owner_address,
                agent=agent.signing_address,
                namespace=scope.namespace,
                operation=operation,
            ):
                result.append(agent)
        except ChainPolicyError:
            continue  # encrypted operations fail closed just like ordinary memory
    return result


def scope_access(session, scope_id, signer, *, manage=False, operation="read"):
    scope = session.get(VaultNamespace, scope_id)
    if not scope or not (
        manager(session, scope.owner_address, signer)
        or (not manage and allowed_agents(session, scope, signer, operation))
    ):
        raise HTTPException(404, "encrypted namespace not found or access denied")
    return scope


def log(session, scope, signer, action, resource):
    state = session.get(PolicyState, scope.owner_address)
    session.add(
        AuditEvent(
            id=str(uuid4()),
            owner_address=scope.owner_address,
            actor_address=signer,
            event_type="vault_" + action,
            resource=resource,
            decision="allowed",
            reason="client-encrypted operation; no server plaintext inspection",
            policy_version=state.version if state else 0,
        )
    )

    record = session.get(VaultRecord, resource)
    if record is not None and action in ("written", "released", "quarantined", "rewrapped"):
        agent = session.get(Agent, record.agent_id)
        event_id = str(uuid4())
        payload = {
            "schema": "memoryseal.vault-event.v1",
            "event_id": event_id,
            "memory_id": record.id,
            "owner": scope.owner_address,
            "agent_id": record.agent_id,
            "agent_address": agent.signing_address,
            "actor_address": signer,
            "event_type": "vault_" + action,
            "commitment": record.commitment,
            "key_version": record.key_version,
            "revision": record.revision,
            "status": record.status,
        }
        session.add(
            VaultOutbox(
                id=event_id,
                memory_id=record.id,
                event_type=payload["event_type"],
                payload=canonical(payload),
                state="pending",
            )
        )


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Identity(Strict):
    public_key: str = Field(max_length=200)
    expected_fingerprint: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")


@router.post("/identity")
def set_identity(data: Identity, signer: Signer, session: Database):
    fingerprint = public_key(data.public_key)
    session.execute(text("BEGIN IMMEDIATE"))
    previous = session.get(EncryptionIdentity, signer)
    if previous and previous.fingerprint != fingerprint:
        # Identity replacement requires explicit compare-and-swap, never silently replace.
        if previous.fingerprint != data.expected_fingerprint:
            raise HTTPException(409, "encryption identity changed; expected fingerprint required")
        previous.public_key, previous.fingerprint = data.public_key, fingerprint
    elif not previous:
        session.add(
            EncryptionIdentity(address=signer, public_key=data.public_key, fingerprint=fingerprint)
        )
    session.commit()
    return {"address": signer, "public_key": data.public_key, "fingerprint": fingerprint}


@router.get("/identity/{address}")
def get_identity(address: str, signer: Signer, session: Database):
    item = session.get(EncryptionIdentity, address.lower())
    if not item:
        raise HTTPException(404, "encryption identity not registered")
    return {"address": item.address, "public_key": item.public_key, "fingerprint": item.fingerprint}


class WrappedKey(Strict):
    recipient_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    ephemeral_public_key: str = Field(max_length=200)
    nonce: str = Field(max_length=24)
    ciphertext: str = Field(max_length=80)


class EpochInput(Strict):
    epoch_signature: str = Field(pattern="^0x[0-9a-fA-F]{130}$")
    expected_version: int = Field(ge=0, strict=True)
    fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    envelopes: dict[str, WrappedKey] = Field(min_length=1, max_length=100)


def validate_epoch(session, scope, data):
    if scope.owner_address not in data.envelopes:
        raise HTTPException(422, "owner recovery envelope required")
    for address, envelope in data.envelopes.items():
        identity = session.get(EncryptionIdentity, address)
        if (
            not identity
            or address != address.lower()
            or identity.fingerprint != envelope.recipient_fingerprint
            or not (
                manager(session, scope.owner_address, address)
                or allowed_agents(session, scope, address, "read")
                or allowed_agents(session, scope, address, "write")
            )
        ):
            raise HTTPException(422, "recipient identity or namespace permission invalid")
        public_key(envelope.ephemeral_public_key)
        decode(envelope.nonce, 12, 12)
        decode(envelope.ciphertext, 48, 48)
    values = {a: e.model_dump() for a, e in data.envelopes.items()}
    manifest = canonical(
        [
            "memoryseal:vault-epoch:v1",
            scope.id,
            scope.owner_address,
            scope.namespace,
            data.expected_version + 1,
            data.fingerprint,
            {a: digest(e) for a, e in values.items()},
        ]
    )
    try:
        recovered = Account.recover_message(
            encode_defunct(text=manifest), signature=data.epoch_signature
        )
        if recovered.lower() != scope.owner_address:
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(422, "epoch manifest requires owner signature") from None
    return canonical(values), manifest


class NamespaceInput(EpochInput):
    id: UUID
    namespace: str = Field(min_length=1, max_length=128)
    owner_address: str


@router.post("/namespaces", status_code=201)
def create_namespace(data: NamespaceInput, signer: Signer, session: Database):
    session.execute(text("BEGIN IMMEDIATE"))
    owner = data.owner_address.lower()
    if not manager(session, owner, signer):
        raise HTTPException(403, "namespace owner or organization admin required")
    if data.expected_version != 0:
        raise HTTPException(409, "new namespaces start at version one")
    if session.get(VaultNamespace, str(data.id)) or session.scalar(
        select(VaultNamespace).where(
            VaultNamespace.owner_address == owner, VaultNamespace.namespace == data.namespace
        )
    ):
        raise HTTPException(409, "encrypted namespace already exists")
    if session.scalar(
        select(Memory.id)
        .where(Memory.owner_address == owner, Memory.namespace == data.namespace)
        .limit(1)
    ):
        raise HTTPException(
            409, "use a new namespace; legacy plaintext history requires explicit migration"
        )
    scope = VaultNamespace(
        id=str(data.id), owner_address=owner, namespace=data.namespace, active_version=1
    )
    envelopes, manifest = validate_epoch(session, scope, data)
    session.add(scope)
    session.flush()
    session.add(
        VaultEpoch(
            namespace_id=scope.id,
            version=1,
            fingerprint=data.fingerprint,
            envelopes_json=envelopes,
            manifest_json=manifest,
            signature=data.epoch_signature,
        )
    )
    log(session, scope, signer, "namespace_created", scope.id)
    session.commit()
    return {"id": scope.id, "active_version": 1}


@router.get("/namespaces")
def list_namespaces(signer: Signer, session: Database):
    rows = session.scalars(select(VaultNamespace)).all()
    return {
        "namespaces": [
            {
                "id": s.id,
                "owner_address": s.owner_address,
                "namespace": s.namespace,
                "active_version": s.active_version,
                "can_manage": manager(session, s.owner_address, signer),
            }
            for s in rows
            if manager(session, s.owner_address, signer)
            or allowed_agents(session, s, signer, "read")
            or allowed_agents(session, s, signer, "write")
        ]
    }


@router.get("/namespaces/{scope_id}/epochs/{version}")
def get_epoch(scope_id: str, version: int, signer: Signer, session: Database):
    scope = session.get(VaultNamespace, scope_id)
    if not scope or not (
        manager(session, scope.owner_address, signer)
        or allowed_agents(session, scope, signer, "read")
        or allowed_agents(session, scope, signer, "write")
    ):
        raise HTTPException(404, "encrypted namespace unavailable")
    epoch = session.get(VaultEpoch, (scope_id, version))
    if not epoch:
        raise HTTPException(404, "key version unavailable")
    envelope = json.loads(epoch.envelopes_json).get(signer)
    if not envelope:
        raise HTTPException(403, "no encrypted key envelope for this wallet")
    return {
        "version": version,
        "fingerprint": epoch.fingerprint,
        "envelope": envelope,
        "manifest": json.loads(epoch.manifest_json),
        "signature": epoch.signature,
        "active_version": scope.active_version,
    }


@router.post("/namespaces/{scope_id}/rotate")
def rotate(scope_id: str, data: EpochInput, signer: Signer, session: Database):
    session.execute(text("BEGIN IMMEDIATE"))
    scope = scope_access(session, scope_id, signer, manage=True)
    if scope.active_version != data.expected_version:
        raise HTTPException(409, "key version changed; refresh before rotating")
    if session.scalar(
        select(VaultEpoch).where(
            VaultEpoch.namespace_id == scope_id, VaultEpoch.fingerprint == data.fingerprint
        )
    ):
        raise HTTPException(422, "rotation requires a fresh encryption key")
    envelopes, manifest = validate_epoch(session, scope, data)
    scope.active_version += 1
    session.add(
        VaultEpoch(
            namespace_id=scope_id,
            version=scope.active_version,
            fingerprint=data.fingerprint,
            envelopes_json=envelopes,
            manifest_json=manifest,
            signature=data.epoch_signature,
        )
    )
    log(session, scope, signer, "key_rotated", scope_id)
    session.commit()
    return {"active_version": scope.active_version}


class Ciphertext(Strict):
    nonce: str = Field(max_length=24)
    ciphertext: str = Field(min_length=24, max_length=50000)

    def checked(self):
        decode(self.nonce, 12, 12)
        decode(self.ciphertext, 16, 37500)
        return self.model_dump()


class RecordInput(Strict):
    id: UUID
    agent_id: str
    key_version: int = Field(ge=1, strict=True)
    commitment: str = Field(pattern="^[0-9a-f]{64}$")
    envelope: Ciphertext


@router.post("/namespaces/{scope_id}/records", status_code=201)
def write_record(scope_id: str, data: RecordInput, signer: Signer, session: Database):
    envelope = data.envelope.checked()
    session.execute(text("BEGIN IMMEDIATE"))
    scope = scope_access(session, scope_id, signer, operation="write")
    if data.agent_id not in [a.id for a in allowed_agents(session, scope, signer, "write")]:
        raise HTTPException(403, "writing requires the registered agent's namespace grant")
    original = digest(data.model_dump(mode="json"))
    previous = session.get(VaultRecord, str(data.id))
    if previous:
        if (
            previous.namespace_id != scope_id
            or previous.agent_id != data.agent_id
            or previous.original_digest != original
        ):
            raise HTTPException(409, "record ID already used for another write")
        return {"id": previous.id, "status": previous.status, "revision": previous.revision}
    if data.key_version != scope.active_version:
        raise HTTPException(409, "stale key version; encrypt with the active key")
    epoch = session.get(VaultEpoch, (scope_id, data.key_version))
    if signer not in json.loads(epoch.envelopes_json):
        raise HTTPException(403, "writer has no active encryption key envelope")
    item = VaultRecord(
        id=str(data.id),
        namespace_id=scope_id,
        agent_id=data.agent_id,
        key_version=data.key_version,
        revision=1,
        commitment=data.commitment,
        envelope_json=canonical(envelope),
        original_digest=original,
        status="quarantined",
    )
    session.add(item)
    log(session, scope, signer, "written", item.id)
    session.commit()
    return {"id": item.id, "status": item.status, "revision": item.revision}


@router.get("/namespaces/{scope_id}/records")
def records(
    scope_id: str,
    signer: Signer,
    session: Database,
    after: str = "",
    limit: int = Query(default=50, ge=1, le=100),
    old_only: bool = False,
):
    scope = scope_access(session, scope_id, signer)
    query = select(VaultRecord).where(VaultRecord.namespace_id == scope_id, VaultRecord.id > after)
    if not manager(session, scope.owner_address, signer):
        query = query.where(VaultRecord.status == "released")
    if old_only:
        query = query.where(VaultRecord.key_version != scope.active_version)
    rows = session.scalars(query.order_by(VaultRecord.id).limit(limit + 1)).all()
    return {
        "records": [
            {
                "id": r.id,
                "agent_id": r.agent_id,
                "key_version": r.key_version,
                "commitment": r.commitment,
                "revision": r.revision,
                "status": r.status,
                "envelope": json.loads(r.envelope_json),
                "cipher_digest": digest(json.loads(r.envelope_json)),
            }
            for r in rows[:limit]
        ],
        "next_after": rows[limit - 1].id if len(rows) > limit else None,
        "active_version": scope.active_version,
    }


class Review(Strict):
    expected_revision: int = Field(ge=1, strict=True)
    cipher_digest: str = Field(pattern="^[0-9a-f]{64}$")
    release: bool = Field(strict=True)


@router.post("/namespaces/{scope_id}/records/{record_id}/review")
def review(scope_id: str, record_id: str, data: Review, signer: Signer, session: Database):
    session.execute(text("BEGIN IMMEDIATE"))
    scope = scope_access(session, scope_id, signer, manage=True)
    item = session.get(VaultRecord, record_id)
    if not item or item.namespace_id != scope_id:
        raise HTTPException(404, "record not found")
    if (
        item.revision != data.expected_revision
        or digest(json.loads(item.envelope_json)) != data.cipher_digest
    ):
        raise HTTPException(409, "encrypted record changed; review the latest content")
    item.status = "released" if data.release else "quarantined"
    item.revision += 1
    log(session, scope, signer, "released" if data.release else "quarantined", item.id)
    session.commit()
    return {"id": item.id, "status": item.status, "revision": item.revision}


class Rewrap(Strict):
    expected_revision: int = Field(ge=1, strict=True)
    key_version: int = Field(ge=1, strict=True)
    envelope: Ciphertext


@router.post("/namespaces/{scope_id}/records/{record_id}/rewrap")
def rewrap(scope_id: str, record_id: str, data: Rewrap, signer: Signer, session: Database):
    envelope = data.envelope.checked()
    session.execute(text("BEGIN IMMEDIATE"))
    scope = scope_access(session, scope_id, signer, manage=True)
    item = session.get(VaultRecord, record_id)
    if not item or item.namespace_id != scope_id:
        raise HTTPException(404, "record not found")
    if data.expected_revision != item.revision or data.key_version != scope.active_version:
        raise HTTPException(409, "record or active key changed; retry from a fresh read")
    item.envelope_json, item.key_version = canonical(envelope), data.key_version
    item.revision += 1
    log(session, scope, signer, "rewrapped", item.id)
    session.commit()
    return {"id": item.id, "revision": item.revision}


class RewrapItem(Rewrap):
    id: UUID


class RewrapBatch(Strict):
    records: list[RewrapItem] = Field(min_length=1, max_length=5)


@router.post("/namespaces/{scope_id}/rewrap-batch")
def rewrap_batch(scope_id: str, data: RewrapBatch, signer: Signer, session: Database):
    if len({r.id for r in data.records}) != len(data.records):
        raise HTTPException(422, "duplicate record")
    checked = [(r, r.envelope.checked()) for r in data.records]
    session.execute(text("BEGIN IMMEDIATE"))
    scope = scope_access(session, scope_id, signer, manage=True)
    changed = 0
    for record, envelope in checked:
        item = session.get(VaultRecord, str(record.id))
        if not item or item.namespace_id != scope_id:
            raise HTTPException(404, "record not found")
        if record.key_version != scope.active_version:
            raise HTTPException(409, "active key changed; refresh collection")
        encoded = canonical(envelope)
        if (
            item.revision == record.expected_revision + 1
            and item.key_version == record.key_version
            and item.envelope_json == encoded
        ):
            continue  # exact retry after a lost response
        if item.revision != record.expected_revision:
            raise HTTPException(409, "record changed; refresh collection")
        item.envelope_json, item.key_version = encoded, record.key_version
        item.revision += 1
        log(session, scope, signer, "rewrapped", item.id)
        changed += 1
    session.commit()
    return {"migrated": changed}


@router.get("/namespaces/{scope_id}/rotation")
def rotation_status(scope_id: str, signer: Signer, session: Database):
    scope = scope_access(session, scope_id, signer, manage=True)
    counts = session.execute(
        select(VaultRecord.key_version, func.count())
        .where(VaultRecord.namespace_id == scope_id)
        .group_by(VaultRecord.key_version)
    ).all()
    return {
        "active_version": scope.active_version,
        "records_by_version": dict(counts),
        "remaining": sum(n for v, n in counts if v != scope.active_version),
    }


@router.get("/namespaces/{scope_id}/records/{record_id}/events")
def record_events(scope_id: str, record_id: str, signer: Signer, session: Database):
    scope_access(session, scope_id, signer, manage=True)
    record = session.get(VaultRecord, record_id)
    if not record or record.namespace_id != scope_id:
        raise HTTPException(404, "record not found")
    rows = session.scalars(
        select(VaultOutbox)
        .where(VaultOutbox.memory_id == record_id)
        .order_by(VaultOutbox.created_at, VaultOutbox.id)
        .limit(100)
    ).all()
    return {
        "events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "state": e.state,
                "entity_key": e.entity_key,
                "transaction_hash": e.transaction_hash,
            }
            for e in rows
        ]
    }


@router.post("/namespaces/{scope_id}/records/{record_id}/events/{event_id}/{action}")
def event_action(
    scope_id: str, record_id: str, event_id: str, action: str, signer: Signer, session: Database
):
    scope_access(session, scope_id, signer, manage=True)
    record = session.get(VaultRecord, record_id)
    entry = session.get(VaultOutbox, event_id)
    if not record or record.namespace_id != scope_id or not entry or entry.memory_id != record_id:
        raise HTTPException(404, "event not found")
    if action == "observe" and entry.state == "published":
        return {"state": observe_published(entry)}
    session.commit()
    if action == "publish" and entry.state == "pending":
        return {
            "state": publish_one(session, memory_id=record_id, event_id=event_id, model=VaultOutbox)
        }
    if action == "reconcile" and entry.state == "uncertain":
        return {"state": reconcile_one(session, event_id, model=VaultOutbox)}
    raise HTTPException(
        409, "action does not match event state; uncertain events must be reconciled"
    )
