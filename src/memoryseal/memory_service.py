"""Local encrypted memory persistence and namespace enforcement."""

import base64
import binascii
import hmac
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session, aliased

from memoryseal.attested_transport import AttestedGatewayTransport, verifier_configured
from memoryseal.bridge_transport import BridgeTransport, bridge_configured
from memoryseal.chain_memory import ChainPolicyError
from memoryseal.chain_memory import is_allowed as chain_memory_allowed
from memoryseal.config import settings
from memoryseal.encryption import (
    SealedMemory,
    namespace_key,
    open_memory,
    protect_source_reference,
    reveal_salt,
    reveal_source_reference,
    seal,
    write_digest,
)
from memoryseal.firewall import is_authorization_claim
from memoryseal.inference import InferenceError, ThreatAnalysis, ZeroGClassifier
from memoryseal.models import Agent, AuditEvent, Capability, Memory, PolicyState, ProvenanceOutbox
from memoryseal.policy import evaluate
from memoryseal.provenance import memory_created, memory_origin_attested, memory_quarantined
from memoryseal.zero_g_provider_verifier import provider_verifier_configured, verify_provider_quote
from memoryseal.zero_g_registry import registry_pins_match
from memoryseal.zero_g_verification import valid_pins, verify_pinned_response


def key_for(owner: str, namespace: str) -> bytes:
    try:
        master = base64.b64decode(settings.encryption_key or "", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=503, detail="memory encryption key unavailable") from exc
    if len(master) != 32:
        raise HTTPException(status_code=503, detail="memory encryption key unavailable")
    return namespace_key(master, owner, namespace)


def context(memory_id: str, owner: str, namespace: str) -> bytes:
    return json.dumps([memory_id, owner, namespace], separators=(",", ":")).encode()


def stored_analysis(raw: str | None) -> tuple[dict | None, str]:
    """Parse stored classifier data without turning corrupt records into readable ones."""
    if raw is None:
        return None, "not_recorded"
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise TypeError("analysis must be an object")
        fields = {key: value for key, value in data.items() if key != "evidence"}
        ThreatAnalysis.model_validate(fields)
        if data.get("evidence") is not None and not isinstance(data["evidence"], dict):
            raise TypeError("invalid analysis evidence")
        return data, "available"
    except (TypeError, ValueError, ValidationError):
        return None, "invalid"


def analysis_requires_quarantine(analysis: dict) -> bool:
    """Apply the same classifier risk rules to new and previously stored memories."""
    return (
        analysis["category"] in ("authorization_claim", "instruction")
        or analysis["risk"] == "high"
        or analysis["suspicious_instruction"]
        or bool(analysis["conflicts_with"])
        or analysis["recommendation"] in ("quarantine", "reject")
    )


def authorize(
    session: Session, agent_id: str, signer: str, operation: str, namespace: str
) -> tuple[Agent, int]:
    agent = session.get(Agent, agent_id)
    if agent is None or agent.signing_address != signer:
        raise HTTPException(status_code=404, detail="agent not found")
    state = session.get(PolicyState, agent.owner_address)

    def deny(reason: str):
        # Only attribute attempts after the agent identity has been verified.
        # Persist the denial before raising, without recording memory content.
        session.add(
            AuditEvent(
                id=str(uuid4()),
                owner_address=agent.owner_address,
                actor_address=signer,
                event_type="namespace_access_denied",
                resource=namespace,
                decision="denied",
                reason=f"{operation}: {reason}",
                policy_version=state.version if state else 0,
            )
        )
        session.commit()
        raise HTTPException(status_code=403, detail=reason)

    if state is None:
        deny("no policy")
    caps = session.scalars(select(Capability).where(Capability.agent_id == agent.id)).all()
    if not evaluate(
        agent, caps, operation=operation, resource=namespace, policy_version=state.version
    ).allowed:
        deny("namespace access denied")
    if settings.require_onchain_memory:
        if (
            not settings.onchain_rpc_url
            or not settings.onchain_chain_id
            or not settings.onchain_registry
        ):
            raise HTTPException(status_code=503, detail="onchain memory policy not configured")
        try:
            permitted = chain_memory_allowed(
                rpc_url=settings.onchain_rpc_url,
                chain_id=settings.onchain_chain_id,
                registry=settings.onchain_registry,
                owner=agent.owner_address,
                agent=agent.signing_address,
                namespace=namespace,
                operation=operation,
            )
        except ChainPolicyError as exc:
            raise HTTPException(
                status_code=503, detail="onchain memory policy unavailable"
            ) from exc
        if not permitted:
            deny("onchain namespace access denied")
    return agent, state.version


