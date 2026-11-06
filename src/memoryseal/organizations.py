"""Wallet-owned team scopes. Delegation affects gateway policy, never wallet custody."""

from typing import Annotated, Literal
from uuid import uuid4

from eth_utils import is_address
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from memoryseal.auth import authenticate
from memoryseal.db import get_session
from memoryseal.models import (
    Agent,
    AuditEvent,
    Capability,
    Organization,
    OrganizationMember,
    PolicyState,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])
Signer = Annotated[str, Depends(authenticate)]
Database = Annotated[Session, Depends(get_session)]


def role_for(session, org, signer):
    if signer == org.owner_address:
        return "owner"
    member = session.get(OrganizationMember, (org.id, signer))
    return member.role if member else None


def require_org(session, org_id, signer, *, manage=False):
    org = session.get(Organization, org_id)
    role = role_for(session, org, signer) if org else None
    if not role:
        raise HTTPException(404, "organization not found")
    if manage and role not in ("owner", "admin"):
        raise HTTPException(403, "organization administrator required")
    return org


def audit(session, org, signer, operation, resource):
    state = session.get(PolicyState, org.owner_address)
    session.add(
        AuditEvent(
            id=str(uuid4()),
            owner_address=org.owner_address,
            actor_address=signer,
            event_type="organization_" + operation,
            resource=resource,
            decision="allowed",
            reason="organization role authorized operation",
            policy_version=state.version if state else 0,
        )
    )


