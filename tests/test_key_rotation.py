import os
from uuid import uuid4

import pytest
from cryptography.exceptions import InvalidTag
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from memoryseal.db import Base
from memoryseal.encryption import (
    SealedMemory,
    namespace_key,
    open_memory,
    reveal_salt,
    seal,
    write_digest,
)
from memoryseal.key_rotation import reencrypt_snapshot
from memoryseal.memory_service import context
from memoryseal.models import Agent, Memory


def seed(session, master, *, corrupt=False):
    session.add(Agent(id="agent", owner_address="owner", signing_address="agent", revoked=False))
    for number in range(2):
        memory_id = f"memory-{number}"
        plaintext = f"private {number}"
        key = namespace_key(master, "owner", "namespace")
        sealed = seal(key, plaintext.encode(), context=context(memory_id, "owner", "namespace"))
        session.add(
            Memory(
                id=memory_id,
                owner_address="owner",
                agent_id="agent",
                namespace="namespace",
                source_type="agent",
                source_reference="local",
                category="observation",
                trust_class="untrusted",
                status="quarantined",
                inference_status="not_configured",
                ciphertext=sealed.ciphertext,
                encryption_nonce=sealed.nonce,
                salt=sealed.salt,
                commitment=sealed.commitment,
                policy_version=1,
                request_id=str(uuid4()),
                request_digest=(
                    "0" * 64
                    if corrupt and number == 1
                    else write_digest(key, "namespace", plaintext, "agent", "local", None)
                ),
            )
        )
    session.commit()


def snapshot(session):
    return [
        (m.id, m.ciphertext, m.encryption_nonce, m.salt, m.commitment, m.request_digest)
        for m in session.scalars(select(Memory).order_by(Memory.id))
    ]


def test_snapshot_rotation_preserves_commitments_and_retry_identity(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'snapshot.db'}")
    Base.metadata.create_all(engine)
    old, new = os.urandom(32), os.urandom(32)
    with Session(engine) as session:
        seed(session, old)
        before = snapshot(session)
    with Session(engine) as session:
        assert reencrypt_snapshot(session, old, new) == 2
    with Session(engine) as session:
        after = snapshot(session)
        for before_row, after_row in zip(before, after, strict=True):
            memory_id, ciphertext, nonce, salt, commitment, digest = after_row
            assert salt != before_row[3]
            assert commitment == before_row[4]
            assert reveal_salt(
                namespace_key(old, "owner", "namespace"),
                before_row[3],
                context=context(memory_id, "owner", "namespace"),
            ) == reveal_salt(
                namespace_key(new, "owner", "namespace"),
                salt,
                context=context(memory_id, "owner", "namespace"),
            )
            assert (ciphertext, nonce, digest) != (before_row[1], before_row[2], before_row[5])
            key = namespace_key(new, "owner", "namespace")
            text = open_memory(
                key,
                SealedMemory(ciphertext, nonce, salt, commitment),
                context=context(memory_id, "owner", "namespace"),
            ).decode()
            assert digest == write_digest(key, "namespace", text, "agent", "local", None)
    engine.dispose()


def test_rotation_rolls_back_when_any_retry_digest_is_invalid(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'snapshot.db'}")
    Base.metadata.create_all(engine)
    old, new = os.urandom(32), os.urandom(32)
    with Session(engine) as session:
        seed(session, old, corrupt=True)
        before = snapshot(session)
    with Session(engine) as session, pytest.raises(ValueError, match="digest mismatch"):
        reencrypt_snapshot(session, old, new)
    with Session(engine) as session:
        assert snapshot(session) == before
    engine.dispose()


