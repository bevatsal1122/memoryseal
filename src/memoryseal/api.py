"""MemorySeal gateway entry point, under active development."""

import hashlib
import json
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from eth_utils import is_address
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from memoryseal import (
    ens_observer,
    memory_service,
    models,  # noqa: F401 - registers schema with metadata
)
from memoryseal.attested_transport import verifier_configured
from memoryseal.auth import authenticate
from memoryseal.bridge_transport import bridge_configured
from memoryseal.config import settings
from memoryseal.cors import dashboard_origins
from memoryseal.db import engine, get_session
from memoryseal.migrations import migrate
from memoryseal.models import Agent, AuditEvent, Capability, Memory, PolicyState, ProvenanceOutbox
from memoryseal.networks import network, public_networks
from memoryseal.onchain import OnchainReceiptVerifier, RpcError
from memoryseal.onchain_deployment import observe_deployment
from memoryseal.outbox_worker import observe_published, publish_one, reconcile_one
from memoryseal.policy import evaluate
from memoryseal.request_limits import RequestBodyLimit
from memoryseal.response_privacy import NoStoreResponses
from memoryseal.token_balance_observer import observe_balance_delta
from memoryseal.zero_g_provider_verifier import provider_verifier_configured
from memoryseal.zero_g_verification import valid_pins


@asynccontextmanager
async def lifespan(_app: FastAPI):
    migrate(engine)
    yield


app = FastAPI(title="MemorySeal Gateway", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestBodyLimit)
app.add_middleware(
    CORSMiddleware,
    allow_origins=dashboard_origins(settings.dashboard_origins),
    allow_methods=["GET", "POST"],
    allow_headers=[
        "Content-Type",
        "X-Memoryseal-Address",
        "X-Memoryseal-Signature",
        "X-Memoryseal-Timestamp",
        "X-Memoryseal-Nonce",
    ],
)
app.add_middleware(NoStoreResponses)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/identity")
def identity(signer: Annotated[str, Depends(authenticate)]):
    """Return the verified signer; this endpoint does not grant any permissions."""
    return {"signer": signer}


@app.get("/integrations/readiness")
def integration_readiness(_signer: Annotated[str, Depends(authenticate)]):
    """Report configuration presence only, without exposing credentials."""
    pins = (
        settings.zero_g_provider_address,
        settings.zero_g_tee_signer,
        settings.zero_g_signature_base_url,
    )
    pins_valid = valid_pins(*pins)
    router_ready = (
        bool(settings.zero_g_api_key and settings.zero_g_model)
        and (
            not settings.require_connection_attestation
            or verifier_configured(
                settings.connection_attestation_verifier,
                settings.connection_attestation_verifier_sha256,
            )
        )
        and (not any(pins) or pins_valid)
        and (not settings.zero_g_registry_rpc_url or pins_valid)
        and (
            not settings.zero_g_experimental_bridge
            or (
                not settings.require_connection_attestation
                and bridge_configured(
                    settings.zero_g_bridge_executable, settings.zero_g_bridge_sha256, pins
                )
                and (
                    not settings.zero_g_provider_verifier
                    or (
                        provider_verifier_configured(
                            settings.zero_g_provider_verifier,
                            settings.zero_g_provider_verifier_sha256,
                        )
                        and bool(settings.zero_g_registry_rpc_url)
                    )
                )
            )
        )
    )
    return {
        "ens_sepolia_configured": bool(settings.ens_rpc_url and settings.ens_network == "sepolia"),
        "zero_g_router_configured": router_ready,
        "zero_g_model": settings.zero_g_model,
        "zero_g_trust_mode": settings.zero_g_trust_mode,
        "onchain_chain_id": settings.onchain_chain_id,
        "onchain_registry": settings.onchain_registry,
        "onchain_executor": settings.onchain_executor,
        "zero_g_experimental_bridge": settings.zero_g_experimental_bridge,
        "unbound_inference_allowed": settings.allow_unbound_inference,
        "request_binding_verification_supported": False,
        "connection_attestation_required": settings.require_connection_attestation,
        "connection_attestation_available": verifier_configured(
            settings.connection_attestation_verifier,
            settings.connection_attestation_verifier_sha256,
        ),
        "arkiv_publisher_configured": bool(settings.arkiv_private_key),
        "onchain_observer_configured": bool(settings.chains)
        or bool(
            settings.onchain_rpc_url
            and settings.onchain_chain_id
            and is_address(settings.onchain_registry or "")
            and int(settings.onchain_registry, 16) != 0
            and is_address(settings.onchain_executor or "")
            and int(settings.onchain_executor, 16) != 0
        ),
        "scope": "configuration only; service access and verification are not established",
    }


class AgentRegistration(BaseModel):
    signing_address: str
    policy_chain_id: int | None = Field(default=None, gt=0, le=2**53 - 1, strict=True)
    # Metadata only until ENS resolution is implemented; never used for authentication.
    ens_name: str | None = Field(default=None, max_length=255)

    @field_validator("signing_address")
    @classmethod
    def valid_address(cls, value: str) -> str:
        if not is_address(value):
            raise ValueError("invalid Ethereum address")
        return value.lower()