class NewOrganization(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@router.post("", status_code=201)
def create(data: NewOrganization, signer: Signer, session: Database):
    session.execute(text("BEGIN IMMEDIATE"))
    if session.scalar(select(Organization).where(Organization.owner_address == signer)):
        raise HTTPException(409, "this owner already has an organization")
    org = Organization(id=str(uuid4()), owner_address=signer, name=data.name, version=1)
    session.add(org)
    if not session.get(PolicyState, signer):
        session.add(PolicyState(owner_address=signer, version=0))
    audit(session, org, signer, "created", org.id)
    session.commit()
    return {"id": org.id, "name": org.name, "owner_address": signer, "version": 1, "role": "owner"}


@router.get("")
def listing(signer: Signer, session: Database):
    ids = select(OrganizationMember.organization_id).where(OrganizationMember.address == signer)
    rows = session.scalars(
        select(Organization).where(
            (Organization.owner_address == signer) | Organization.id.in_(ids)
        )
    ).all()
    return {
        "organizations": [
            {
                "id": o.id,
                "name": o.name,
                "owner_address": o.owner_address,
                "version": o.version,
                "role": role_for(session, o, signer),
            }
            for o in rows
        ]
    }


@router.get("/{org_id}")
def detail(org_id: str, signer: Signer, session: Database):
    org = require_org(session, org_id, signer)
    agents = session.scalars(select(Agent).where(Agent.owner_address == org.owner_address)).all()
    caps = session.scalars(
        select(Capability).where(Capability.agent_id.in_([a.id for a in agents]))
    ).all()
    return {
        "id": org.id,
        "name": org.name,
        "owner_address": org.owner_address,
        "version": org.version,
        "role": role_for(session, org, signer),
        "members": [
            {"address": m.address, "role": m.role}
            for m in session.scalars(
                select(OrganizationMember).where(OrganizationMember.organization_id == org.id)
            )
        ],
        "agents": [
            {"id": a.id, "signing_address": a.signing_address, "revoked": a.revoked} for a in agents
        ],
        "capabilities": [
            {
                "id": c.id,
                "agent_id": c.agent_id,
                "operation": c.operation,
                "resource": c.resource,
                "max_amount": str(c.max_amount) if c.max_amount else None,
                "expires_at": c.expires_at,
                "revoked": c.revoked,
            }
            for c in caps
        ],
    }


class MemberChange(BaseModel):
    address: str
    role: Literal["admin", "auditor", "remove"]
    expected_version: int = Field(ge=1, strict=True)


@router.post("/{org_id}/members")
def membership(org_id: str, data: MemberChange, signer: Signer, session: Database):
    session.execute(text("BEGIN IMMEDIATE"))
    org = require_org(session, org_id, signer)
    if signer != org.owner_address:
        raise HTTPException(403, "only the owner can change membership")
    if org.version != data.expected_version:
        raise HTTPException(409, "organization version changed")
    address = data.address.lower()
    if not is_address(address) or int(address, 16) == 0 or address == org.owner_address:
        raise HTTPException(422, "invalid member; owner cannot be replaced or removed")
    member = session.get(OrganizationMember, (org_id, address))
    if data.role == "remove":
        if member:
            session.delete(member)
    elif member:
        member.role = data.role
    else:
        session.add(OrganizationMember(organization_id=org_id, address=address, role=data.role))
    org.version += 1
    audit(session, org, signer, "membership_changed", address)
    session.commit()
    return {"version": org.version}


class OrganizationAgent(BaseModel):
    signing_address: str
    policy_chain_id: int | None = Field(default=None, gt=0, le=2**53 - 1, strict=True)


@router.post("/{org_id}/agents")
def register(org_id: str, data: OrganizationAgent, signer: Signer, session: Database):
    session.execute(text("BEGIN IMMEDIATE"))
    org = require_org(session, org_id, signer, manage=True)
    from memoryseal.networks import network

    if data.policy_chain_id is not None:
        network(data.policy_chain_id)
    address = data.signing_address.lower()
    if not is_address(address) or int(address, 16) == 0:
        raise HTTPException(422, "invalid agent address")
    if session.scalar(
        select(Agent).where(
            Agent.owner_address == org.owner_address, Agent.signing_address == address
        )
    ):
        raise HTTPException(409, "agent already registered")
    agent = Agent(
        id=str(uuid4()),
        owner_address=org.owner_address,
        signing_address=address,
        policy_chain_id=data.policy_chain_id,
        revoked=False,
    )
    session.add(agent)
    audit(session, org, signer, "agent_registered", agent.id)
    session.commit()
    return {"id": agent.id}


@router.post("/{org_id}/capabilities")
def grant(org_id: str, data: dict, signer: Signer, session: Database):
    from pydantic import ValidationError

    from memoryseal.api import CapabilityGrant

    try:
        value = CapabilityGrant.model_validate(data)
    except ValidationError:
        raise HTTPException(422, "invalid capability") from None
    session.execute(text("BEGIN IMMEDIATE"))
    org = require_org(session, org_id, signer, manage=True)
    agent = session.get(Agent, value.agent_id)
    if not agent or agent.owner_address != org.owner_address or agent.revoked:
        raise HTTPException(404, "active organization agent not found")
    if (value.operation == "transfer") != (value.max_amount is not None):
        raise HTTPException(422, "transfer requires a limit; memory operations do not")
    state = session.get(PolicyState, org.owner_address)
    state.version += 1
    session.execute(
        update(Capability)
        .where(
            Capability.agent_id == agent.id,
            Capability.operation == value.operation,
            Capability.resource == value.resource,
        )
        .values(revoked=True)
    )
    cap = Capability(
        id=str(uuid4()),
        agent_id=agent.id,
        operation=value.operation,
        resource=value.resource,
        max_amount=value.max_amount,
        expires_at=value.expires_at,
        revoked=False,
        policy_version=state.version,
    )
    session.add(cap)
    audit(session, org, signer, "capability_granted", cap.id)
    session.commit()
    return {"id": cap.id, "policy_version": state.version}


@router.post("/{org_id}/revoke/{kind}/{item_id}")
def revoke(
    org_id: str,
    kind: Literal["agent", "capability"],
    item_id: str,
    signer: Signer,
    session: Database,
):
    session.execute(text("BEGIN IMMEDIATE"))
    org = require_org(session, org_id, signer, manage=True)
    item = session.get(Agent if kind == "agent" else Capability, item_id)
    agent = item if kind == "agent" else session.get(Agent, item.agent_id) if item else None
    if not agent or agent.owner_address != org.owner_address:
        raise HTTPException(404, "organization resource not found")
    state = session.get(PolicyState, org.owner_address)
    if not item.revoked:
        item.revoked = True
        state.version += 1
        audit(session, org, signer, kind + "_revoked", item_id)
    session.commit()
    return {"revoked": True, "policy_version": state.version}
