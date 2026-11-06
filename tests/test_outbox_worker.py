import json
import subprocess
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eth_account import Account
from pydantic import SecretStr
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import Update

from memoryseal.config import settings
from memoryseal.db import Base
from memoryseal.models import Agent, Memory, ProvenanceOutbox
from memoryseal.outbox_worker import (
    observe_published,
    observer_env,
    publish_one,
    publisher_env,
    reconcile_one,
    recover_interrupted,
)


def test_outbox_claim_and_uncertain_failure(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'outbox.db'}")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(Agent(id="a", owner_address="owner", signing_address="agent", revoked=False))
        session.add(
            Memory(
                id="m",
                owner_address="owner",
                agent_id="a",
                namespace="n",
                source_type="agent",
                category="other",
                trust_class="untrusted",
                status="accepted",
                ciphertext=b"cipher",
                encryption_nonce=b"nonce",
                salt=b"salt",
                commitment="c",
                policy_version=1,
            )
        )
        session.add(ProvenanceOutbox(id="e", memory_id="m", payload="{}", state="pending"))
        session.commit()

        monkeypatch.setattr(settings, "arkiv_private_key", None)
        assert publish_one(session) == "not_configured"
        assert session.get(ProvenanceOutbox, "e").state == "pending"
        account = Account.create()
        test_key = "0x" + account.key.hex()
        monkeypatch.setattr(settings, "arkiv_private_key", SecretStr(test_key))
        monkeypatch.setattr(settings, "arkiv_creator_address", account.address)
        monkeypatch.setenv("MEMORYSEAL_ZERO_G_API_KEY", "unrelated-secret")

        def timeout(*_args, **kwargs):
            assert kwargs["env"]["MEMORYSEAL_ARKIV_PRIVATE_KEY"] == test_key
            assert "MEMORYSEAL_ZERO_G_API_KEY" not in kwargs["env"]
            raise subprocess.TimeoutExpired("node", 60)

        assert publish_one(session, runner=timeout) == "uncertain"
        assert session.get(ProvenanceOutbox, "e").state == "uncertain"
        assert session.get(ProvenanceOutbox, "e").creator_address == account.address.lower()
        assert publish_one(session, runner=timeout) is None
        missing = SimpleNamespace(stdout=json.dumps({"found": False}))
        assert reconcile_one(session, "e", runner=lambda *_args, **_kwargs: missing) == "uncertain"
        match = SimpleNamespace(
            stdout=json.dumps({"entityKey": "0x" + "a" * 64, "reconciled": True})
        )
        assert reconcile_one(session, "e", runner=lambda *_args, **_kwargs: match) == "published"
        assert session.get(ProvenanceOutbox, "e").entity_key == "0x" + "a" * 64
        session.get(ProvenanceOutbox, "e").state = "pending"
        session.commit()
        receipt = SimpleNamespace(
            stdout=json.dumps({"entityKey": "0x" + "1" * 64, "txHash": "0x" + "2" * 64})
        )
        assert publish_one(session, runner=lambda *_args, **_kwargs: receipt) == "published"
        assert session.get(ProvenanceOutbox, "e").transaction_hash == "0x" + "2" * 64
        entry = session.get(ProvenanceOutbox, "e")
        matched = SimpleNamespace(
            stdout=json.dumps({"entityKey": "0x" + "1" * 64, "reconciled": True})
        )
        assert observe_published(entry, runner=lambda *_args, **_kwargs: matched) == "matched"
        assert observe_published(entry, runner=lambda *_args, **_kwargs: missing) == "not_found"
        assert observe_published(entry, runner=lambda *_args, **_kwargs: match) == "conflict"
        conflict = SimpleNamespace(stdout=json.dumps({"conflict": True}))
        assert observe_published(entry, runner=lambda *_args, **_kwargs: conflict) == "conflict"

        def observer_timeout(*_args, **kwargs):
            assert (
                kwargs["env"]["MEMORYSEAL_ARKIV_CREATOR_ADDRESS"].lower() == account.address.lower()
            )
            assert "MEMORYSEAL_ARKIV_PRIVATE_KEY" not in kwargs["env"]
            assert "MEMORYSEAL_ZERO_G_API_KEY" not in kwargs["env"]
            raise subprocess.TimeoutExpired("node", 60)

        assert observe_published(entry, runner=observer_timeout) == "unavailable"
        assert entry.state == "published"
        assert recover_interrupted(session, "e") == "not_publishing"

        rotated = Account.create()
        monkeypatch.setattr(settings, "arkiv_private_key", SecretStr("0x" + rotated.key.hex()))
        monkeypatch.setattr(settings, "arkiv_creator_address", rotated.address)
        assert observe_published(entry, runner=observer_timeout) == "unavailable"
        entry.state = "pending"
        session.commit()
        assert publish_one(session, memory_id="m", runner=timeout) == "creator_mismatch"
        assert entry.state == "pending"
        monkeypatch.setattr(settings, "arkiv_private_key", SecretStr(test_key))
        monkeypatch.setattr(settings, "arkiv_creator_address", account.address)

        # Even if an operator mistakenly recovers a still-running worker, its
        # late receipt must not overwrite the recovered state or cause a retry.
        entry.state = "pending"
        session.commit()

        def recovery_during_publish(*_args, **_kwargs):
            with Session(engine) as other:
                assert recover_interrupted(other, "e") == "uncertain"
            return receipt

        assert publish_one(session, runner=recovery_during_publish) == "state_changed"
        session.expire_all()
        assert session.get(ProvenanceOutbox, "e").state == "uncertain"
        assert publish_one(session, runner=timeout) is None
        assert reconcile_one(session, "e", runner=lambda *_args, **_kwargs: missing) == "uncertain"
        assert reconcile_one(session, "e", runner=lambda *_args, **_kwargs: matched) == "published"

        # Legacy uncertain records had no stored publisher; bind the queried one.
        entry = session.get(ProvenanceOutbox, "e")
        entry.state = "uncertain"
        entry.creator_address = None
        entry.entity_key = None
        session.commit()
        assert reconcile_one(session, "e", runner=lambda *_args, **_kwargs: matched) == "published"
        session.expire_all()
        assert session.get(ProvenanceOutbox, "e").creator_address == account.address.lower()

        # A concurrent change while lookup runs must not publish stale evidence.
        for mutation in ("creator_address", "payload"):
            entry = session.get(ProvenanceOutbox, "e")
            entry.state = "uncertain"
            entry.creator_address = account.address.lower()
            entry.payload = "{}"
            entry.entity_key = None
            session.commit()

            def changed_during_lookup(*_args, field=mutation, **_kwargs):
                with Session(engine) as other:
                    current = other.get(ProvenanceOutbox, "e")
                    setattr(
                        current,
                        field,
                        Account.create().address.lower()
                        if field == "creator_address"
                        else '{"changed":true}',
                    )
                    other.commit()
                return matched

            assert reconcile_one(session, "e", runner=changed_during_lookup) == "uncertain"
            session.expire_all()
            assert session.get(ProvenanceOutbox, "e").state == "uncertain"

        # A later claim or changed publication input must not receive an old receipt.
        for mutation in ("attempt_id", "creator_address", "payload"):
            for fails in (False, True):
                entry = session.get(ProvenanceOutbox, "e")
                entry.state = "pending"
                entry.creator_address = account.address.lower()
                entry.payload = "{}"
                entry.entity_key = None
                session.commit()

                def change_during_publish(*_args, field=mutation, fail=fails, **_kwargs):
                    with Session(engine) as other:
                        current = other.get(ProvenanceOutbox, "e")
                        replacement = {
                            "attempt_id": str(uuid4()),
                            "creator_address": Account.create().address.lower(),
                            "payload": '{"changed":true}',
                        }[field]
                        setattr(current, field, replacement)
                        other.commit()
                    if fail:
                        raise subprocess.TimeoutExpired("node", 60)
                    return receipt

                assert publish_one(session, runner=change_during_publish) == "state_changed"
                session.expire_all()
                current = session.get(ProvenanceOutbox, "e")
                assert current.state == "publishing"
                assert current.entity_key is None
    engine.dispose()


