"""Explicit signed owner review is distinct from attestation and action authority."""

import base64
import os
from contextlib import ExitStack

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


def test_scoped_acceptance_policy(tmp_path, monkeypatch, gateway_transport):
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
            owner, writer, reader, other = [
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
            aid = owner.register_agent(writer.address)["id"]
            bid = owner.register_agent(reader.address)["id"]
            owner.grant(aid, "write", "scope")
            owner.grant(bid, "read", "scope")

            def policy(mode="standard", actor=owner, namespace="scope", version=None):
                return actor.set_acceptance_rule(
                    aid,
                    namespace,
                    mode,
                    policy_version=version
                    if version is not None
                    else owner._request("GET", "/capabilities")["policy_version"],
                )

            def write(namespace="scope", source="agent"):
                return writer.write_memory(
                    aid, namespace, "The meeting is Tuesday", source_type=source
                )

            old = write()
            assert old["status"] == "quarantined"
            for actor in (writer, reader, other):
                with pytest.raises(httpx.HTTPStatusError) as denied:
                    policy(actor=actor)
                assert denied.value.response.status_code == 404
            with pytest.raises(httpx.HTTPStatusError) as stale:
                policy(version=999)
            assert stale.value.response.status_code == 409
            policy()
            fresh = write()
            assert fresh["status"] == "accepted"
            assert (
                owner.list_memories(memory_id=fresh["id"])["memories"][0]["inference_status"]
                == "unverified"
            )
            assert [m["id"] for m in reader.read_memory(bid, "scope")["memories"]] == [fresh["id"]]
            assert write(source="external")["status"] == "quarantined"
            for changes in (
                {"risk": "medium"},
                {"conflicts_with": ["conflict"]},
                {"category": "instruction"},
                {"recommendation": "reject"},
            ):
                analysis_overrides.update(changes)
                assert write()["status"] == "quarantined"
                analysis_overrides.clear()
            child = writer.write_memory(
                aid,
                "scope",
                "An ordinary child observation",
                source_type="agent",
                parent_id=old["id"],
            )
            assert child["status"] == "quarantined"
            assert owner.list_memories(memory_id=fresh["id"])["memories"][0]["auto_accepted"]
            with pytest.raises(httpx.HTTPStatusError) as invalid:
                policy(namespace="*")
            assert invalid.value.response.status_code == 422
            with pytest.raises(httpx.HTTPStatusError):
                write(namespace="other")
            owner.grant(aid, "write", "other")
            assert write(namespace="other")["status"] == "quarantined"
            policy("strict")
            assert reader.read_memory(bid, "scope")["memories"] == []
            assert write()["status"] == "quarantined"
            policy()
            owner.revoke_agent(aid)
            assert reader.read_memory(bid, "scope")["memories"] == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "field,value",
    [
        ("category", "instruction"),
        ("category", "authorization_claim"),
        ("category", "other"),
        ("risk", "medium"),
        ("risk", "high"),
        ("suspicious_instruction", True),
        ("conflicts_with", ["conflict"]),
        ("recommendation", "quarantine"),
        ("recommendation", "reject"),
    ],
)
def test_standard_rejects_risky_analysis(field, value):
    from memoryseal.memory_service import standard_eligible

    analysis = {
        "category": "observation",
        "risk": "low",
        "suspicious_instruction": False,
        "conflicts_with": [],
        "recommendation": "accept",
    }
    assert standard_eligible(analysis, "unverified")
    assert not standard_eligible(analysis | {field: value}, "unverified")
    for status in ("failed", "verification_failed", "stale", "not_configured"):
        assert not standard_eligible(analysis, status)
