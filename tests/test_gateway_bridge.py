import base64
import hashlib
import json
import os
import sys

from eth_account import Account
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from memoryseal import auth
from memoryseal.api import app
from memoryseal.bridge_runner import run_bridge
from memoryseal.client import MemorySealClient
from memoryseal.config import settings
from memoryseal.db import Base, get_session


def test_bridge_gateway_is_opt_in_and_never_promotes_unverified_output(
    tmp_path, monkeypatch, gateway_transport
):
    engine = create_engine(f"sqlite:///{tmp_path / 'gateway.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(auth, "SessionLocal", sessions)
    monkeypatch.setattr(settings, "encryption_key", base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setattr(settings, "zero_g_api_key", SecretStr("key"))
    monkeypatch.setattr(settings, "zero_g_model", "model")
    monkeypatch.setattr(settings, "zero_g_experimental_bridge", True)
    monkeypatch.setattr("memoryseal.bridge_transport.importlib.util.find_spec", lambda _: object())
    monkeypatch.setattr(settings, "zero_g_provider_address", "0x" + "1" * 40)
    monkeypatch.setattr(settings, "zero_g_tee_signer", "0x" + "2" * 40)
    monkeypatch.setattr(settings, "zero_g_signature_base_url", "https://provider.example")
    monkeypatch.setattr(settings, "zero_g_registry_rpc_url", None)
    monkeypatch.setattr(settings, "require_connection_attestation", False)
    binary = tmp_path / "bridge"
    binary.write_text("placeholder")
    binary.chmod(0o700)
    monkeypatch.setattr(settings, "zero_g_bridge_executable", str(binary))
    monkeypatch.setattr(settings, "zero_g_bridge_sha256", "a" * 64)
    calls = []
    analysis = {
        "category": "observation",
        "risk": "low",
        "suspicious_instruction": False,
        "conflicts_with": [],
        "recommendation": "accept",
    }

    def fake_bridge(binary, digest, request, *, timeout):
        calls.append(request)
        return {
            "body": {
                "x_0g_trace": {
                    "request_id": "r",
                    "provider": settings.zero_g_provider_address,
                    "tee_verified": True,
                },
                "choices": [{"message": {"content": json.dumps(analysis)}}],
            },
            "response_key": "key",
            "provider": settings.zero_g_provider_address,
        }

    monkeypatch.setattr("memoryseal.bridge_transport.run_bridge", fake_bridge)
    monkeypatch.setattr(
        "memoryseal.memory_service.verify_pinned_response",
        lambda **_: (_ for _ in ()).throw(AssertionError("legacy verifier invoked")),
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
                agent_id = owner.register_agent(agent.address)["id"]
                owner.grant(agent_id, "write", "research")
                assert owner.integration_readiness()["zero_g_router_configured"] is True
                written = agent.write_memory(
                    agent_id, "research", "private example", source_type="agent"
                )
                assert written["status"] == "quarantined"
                record = owner.list_memories(memory_id=written["id"])["memories"][0]
                assert record["inference_status"] == "unverified"
                assert (
                    record["analysis"]["evidence"]["inference_transport"] == "experimental_bridge"
                )
                assert (
                    record["analysis"]["evidence"]["bridge_reported_provider"]
                    == settings.zero_g_provider_address
                )
                assert calls[0]["provider"] == settings.zero_g_provider_address
                assert len(calls) == 1
                verifier = tmp_path / "verifier"
                verifier.write_text("placeholder")
                verifier.chmod(0o700)
                monkeypatch.setattr(settings, "zero_g_provider_verifier", str(verifier))
                assert owner.integration_readiness()["zero_g_router_configured"] is False
                monkeypatch.setattr(settings, "zero_g_registry_rpc_url", "https://rpc.example")
                assert owner.integration_readiness()["zero_g_router_configured"] is False
                monkeypatch.setattr(settings, "zero_g_provider_verifier_sha256", "a" * 64)
                monkeypatch.setattr(
                    "memoryseal.memory_service.registry_pins_match", lambda **_: True
                )
                monkeypatch.setattr(
                    "memoryseal.memory_service.verify_provider_quote", lambda *_, **__: None
                )
                assert owner.integration_readiness()["zero_g_router_configured"] is True
                rejected = agent.write_memory(
                    agent_id, "research", "quote failure", source_type="agent"
                )
                assert rejected["status"] == "quarantined"
                assert (
                    owner.list_memories(memory_id=rejected["id"])["memories"][0]["inference_status"]
                    == "failed"
                )
                assert len(calls) == 1
                monkeypatch.setattr(
                    "memoryseal.memory_service.verify_provider_quote",
                    lambda *_, **__: {
                        "provider": settings.zero_g_provider_address.lower(),
                        "signer": settings.zero_g_tee_signer.lower(),
                        "encryption_key": "11" * 32,
                    },
                )
                missing_receipt = agent.write_memory(
                    agent_id, "research", "missing receipt", source_type="agent"
                )
                assert missing_receipt["status"] == "quarantined"
                assert (
                    owner.list_memories(memory_id=missing_receipt["id"])["memories"][0][
                        "inference_status"
                    ]
                    == "failed"
                )
                assert calls[-1]["recipient_key"] == "11" * 32
                assert len(calls) == 2
                for verifier_function in (
                    "verify_bridge_receipt",
                    "verify_bridge_binding",
                    "verify_bridge_challenge",
                    "verify_bridge_request",
                ):
                    monkeypatch.setattr(
                        f"memoryseal.bridge_transport.{verifier_function}", lambda *_, **__: True
                    )

                receipt_key = [bytes.fromhex("11" * 32)]

                def bridge_with_receipt(binary, digest, request, *, timeout):
                    response = fake_bridge(binary, digest, request, timeout=timeout)
                    response["receipt"] = {
                        "artifacts": {},
                        "request_seed": "synthetic-seed",
                        "request_plaintext": "synthetic-plaintext",
                        "request_recipient_key": base64.b64encode(receipt_key[0]).decode(),
                    }
                    return response

                monkeypatch.setattr("memoryseal.bridge_transport.run_bridge", bridge_with_receipt)
                matched = agent.write_memory(
                    agent_id, "research", "matching key", source_type="agent"
                )
                record = owner.list_memories(memory_id=matched["id"])["memories"][0]
                assert record["status"] == "quarantined"
                assert record["inference_status"] == "unverified"
                assert record["analysis"]["evidence"]["bridge_quote_recipient_key_matched"] is True
                assert "synthetic-seed" not in json.dumps(record)
                assert "synthetic-plaintext" not in json.dumps(record)
                assert "11" * 32 not in json.dumps(record)
                receipt_key[0] = bytes.fromhex("22" * 32)
                mismatch = agent.write_memory(
                    agent_id, "research", "wrong receipt key", source_type="agent"
                )
                record = owner.list_memories(memory_id=mismatch["id"])["memories"][0]
                assert record["status"] == "quarantined"
                assert record["inference_status"] == "failed"
                monkeypatch.setattr(
                    "memoryseal.memory_service.registry_pins_match", lambda **_: False
                )
                monkeypatch.setattr(
                    "memoryseal.memory_service.verify_provider_quote",
                    lambda *_, **__: (_ for _ in ()).throw(AssertionError("verifier invoked")),
                )
                previous_calls = len(calls)
                rejected = agent.write_memory(
                    agent_id, "research", "registry mismatch", source_type="agent"
                )
                assert rejected["status"] == "quarantined"
                assert len(calls) == previous_calls
                monkeypatch.setattr("memoryseal.bridge_transport.run_bridge", fake_bridge)
                calls.clear()
                calls.append({"provider": settings.zero_g_provider_address})
                monkeypatch.setattr(settings, "zero_g_provider_verifier", None)
                monkeypatch.setattr(settings, "zero_g_registry_rpc_url", None)
                monkeypatch.setattr(settings, "zero_g_bridge_sha256", None)
                assert owner.integration_readiness()["zero_g_router_configured"] is False
                failed = agent.write_memory(
                    agent_id, "research", "second example", source_type="agent"
                )
                assert failed["status"] == "quarantined"
                assert (
                    owner.list_memories(memory_id=failed["id"])["memories"][0]["inference_status"]
                    == "failed"
                )
                assert len(calls) == 1
                monkeypatch.setattr(settings, "zero_g_bridge_sha256", "a" * 64)
                monkeypatch.setattr(settings, "require_connection_attestation", True)
                assert owner.integration_readiness()["zero_g_router_configured"] is False
                failed = agent.write_memory(
                    agent_id, "research", "third example", source_type="agent"
                )
                assert failed["status"] == "quarantined"
                assert len(calls) == 1
                monkeypatch.setattr(settings, "require_connection_attestation", False)
                monkeypatch.setattr(settings, "zero_g_api_key", None)
                monkeypatch.setattr(settings, "zero_g_model", None)
                missing = agent.write_memory(
                    agent_id, "research", "missing credentials", source_type="agent"
                )
                assert missing["status"] == "quarantined"
                assert (
                    owner.list_memories(memory_id=missing["id"])["memories"][0]["inference_status"]
                    == "failed"
                )
                assert len(calls) == 1
                monkeypatch.setattr(settings, "zero_g_api_key", SecretStr("key"))
                monkeypatch.setattr(settings, "zero_g_model", "model")
                monkeypatch.setattr("memoryseal.bridge_transport.run_bridge", run_bridge)
                marker = tmp_path / "invoked"
                binary.write_text(
                    f"#!{sys.executable}\n"
                    "import json, sys\n"
                    "request = json.load(sys.stdin)\n"
                    "assert request['api_key'] == 'key'\n"
                    "assert request['provider'] == '0x' + '1' * 40\n"
                    f"open({str(marker)!r}, 'w').close()\n"
                    f"analysis = {analysis!r}\n"
                    "body = {'choices': [{'message': {'content': json.dumps(analysis)}}]}\n"
                    "print(json.dumps({'status': 200, 'response_key': 'key', 'provider': request['provider'], 'body': body}))\n"
                )
                monkeypatch.setattr(
                    settings,
                    "zero_g_bridge_sha256",
                    hashlib.sha256(binary.read_bytes()).hexdigest(),
                )
                actual = agent.write_memory(
                    agent_id, "research", "real subprocess", source_type="agent"
                )
                assert marker.exists()
                assert actual["status"] == "quarantined"
                assert (
                    owner.list_memories(memory_id=actual["id"])["memories"][0]["inference_status"]
                    == "unverified"
                )
                marker.unlink()
                monkeypatch.setattr(settings, "zero_g_bridge_sha256", "0" * 64)
                mismatch = agent.write_memory(
                    agent_id, "research", "digest mismatch", source_type="agent"
                )
                assert mismatch["status"] == "quarantined"
                assert (
                    owner.list_memories(memory_id=mismatch["id"])["memories"][0]["inference_status"]
                    == "failed"
                )
                assert not marker.exists()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