def test_rotated_snapshot_preserves_signed_gateway_retry(tmp_path, monkeypatch, gateway_transport):
    import base64

    from eth_account import Account
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    from memoryseal import auth
    from memoryseal.api import app
    from memoryseal.client import MemorySealClient
    from memoryseal.config import settings
    from memoryseal.db import get_session

    engine = create_engine(f"sqlite:///{tmp_path / 'gateway-snapshot.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    old, new = os.urandom(32), os.urandom(32)
    monkeypatch.setattr(auth, "SessionLocal", sessions)
    monkeypatch.setattr(settings, "encryption_key", base64.b64encode(old).decode())
    monkeypatch.setattr(settings, "zero_g_api_key", None)
    monkeypatch.setattr(settings, "zero_g_model", None)

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
                owner.grant(agent_id, "write", "scope")
                request_id = str(uuid4())
                first = agent.write_memory(
                    agent_id, "scope", "private data", source_type="agent", request_id=request_id
                )
                original = owner.inspect_memory(first["id"])
                with sessions() as rotation:
                    assert reencrypt_snapshot(rotation, old, new) == 1
                monkeypatch.setattr(settings, "encryption_key", base64.b64encode(new).decode())
                retry = agent.write_memory(
                    agent_id, "scope", "private data", source_type="agent", request_id=request_id
                )
                assert retry["id"] == first["id"]
                assert retry["commitment"] == first["commitment"]
                assert owner.inspect_memory(first["id"]) == original
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_prepare_rotated_copy_preserves_source_and_wal_contents(tmp_path):
    import sqlite3

    from memoryseal.key_rotation import prepare_rotated_snapshot
    from memoryseal.migrations import migrate

    source, destination = tmp_path / "source.db", tmp_path / "rotated.db"
    engine = create_engine(f"sqlite:///{source}")
    migrate(engine)
    old, new = os.urandom(32), os.urandom(32)
    keeper = sqlite3.connect(source)
    assert keeper.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    with Session(engine) as session:
        seed(session, old)
        before = snapshot(session)
    assert prepare_rotated_snapshot(source, destination, old, new) == 2
    with Session(engine) as session:
        assert snapshot(session) == before
    rotated_engine = create_engine(f"sqlite:///{destination}")
    with Session(rotated_engine) as session:
        rows = snapshot(session)
        assert [row[4] for row in rows] == [row[4] for row in before]
        for row in rows:
            key = namespace_key(new, "owner", "namespace")
            assert open_memory(
                key,
                SealedMemory(row[1], row[2], row[3], row[4]),
                context=context(row[0], "owner", "namespace"),
            ).startswith(b"private ")
    assert destination.stat().st_mode & 0o077 == 0
    assert not (tmp_path / "rotated.db-wal").exists()
    keeper.close()
    rotated_engine.dispose()
    engine.dispose()


def test_prepare_snapshot_fails_without_leaving_output(tmp_path):
    from memoryseal.key_rotation import prepare_rotated_snapshot
    from memoryseal.migrations import migrate
    from memoryseal.models import ProvenanceOutbox

    source, destination = tmp_path / "source.db", tmp_path / "rotated.db"
    engine = create_engine(f"sqlite:///{source}")
    migrate(engine)
    old, new = os.urandom(32), os.urandom(32)
    with Session(engine) as session:
        seed(session, old)
        before = snapshot(session)
    with pytest.raises(InvalidTag):
        prepare_rotated_snapshot(source, destination, os.urandom(32), new)
    assert not destination.exists()
    with Session(engine) as session:
        assert snapshot(session) == before
        session.add(
            ProvenanceOutbox(id="event", memory_id="memory-0", payload="{}", state="publishing")
        )
        session.commit()
    with pytest.raises(ValueError, match="in-flight"):
        prepare_rotated_snapshot(source, destination, old, new)
    assert not destination.exists()
    destination.write_text("keep")
    with pytest.raises(ValueError, match="destination"):
        prepare_rotated_snapshot(source, destination, old, new)
    assert destination.read_text() == "keep"
    engine.dispose()


def test_rotation_prepare_command_creates_copy_without_switching_source(tmp_path):
    import base64
    import json
    import subprocess
    import sys

    from memoryseal.migrations import migrate

    source, destination = tmp_path / "source.db", tmp_path / "rotated.db"
    engine = create_engine(f"sqlite:///{source}")
    migrate(engine)
    old, new = os.urandom(32), os.urandom(32)
    with Session(engine) as session:
        seed(session, old)
        before = snapshot(session)
    old_encoded, new_encoded = (base64.b64encode(key).decode() for key in (old, new))
    env = {name: value for name, value in os.environ.items() if not name.startswith("MEMORYSEAL_")}
    env.update(MEMORYSEAL_ROTATION_OLD_KEY=old_encoded, MEMORYSEAL_ROTATION_NEW_KEY=new_encoded)
    command = [
        sys.executable,
        "-m",
        "memoryseal.demo.prepare_rotation",
        str(source),
        str(destination),
    ]
    result = subprocess.run(
        command, env=env, cwd=tmp_path, capture_output=True, text=True, timeout=15, check=False
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["memory_count"] == 2
    assert report["cutover_performed"] is False
    assert old_encoded not in result.stdout + result.stderr
    assert new_encoded not in result.stdout + result.stderr
    with Session(engine) as session:
        assert snapshot(session) == before
    verify_command = [
        sys.executable,
        "-m",
        "memoryseal.demo.verify_rotation",
        str(source),
        str(destination),
    ]
    verified = subprocess.run(
        verify_command,
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert verified.returncode == 0, verified.stderr
    assert json.loads(verified.stdout)["memory_count"] == 2
    assert old_encoded not in verified.stdout + verified.stderr
    assert new_encoded not in verified.stdout + verified.stderr
    wrong_env = {**env, "MEMORYSEAL_ROTATION_NEW_KEY": base64.b64encode(os.urandom(32)).decode()}
    failed = subprocess.run(
        verify_command,
        env=wrong_env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert failed.returncode != 0
    assert wrong_env["MEMORYSEAL_ROTATION_NEW_KEY"] not in failed.stdout + failed.stderr
    result = subprocess.run(
        command, env=env, cwd=tmp_path, capture_output=True, text=True, timeout=15, check=False
    )
    assert result.returncode != 0
    assert old_encoded not in result.stdout + result.stderr
    assert new_encoded not in result.stdout + result.stderr
    assert destination.is_file()
    engine.dispose()


def test_rotation_prepare_command_rejects_invalid_key_without_creating_file(tmp_path):
    import base64
    import subprocess
    import sys

    source, destination = tmp_path / "source.db", tmp_path / "rotated.db"
    source.write_bytes(b"not accessed")
    env = {name: value for name, value in os.environ.items() if not name.startswith("MEMORYSEAL_")}
    env.update(
        MEMORYSEAL_ROTATION_OLD_KEY="invalid-secret",
        MEMORYSEAL_ROTATION_NEW_KEY=base64.b64encode(os.urandom(32)).decode(),
    )
    result = subprocess.run(
        [sys.executable, "-m", "memoryseal.demo.prepare_rotation", str(source), str(destination)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode != 0
    assert not destination.exists()
    assert "invalid-secret" not in result.stdout + result.stderr


def test_verify_rotation_detects_tampering_and_source_changes(tmp_path):
    from memoryseal.key_rotation import prepare_rotated_snapshot, verify_rotated_snapshot
    from memoryseal.migrations import migrate

    source, rotated = tmp_path / "source.db", tmp_path / "rotated.db"
    engine = create_engine(f"sqlite:///{source}")
    migrate(engine)
    old, new = os.urandom(32), os.urandom(32)
    with Session(engine) as session:
        seed(session, old)
    assert prepare_rotated_snapshot(source, rotated, old, new) == 2
    assert verify_rotated_snapshot(source, rotated, old, new) == 2
    with pytest.raises(InvalidTag):
        verify_rotated_snapshot(source, rotated, old, os.urandom(32))
    target = create_engine(f"sqlite:///{rotated}")
    with Session(target) as session:
        session.get(Memory, "memory-0").request_digest = "0" * 64
        session.commit()
    with pytest.raises(ValueError, match="digest"):
        verify_rotated_snapshot(source, rotated, old, new)
    target.dispose()
    rotated.unlink()
    prepare_rotated_snapshot(source, rotated, old, new)
    with Session(engine) as session:
        session.get(Agent, "agent").revoked = True
        session.commit()
    with pytest.raises(ValueError, match="records differ"):
        verify_rotated_snapshot(source, rotated, old, new)
    engine.dispose()


def test_empty_snapshot_reports_keys_not_verified(tmp_path):
    import base64
    import json
    import subprocess
    import sys

    from memoryseal.migrations import migrate

    source, destination = tmp_path / "empty.db", tmp_path / "rotated.db"
    engine = create_engine(f"sqlite:///{source}")
    migrate(engine)
    engine.dispose()
    env = {name: value for name, value in os.environ.items() if not name.startswith("MEMORYSEAL_")}
    env.update(
        MEMORYSEAL_ROTATION_OLD_KEY=base64.b64encode(os.urandom(32)).decode(),
        MEMORYSEAL_ROTATION_NEW_KEY=base64.b64encode(os.urandom(32)).decode(),
    )
    outputs = []
    for module in ("memoryseal.demo.prepare_rotation", "memoryseal.demo.verify_rotation"):
        result = subprocess.run(
            [sys.executable, "-m", module, str(source), str(destination)],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        outputs.append(json.loads(result.stdout))
    assert outputs[0]["memory_count"] == 0
    assert outputs[0]["source_key_checked_against_memory"] is False
    assert outputs[1]["status"] == "matched_no_encrypted_memories"
    assert outputs[1]["keys_verified_against_memory"] is False
