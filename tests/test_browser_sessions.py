import time

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from memoryseal import browser_sessions
from memoryseal.api import app
from memoryseal.db import Base, get_session
from memoryseal.models import BrowserCredential


@pytest.fixture
def setup(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'sessions.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(browser_sessions, "SessionLocal", factory)

    def db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = db
    with TestClient(app) as client:
        yield client, factory
    app.dependency_overrides.pop(get_session)


def sign_in(client, account=None):
    account = account or Account.create()
    headers = {"Origin": "http://localhost:3000"}
    challenge = client.post(
        "/auth/challenge", json={"address": account.address}, headers=headers
    ).json()
    signature = Account.sign_message(
        encode_defunct(text=challenge["message"]), account.key
    ).signature.hex()
    payload = {"challenge": challenge["challenge"], "signature": signature}
    response = client.post("/auth/session", json=payload, headers=headers)
    assert response.status_code == 200
    return account, {**headers, "Authorization": "Bearer " + response.json()["token"]}, payload


def test_read_session_replay_scope_expiry_logout(setup):
    client, factory = setup
    account, headers, payload = sign_in(client)
    for _ in range(4):
        assert client.get("/identity", headers=headers).json() == {
            "signer": account.address.lower()
        }
    assert client.get("/agents", headers=headers).json() == {"agents": []}
    assert client.post("/auth/session", json=payload, headers=headers).status_code == 401
    # A bearer token must never bypass the existing write signature/provenance requirement.
    assert (
        client.post(
            "/agents/register", headers=headers, json={"signing_address": Account.create().address}
        ).status_code
        == 403
    )
    assert (
        client.get("/identity", headers={**headers, "Origin": "https://evil.example"}).status_code
        == 403
    )
    assert (
        client.get("/identity", headers={"Authorization": headers["Authorization"]}).status_code
        == 403
    )
    assert client.post("/auth/logout", headers=headers).status_code == 200
    assert client.get("/identity", headers=headers).status_code == 401
    _, headers, _ = sign_in(client)
    with factory() as db:
        row = db.get(BrowserCredential, browser_sessions.digest(headers["Authorization"][7:]))
        row.expires_at = int(time.time()) - 1
        db.commit()
    assert client.get("/identity", headers=headers).status_code == 401


def test_wrong_signer_expired_challenge_and_bad_origin(setup):
    client, factory = setup
    headers = {"Origin": "http://localhost:3000"}
    address = Account.create().address
    assert client.post("/auth/challenge", json={"address": address}).status_code == 403
    c = client.post("/auth/challenge", json={"address": address}, headers=headers).json()
    signature = Account.sign_message(
        encode_defunct(text=c["message"]), Account.create().key
    ).signature.hex()
    assert (
        client.post(
            "/auth/session",
            json={"challenge": c["challenge"], "signature": signature},
            headers=headers,
        ).status_code
        == 401
    )
    with factory() as db:
        row = db.get(BrowserCredential, browser_sessions.digest(c["challenge"]))
        row.expires_at = 0
        db.commit()
    assert (
        client.post(
            "/auth/session",
            json={"challenge": c["challenge"], "signature": signature},
            headers=headers,
        ).status_code
        == 401
    )