@app.post("/agents/register", status_code=201)
def register_agent(
    data: AgentRegistration,
    owner: Annotated[str, Depends(authenticate)],
    session: Annotated[Session, Depends(get_session)],
):
    if data.policy_chain_id is not None:
        network(data.policy_chain_id)
    agent = Agent(
        policy_chain_id=data.policy_chain_id,
        id=str(uuid4()),
        owner_address=owner,
        signing_address=data.signing_address,
        ens_name=data.ens_name,
        revoked=False,
    )
    session.add(agent)
    try:
        session.execute(
            sqlite_insert(PolicyState)
            .values(owner_address=owner, version=0)
            .on_conflict_do_nothing(index_elements=["owner_address"])
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="agent signing address already registered for owner"
        ) from exc
    return {
        "id": agent.id,
        "owner_address": owner,
        "signing_address": agent.signing_address,
        "ens_name": agent.ens_name,
        "policy_chain_id": agent.policy_chain_id,
        "ens_verified": False,
        "revoked": agent.revoked,
    }


@app.get("/agents")
def list_agents(
    owner: Annotated[str, Depends(authenticate)], session: Annotated[Session, Depends(get_session)]
):
    agents = session.scalars(select(Agent).where(Agent.owner_address == owner)).all()
    return {
        "agents": [
            {
                "id": agent.id,
                "signing_address": agent.signing_address,
                "ens_name": agent.ens_name,
                "policy_chain_id": agent.policy_chain_id,
                "ens_verified": False,
                "revoked": agent.revoked,
            }
            for agent in agents
        ]
    }


@app.get("/capabilities")
def list_capabilities(
    owner: Annotated[str, Depends(authenticate)], session: Annotated[Session, Depends(get_session)]
):
    capabilities = session.scalars(
        select(Capability)
        .join(Agent, Agent.id == Capability.agent_id)
        .where(Agent.owner_address == owner)
    ).all()
    state = session.get(PolicyState, owner)
    return {
        "policy_version": state.version if state else 0,
        "capabilities": [
            {
                "id": cap.id,
                "agent_id": cap.agent_id,
                "operation": cap.operation,
                "resource": cap.resource,
                "max_amount": str(cap.max_amount) if cap.max_amount is not None else None,
                "expires_at": cap.expires_at,
                "revoked": cap.revoked,
                "policy_version": cap.policy_version,
            }
            for cap in capabilities
        ],
    }


@app.get("/agent-access")
def agent_access(
    signer: Annotated[str, Depends(authenticate)],
    session: Annotated[Session, Depends(get_session)],
):
    """Discover only registrations controlled by the signing agent wallet."""
    agents = session.scalars(select(Agent).where(Agent.signing_address == signer)).all()
    return {
        "agents": [
            {
                "id": agent.id,
                "owner_address": agent.owner_address,
                "signing_address": agent.signing_address,
                "ens_name": agent.ens_name,
                "policy_chain_id": agent.policy_chain_id,
                "revoked": agent.revoked,
                "policy_version": (
                    state.version if (state := session.get(PolicyState, agent.owner_address)) else 0
                ),
                "capabilities": [
                    {
                        "id": cap.id,
                        "operation": cap.operation,
                        "resource": cap.resource,
                        "max_amount": str(cap.max_amount) if cap.max_amount is not None else None,
                        "expires_at": cap.expires_at,
                        "revoked": cap.revoked,
                    }
                    for cap in session.scalars(
                        select(Capability).where(Capability.agent_id == agent.id)
                    ).all()
                ],
            }
            for agent in agents
        ]
    }


@app.get("/events")
def list_events(
    owner: Annotated[str, Depends(authenticate)], session: Annotated[Session, Depends(get_session)]
):
    events = session.scalars(
        select(AuditEvent)
        .where(AuditEvent.owner_address == owner)
        .order_by(AuditEvent.created_at.desc())
        .limit(100)
    ).all()
    capability_ids = [
        event.resource
        for event in events
        if event.event_type in ("capability_granted", "capability_revoked")
    ]
    capabilities = {
        cap.id: cap
        for cap in session.scalars(
            select(Capability).where(Capability.id.in_(capability_ids))
        ).all()
    }

    def describe(event):
        details = None
        reason = event.reason
        if event.event_type == "transfer_simulated":
            try:
                parsed = json.loads(reason)
                if (
                    isinstance(parsed, dict)
                    and parsed.get("schema") == "memoryseal.transfer-simulation.v1"
                ):
                    details, reason = parsed, parsed["reason"]
            except (ValueError, KeyError, TypeError):
                pass  # Older audit rows store a plain-text reason.
        cap = (
            capabilities.get(event.resource)
            if event.event_type in ("capability_granted", "capability_revoked")
            else None
        )
        if cap:
            details = {
                "agent_id": cap.agent_id,
                "operation": cap.operation,
                "resource": cap.resource,
                "max_amount": str(cap.max_amount) if cap.max_amount is not None else None,
                "expires_at": cap.expires_at,
            }
        return {
            "id": event.id,
            "actor": event.actor_address,
            "event_type": event.event_type,
            "resource": event.resource,
            "decision": event.decision,
            "reason": reason,
            "details": details,
            "policy_version": event.policy_version,
            "created_at": event.created_at,
        }

    return {"events": [describe(event) for event in events]}


