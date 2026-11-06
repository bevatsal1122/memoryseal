import time

from eth_account import Account
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from memoryseal import auth
from memoryseal.api import app
from memoryseal.config import settings
from memoryseal.db import Base
from memoryseal.signatures import sign_request


def test_signed_request_cannot_be_replayed_or_modified(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'auth.db'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(auth, "SessionLocal", sessionmaker(bind=engine))
    account = Account.create()
    timestamp = int(time.time())
    fields = {
        "audience": settings.request_audience,
        "method": "GET",
        "target": "/identity",
        "body": b"",
        "timestamp": timestamp,
        "nonce": "a" * 32,
    }
    headers = {
        "x-memoryseal-address": account.address,
        "x-memoryseal-signature": sign_request(account.key, **fields),
        "x-memoryseal-timestamp": str(timestamp),
        "x-memoryseal-nonce": "a" * 32,
    }
    with TestClient(app) as client:
        response = client.get("/identity", headers=headers)
        assert response.headers["cache-control"] == "no-store"
        assert response.json() == {
            "signer": account.address.lower()
        }
        assert client.get("/identity", headers=headers).status_code == 401
        assert client.get("/identity?different=1", headers=headers).status_code == 401
        unauthorized = client.get("/identity")
        assert unauthorized.status_code == 401
        assert unauthorized.headers["cache-control"] == "no-store"
        oversized = client.post("/identity", content=b"x" * 524_289)
        assert oversized.status_code == 413
        assert oversized.headers["cache-control"] == "no-store"
        preflight = client.options(
            "/identity",
            headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
        )
        assert preflight.headers["cache-control"] == "no-store"
