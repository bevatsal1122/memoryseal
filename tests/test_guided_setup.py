"""Explicit signed owner review is distinct from attestation and action authority."""

import base64
import os
from contextlib import ExitStack
from uuid import uuid4

import httpx
import pytest
from eth_account import Account
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from memoryseal import auth
from memoryseal.api import app
from memoryseal.client import MemorySealClient
from memoryseal.config import settings
from memoryseal.db import Base, get_session
from memoryseal.inference import InferenceResult, ThreatAnalysis


def test_atomic_setup_and_scoped_session_reads(tmp_path, monkeypatch, gateway_transport):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(auth, "SessionLocal", sessions)
    monkeypatch.setattr(settings, "encryption_key", base64.b64encode(os.urandom(32)).decode())
    for key, value in {
        "zero_g_api_key": SecretStr("mock"),
        "zero_g_model": "mock",
        "zero_g_trust_mode": "router_default",
        "require_connection_attestation": False,
        "allow_unbound_inference": False,
        "zero_g_experimental_bridge": False,
        "require_onchain_memory": False,
        "zero_g_provider_address": None,
        "zero_g_tee_signer": None,
        "zero_g_signature_base_url": None,
        "zero_g_registry_rpc_url": None,
    }.items():
        monkeypatch.setattr(settings, key, value)

    analysis_overrides = {}

    class Classifier:
        def __init__(self, *args, **kwargs):
            pass

        def close(self):
            pass

        def analyze(self, **kwargs):
            return InferenceResult(
                ThreatAnalysis(
                    **(
                        {
                            "category": "observation",
                            "risk": "low",
                            "suspicious_instruction": False,
                            "conflicts_with": [],
                            "recommendation": "accept",
                        }
                        | analysis_overrides
                    )
                ),
                "request",
                None,
                None,
                None,
                "mainnet",
            )

    monkeypatch.setattr("memoryseal.memory_service.ZeroGClassifier", Classifier)

    def db():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = db
    try:
        with TestClient(app) as server, ExitStack() as stack:
            owner, writer, reader, _other = [
                stack.enter_context(
                    MemorySealClient(
                        "http://testserver",
                        Account.create().key,
                        audience=settings.request_audience,
                        transport=gateway_transport(server),
                    )
                )
                for _ in range(4)
            ]
            from eth_account.messages import encode_defunct

            from memoryseal import browser_sessions
            from memoryseal.models import Agent, Capability, PolicyState

            monkeypatch.setattr(browser_sessions, "SessionLocal", sessions)
            payload = {
                "request_id": str(uuid4()),
                "signing_address": writer.address,
                "label": "Research",
                "namespace": "research",
                "operations": ["read", "write"],
                "acceptance": "standard",
                "policy_version": 0,
            }
            result = owner._post("/agents/setup", payload)
            assert owner._post("/agents/setup", payload) == result
            with sessions() as db:
                from sqlalchemy import func, select

                assert db.scalar(select(func.count()).select_from(Agent)) == 1
                assert db.scalar(select(func.count()).select_from(Capability)) == 2
                assert db.get(PolicyState, owner.address.lower()).version == 1
            with pytest.raises(httpx.HTTPStatusError):
                owner._post("/agents/setup", payload | {"namespace": "other"})
            with pytest.raises(httpx.HTTPStatusError):
                owner._post(
                    "/agents/setup",
                    payload
                    | {
                        "request_id": str(uuid4()),
                        "signing_address": reader.address,
                        "policy_version": 0,
                    },
                )
            assert len(owner._request("GET", "/agents")["agents"]) == 1
            memory = writer.write_memory(
                result["id"], "research", "Meeting is Tuesday", source_type="agent"
            )
            assert memory["status"] == "accepted"
            assert owner._request("GET", "/workspace-summary")["memories"] == 1
            # Browser session authorizes only the exact read endpoint, never writes.
            actor = Account.create()
            aid = owner.register_agent(actor.address)["id"]
            owner.grant(aid, "read", "research")
            headers = {"Origin": "http://localhost:3000"}
            challenge = server.post(
                "/auth/challenge", headers=headers, json={"address": actor.address}
            ).json()
            signature = Account.sign_message(
                encode_defunct(text=challenge["message"]), actor.key
            ).signature.hex()
            token = server.post(
                "/auth/session",
                headers=headers,
                json={"challenge": challenge["challenge"], "signature": signature},
            ).json()["token"]
            headers["Authorization"] = "Bearer " + token
            got = server.post(
                "/memory/read", headers=headers, json={"agent_id": aid, "namespace": "research"}
            )
            assert got.status_code == 200 and len(got.json()["memories"]) == 1
            assert (
                server.post(
                    "/memory/read",
                    headers=headers,
                    json={"agent_id": result["id"], "namespace": "research"},
                ).status_code
                == 404
            )
            for path in ("/memory/write", "/agents/setup", "/acceptance-rules"):
                assert server.post(path, headers=headers, json=payload).status_code == 403
            owner.revoke_agent(aid)
            assert (
                server.post(
                    "/memory/read", headers=headers, json={"agent_id": aid, "namespace": "research"}
                ).status_code
                == 403
            )
    finally:
        app.dependency_overrides.clear()