@app.get("/memories")
def list_memories(
    owner: Annotated[str, Depends(authenticate)],
    session: Annotated[Session, Depends(get_session)],
    agent_id: Annotated[str | None, Query(max_length=36)] = None,
    namespace: Annotated[str | None, Query(max_length=128)] = None,
    memory_id: Annotated[str | None, Query(max_length=36)] = None,
    request_id: UUID | None = None,
    parent_id: Annotated[str | None, Query(max_length=36)] = None,
    status: Literal["accepted", "quarantined"] | None = None,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
):
    query = select(Memory).where(Memory.owner_address == owner)
    if agent_id:
        query = query.where(Memory.agent_id == agent_id)
    if namespace:
        query = query.where(Memory.namespace == namespace)
    if memory_id:
        query = query.where(Memory.id == memory_id)
    if request_id:
        query = query.where(Memory.request_id == str(request_id))
    if parent_id:
        query = query.where(Memory.parent_id == parent_id)
    if status:
        query = query.where(Memory.status == status)
    memories = session.scalars(
        query.order_by(Memory.created_at.desc(), Memory.id.desc()).offset(offset).limit(limit + 1)
    ).all()
    has_more = len(memories) > limit
    memories = memories[:limit]
    provenance = {
        entry.memory_id: entry
        for entry in session.scalars(
            select(ProvenanceOutbox).where(
                ProvenanceOutbox.memory_id.in_([m.id for m in memories]),
                ProvenanceOutbox.event_type == "memory_created",
            )
        ).all()
    }
    creation_reasons = {
        event.resource: event.reason
        for event in session.scalars(
            select(AuditEvent).where(
                AuditEvent.owner_address == owner,
                AuditEvent.event_type == "memory_created",
                AuditEvent.resource.in_([m.id for m in memories]),
            )
        ).all()
    }
    lineage_by_namespace = {
        name: memory_service.readable_lineage(
            session, owner, name, [item.id for item in memories if item.namespace == name]
        )
        for name in {item.namespace for item in memories}
    }
    analyses = {item.id: memory_service.stored_analysis(item.analysis_json) for item in memories}
    return {
        "next_offset": offset + limit if has_more else None,
        "memories": [
            {
                "id": item.id,
                "agent_id": item.agent_id,
                "request_id": item.request_id,
                "namespace": item.namespace,
                "source_type": item.source_type,
                "category": item.category,
                "inference_status": item.inference_status,
                "inference_reference": item.inference_reference,
                "analysis": analyses[item.id][0],
                "analysis_state": analyses[item.id][1],
                "trust_class": item.trust_class,
                "status": item.status,
                "owner_reviewed": item.owner_review_commitment == item.commitment,
                "creation_reason": creation_reasons.get(item.id),
                "lineage_eligible": item.id in lineage_by_namespace[item.namespace],
                "commitment": item.commitment,
                "parent_id": item.parent_id,
                "policy_version": item.policy_version,
                "created_at": item.created_at,
                "provenance": (
                    {
                        "event_id": provenance[item.id].id,
                        "state": provenance[item.id].state,
                        "creator_address": provenance[item.id].creator_address,
                        "entity_key": provenance[item.id].entity_key,
                        "transaction_hash": provenance[item.id].transaction_hash,
                    }
                    if item.id in provenance
                    else None
                ),
            }
            for item in memories
        ],
    }


@app.post("/memories/{memory_id}/observe-provenance")
def observe_provenance(
    memory_id: str,
    owner: Annotated[str, Depends(authenticate)],
    session: Annotated[Session, Depends(get_session)],
):
    memory = session.get(Memory, memory_id)
    if memory is None or memory.owner_address != owner:
        raise HTTPException(status_code=404, detail="memory not found")
    entry = session.scalar(
        select(ProvenanceOutbox).where(
            ProvenanceOutbox.memory_id == memory_id, ProvenanceOutbox.event_type == "memory_created"
        )
    )
    if entry is None:
        return {"observation": "not_published"}
    return {"observation": observe_published(entry)}


def public_event_request_proof(request: Request, body: bytes) -> dict:
    audience = settings.request_audience
    signature = request.headers["x-memoryseal-signature"]
    signature = "0x" + signature.removeprefix("0x").removeprefix("0X").lower()
    timestamp = int(request.headers["x-memoryseal-timestamp"])
    if (
        request.url.query
        or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", audience)
        or not re.fullmatch(r"0x[0-9a-f]{130}", signature)
        or not re.fullmatch(r"[0-9a-f]{32}", request.headers["x-memoryseal-nonce"])
        or not 0 <= timestamp <= 2**53 - 1
    ):
        raise HTTPException(status_code=400, detail="unsupported public event proof format")
    return {
        "request_audience": audience,
        "request_timestamp": str(timestamp),
        "request_nonce": request.headers["x-memoryseal-nonce"],
        "request_body_sha256": hashlib.sha256(body).hexdigest(),
        "request_signature": signature,
    }


