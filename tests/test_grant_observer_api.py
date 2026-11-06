"""The grant observer must bind its signer to an owned agent."""

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


def test_grant_observer_authenticates_owner_and_binds_agent(
    tmp_path, monkeypatch, gateway_transport
):
    engine = create_engine(f"sqlite:///{tmp_path / 'grant.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(auth, "SessionLocal", sessions)
    monkeypatch.setattr(settings, "onchain_rpc_url", "https://rpc.example")
    monkeypatch.setattr(settings, "onchain_chain_id", 11155111)
    monkeypatch.setattr(settings, "onchain_registry", "0x" + "3" * 40)
    seen = []

    class Verifier:
        def __init__(self, rpc, owner, **kwargs):
            seen.append((owner, kwargs))

        def verify_transfer_grant(self, tx_hash, **kwargs):
            seen.append((tx_hash, kwargs))
            return {"status": "success", "grant_verified": True, "block_number": 5}

        def close(self):
            pass

    monkeypatch.setattr("memoryseal.api.OnchainReceiptVerifier", Verifier)

    def db():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = db
    try:
        with TestClient(app) as server:
            owner_account, outsider_account, agent_account = (Account.create() for _ in range(3))
            with (
                MemorySealClient(
                    "http://testserver",
                    owner_account.key,
                    audience=settings.request_audience,
                    transport=gateway_transport(server),
                ) as owner,
                MemorySealClient(
                    "http://testserver",
                    outsider_account.key,
                    audience=settings.request_audience,
                    transport=gateway_transport(server),
                ) as outsider,
            ):
                agent_id = owner.register_agent(agent_account.address)["id"]
                args = {
                    "agent_id": agent_id,
                    "transaction_hash": "0x" + "a" * 64,
                    "token": "0x" + "4" * 40,
                    "max_amount": 2000,
                    "expires_at": 0,
                    "policy_version": 2,
                }
                result = owner.observe_onchain_grant(**args)
                assert result["observation"]["grant_verified"] is True
                assert seen[0][0] == owner.address.lower()
                assert seen[1][1]["agent"] == agent_account.address.lower()
                with pytest.raises(httpx.HTTPStatusError) as error:
                    outsider.observe_onchain_grant(**args)
                assert error.value.response.status_code == 404
                assert len(seen) == 2
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
