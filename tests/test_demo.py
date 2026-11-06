import base64
import importlib.util
import json
import os

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
from memoryseal.demo.run import run_demo
from memoryseal.inference import InferenceResult, ThreatAnalysis


def test_reference_agents_use_gateway_to_run_demo(tmp_path, monkeypatch, gateway_transport):
    engine = create_engine(f"sqlite:///{tmp_path / 'demo.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(auth, "SessionLocal", sessions)
    monkeypatch.setattr(settings, "encryption_key", base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setattr(settings, "zero_g_api_key", None)
    monkeypatch.setattr(settings, "zero_g_model", None)

    def db():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = db
    try:
        with TestClient(app) as server:
            demo_owner = Account.create()
            result = run_demo(
                lambda account: MemorySealClient(
                    "http://testserver",
                    account.key,
                    audience=settings.request_audience,
                    transport=gateway_transport(server),
                ),
                owner_account=demo_owner,
            )
        assert result["owner"] == demo_owner.address
        assert len(result["agents"]) == 3
        assert result["research_memories"] == 0
        assert result["finance_research_memories"] == 0
        assert result["finance_read_research_write"] is False
        assert result["research_write_status"] == "quarantined"
        assert result["claim"]["status"] == "quarantined"
        assert result["finance_read_claim"] is False
        assert result["origin_events"]["research"]["changed"] is True
        assert result["origin_events"]["browser"]["changed"] is True
        assert "commitment_salt" not in json.dumps(result)
        assert result["denied"]["executed"] is False
        assert result["denied"]["allowed"] is False
        assert result["allowed"]["allowed"] is True
        assert result["allowed"]["executed"] is False
        if importlib.util.find_spec("eth_tester") is not None:
            from memoryseal.demo.onchain import run_onchain_demo

            with TestClient(app) as server:
                chain_result = run_onchain_demo(
                    lambda account: MemorySealClient(
                        "http://testserver",
                        account.key,
                        audience=settings.request_audience,
                        transport=gateway_transport(server),
                    )
                )
            assert chain_result["origin_events"]["research"]["changed"] is True
            assert chain_result["finance_research_memories"] == 0
            assert chain_result["finance_read_research_write"] is False
            assert chain_result["finance_read_claim"] is False
            assert chain_result["origin_events"]["browser"]["changed"] is True
            assert "commitment_salt" not in json.dumps(chain_result)
            assert chain_result["received_base_units"] == str(2000 * 10**18)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_cross_agent_memory_and_protected_transfer_with_mocked_inference(
    tmp_path, monkeypatch, gateway_transport
):
    pytest.importorskip("eth_tester")
    from memoryseal.demo.onchain import run_onchain_demo

    engine = create_engine(f"sqlite:///{tmp_path / 'shared-demo.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(auth, "SessionLocal", sessions)
    monkeypatch.setattr(settings, "encryption_key", base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setattr(settings, "zero_g_api_key", SecretStr("test-only"))
    monkeypatch.setattr(settings, "zero_g_model", "mock-model")
    monkeypatch.setattr(settings, "require_connection_attestation", False)
    monkeypatch.setattr(settings, "allow_unbound_inference", True)
    monkeypatch.setattr(settings, "zero_g_experimental_bridge", False)
    monkeypatch.setattr(settings, "zero_g_provider_address", None)
    monkeypatch.setattr(settings, "zero_g_tee_signer", None)
    monkeypatch.setattr(settings, "zero_g_signature_base_url", None)
    monkeypatch.setattr(settings, "zero_g_registry_rpc_url", None)

    class MockClassifier:
        def __init__(self, *args, **kwargs):
            pass

        def analyze(self, **kwargs):
            return InferenceResult(
                analysis=ThreatAnalysis(
                    category="observation",
                    risk="low",
                    suspicious_instruction=False,
                    conflicts_with=[],
                    recommendation="accept",
                ),
                request_id="mock-request",
                response_key="mock-key",
                provider="0x" + "1" * 40,
                router_verified=True,
                network="testnet",
            )

        def close(self):
            pass

    monkeypatch.setattr("memoryseal.memory_service.ZeroGClassifier", MockClassifier)

    def db():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = db
    try:
        with TestClient(app) as server:
            result = run_onchain_demo(
                lambda account: MemorySealClient(
                    "http://testserver",
                    account.key,
                    audience=settings.request_audience,
                    transport=gateway_transport(server),
                )
            )
        assert result["research_write_status"] == "accepted"
        assert result["research_memories"] == result["finance_research_memories"] == 1
        assert result["finance_read_research_write"] is True
        assert result["claim"]["status"] == "quarantined"
        assert result["finance_read_claim"] is False
        assert result["policy_version"] == 2
        assert result["received_base_units"] == str(2000 * 10**18)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