@app.post("/memories/{memory_id}/quarantine")
async def quarantine_memory(
    memory_id: str,
    request: Request,
    owner: Annotated[str, Depends(authenticate)],
    session: Annotated[Session, Depends(get_session)],
):
    body = await request.body()
    if body not in (b"", b"{}"):
        raise HTTPException(status_code=400, detail="unsupported public event proof format")
    proof = public_event_request_proof(request, body)
    return memory_service.quarantine_for_owner(
        session, memory_id=memory_id, owner=owner, request_proof=proof
    )


def parse_signed_memory_event(body: bytes) -> tuple[str, str, int]:
    try:
        value = json.loads(body)
        if not isinstance(value, dict) or set(value) != {
            "event_id",
            "commitment",
            "policy_version",
        }:
            raise ValueError("invalid fields")
        event_id, commitment, version = (
            value["event_id"],
            value["commitment"],
            value["policy_version"],
        )
        if (
            not isinstance(event_id, str)
            or str(UUID(event_id)) != event_id
            or not isinstance(commitment, str)
            or not re.fullmatch(r"[0-9a-f]{64}", commitment)
            or isinstance(version, bool)
            or not isinstance(version, int)
            or not 0 <= version < 2**53
        ):
            raise ValueError("invalid values")
        canonical = json.dumps(
            {"event_id": event_id, "commitment": commitment, "policy_version": version},
            separators=(",", ":"),
        ).encode()
        if body != canonical:
            raise ValueError("noncanonical body")
    except (ValueError, TypeError, UnicodeError):
        raise HTTPException(status_code=400, detail="invalid signed memory event") from None
    return event_id, commitment, version


@app.post("/memories/{memory_id}/quarantine-event")
async def quarantine_with_signed_event(
    memory_id: str,
    request: Request,
    owner: Annotated[str, Depends(authenticate)],
    session: Annotated[Session, Depends(get_session)],
):
    body = await request.body()
    event_id, commitment, version = parse_signed_memory_event(body)
    proof = public_event_request_proof(request, body)
    return memory_service.quarantine_for_owner(
        session,
        memory_id=memory_id,
        owner=owner,
        request_proof=proof,
        expected_commitment=commitment,
        expected_version=version,
        event_id=event_id,
    )


@app.post("/memories/{memory_id}/review-event")
async def review_memory(
    memory_id: str,
    request: Request,
    owner: Annotated[str, Depends(authenticate)],
    session: Annotated[Session, Depends(get_session)],
):
    body = await request.body()
    event_id, commitment, version = parse_signed_memory_event(body)
    return memory_service.review_for_owner(
        session,
        memory_id=memory_id,
        owner=owner,
        event_id=event_id,
        commitment=commitment,
        policy_version=version,
        request_proof=public_event_request_proof(request, body),
    )


@app.post("/memories/{memory_id}/author-commitment-salt")
def author_commitment_salt(
    memory_id: str,
    signer: Annotated[str, Depends(authenticate)],
    session: Annotated[Session, Depends(get_session)],
):
    return memory_service.author_commitment_salt(session, memory_id=memory_id, signer=signer)


@app.post("/memories/{memory_id}/attest-origin")
async def attest_memory_origin(
    memory_id: str,
    request: Request,
    signer: Annotated[str, Depends(authenticate)],
    session: Annotated[Session, Depends(get_session)],
):
    body = await request.body()
    event_id, commitment, version = parse_signed_memory_event(body)
    proof = public_event_request_proof(request, body)
    return memory_service.attest_origin(
        session,
        memory_id=memory_id,
        signer=signer,
        event_id=event_id,
        commitment=commitment,
        policy_version=version,
        request_proof=proof,
    )


@app.get("/memories/{memory_id}/provenance-events")
def memory_provenance_events(
    memory_id: str,
    owner: Annotated[str, Depends(authenticate)],
    session: Annotated[Session, Depends(get_session)],
):
    item = session.get(Memory, memory_id)
    if item is None or item.owner_address != owner:
        raise HTTPException(status_code=404, detail="memory not found")
    events = session.scalars(
        select(ProvenanceOutbox)
        .where(ProvenanceOutbox.memory_id == memory_id)
        .order_by(ProvenanceOutbox.created_at, ProvenanceOutbox.id)
        .limit(101)
    ).all()
    return {
        "truncated": len(events) > 100,
        "events": [
            {
                "event_id": e.id,
                "event_type": e.event_type,
                "state": e.state,
                "creator_address": e.creator_address,
                "entity_key": e.entity_key,
                "transaction_hash": e.transaction_hash,
            }
            for e in events[:100]
        ],
    }