def test_oversized_publisher_output_leaves_event_uncertain(tmp_path, monkeypatch):
    publisher = tmp_path / "publisher.mjs"
    publisher.write_text("process.stdout.write('x'.repeat(1600000));\n")
    monkeypatch.setattr("memoryseal.outbox_worker.PUBLISHER", publisher)
    monkeypatch.setattr(settings, "arkiv_private_key", SecretStr("0x" + Account.create().key.hex()))
    monkeypatch.setattr(settings, "arkiv_creator_address", None)
    engine = create_engine(f"sqlite:///{tmp_path / 'oversized.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(ProvenanceOutbox(id="event", memory_id="memory", payload="{}", state="pending"))
        session.commit()
        assert publish_one(session) == "uncertain"
        assert session.get(ProvenanceOutbox, "event").state == "uncertain"
        assert publish_one(session) is None
    engine.dispose()


def test_reader_can_use_public_creator_without_publisher_secret(monkeypatch):
    account = Account.create()
    monkeypatch.setattr(settings, "arkiv_creator_address", account.address)
    monkeypatch.setattr(settings, "arkiv_private_key", None)
    env = observer_env()
    assert env["MEMORYSEAL_ARKIV_CREATOR_ADDRESS"] == account.address
    assert "MEMORYSEAL_ARKIV_PRIVATE_KEY" not in env
    monkeypatch.setattr(settings, "arkiv_private_key", SecretStr("0x" + Account.create().key.hex()))
    assert publisher_env() is None
    monkeypatch.setattr(settings, "arkiv_creator_address", None)
    monkeypatch.setattr(settings, "arkiv_private_key", SecretStr(account.key.hex()))
    env = observer_env()
    assert env["MEMORYSEAL_ARKIV_CREATOR_ADDRESS"] == account.address
    assert "MEMORYSEAL_ARKIV_PRIVATE_KEY" not in env


def test_publish_targeted_memory_without_touching_other_or_retrying(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'targeted.db'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings, "arkiv_private_key", SecretStr(Account.create().key.hex()))
    monkeypatch.setattr(settings, "arkiv_creator_address", None)
    with Session(engine, expire_on_commit=False) as session:
        session.add(Agent(id="a", owner_address="owner", signing_address="agent", revoked=False))
        for name in ("research", "claim"):
            session.add(
                Memory(
                    id=name,
                    owner_address="owner",
                    agent_id="a",
                    namespace="n",
                    source_type="agent",
                    category="other",
                    trust_class="untrusted",
                    status="accepted",
                    ciphertext=b"c",
                    encryption_nonce=b"n",
                    salt=b"s",
                    commitment="c",
                    policy_version=1,
                )
            )
            session.add(
                ProvenanceOutbox(id=f"event-{name}", memory_id=name, payload=name, state="pending")
            )
        session.commit()
        # An older event bound to a different key must not block the queue.
        research = session.get(ProvenanceOutbox, "event-research")
        research.creator_address = Account.create().address.lower()
        session.commit()

        def publish(*_args, **kwargs):
            assert kwargs["input"] == "claim"
            return SimpleNamespace(stdout=json.dumps({"entityKey": "0x" + "1" * 64}))

        assert publish_one(session, memory_id="research", runner=publish) == "creator_mismatch"
        original_execute = session.execute
        raced = False

        def execute_with_race(statement, *args, **kwargs):
            nonlocal raced
            if isinstance(statement, Update) and not raced:
                raced = True
                with Session(engine) as other:
                    other.execute(
                        update(ProvenanceOutbox)
                        .where(ProvenanceOutbox.id == "event-claim")
                        .values(state="publishing")
                    )
                    other.commit()
            return original_execute(statement, *args, **kwargs)

        monkeypatch.setattr(session, "execute", execute_with_race)
        assert (
            publish_one(session, runner=lambda *_args, **_kwargs: pytest.fail("duplicate"))
            == "state_changed"
        )
        monkeypatch.setattr(session, "execute", original_execute)
        session.get(ProvenanceOutbox, "event-claim").state = "pending"
        session.commit()
        assert publish_one(session, runner=publish) == "published"
        assert session.get(ProvenanceOutbox, "event-research").state == "pending"
        assert publish_one(session, runner=publish) == "creator_mismatch"
        assert publish_one(session, memory_id="claim", runner=publish) == "not_pending"
        assert publish_one(session, memory_id="missing", runner=publish) == "not_pending"
    engine.dispose()
