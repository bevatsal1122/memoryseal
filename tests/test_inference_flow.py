"""Exercise gateway classification and signature verification without live credentials."""

import base64
import json
import os
from uuid import uuid4

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from memoryseal import auth
from memoryseal.api import app
from memoryseal.client import MemorySealClient
from memoryseal.config import settings
from memoryseal.db import Base, get_session
from memoryseal.inference import ZeroGClassifier
from memoryseal.models import Memory
from memoryseal.zero_g_verification import verify_pinned_response


def test_gateway_checks_real_signature_and_quarantines_changed_response(
    tmp_path, monkeypatch, gateway_transport
):
    engine = create_engine(f"sqlite:///{tmp_path / 'inference.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(auth, "SessionLocal", sessions)
    monkeypatch.setattr(settings, "encryption_key", base64.b64encode(os.urandom(32)).decode())
    signer, provider = Account.create(), Account.create().address
    monkeypatch.setattr(settings, "zero_g_api_key", SecretStr("router-secret"))
    monkeypatch.setattr(settings, "zero_g_model", "test-model")
    monkeypatch.setattr(settings, "require_connection_attestation", False)  # mocked router
    monkeypatch.setattr(settings, "allow_unbound_inference", True)  # legacy compatibility
    monkeypatch.setattr(settings, "zero_g_provider_address", provider)
    monkeypatch.setattr(settings, "zero_g_tee_signer", signer.address)
    monkeypatch.setattr(settings, "zero_g_signature_base_url", "https://provider.example")
    monkeypatch.setattr(settings, "zero_g_registry_rpc_url", "https://rpc.example")
    monkeypatch.setattr("memoryseal.memory_service.registry_pins_match", lambda **kwargs: True)
    analysis = json.dumps(
        {
            "category": "observation",
            "risk": "low",
            "suspicious_instruction": False,
            "conflicts_with": [],
            "recommendation": "accept",
        }
    )
    signature = Account.sign_message(encode_defunct(text=analysis), signer.key).signature.hex()
    tampered = False
    oversized = False
    missing_request = False

    def router(request):
        if oversized:
            return httpx.Response(200, content=b" " * 1_048_577)
        assert request.headers["x-0g-provider-address"].lower() == provider.lower()
        assert request.headers["x-0g-provider-trust-mode"] == "private"
        assert request.headers["x-0g-provider-allow-fallbacks"] == "false"
        assert json.loads(request.content)["verify_tee"] is True
        return httpx.Response(
            200,
            headers={"ZG-Res-Key": "chat-1"},
            json={
                "id": "chat-1",
                "x_0g_trace": {
                    "request_id": None if missing_request else "request-1",
                    "provider": provider,
                    "tee_verified": True,
                },
                "choices": [{"message": {"content": analysis}}],
            },
        )

    def receipt(request):
        assert request.url.host == "provider.example"
        assert "authorization" not in request.headers
        return httpx.Response(
            200, json={"text": analysis + (" " if tampered else ""), "signature": signature}
        )

    monkeypatch.setattr(
        "memoryseal.memory_service.ZeroGClassifier",
        lambda *args, **kwargs: ZeroGClassifier(
            *args, **kwargs, transport=httpx.MockTransport(router)
        ),
    )
    monkeypatch.setattr(
        "memoryseal.memory_service.verify_pinned_response",
        lambda **kwargs: verify_pinned_response(**kwargs, transport=httpx.MockTransport(receipt)),
    )

    def db():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = db
    try:
        with TestClient(app) as server:
            owner_account, agent_account = Account.create(), Account.create()
            with (
                MemorySealClient(
                    "http://testserver",
                    owner_account.key,
                    audience=settings.request_audience,
                    transport=gateway_transport(server),
                ) as owner,
                MemorySealClient(
                    "http://testserver",
                    agent_account.key,
                    audience=settings.request_audience,
                    transport=gateway_transport(server),
                ) as agent,
            ):
                agent_id = owner.register_agent(agent_account.address)["id"]
                write_capability = owner.grant(agent_id, "write", "observations")
                owner.grant(agent_id, "read", "observations")
                request_id = str(uuid4())
                accepted = agent.write_memory(
                    agent_id,
                    "observations",
                    "A normal observation",
                    source_type="agent",
                    request_id=request_id,
                )
                assert accepted["status"] == "accepted"
                assert accepted["lineage_eligible"] is True
                meta = owner.list_memories(memory_id=accepted["id"])["memories"][0]
                assert meta["inference_status"] == "pinned_signature_verified"
                assert meta["analysis"]["evidence"]["provider_record_matched"] is True
                assert meta["analysis"]["evidence"]["pinned_signature_verified"] is True
                # A legacy accepted record can predate the no-inference read gate.
                with sessions() as db_session:
                    db_session.get(Memory, accepted["id"]).inference_status = "not_configured"
                    db_session.commit()
                assert (
                    owner.list_memories(memory_id=accepted["id"])["memories"][0]["lineage_eligible"]
                    is False
                )
                retried = agent.write_memory(
                    agent_id,
                    "observations",
                    "A normal observation",
                    source_type="agent",
                    request_id=request_id,
                )
                assert retried["id"] == accepted["id"]
                assert retried["status"] == "accepted"
                assert retried["lineage_eligible"] is False
                derived = agent.write_memory(
                    agent_id,
                    "observations",
                    "A new observation derived from the older record",
                    source_type="agent",
                    parent_id=accepted["id"],
                )
                assert derived["status"] == "quarantined"
                assert derived["lineage_eligible"] is False
                derived_metadata = owner.list_memories(memory_id=derived["id"])["memories"][0]
                assert derived_metadata["inference_status"] == "pinned_signature_verified"
                assert derived_metadata["lineage_eligible"] is False
                assert agent.read_memory(agent_id, "observations")["memories"] == []
                with sessions() as db_session:
                    db_session.get(
                        Memory, accepted["id"]
                    ).inference_status = "pinned_signature_verified"
                    db_session.commit()
                tampered = True
                quarantined = agent.write_memory(
                    agent_id, "observations", "Another observation", source_type="agent"
                )
                assert quarantined["status"] == "quarantined"
                meta = owner.list_memories(memory_id=quarantined["id"])["memories"][0]
                assert meta["inference_status"] == "verification_failed"
                assert meta["analysis"]["evidence"]["pinned_signature_verified"] is False
                oversized = True
                failed = agent.write_memory(
                    agent_id, "observations", "A third observation", source_type="agent"
                )
                assert failed["status"] == "quarantined"
                failed_meta = owner.list_memories(memory_id=failed["id"])["memories"][0]
                assert failed_meta["inference_status"] == "failed"
                assert failed_meta["trust_class"] == "untrusted"
                oversized = False
                tampered = False
                descendant = agent.write_memory(
                    agent_id,
                    "observations",
                    "An apparently benign revision",
                    source_type="agent",
                    parent_id=failed["id"],
                )
                assert descendant["status"] == "quarantined"
                # Simulate a legacy accepted child created before ancestry checks existed.
                with sessions() as db_session:
                    db_session.get(Memory, descendant["id"]).status = "accepted"
                    db_session.commit()
                legacy_metadata = owner.list_memories(memory_id=descendant["id"])["memories"][0]
                assert legacy_metadata["status"] == "accepted"
                assert legacy_metadata["lineage_eligible"] is False
                assert (
                    owner.list_memories(memory_id=accepted["id"])["memories"][0]["lineage_eligible"]
                    is True
                )
                legacy_child = agent.write_memory(
                    agent_id,
                    "observations",
                    "A revision of the legacy child",
                    source_type="agent",
                    parent_id=descendant["id"],
                )
                assert legacy_child["status"] == "quarantined"
                later = agent.write_memory(
                    agent_id, "observations", "A later observation", source_type="agent"
                )
                assert later["status"] == "accepted"
                first = agent.read_memory_page(agent_id, "observations", limit=1)
                assert [m["id"] for m in first["memories"]] == [accepted["id"]]
                second = agent.read_memory_page(
                    agent_id, "observations", offset=first["next_offset"], limit=1
                )
                assert second["memories"] == []
                assert second["next_offset"] is not None
                third = agent.read_memory_page(
                    agent_id, "observations", offset=second["next_offset"], limit=1
                )
                assert [m["id"] for m in third["memories"]] == [later["id"]]
                assert third["next_offset"] is None
                readable = agent.read_memory(agent_id, "observations")["memories"]
                assert {item["id"] for item in readable} == {accepted["id"], later["id"]}
                analysis = json.dumps(
                    {
                        "category": "observation",
                        "risk": "low",
                        "suspicious_instruction": False,
                        "conflicts_with": [
                            write_capability["id"],
                            "private conflict text must not be stored",
                        ],
                        "recommendation": "accept",
                    }
                )
                signature = Account.sign_message(
                    encode_defunct(text=analysis), signer.key
                ).signature.hex()
                conflict = agent.write_memory(
                    agent_id, "observations", "A conflicting observation", source_type="agent"
                )
                assert conflict["status"] == "quarantined"
                with sessions() as db_session:
                    stored = db_session.get(Memory, conflict["id"]).analysis_json
                    assert "private conflict text must not be stored" not in stored
                    assert json.loads(stored)["conflicts_with"] == [
                        write_capability["id"],
                        "unresolved",
                    ]
                # Records accepted by older versions must also fail closed on reads.
                with sessions() as db_session:
                    db_session.get(Memory, conflict["id"]).status = "accepted"
                    db_session.commit()
                assert conflict["id"] not in {
                    item["id"] for item in agent.read_memory(agent_id, "observations")["memories"]
                }
                assert owner.list_memories(memory_id=conflict["id"])["memories"][0][
                    "lineage_eligible"
                ] is False
                with sessions() as db_session:
                    db_session.get(Memory, conflict["id"]).analysis_json = "{"
                    db_session.commit()
                corrupt = owner.list_memories(memory_id=conflict["id"])["memories"][0]
                assert corrupt["analysis"] is None
                assert corrupt["analysis_state"] == "invalid"
                assert corrupt["lineage_eligible"] is False
                assert conflict["id"] not in {
                    item["id"] for item in agent.read_memory(agent_id, "observations")["memories"]
                }
                missing_request = True
                missing = agent.write_memory(
                    agent_id, "observations", "Another benign observation", source_type="agent"
                )
                assert missing["status"] == "quarantined"
                missing_meta = owner.list_memories(memory_id=missing["id"])["memories"][0]
                assert missing_meta["inference_reference"] is None
                assert missing_meta["inference_status"] == "verification_failed"
                assert missing_meta["analysis"]["evidence"]["pinned_signature_verified"] is True
                missing_request = False
                monkeypatch.setattr(settings, "allow_unbound_inference", False)
                unbound = agent.write_memory(
                    agent_id, "observations", "An unbound observation", source_type="agent"
                )
                assert unbound["status"] == "quarantined"
                assert owner.list_memories(memory_id=unbound["id"])["memories"][0][
                    "inference_status"
                ] == "pinned_signature_verified"
                assert agent.read_memory(agent_id, "observations")["memories"] == []
                assert owner.list_memories(memory_id=accepted["id"])["memories"][0][
                    "lineage_eligible"
                ] is False
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