@app.post("/memories/{memory_id}/provenance-events/{event_id}/observe")
def observe_memory_event(
    memory_id: str,
    event_id: str,
    owner: Annotated[str, Depends(authenticate)],
    session: Annotated[Session, Depends(get_session)],
):
    item = session.get(Memory, memory_id)
    if item is None or item.owner_address != owner:
        raise HTTPException(status_code=404, detail="memory not found")
    event = session.get(ProvenanceOutbox, event_id)
    if event is None or event.memory_id != memory_id:
        raise HTTPException(status_code=404, detail="provenance event not found")
    return {"event_id": event.id, "observation": observe_published(event)}


@app.get("/memories/{memory_id}")
def inspect_memory(
    memory_id: str,
    owner: Annotated[str, Depends(authenticate)],
    session: Annotated[Session, Depends(get_session)],
):
    return memory_service.inspect_for_owner(session, memory_id=memory_id, owner=owner)


@app.post("/memories/{memory_id}/provenance-events/{event_id}/publish")
def publish_memory_event(
    memory_id: str,
    event_id: str,
    owner: Annotated[str, Depends(authenticate)],
    session: Annotated[Session, Depends(get_session)],
):
    item = session.get(Memory, memory_id)
    event = session.get(ProvenanceOutbox, event_id)
    if item is None or item.owner_address != owner or event is None or event.memory_id != memory_id:
        raise HTTPException(status_code=404, detail="provenance event not found")
    if event.state != "pending":
        raise HTTPException(
            status_code=409,
            detail="only pending events can be published; reconcile uncertain events",
        )
    session.commit()
    return {
        "event_id": event_id,
        "state": publish_one(session, memory_id=memory_id, event_id=event_id),
    }


@app.post("/memories/{memory_id}/provenance-events/{event_id}/reconcile")
def reconcile_memory_event(
    memory_id: str,
    event_id: str,
    owner: Annotated[str, Depends(authenticate)],
    session: Annotated[Session, Depends(get_session)],
):
    item = session.get(Memory, memory_id)
    event = session.get(ProvenanceOutbox, event_id)
    if item is None or item.owner_address != owner or event is None or event.memory_id != memory_id:
        raise HTTPException(status_code=404, detail="provenance event not found")
    if event.state != "uncertain":
        raise HTTPException(status_code=409, detail="only uncertain events can be reconciled")
    session.commit()
    return {"event_id": event_id, "state": reconcile_one(session, event_id)}


def validate_integer_amount(value):
    if value is None:
        return value
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("amount must be an integer or decimal string")  # noqa: TRY004 - Pydantic turns ValueError into a validation response
    if isinstance(value, str) and (not value.isascii() or not value.isdecimal() or len(value) > 78):
        raise ValueError("amount must be a decimal string of at most 78 digits")
    return value


class CapabilityGrant(BaseModel):
    agent_id: str
    operation: Literal["read", "write", "transfer"]
    resource: str = Field(min_length=1, max_length=128)
    max_amount: int | None = Field(default=None, gt=0, lt=2**256)
    expires_at: datetime | None = None

    @field_validator("max_amount", mode="before")
    @classmethod
    def amount_is_integer(cls, value):
        return validate_integer_amount(value)

    @field_validator("expires_at")
    @classmethod
    def valid_expiry(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value <= datetime.now(UTC)):
            raise ValueError("expiry must be a future timezone-aware datetime")
        return value


def owned_agent(session: Session, agent_id: str, owner: str) -> Agent:
    agent = session.get(Agent, agent_id)
    if agent is None or agent.owner_address != owner:
        raise HTTPException(status_code=404, detail="agent not found")
    return agent


@app.post("/agents/{agent_id}/observe-ens")
def observe_ens(
    agent_id: str,
    owner: Annotated[str, Depends(authenticate)],
    session: Annotated[Session, Depends(get_session)],
):
    agent = owned_agent(session, agent_id, owner)
    if not agent.ens_name:
        raise HTTPException(status_code=422, detail="agent has no ENS name")
    name, address = agent.ens_name, agent.signing_address
    session.rollback()
    try:
        result = ens_observer.observe(name, address)
    except ens_observer.EnsObservationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    session.expire_all()
    agent = owned_agent(session, agent_id, owner)
    if agent.ens_name != name or agent.signing_address != address:
        raise HTTPException(status_code=409, detail="agent identity changed during lookup")
    state = session.get(PolicyState, owner)
    session.add(
        AuditEvent(
            id=str(uuid4()),
            owner_address=owner,
            actor_address=owner,
            event_type="ens_address_observed",
            resource=agent.id,
            decision="match" if result["matches"] else "mismatch",
            reason=json.dumps(result),
            policy_version=state.version if state else 0,
        )
    )
    session.commit()
    return {"observation": result, "source": "configured_rpc", "finalized": False}


@app.get("/onchain/observe-deployment")
def observe_onchain_deployment(
    _signer: Annotated[str, Depends(authenticate)], chain_id: int | None = None
):
    """Observe the selected executor's registry at a single RPC block."""
    selected = network(chain_id)
    if not all(
        (
            selected.onchain_rpc_url,
            selected.onchain_chain_id,
            selected.onchain_registry,
            selected.onchain_executor,
        )
    ):
        raise HTTPException(status_code=503, detail="onchain deployment observer is not configured")
    try:
        result = observe_deployment(
            rpc_url=selected.onchain_rpc_url,
            chain_id=selected.onchain_chain_id,
            registry=selected.onchain_registry,
            executor=selected.onchain_executor,
        )
    except (RpcError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="could not observe onchain deployment") from exc
    return {"observation": result, "source": "configured_rpc", "finalized": False}


