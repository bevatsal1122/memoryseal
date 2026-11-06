"""Verify repeatable bootstrap against the real signed gateway."""

import base64
import os
from uuid import uuid4

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
from memoryseal.demo.bootstrap import bootstrap


def test_expired_existing_grant_stops_bootstrap_before_any_mutation():
    accounts = [Account.create() for _ in range(4)]
    roles = ("browser", "research", "finance")
    addresses = {role: account.address for role, account in zip(roles, accounts[1:], strict=True)}
    names = {role: f"{role}.example.eth" for role in roles}

    class Owner:
        address = accounts[0].address

        def list_agents(self):
            return {
                "agents": [
                    {
                        "id": "finance-id",
                        "signing_address": addresses["finance"],
                        "ens_name": names["finance"],
                        "revoked": False,
                    }
                ]
            }

        def list_capabilities(self):
            return {
                "capabilities": [
                    {
                        "agent_id": "finance-id",
                        "operation": "read",
                        "resource": "research",
                        "revoked": False,
                        "expires_at": "2000-01-01T00:00:00+00:00",
                    }
                ]
            }

        def register_agent(self, *_args):
            pytest.fail("bootstrap must not register an agent")

        def grant(self, *_args):
            pytest.fail("bootstrap must not create grants")

    with pytest.raises(ValueError, match="finance read grant.*expired"):
        bootstrap(
            Owner(),
            addresses,
            names,
            {"research": str(uuid4()), "claim": str(uuid4())},
            observe=lambda name, _address: {"name": name, "matches": True, "chainId": 11155111},
        )


def test_bootstrap_is_narrow_repeatable_and_checks_all_names_first(
    tmp_path, monkeypatch, gateway_transport
):
    engine = create_engine(f"sqlite:///{tmp_path / 'bootstrap.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(auth, "SessionLocal", sessions)
    monkeypatch.setattr(settings, "encryption_key", base64.b64encode(os.urandom(32)).decode())

    def db():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = db
    try:
        with TestClient(app) as server:
            accounts = [Account.create() for _ in range(4)]
            owner = MemorySealClient(
                "http://testserver",
                accounts[0].key,
                audience=settings.request_audience,
                transport=gateway_transport(server),
            )
            names = {name: f"{name}.example.eth" for name in ("browser", "research", "finance")}
            addresses = {
                name: account.address for name, account in zip(names, accounts[1:], strict=True)
            }
            requests = {"research": str(uuid4()), "claim": str(uuid4())}

            def bad(name, address):
                return {
                    "name": name,
                    "matches": not name.startswith("research"),
                    "chainId": 11155111,
                }

            with pytest.raises(ValueError, match="Claim amount"):
                bootstrap(
                    owner,
                    addresses,
                    names,
                    requests,
                    local_transfer={"asset": "T", "max_amount": "100", "claim_amount": "100"},
                    observe=bad,
                )
            assert owner.list_agents()["agents"] == []
            with pytest.raises(ValueError, match="research ENS"):
                bootstrap(owner, addresses, names, requests, observe=bad)
            assert owner.list_agents()["agents"] == []

            def good(name, address):
                return {"name": name, "matches": True, "chainId": 11155111}

            transfer = {"asset": "0x" + "1" * 40, "max_amount": "100", "claim_amount": "5000"}
            first = bootstrap(
                owner, addresses, names, requests, local_transfer=transfer, observe=good
            )
            assert first["local_transfer"] == transfer
            version = owner.list_capabilities()["policy_version"]
            again = bootstrap(owner, addresses, names, requests, observe=good)
            assert first["agents"] == again["agents"]
            assert first["request_ids"] == requests
            assert owner.list_capabilities()["policy_version"] == version
            grants = owner.list_capabilities()["capabilities"]
            assert {(cap["agent_id"], cap["operation"], cap["resource"]) for cap in grants} == {
                (first["agents"]["browser"], "write", "browser-observations"),
                (first["agents"]["research"], "write", "research"),
                (first["agents"]["research"], "read", "research"),
                (first["agents"]["finance"], "read", "browser-observations"),
                (first["agents"]["finance"], "read", "research"),
            }
            owner.close()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
