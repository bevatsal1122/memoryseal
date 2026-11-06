"""A required but unavailable attestation must prevent private inference."""

import base64
import json
import os

import httpx
from eth_account import Account
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from memoryseal import auth
from memoryseal.api import app
from memoryseal.client import MemorySealClient
from memoryseal.config import Settings, settings
from memoryseal.db import Base, get_session


def test_connection_attestation_is_required_by_default(monkeypatch):
    monkeypatch.delenv("MEMORYSEAL_REQUIRE_CONNECTION_ATTESTATION", raising=False)
    monkeypatch.delenv("MEMORYSEAL_ALLOW_UNBOUND_INFERENCE", raising=False)
    config = Settings(_env_file=None)
    assert config.require_connection_attestation is True
    assert config.allow_unbound_inference is False


def test_required_attestation_blocks_outbound_and_quarantines(
    tmp_path, monkeypatch, gateway_transport
):
    engine = create_engine(f"sqlite:///{tmp_path / 'gate.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(auth, "SessionLocal", sessions)
    monkeypatch.setattr(settings, "encryption_key", base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setattr(settings, "zero_g_api_key", SecretStr("test"))
    monkeypatch.setattr(settings, "zero_g_model", "test")
    # This fixture exercises the explicit private-mode verification path.
    monkeypatch.setattr(settings, "zero_g_trust_mode", "private")
    monkeypatch.setattr(settings, "require_connection_attestation", True)
    monkeypatch.setattr(settings, "allow_unbound_inference", False)
    monkeypatch.setattr(settings, "zero_g_registry_rpc_url", "https://rpc.example")
    monkeypatch.setattr(
        "memoryseal.memory_service.registry_pins_match",
        lambda **_: (_ for _ in ()).throw(AssertionError("unexpected RPC")),
    )
    monkeypatch.setattr(
        "memoryseal.memory_service.ZeroGClassifier",
        lambda *_, **__: (_ for _ in ()).throw(AssertionError("unexpected inference")),
    )

    def db():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = db
    try:
        with TestClient(app) as server:
            accounts = [Account.create(), Account.create()]
            with (
                MemorySealClient(
                    "http://testserver",
                    accounts[0].key,
                    audience=settings.request_audience,
                    transport=gateway_transport(server),
                ) as owner,
                MemorySealClient(
                    "http://testserver",
                    accounts[1].key,
                    audience=settings.request_audience,
                    transport=gateway_transport(server),
                ) as agent,
            ):
                agent_id = owner.register_agent(agent.address)["id"]
                owner.grant(agent_id, "write", "research")
                readiness = owner.integration_readiness()
                assert readiness["connection_attestation_required"] is True
                assert readiness["request_binding_verification_supported"] is False
                assert readiness["unbound_inference_allowed"] is False
                assert readiness["connection_attestation_available"] is False
                assert readiness["zero_g_router_configured"] is False
                write = agent.write_memory(
                    agent_id, "research", "private content", source_type="agent"
                )
                assert write["status"] == "quarantined"
                item = owner.list_memories(memory_id=write["id"])["memories"][0]
                assert item["inference_status"] == "failed"

                verifier = tmp_path / "trusted-verifier"
                verifier.write_text("test placeholder")
                verifier.chmod(0o700)
                monkeypatch.setattr(settings, "connection_attestation_verifier", str(verifier))
                assert owner.integration_readiness()["connection_attestation_available"] is False
                monkeypatch.setattr(settings, "connection_attestation_verifier_sha256", "a" * 64)
                monkeypatch.setattr(settings, "zero_g_registry_rpc_url", None)
                monkeypatch.setattr(settings, "zero_g_provider_address", None)
                monkeypatch.setattr(settings, "zero_g_tee_signer", None)
                monkeypatch.setattr(settings, "zero_g_signature_base_url", None)
                requests = []

                def handler(request):
                    requests.append(request)
                    return httpx.Response(
                        200,
                        headers={"ZG-Res-Key": "response"},
                        json={
                            "id": "response",
                            "x_0g_trace": {
                                "request_id": "request",
                                "provider": "0x" + "1" * 40,
                                "tee_verified": True,
                            },
                            "choices": [
                                {
                                    "message": {
                                        "content": json.dumps(
                                            {
                                                "category": "observation",
                                                "risk": "low",
                                                "suspicious_instruction": False,
                                                "conflicts_with": [],
                                                "recommendation": "accept",
                                            }
                                        )
                                    }
                                }
                            ],
                        },
                    )

                def fake_attested_transport(binary, network, *, expected_sha256):
                    assert expected_sha256 == "a" * 64
                    transport = httpx.MockTransport(handler)
                    transport.verified_fingerprint = "a" * 64
                    return transport

                monkeypatch.setattr(
                    "memoryseal.memory_service.AttestedGatewayTransport", fake_attested_transport
                )
                from memoryseal.inference import ZeroGClassifier

                monkeypatch.setattr("memoryseal.memory_service.ZeroGClassifier", ZeroGClassifier)
                configured = owner.integration_readiness()
                assert configured["connection_attestation_available"] is True
                assert configured["zero_g_router_configured"] is True
                successful = agent.write_memory(
                    agent_id, "research", "other content", source_type="agent"
                )
                assert successful["status"] == "quarantined"
                observed = owner.list_memories(memory_id=successful["id"])["memories"][0]
                assert (
                    observed["creation_reason"]
                    == "inference response is not verified against the request"
                )
                assert observed["analysis"]["evidence"]["gateway_connection_attested"] is True
                assert observed["analysis"]["evidence"]["gateway_certificate_sha256"] == "a" * 64
                assert len(requests) == 1
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