def write(
    session: Session,
    *,
    agent_id: str,
    signer: str,
    namespace: str,
    content: str,
    source_type: str,
    source_reference: str | None,
    parent_id: str | None,
    request_id: str | None = None,
) -> Memory:
    session.execute(text("BEGIN IMMEDIATE"))
    session.expire_all()
    agent, version = authorize(session, agent_id, signer, "write", namespace)
    digest = None
    if request_id:
        digest = write_digest(
            key_for(agent.owner_address, namespace),
            namespace,
            content,
            source_type,
            source_reference,
            parent_id,
        )

    def existing_request():
        if not request_id:
            return None
        item = session.scalar(
            select(Memory).where(Memory.agent_id == agent_id, Memory.request_id == request_id)
        )
        if item and (
            not item.request_digest or not hmac.compare_digest(item.request_digest, digest)
        ):
            raise HTTPException(
                status_code=409, detail="request_id already used for a different write"
            )
        return item

    prior = existing_request()
    if prior:
        session.commit()
        return prior
    parent = None
    if parent_id:
        parent = session.get(Memory, parent_id)
        if (
            not parent
            or parent.owner_address != agent.owner_address
            or parent.namespace != namespace
        ):
            raise HTTPException(status_code=404, detail="parent memory not found")
    # Do not hold a database write lock during inference. Recheck permissions
    # afterwards, so a concurrent revocation prevents the write.
    snapshot_version = version
    capabilities = session.execute(
        select(Capability, Agent)
        .join(Agent, Agent.id == Capability.agent_id)
        .where(
            Agent.owner_address == agent.owner_address,
            Agent.revoked.is_(False),
            Capability.revoked.is_(False),
            or_(Capability.expires_at.is_(None), Capability.expires_at > datetime.now(UTC)),
        )
    ).all()
    known_capability_ids = {cap.id for cap, _ in capabilities}
    policy_context = json.dumps(
        {
            "source": "local_gateway",
            "policy_version": snapshot_version,
            "capabilities": [
                {
                    "id": cap.id,
                    "agent_id": subject.id,
                    "operation": cap.operation,
                    "resource": cap.resource,
                    "max_amount": str(cap.max_amount) if cap.max_amount is not None else None,
                    "expires_at": cap.expires_at.isoformat() if cap.expires_at else None,
                }
                for cap, subject in capabilities
            ],
        }
    )
    expiries = [
        cap.expires_at.replace(tzinfo=UTC)
        if cap.expires_at.tzinfo is None
        else cap.expires_at.astimezone(UTC)
        for cap, _ in capabilities
        if cap.expires_at is not None
    ]
    earliest_expiry = min(expiries) if expiries else None
    agent_context = {
        "agent_id": agent.id,
        "namespace": namespace,
        "signing_address": agent.signing_address,
    }
    session.commit()
    analysis, reference, evidence = None, None, None
    inference_status = "not_configured"
    api_key = settings.zero_g_api_key.get_secret_value() if settings.zero_g_api_key else ""
    pins = (
        settings.zero_g_provider_address,
        settings.zero_g_tee_signer,
        settings.zero_g_signature_base_url,
    )
    pins_invalid = any(pins) and not valid_pins(*pins)
    if settings.zero_g_registry_rpc_url and not valid_pins(*pins):
        pins_invalid = True
    attestation_ready = not settings.require_connection_attestation or verifier_configured(
        settings.connection_attestation_verifier, settings.connection_attestation_verifier_sha256
    )
    bridge_mode = settings.zero_g_experimental_bridge
    bridge_ready = not bridge_mode or (
        settings.zero_g_trust_mode == "private"
        and not settings.require_connection_attestation
        and bridge_configured(
            settings.zero_g_bridge_executable, settings.zero_g_bridge_sha256, pins
        )
        and (
            not settings.zero_g_provider_verifier
            or (
                provider_verifier_configured(
                    settings.zero_g_provider_verifier, settings.zero_g_provider_verifier_sha256
                )
                and bool(settings.zero_g_registry_rpc_url)
            )
        )
    )
    registry_checked = False
    if (
        settings.zero_g_registry_rpc_url
        and not pins_invalid
        and api_key
        and settings.zero_g_model
        and attestation_ready
        and bridge_ready
    ):
        registry_checked = registry_pins_match(
            rpc_url=settings.zero_g_registry_rpc_url,
            network=settings.zero_g_network,
            provider=pins[0],
            signer=pins[1],
            base_url=pins[2],
        )
        if not registry_checked:
            pins_invalid = True
    quote_key = None
    if (
        bridge_mode
        and settings.zero_g_provider_verifier
        and not pins_invalid
        and api_key
        and settings.zero_g_model
        and attestation_ready
        and bridge_ready
        and registry_checked
    ):
        quote = verify_provider_quote(
            Path(settings.zero_g_provider_verifier),
            expected_sha256=settings.zero_g_provider_verifier_sha256,
            network=settings.zero_g_network,
            rpc_url=settings.zero_g_registry_rpc_url,
            provider=pins[0],
            signer=pins[1],
            endpoint=pins[2],
        )
        if (
            not isinstance(quote, dict)
            or quote.get("provider") != pins[0].lower()
            or quote.get("signer") != pins[1].lower()
            or not isinstance(quote.get("encryption_key"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", quote["encryption_key"])
            or int(quote["encryption_key"], 16) == 0
        ):
            pins_invalid = True
        else:
            quote_key = quote["encryption_key"]
    if bool(api_key) != bool(settings.zero_g_model):
        inference_status = "failed"
    if bridge_mode and not (api_key and settings.zero_g_model):
        inference_status = "failed"
    if pins_invalid:
        inference_status = "failed"
    if not attestation_ready:
        inference_status = "failed"
    if not bridge_ready:
        inference_status = "failed"
    if (
        api_key
        and settings.zero_g_model
        and not pins_invalid
        and attestation_ready
        and bridge_ready
    ):
        transport = (
            BridgeTransport(
                Path(settings.zero_g_bridge_executable),
                settings.zero_g_bridge_sha256,
                settings.zero_g_network,
                provider=pins[0],
                signer=pins[1],
                endpoint=pins[2],
                recipient_key=quote_key,
            )
            if bridge_mode
            else AttestedGatewayTransport(
                Path(settings.connection_attestation_verifier),
                settings.zero_g_network,
                expected_sha256=settings.connection_attestation_verifier_sha256,
            )
            if settings.require_connection_attestation
            else None
        )
        extra = {"transport": transport} if transport is not None else {}
        classifier = ZeroGClassifier(
            api_key,
            settings.zero_g_model,
            network=settings.zero_g_network,
            provider=settings.zero_g_provider_address,
            trust_mode=settings.zero_g_trust_mode,
            **extra,
        )
        try:
            result = classifier.analyze(
                content=content,
                source_type=source_type,
                policy_context=policy_context,
                agent_context=agent_context,
            )
            analysis, reference = result.analysis, result.request_id
            evidence = {
                "policy_snapshot_version": snapshot_version,
                "policy_snapshot_capability_ids": sorted(cap.id for cap, _ in capabilities),
                "policy_snapshot_transfer_limits": [
                    {
                        "id": cap.id,
                        "agent_id": subject.id,
                        "resource": cap.resource,
                        "max_amount": str(cap.max_amount),
                    }
                    for cap, subject in capabilities
                    if cap.operation == "transfer" and cap.max_amount is not None
                ],
                "gateway_connection_attested": bool(
                    settings.require_connection_attestation
                    and getattr(transport, "verified_fingerprint", None)
                ),
                "gateway_certificate_sha256": getattr(transport, "verified_fingerprint", None),
                "network": result.network,
                "trust_mode": settings.zero_g_trust_mode,
                "inference_transport": "experimental_bridge" if bridge_mode else "router",
                "bridge_reported_provider": getattr(transport, "reported_provider", None)
                if bridge_mode
                else None,
                "bridge_receipt_signer_matched": getattr(transport, "receipt_signer_matched", None)
                if bridge_mode
                else None,
                "bridge_receipt_binding_matched": getattr(
                    transport, "receipt_binding_matched", None
                )
                if bridge_mode
                else None,
                "bridge_receipt_challenge_matched": getattr(
                    transport, "receipt_challenge_matched", None
                )
                if bridge_mode
                else None,
                "bridge_receipt_response_choices_matched": getattr(
                    transport, "receipt_response_choices_matched", None
                )
                if bridge_mode
                else None,
                "bridge_receipt_request_messages_matched": getattr(
                    transport, "receipt_request_messages_matched", None
                )
                if bridge_mode
                else None,
                "bridge_quote_recipient_key_matched": (
                    True
                    if quote_key
                    and getattr(transport, "receipt_request_messages_matched", None) is True
                    else None
                ),
                "response_key": result.response_key,
                "provider": result.provider,
                "router_verified": result.router_verified,
                "provider_record_matched": registry_checked
                if settings.zero_g_registry_rpc_url
                else None,
            }
            inference_status = "unverified"
            if bridge_mode:
                # The executable is an operator trust input; its output cannot
                # independently establish provider attestation or receipt validity.
                inference_status = "unverified"
            elif settings.zero_g_trust_mode != "private":
                inference_status = "unverified"
            elif result.router_verified is False:
                inference_status = "verification_failed"
            elif (
                result.router_verified is True
                and result.provider
                and reference
                and result.response_key
            ):
                inference_status = "router_verified"
            if any(pins) and not bridge_mode and settings.zero_g_trust_mode == "private":
                signature_valid = bool(all(pins)) and verify_pinned_response(
                    provider=result.provider,
                    response_key=result.response_key,
                    response_text=result.response_text,
                    model=settings.zero_g_model,
                    expected_provider=pins[0],
                    signer=pins[1],
                    base_url=pins[2],
                )
                evidence["pinned_signature_verified"] = signature_valid
                inference_status = (
                    "pinned_signature_verified"
                    if signature_valid and inference_status == "router_verified"
                    else "verification_failed"
                )
        except InferenceError:
            inference_status = "failed"
        finally:
            classifier.close()
    if analysis is not None:
        # Model output is untrusted and may echo the private prompt. Only the
        # capability IDs in the supplied policy snapshot are safe references;
        # retain a marker for unknown conflicts so they still quarantine.
        conflicts = [value for value in analysis.conflicts_with if value in known_capability_ids]
        if any(value not in known_capability_ids for value in analysis.conflicts_with):
            conflicts.append("unresolved")
        analysis = analysis.model_copy(update={"conflicts_with": conflicts})
    session.execute(text("BEGIN IMMEDIATE"))
    session.expire_all()
    agent, version = authorize(session, agent_id, signer, "write", namespace)
    prior = existing_request()
    if prior:
        session.commit()
        return prior
    if inference_status in (
        "unverified",
        "verification_failed",
        "router_verified",
        "pinned_signature_verified",
    ) and (
        version != snapshot_version
        or (earliest_expiry is not None and earliest_expiry <= datetime.now(UTC))
    ):
        inference_status = "stale"
    if parent_id:
        parent = session.get(Memory, parent_id)
        if (
            not parent
            or parent.owner_address != agent.owner_address
            or parent.namespace != namespace
        ):
            raise HTTPException(status_code=404, detail="parent memory not found")
    memory_id = str(uuid4())
    encrypted = seal(
        key_for(agent.owner_address, namespace),
        content.encode(),
        context=context(memory_id, agent.owner_address, namespace),
    )
    authorization_claim = is_authorization_claim(content)
    reason = "untrusted agent memory"
    if inference_status == "not_configured":
        reason = "inference not configured"
    elif inference_status == "failed":
        reason = "inference failed"
    elif inference_status in ("unverified", "verification_failed"):
        reason = "inference verification missing or failed"
    elif inference_status == "stale":
        reason = "policy context changed during inference"
    elif not settings.allow_unbound_inference:
        reason = "inference response is not verified against the request"
    elif analysis and analysis_requires_quarantine(analysis.model_dump()):
        reason = "classifier indicated risk"
    elif authorization_claim:
        reason = "untrusted authorization claim"
    elif source_type == "external":
        reason = "external source requires quarantine"
    elif parent is not None and parent.id not in readable_lineage(
        session, agent.owner_address, namespace, [parent.id]
    ):
        reason = "parent memory has quarantined or invalid ancestry"
    status = "accepted" if reason == "untrusted agent memory" else "quarantined"
    item = Memory(
        id=memory_id,
        owner_address=agent.owner_address,
        agent_id=agent.id,
        request_id=request_id,
        request_digest=digest,
        namespace=namespace,
        source_type=source_type,
        source_reference=None,
        source_reference_encrypted=protect_source_reference(
            key_for(agent.owner_address, namespace),
            source_reference,
            context=context(memory_id, agent.owner_address, namespace),
        ),
        category="authorization_claim"
        if authorization_claim
        else (analysis.category if analysis else "unclassified"),
        trust_class="untrusted",
        status=status,
        inference_status=inference_status,
        inference_reference=reference,
        analysis_json=json.dumps({**analysis.model_dump(), "evidence": evidence})
        if analysis
        else None,
        ciphertext=encrypted.ciphertext,
        encryption_nonce=encrypted.nonce,
        salt=encrypted.salt,
        commitment=encrypted.commitment,
        parent_id=parent_id,
        policy_version=version,
    )
    session.add(item)
    session.add(memory_created(item, agent_address=signer))
    session.add(
        AuditEvent(
            id=str(uuid4()),
            owner_address=agent.owner_address,
            actor_address=signer,
            event_type="memory_created",
            resource=memory_id,
            decision=status,
            reason=reason,
            policy_version=version,
        )
    )
    session.commit()
    return item


def readable_lineage(
    session: Session, owner: str, namespace: str, memory_ids: list[str]
) -> set[str]:
    """Check only requested memories and their recorded ancestors."""
    # Neither supported router status proves request/response binding. Old
    # accepted records must not bypass the current security policy.
    if not settings.allow_unbound_inference:
        return set()
    nodes = {}
    # Chunk seeds to stay below SQLite's bound-variable limits. UNION, not UNION
    # ALL, terminates even if corrupt legacy data contains a cycle.
    for offset in range(0, len(memory_ids), 500):
        seeds = memory_ids[offset : offset + 500]
        ancestors = (
            select(
                Memory.id,
                Memory.parent_id,
                Memory.status,
                Memory.inference_status,
                Memory.category,
                Memory.analysis_json,
                Memory.source_type,
            )
            .where(
                Memory.id.in_(seeds),
                Memory.owner_address == owner,
                Memory.namespace == namespace,
            )
            .cte(name="ancestors", recursive=True)
        )
        parent = aliased(Memory)
        ancestors = ancestors.union(
            select(
                parent.id,
                parent.parent_id,
                parent.status,
                parent.inference_status,
                parent.category,
                parent.analysis_json,
                parent.source_type,
            )
            .join(ancestors, parent.id == ancestors.c.parent_id)
            .where(parent.owner_address == owner, parent.namespace == namespace)
        )
        rows = session.execute(select(ancestors)).all()
        nodes.update(
            {
                row.id: (
                    row.parent_id,
                    row.status,
                    row.inference_status,
                    row.category,
                    row.analysis_json,
                    row.source_type,
                )
                for row in rows
            }
        )
    resolved: dict[str, bool] = {}
    for memory_id in nodes:
        path: list[str] = []
        visiting: set[str] = set()
        current = memory_id
        while current not in resolved:
            if current in visiting or current not in nodes:
                valid = False
                break
            parent, status, inference_status, category, analysis_json, source_type = nodes[current]
            analysis, analysis_state = stored_analysis(analysis_json)
            unsafe_analysis = analysis_state != "available" or analysis_requires_quarantine(
                analysis
            )
            if (
                status != "accepted"
                or inference_status not in ("router_verified", "pinned_signature_verified")
                or category in ("instruction", "authorization_claim")
                or source_type != "agent"
                or unsafe_analysis
            ):
                valid = False
                resolved[current] = False
                break
            path.append(current)
            visiting.add(current)
            if parent is None:
                valid = True
                break
            current = parent
        else:
            valid = resolved[current]
        for entry in path:
            resolved[entry] = valid
    return {memory_id for memory_id in memory_ids if resolved.get(memory_id, False)}


def read(
    session: Session, *, agent_id: str, signer: str, namespace: str, offset: int, limit: int
) -> dict:
    session.execute(text("BEGIN IMMEDIATE"))
    agent, _ = authorize(session, agent_id, signer, "read", namespace)
    items = session.scalars(
        select(Memory)
        .where(
            Memory.owner_address == agent.owner_address,
            Memory.namespace == namespace,
            Memory.status == "accepted",
        )
        .order_by(Memory.created_at, Memory.id)
        .offset(offset)
        .limit(limit + 1)
    ).all()
    has_more = len(items) > limit
    items = items[:limit]
    allowed = readable_lineage(session, agent.owner_address, namespace, [item.id for item in items])
    key = key_for(agent.owner_address, namespace)
    result = []
    for item in items:
        if item.id not in allowed:
            continue
        sealed = SealedMemory(item.ciphertext, item.encryption_nonce, item.salt, item.commitment)
        content = open_memory(key, sealed, context=context(item.id, item.owner_address, namespace))
        result.append(
            {
                "id": item.id,
                "content": content.decode(),
                "source_type": item.source_type,
                "trust_class": item.trust_class,
                "commitment": item.commitment,
                "parent_id": item.parent_id,
            }
        )
    session.commit()
    return {"memories": result, "next_offset": offset + limit if has_more else None}


def author_commitment_salt(session: Session, *, memory_id: str, signer: str) -> dict:
    """Disclose the opening only to the original agent with current write access."""
    session.execute(text("BEGIN IMMEDIATE"))
    session.expire_all()
    item = session.get(Memory, memory_id)
    if item is None:
        raise HTTPException(status_code=404, detail="memory not found")
    agent = session.get(Agent, item.agent_id)
    if (
        agent is None
        or agent.owner_address != item.owner_address
        or agent.signing_address != signer
    ):
        raise HTTPException(status_code=404, detail="memory not found")
    authorize(session, agent.id, signer, "write", item.namespace)
    key = key_for(item.owner_address, item.namespace)
    binding = context(item.id, item.owner_address, item.namespace)
    open_memory(
        key,
        SealedMemory(item.ciphertext, item.encryption_nonce, item.salt, item.commitment),
        context=binding,
    )
    salt = base64.b64encode(reveal_salt(key, item.salt, context=binding)).decode("ascii")
    session.add(
        AuditEvent(
            id=str(uuid4()),
            owner_address=item.owner_address,
            actor_address=signer,
            event_type="memory_author_salt_disclosed",
            resource=item.id,
            decision="allowed",
            reason="author requested commitment opening",
            policy_version=item.policy_version,
        )
    )
    session.commit()
    return {"id": item.id, "commitment": item.commitment, "commitment_salt": salt}


def attest_origin(
    session: Session,
    *,
    memory_id: str,
    signer: str,
    event_id: str,
    commitment: str,
    policy_version: int,
    request_proof: dict,
) -> dict:
    """Record the original agent's signed acknowledgement of a commitment."""
    session.execute(text("BEGIN IMMEDIATE"))
    session.expire_all()
    item = session.get(Memory, memory_id)
    if item is None:
        raise HTTPException(status_code=404, detail="memory not found")
    agent = session.get(Agent, item.agent_id)
    if (
        agent is None
        or agent.owner_address != item.owner_address
        or agent.signing_address != signer
    ):
        raise HTTPException(status_code=404, detail="memory not found")
    authorize(session, agent.id, signer, "write", item.namespace)
    if item.commitment != commitment or item.policy_version != policy_version:
        raise HTTPException(status_code=409, detail="memory commitment or creation policy changed")
    if item.status not in ("accepted", "quarantined") or item.trust_class != "untrusted":
        raise HTTPException(status_code=409, detail="memory status cannot be attested")
    existing = session.scalar(
        select(ProvenanceOutbox).where(
            ProvenanceOutbox.memory_id == memory_id,
            ProvenanceOutbox.event_type == "memory_origin_attested",
        )
    )
    if existing:
        session.commit()
        return {"id": item.id, "changed": False, "event_id": existing.id}
    if session.get(ProvenanceOutbox, event_id) is not None:
        raise HTTPException(status_code=409, detail="provenance event identifier already used")
    entry = memory_origin_attested(
        item, agent_address=signer, event_id=event_id, request_proof=request_proof
    )
    session.add(entry)
    session.add(
        AuditEvent(
            id=str(uuid4()),
            owner_address=item.owner_address,
            actor_address=signer,
            event_type="memory_origin_attested",
            resource=item.id,
            decision="recorded",
            reason="agent signed memory commitment",
            policy_version=item.policy_version,
        )
    )
    session.commit()
    return {"id": item.id, "changed": True, "event_id": entry.id}


def quarantine_for_owner(
    session: Session,
    *,
    memory_id: str,
    owner: str,
    request_proof: dict,
    expected_commitment: str | None = None,
    expected_version: int | None = None,
    event_id: str | None = None,
) -> dict:
    """Quarantine once under the same write lock used by memory reads and writes."""
    session.execute(text("BEGIN IMMEDIATE"))
    session.expire_all()
    item = session.get(Memory, memory_id)
    if item is None or item.owner_address != owner:
        raise HTTPException(status_code=404, detail="memory not found")
    if item.status == "quarantined":
        session.commit()
        return {"id": item.id, "status": "quarantined", "changed": False, "event_id": None}
    if item.status != "accepted":
        raise HTTPException(status_code=409, detail="memory status cannot be quarantined")
    agent = session.get(Agent, item.agent_id)
    if agent is None or agent.owner_address != owner:
        raise HTTPException(status_code=409, detail="memory identity unavailable")
    state = session.get(PolicyState, owner)
    if state is None:
        raise HTTPException(status_code=409, detail="owner policy unavailable")
    if event_id is not None and (
        item.commitment != expected_commitment or state.version != expected_version
    ):
        raise HTTPException(status_code=409, detail="memory commitment or policy changed")
    if event_id is not None and session.get(ProvenanceOutbox, event_id) is not None:
        raise HTTPException(status_code=409, detail="provenance event identifier already used")
    item.status = "quarantined"
    entry = memory_quarantined(
        item,
        agent_address=agent.signing_address,
        policy_version=state.version,
        request_proof=request_proof,
        event_id=event_id,
    )
    session.add(entry)
    session.add(
        AuditEvent(
            id=str(uuid4()),
            owner_address=owner,
            actor_address=owner,
            event_type="memory_quarantined",
            resource=item.id,
            decision="quarantined",
            reason="owner quarantined memory",
            policy_version=state.version,
        )
    )
    session.commit()
    return {"id": item.id, "status": item.status, "changed": True, "event_id": entry.id}


def inspect_for_owner(session: Session, *, memory_id: str, owner: str) -> dict:
    """Reveal a memory, including quarantined content, only to its owner."""
    item = session.get(Memory, memory_id)
    if item is None or item.owner_address != owner:
        raise HTTPException(status_code=404, detail="memory not found")
    sealed = SealedMemory(item.ciphertext, item.encryption_nonce, item.salt, item.commitment)
    content = open_memory(
        key_for(owner, item.namespace), sealed, context=context(item.id, owner, item.namespace)
    ).decode()
    source_reference = reveal_source_reference(
        key_for(owner, item.namespace),
        item.source_reference,
        item.source_reference_encrypted,
        context=context(item.id, owner, item.namespace),
    )
    session.add(
        AuditEvent(
            id=str(uuid4()),
            owner_address=owner,
            actor_address=owner,
            event_type="memory_inspected",
            resource=item.id,
            decision="allowed",
            reason="owner inspected memory",
            policy_version=item.policy_version,
        )
    )
    session.commit()
    return {
        "id": item.id,
        "content": content,
        "commitment_salt": base64.b64encode(
            reveal_salt(
                key_for(owner, item.namespace),
                item.salt,
                context=context(item.id, owner, item.namespace),
            )
        ).decode("ascii"),
        "source_reference": source_reference,
        "status": item.status,
        "trust_class": item.trust_class,
        "commitment": item.commitment,
    }
