"""Chain routing is explicit, isolated per request, and hides RPC credentials."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from memoryseal.api import app
from memoryseal.auth import authenticate
from memoryseal.config import Settings, settings
from memoryseal.networks import ChainConfig


def test_chain_configuration_and_request_isolation(monkeypatch):
    a = ChainConfig(
        chain_id=31337,
        name="Local A",
        rpc_url="https://rpc.example/a?key=secret",
        registry="0x" + "1" * 40,
        executor="0x" + "2" * 40,
    )
    b = ChainConfig(
        chain_id=31338,
        name="Local B",
        rpc_url="https://rpc.example/b",
        registry="0x" + "3" * 40,
        executor="0x" + "4" * 40,
    )
    monkeypatch.setattr(settings, "chains", [a, b])
    monkeypatch.setattr(settings, "onchain_chain_id", 11155111)
    seen = []

    def observe(**kwargs):
        seen.append(kwargs)
        return kwargs | {"rpc_url": "redacted"}

    monkeypatch.setattr("memoryseal.api.observe_deployment", observe)
    app.dependency_overrides[authenticate] = lambda: "0x" + "5" * 40
    try:
        with TestClient(app) as client:
            public = client.get("/chains")
            assert "rpc.example" not in public.text and "secret" not in public.text
            assert client.get("/onchain/observe-deployment?chain_id=31337").status_code == 200
            assert client.get("/onchain/observe-deployment?chain_id=31338").status_code == 200
            assert client.get("/onchain/observe-deployment?chain_id=999").status_code == 404
            assert [c["chain_id"] for c in seen] == [31337, 31338]
            assert seen[0]["rpc_url"] == a.rpc_url and seen[1]["registry"] == b.registry
            assert settings.onchain_chain_id == 11155111
    finally:
        app.dependency_overrides.clear()
    with pytest.raises(ValidationError):
        Settings(chains=[a, a], _env_file=None)
    with pytest.raises(ValidationError):
        ChainConfig(**(a.model_dump() | {"rpc_url": "http://remote.example"}))


def test_vault_respects_agent_chain_binding_and_fails_closed(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from memoryseal.chain_memory import ChainPolicyError
    from memoryseal.db import Base
    from memoryseal.models import Agent, Capability, PolicyState, VaultNamespace
    from memoryseal.vault import allowed_agents

    engine = create_engine(f"sqlite:///{tmp_path / 'policy.db'}")
    Base.metadata.create_all(engine)
    chain = ChainConfig(
        chain_id=31338,
        name="B",
        rpc_url="https://rpc.example/b",
        registry="0x" + "3" * 40,
        executor="0x" + "4" * 40,
    )
    monkeypatch.setattr(settings, "chains", [chain])
    monkeypatch.setattr(settings, "require_onchain_memory", True)
    owner, signer = "0x" + "1" * 40, "0x" + "2" * 40
    with Session(engine) as session:
        session.add(PolicyState(owner_address=owner, version=1))
        session.add(
            Agent(
                id="agent",
                owner_address=owner,
                signing_address=signer,
                policy_chain_id=31338,
                revoked=False,
            )
        )
        session.flush()
        session.add(
            Capability(
                id="cap",
                agent_id="agent",
                operation="read",
                resource="secret",
                revoked=False,
                policy_version=1,
            )
        )
        scope = VaultNamespace(
            id="scope", owner_address=owner, namespace="secret", active_version=1
        )
        session.add(scope)
        session.commit()
        seen = []

        def chain_check(**args):
            seen.append(args)
            return False

        monkeypatch.setattr("memoryseal.vault.chain_allowed", chain_check)
        assert allowed_agents(session, scope, signer, "read") == []
        assert seen[0]["chain_id"] == 31338 and seen[0]["registry"] == chain.registry
        monkeypatch.setattr("memoryseal.vault.chain_allowed", lambda **kw: True)
        assert len(allowed_agents(session, scope, signer, "read")) == 1

        def offline(**kw):
            raise ChainPolicyError("offline")

        monkeypatch.setattr("memoryseal.vault.chain_allowed", offline)
        assert allowed_agents(session, scope, signer, "read") == []
    engine.dispose()
