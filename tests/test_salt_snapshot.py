"""Salt-only snapshots preserve content and detect invalid or changing sources."""

import base64
import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from memoryseal.encryption import namespace_key, reveal_salt, seal, write_digest
from memoryseal.key_rotation import (
    prepare_salt_snapshot,
    prepare_source_snapshot,
    verify_salt_snapshot,
    verify_source_snapshot,
)
from memoryseal.memory_service import context
from memoryseal.migrations import migrate
from memoryseal.models import Agent, Memory


def snapshot(session):
    return [
        (
            item.id,
            item.ciphertext,
            item.encryption_nonce,
            item.salt,
            item.commitment,
            item.request_digest,
        )
        for item in session.query(Memory).order_by(Memory.id)
    ]


def legacy_source(path, master):
    engine = create_engine(f"sqlite:///{path}")
    migrate(engine)
    with Session(engine) as session:
        session.add(
            Agent(id="agent", owner_address="owner", signing_address="agent", revoked=False)
        )
        key = namespace_key(master, "owner", "namespace")
        for number in range(2):
            memory_id, content = f"memory-{number}", f"private {number}"
            sealed = seal(key, content.encode(), context=context(memory_id, "owner", "namespace"))
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
                    request_id=f"request-{number}",
                    request_digest=write_digest(key, "namespace", content, "agent", "local", None),
                )
            )
        session.commit()
        item = session.get(Memory, "memory-0")
        key = namespace_key(master, item.owner_address, item.namespace)
        item.salt = reveal_salt(
            key, item.salt, context=context(item.id, item.owner_address, item.namespace)
        )
        session.commit()
    return engine


def test_prepare_and_verify_salt_snapshot_without_changing_source(tmp_path):
    master = os.urandom(32)
    source, copy = tmp_path / "source.db", tmp_path / "copy.db"
    engine = legacy_source(source, master)
    with Session(engine) as session:
        before = snapshot(session)
    assert prepare_salt_snapshot(source, copy, master) == (2, 1)
    assert verify_salt_snapshot(source, copy, master) == 2
    with Session(engine) as session:
        assert snapshot(session) == before
        session.get(Memory, "memory-0").source_reference = "changed"
        session.commit()
    with pytest.raises(ValueError, match="metadata differs"):
        verify_salt_snapshot(source, copy, master)
    with pytest.raises(ValueError, match="destination"):
        prepare_salt_snapshot(source, copy, master)
    engine.dispose()


def test_invalid_salt_snapshot_fails_without_publishing_copy(tmp_path):
    master = os.urandom(32)
    source, copy = tmp_path / "source.db", tmp_path / "copy.db"
    engine = legacy_source(source, master)
    with Session(engine) as session:
        session.get(Memory, "memory-1").request_digest = "0" * 64
        session.commit()
    with pytest.raises(ValueError, match="digest mismatch"):
        prepare_salt_snapshot(source, copy, master)
    assert not copy.exists()
    engine.dispose()


def test_source_snapshot_protects_legacy_values_and_detects_tampering(tmp_path):
    master = os.urandom(32)
    source, copy = tmp_path / "source.db", tmp_path / "copy.db"
    engine = legacy_source(source, master)
    assert prepare_source_snapshot(source, copy, master) == (2, 2)
    assert verify_source_snapshot(source, copy, master) == 2
    second_copy = tmp_path / "second.db"
    assert prepare_source_snapshot(copy, second_copy, master) == (2, 0)
    assert verify_source_snapshot(copy, second_copy, master) == 2
    with Session(engine) as session:
        assert session.get(Memory, "memory-0").source_reference == "local"
    copy_engine = create_engine(f"sqlite:///{copy}")
    with Session(copy_engine) as session:
        item = session.get(Memory, "memory-0")
        assert item.source_reference is None
        assert b"local" not in item.source_reference_encrypted
        item.source_reference = "tampered"
        item.source_reference_encrypted = None
        session.commit()
    with pytest.raises(ValueError, match="plaintext source"):
        verify_source_snapshot(source, copy, master)
    copy_engine.dispose()
    engine.dispose()


def test_source_snapshot_rejects_bad_retry_digest_without_publishing(tmp_path):
    master = os.urandom(32)
    source, copy = tmp_path / "source.db", tmp_path / "copy.db"
    engine = legacy_source(source, master)
    with Session(engine) as session:
        session.get(Memory, "memory-0").request_digest = "0" * 64
        session.commit()
    with pytest.raises(ValueError, match="digest mismatch"):
        prepare_source_snapshot(source, copy, master)
    assert not copy.exists()
    engine.dispose()


@pytest.mark.parametrize("module", ["protect_salts", "protect_sources"])
def test_snapshot_cli_does_not_print_key_and_refuses_wrong_key(tmp_path, module):
    master = os.urandom(32)
    source, copy = tmp_path / "source.db", tmp_path / "copy.db"
    engine = legacy_source(source, master)
    key = base64.b64encode(master).decode()
    env = {k: v for k, v in os.environ.items() if not k.startswith("MEMORYSEAL_")}
    env["MEMORYSEAL_SNAPSHOT_KEY"] = key
    command = [sys.executable, "-m", f"memoryseal.demo.{module}"]
    for operation in ("prepare", "verify"):
        result = subprocess.run(
            command + [operation, str(source), str(copy)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        assert result.returncode == 0, result.stderr
        assert key not in result.stdout + result.stderr
        assert '"cutover_performed": false' in result.stdout
    env["MEMORYSEAL_SNAPSHOT_KEY"] = base64.b64encode(os.urandom(32)).decode()
    result = subprocess.run(
        command + ["verify", str(source), str(copy)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode != 0
    assert key not in result.stdout + result.stderr
    engine.dispose()