class OnchainObservation(BaseModel):
    agent_id: str
    transaction_hash: str = Field(pattern=r"^0x[0-9a-fA-F]{64}$")
    token: str
    recipient: str
    amount: str = Field(pattern=r"^[0-9]{1,78}$")
    policy_version: int = Field(ge=0, le=2**63 - 1)

    @field_validator("policy_version", mode="before")
    @classmethod
    def version_is_integer(cls, value):
        return validate_integer_amount(value)

    @field_validator("token", "recipient")
    @classmethod
    def address_valid(cls, value: str) -> str:
        if not is_address(value):
            raise ValueError("invalid address")
        return value.lower()

    @field_validator("amount")
    @classmethod
    def amount_valid(cls, value: str) -> str:
        if not 0 < int(value) < 2**256:
            raise ValueError("invalid amount")
        return str(int(value))


class TokenBalanceObservation(BaseModel):
    token: str
    recipient: str
    block_number: int = Field(gt=0, le=2**63 - 1)

    @field_validator("block_number", mode="before")
    @classmethod
    def block_is_integer(cls, value):
        return validate_integer_amount(value)

    @field_validator("token", "recipient")
    @classmethod
    def valid_address(cls, value: str) -> str:
        if not is_address(value):
            raise ValueError("invalid address")
        return value.lower()


@app.post("/actions/observe-token-balance")
def observe_token_balance(
    data: TokenBalanceObservation,
    _owner: Annotated[str, Depends(authenticate)],
    chain_id: int | None = None,
):
    selected = network(chain_id)
    if not selected.onchain_rpc_url or not selected.onchain_chain_id:
        raise HTTPException(status_code=503, detail="onchain observer is not configured")
    try:
        observation = observe_balance_delta(
            rpc_url=selected.onchain_rpc_url,
            chain_id=selected.onchain_chain_id,
            token=data.token,
            recipient=data.recipient,
            block_number=data.block_number,
        )
    except (RpcError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="could not observe token balances") from exc
    return {
        "observation": observation,
        "chain_id": selected.onchain_chain_id,
        "source": "configured_rpc",
        "finalized": False,
    }


class OnchainGrantObservation(BaseModel):
    agent_id: str
    transaction_hash: str = Field(pattern=r"^0x[0-9a-fA-F]{64}$")
    token: str
    max_amount: str = Field(pattern=r"^[0-9]{1,78}$")
    expires_at: int = Field(ge=0, le=2**64 - 1)
    policy_version: int = Field(ge=0, le=2**63 - 1)

    @field_validator("expires_at", "policy_version", mode="before")
    @classmethod
    def numbers_are_integers(cls, value):
        return validate_integer_amount(value)

    @field_validator("token")
    @classmethod
    def token_valid(cls, value: str) -> str:
        if not is_address(value):
            raise ValueError("invalid address")
        return value.lower()

    @field_validator("max_amount")
    @classmethod
    def amount_valid(cls, value: str) -> str:
        if not 0 < int(value) < 2**256:
            raise ValueError("invalid amount")
        return str(int(value))


@app.post("/actions/observe-onchain-grant")
def observe_onchain_grant(
    data: OnchainGrantObservation,
    owner: Annotated[str, Depends(authenticate)],
    session: Annotated[Session, Depends(get_session)],
    chain_id: int | None = None,
):
    selected = network(chain_id)
    agent = owned_agent(session, data.agent_id, owner)
    if (
        not selected.onchain_rpc_url
        or not selected.onchain_chain_id
        or not selected.onchain_registry
    ):
        raise HTTPException(status_code=503, detail="onchain registry observer is not configured")
    try:
        verifier = OnchainReceiptVerifier(
            selected.onchain_rpc_url,
            owner,
            chain_id=selected.onchain_chain_id,
            executor=selected.onchain_registry,
        )
        try:
            observation = verifier.verify_transfer_grant(
                data.transaction_hash,
                agent=agent.signing_address,
                token=data.token,
                max_amount=int(data.max_amount),
                expires_at=data.expires_at,
                version=data.policy_version,
            )
        finally:
            verifier.close()
    except (RpcError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="could not verify onchain grant") from exc
    return {
        "observation": observation,
        "source": "configured_rpc",
        "finalized": False,
        "chain_id": selected.onchain_chain_id,
        "registry": selected.onchain_registry,
    }


