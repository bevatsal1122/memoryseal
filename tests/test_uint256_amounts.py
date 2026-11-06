"""Large token limits survive gateway storage and policy evaluation exactly."""

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


def test_large_transfer_limits_round_trip_and_compare(tmp_path, monkeypatch, gateway_transport):
    engine = create_engine(f"sqlite:///{tmp_path / 'amount.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(auth, "SessionLocal", sessions)

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
                limit = 100 * 10**18
                grant = owner.grant(agent_id, "transfer", "TEST", max_amount=limit)
                assert owner.list_capabilities()["capabilities"][0]["max_amount"] == str(limit)
                assert agent.simulate_transfer(agent_id, "TEST", limit, grant["policy_version"])[
                    "allowed"
                ]
                assert not agent.simulate_transfer(
                    agent_id, "TEST", limit + 1, grant["policy_version"]
                )["allowed"]
                grant = owner.grant(agent_id, "transfer", "TEST", max_amount=2**256 - 1)
                assert owner.list_capabilities()["capabilities"][-1]["max_amount"] == str(
                    2**256 - 1
                )
                assert agent.simulate_transfer(
                    agent_id, "TEST", 2**256 - 1, grant["policy_version"]
                )["allowed"]
                with pytest.raises(httpx.HTTPStatusError) as error:
                    owner.grant(agent_id, "transfer", "TEST", max_amount=2**256)
                assert error.value.response.status_code == 422
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
