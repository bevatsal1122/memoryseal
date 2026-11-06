"""The shared publisher's CAS state machine also handles encrypted-vault metadata."""

import json
from types import SimpleNamespace
from uuid import uuid4

from eth_account import Account
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from memoryseal.config import settings
from memoryseal.db import Base
from memoryseal.models import Agent, VaultNamespace, VaultOutbox, VaultRecord
from memoryseal.outbox_worker import publish_one


def test_vault_publication_uses_existing_claim_logic(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "arkiv_private_key", SecretStr(Account.create().key.hex()))
    monkeypatch.setattr(settings, "arkiv_creator_address", None)
    engine = create_engine(f"sqlite:///{tmp_path / 'vault.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        a, s, r, e = [str(uuid4()) for _ in range(4)]
        address = "0x" + "1" * 40
        session.add(Agent(id=a, owner_address=address, signing_address=address))
        session.add(
            VaultNamespace(id=s, owner_address=address, namespace="private", active_version=1)
        )
        session.flush()
        session.add(
            VaultRecord(
                id=r,
                namespace_id=s,
                agent_id=a,
                key_version=1,
                revision=1,
                envelope_json='{"ciphertext":"not published"}',
                original_digest="b" * 64,
                commitment="a" * 64,
                status="quarantined",
            )
        )
        session.flush()
        session.add(
            VaultOutbox(
                id=e,
                memory_id=r,
                event_type="vault_written",
                payload='{"commitment":"' + "a" * 64 + '"}',
                state="pending",
            )
        )
        session.commit()

        def runner(*args, **kwargs):
            assert "not published" not in kwargs["input"]
            return SimpleNamespace(
                stdout=json.dumps({"entityKey": "0x" + "2" * 64, "txHash": "0x" + "3" * 64})
            )

        assert (
            publish_one(session, memory_id=r, event_id=e, model=VaultOutbox, runner=runner)
            == "published"
        )
        assert (
            publish_one(session, memory_id=r, event_id=e, model=VaultOutbox, runner=runner)
            == "not_pending"
        )
    engine.dispose()