@app.post("/actions/observe-onchain")
def observe_onchain(
    data: OnchainObservation,
    owner: Annotated[str, Depends(authenticate)],
    session: Annotated[Session, Depends(get_session)],
    chain_id: int | None = None,
):
    selected = network(chain_id)
    agent = owned_agent(session, data.agent_id, owner)
    if (
        not selected.onchain_rpc_url
        or not selected.onchain_chain_id
        or not selected.onchain_executor
    ):
        raise HTTPException(status_code=503, detail="onchain observer is not configured")
    try:
        verifier = OnchainReceiptVerifier(
            selected.onchain_rpc_url,
            agent.signing_address,
            chain_id=selected.onchain_chain_id,
            executor=selected.onchain_executor,
        )
        try:
            observation = verifier.verify_transfer(
                data.transaction_hash,
                owner=owner,
                token=data.token,
                recipient=data.recipient,
                amount=int(data.amount),
                policy_version=data.policy_version,
            )
        finally:
            verifier.close()
    except (RpcError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="could not verify onchain observation") from exc
    if observation.get("transfer_verified") or observation.get("reverted_call_verified"):
        # An RPC observation can be reorged later; this is not a finality claim.
        detail = json.dumps(
            {
                "chain_id": selected.onchain_chain_id,
                "executor": selected.onchain_executor,
                "agent_id": data.agent_id,
                "token": data.token,
                "recipient": data.recipient,
                "amount": data.amount,
                "block_hash": observation["block_hash"],
                "block_number": observation["block_number"],
            },
            separators=(",", ":"),
        )
        session.add(
            AuditEvent(
                id=str(uuid4()),
                owner_address=owner,
                actor_address=agent.signing_address,
                event_type="onchain_transfer_observed"
                if observation.get("transfer_verified")
                else "onchain_transfer_revert_observed",
                resource=data.transaction_hash.lower(),
                decision="observed" if observation.get("transfer_verified") else "reverted",
                reason=detail,
                policy_version=data.policy_version,
            )
        )
        session.commit()
    return {
        "observation": observation,
        "source": "configured_rpc",
        "finalized": False,
        "chain_id": selected.onchain_chain_id,
        "executor": selected.onchain_executor,
    }


def advance_policy(session: Session, owner: str) -> int:
    return session.execute(
        update(PolicyState)
        .where(PolicyState.owner_address == owner)
        .values(version=PolicyState.version + 1)
        .returning(PolicyState.version)
    ).scalar_one()


@app.post("/agents/{agent_id}/revoke")
def revoke_agent(
    agent_id: str,
    owner: Annotated[str, Depends(authenticate)],
    session: Annotated[Session, Depends(get_session)],
):
    agent = owned_agent(session, agent_id, owner)
    if agent.revoked:
        raise HTTPException(status_code=409, detail="agent already revoked")
    version = advance_policy(session, owner)
    changed = session.execute(
        update(Agent).where(Agent.id == agent_id, Agent.revoked.is_(False)).values(revoked=True)
    )
    if changed.rowcount != 1:
        session.rollback()
        raise HTTPException(status_code=409, detail="agent already revoked")
    session.add(
        AuditEvent(
            id=str(uuid4()),
            owner_address=owner,
            actor_address=owner,
            event_type="agent_revoked",
            resource=agent_id,
            decision="allowed",
            reason="owner signed revocation",
            policy_version=version,
        )
    )
    session.commit()
    return {"id": agent_id, "policy_version": version, "revoked": True}


@app.post("/capabilities/grant", status_code=201)
def grant_capability(
    data: CapabilityGrant,
    owner: Annotated[str, Depends(authenticate)],
    session: Annotated[Session, Depends(get_session)],
):
    agent = owned_agent(session, data.agent_id, owner)
    if agent.revoked:
        raise HTTPException(status_code=400, detail="agent revoked")
    if (data.operation == "transfer") != (data.max_amount is not None):
        raise HTTPException(
            status_code=422, detail="transfer requires a limit; memory operations do not"
        )
    version = advance_policy(session, owner)
    # A new grant replaces prior grants in the same scope, so reducing a limit
    # cannot leave a wider permission active.
    session.execute(
        update(Capability)
        .where(
            Capability.agent_id == agent.id,
            Capability.operation == data.operation,
            Capability.resource == data.resource,
            Capability.revoked.is_(False),
        )
        .values(revoked=True)
    )
    cap = Capability(
        id=str(uuid4()),
        agent_id=agent.id,
        operation=data.operation,
        resource=data.resource,
        max_amount=data.max_amount,
        expires_at=data.expires_at,
        revoked=False,
        policy_version=version,
    )
    session.add(cap)
    session.add(
        AuditEvent(
            id=str(uuid4()),
            owner_address=owner,
            actor_address=owner,
            event_type="capability_granted",
            resource=cap.id,
            decision="allowed",
            reason="owner signed grant",
            policy_version=version,
        )
    )
    session.commit()
    return {"id": cap.id, "policy_version": version}


@app.post("/capabilities/{capability_id}/revoke")
def revoke_capability(
    capability_id: str,
    owner: Annotated[str, Depends(authenticate)],
    session: Annotated[Session, Depends(get_session)],
):
    cap = session.get(Capability, capability_id)
    if cap is None:
        raise HTTPException(status_code=404, detail="capability not found")
    owned_agent(session, cap.agent_id, owner)
    if cap.revoked:
        raise HTTPException(status_code=409, detail="capability already revoked")
    version = advance_policy(session, owner)
    changed = session.execute(
        update(Capability)
        .where(Capability.id == capability_id, Capability.revoked.is_(False))
        .values(revoked=True)
    )
    if changed.rowcount != 1:
        session.rollback()
        raise HTTPException(status_code=409, detail="capability already revoked")
    session.add(
        AuditEvent(
            id=str(uuid4()),
            owner_address=owner,
            actor_address=owner,
            event_type="capability_revoked",
            resource=cap.id,
            decision="allowed",
            reason="owner signed revocation",
            policy_version=version,
        )
    )
    session.commit()
    return {"id": cap.id, "policy_version": version}


