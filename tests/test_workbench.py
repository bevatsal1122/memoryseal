"""Wallet-role isolation and targeted provenance controls used by the website."""

import base64
import os
from contextlib import ExitStack

import httpx
import pytest
from eth_account import Account
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from memoryseal import auth
from memoryseal.api import app
from memoryseal.client import MemorySealClient
from memoryseal.config import settings
from memoryseal.db import Base, get_session
from memoryseal.models import ProvenanceOutbox


def test_agent_discovery_and_owner_provenance_controls(tmp_path, monkeypatch, gateway_transport):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(auth, "SessionLocal", sessions)
    monkeypatch.setattr(settings, "encryption_key", base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setattr(settings, "zero_g_api_key", None)
    monkeypatch.setattr(settings, "zero_g_model", None)
    monkeypatch.setattr(settings, "require_connection_attestation", False)
    monkeypatch.setattr(settings, "require_onchain_memory", False)

    def db():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = db
    calls = []

    def publish(session, *, memory_id, event_id):
        calls.append((memory_id, event_id))
        row = session.get(ProvenanceOutbox, event_id)
        row.state = "uncertain"
        session.commit()
        return "uncertain"

    def reconcile(session, event_id):
        calls.append(("lookup", event_id))
        return "uncertain"

    monkeypatch.setattr("memoryseal.api.publish_one", publish)
    monkeypatch.setattr("memoryseal.api.reconcile_one", reconcile)
    try:
        with TestClient(app) as server, ExitStack() as stack:
            clients = [
                stack.enter_context(
                    MemorySealClient(
                        "http://testserver",
                        Account.create().key,
                        audience=settings.request_audience,
                        transport=gateway_transport(server),
                    )
                )
                for _ in range(3)
            ]
            owner, agent, other = clients
            aid = owner.register_agent(agent.address)["id"]
            owner.grant(aid, "write", "scope")
            assert owner.agent_access()["agents"] == []
            assert other.agent_access()["agents"] == []
            access = agent.agent_access()["agents"]
            assert len(access) == 1 and access[0]["id"] == aid
            assert access[0]["owner_address"] == owner.address.lower()
            assert access[0]["capabilities"][0]["resource"] == "scope"
            memory = agent.write_memory(aid, "scope", "Synthetic", source_type="agent")
            mid = memory["id"]
            eid = owner.memory_provenance_events(mid)["events"][0]["event_id"]
            for outsider in (agent, other):
                with pytest.raises(httpx.HTTPStatusError) as error:
                    outsider.publish_memory_event(mid, eid)
                assert error.value.response.status_code == 404
            assert not calls
            assert owner.publish_memory_event(mid, eid)["state"] == "uncertain"
            with pytest.raises(httpx.HTTPStatusError) as error:
                owner.publish_memory_event(mid, eid)
            assert error.value.response.status_code == 409
            assert owner.reconcile_memory_event(mid, eid)["state"] == "uncertain"
            assert calls == [(mid, eid), ("lookup", eid)]
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