class SimulatedTransfer(BaseModel):
    agent_id: str
    asset: str = Field(min_length=1, max_length=128)
    amount: int = Field(gt=0, lt=2**256)
    policy_version: int = Field(ge=0)

    @field_validator("policy_version", mode="before")
    @classmethod
    def version_is_integer(cls, value):
        return validate_integer_amount(value)

    @field_validator("amount", mode="before")
    @classmethod
    def amount_is_integer(cls, value):
        return validate_integer_amount(value)


@app.post("/actions/simulate-transfer")
def simulate_transfer(
    data: SimulatedTransfer,
    signer: Annotated[str, Depends(authenticate)],
    session: Annotated[Session, Depends(get_session)],
):
    # The local simulator serializes decisions with policy changes. A real tool
    # or contract must perform its own check at its execution boundary.
    session.execute(text("BEGIN IMMEDIATE"))
    agent = session.get(Agent, data.agent_id)
    if agent is None or agent.signing_address != signer:
        raise HTTPException(status_code=404, detail="agent not found")
    current = session.get(PolicyState, agent.owner_address)
    if current is None:
        raise HTTPException(status_code=403, detail="no policy")
    capabilities = session.scalars(select(Capability).where(Capability.agent_id == agent.id)).all()
    decision = evaluate(
        agent,
        capabilities,
        operation="transfer",
        resource=data.asset,
        amount=data.amount,
        policy_version=current.version,
        expected_version=data.policy_version,
    )
    event = AuditEvent(
        id=str(uuid4()),
        owner_address=agent.owner_address,
        actor_address=signer,
        event_type="transfer_simulated",
        resource=data.asset,
        decision="allowed" if decision.allowed else "denied",
        reason=json.dumps(
            {
                "schema": "memoryseal.transfer-simulation.v1",
                "reason": decision.reason,
                "agent_id": agent.id,
                "asset": data.asset,
                "amount": str(data.amount),
                "requested_policy_version": data.policy_version,
                "capabilities": [
                    {
                        "id": cap.id,
                        "max_amount": str(cap.max_amount) if cap.max_amount is not None else None,
                        "revoked": cap.revoked,
                        "expires_at": cap.expires_at.isoformat() if cap.expires_at else None,
                    }
                    for cap in capabilities
                    if not cap.revoked
                    and cap.operation == "transfer"
                    and cap.resource == data.asset
                ],
            },
            separators=(",", ":"),
        ),
        policy_version=decision.policy_version,
    )
    session.add(event)
    session.commit()
    return {
        "allowed": decision.allowed,
        "executed": False,
        "simulation": True,
        "reason": decision.reason,
        "policy_version": decision.policy_version,
        "event_id": event.id,
    }


class MemoryWrite(BaseModel):
    agent_id: str
    namespace: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=32768)
    source_type: Literal["external", "agent"]
    source_reference: str | None = Field(default=None, max_length=1024)
    parent_id: str | None = None
    request_id: str | None = None

    @field_validator("request_id")
    @classmethod
    def valid_request_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return str(UUID(value))
        except ValueError as exc:
            raise ValueError("request_id must be a UUID") from exc


class MemoryRead(BaseModel):
    agent_id: str
    namespace: str = Field(min_length=1, max_length=128)
    offset: int = Field(default=0, ge=0, le=2**63 - 101)
    limit: int = Field(default=100, ge=1, le=100)


@app.post("/memory/write", status_code=201)
def write_memory(
    data: MemoryWrite,
    signer: Annotated[str, Depends(authenticate)],
    session: Annotated[Session, Depends(get_session)],
):
    item = memory_service.write(session, signer=signer, **data.model_dump())
    eligible = item.id in memory_service.readable_lineage(
        session, item.owner_address, item.namespace, [item.id]
    )
    return {
        "id": item.id,
        "request_id": item.request_id,
        "status": item.status,
        "lineage_eligible": eligible,
        "trust_class": item.trust_class,
        "commitment": item.commitment,
        "policy_version": item.policy_version,
    }


@app.post("/memory/read")
def read_memory(
    data: MemoryRead,
    signer: Annotated[str, Depends(authenticate)],
    session: Annotated[Session, Depends(get_session)],
):
    return memory_service.read(session, signer=signer, **data.model_dump())


@app.get("/chains")
def list_chains(_signer: Annotated[str, Depends(authenticate)]):
    return {"chains": public_networks()}


from memoryseal.organizations import router as organization_router
from memoryseal.vault import router as vault_router

app.include_router(organization_router)
app.include_router(vault_router)
