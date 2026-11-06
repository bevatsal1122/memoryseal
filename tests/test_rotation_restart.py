"""Exercise snapshot rotation across isolated gateway processes."""

import base64
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from uuid import uuid4

from eth_account import Account

from memoryseal.client import MemorySealClient


@contextmanager
def gateway(tmp_path, database, key):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    env = {k: v for k, v in os.environ.items() if not k.startswith("MEMORYSEAL_")}
    env.update(
        MEMORYSEAL_DATABASE_URL=f"sqlite:///{database}",
        MEMORYSEAL_ENCRYPTION_KEY=base64.b64encode(key).decode(),
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "memoryseal.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError("gateway exited before startup")
            try:
                with urllib.request.urlopen(url + "/health", timeout=0.2) as response:
                    if response.status == 200:
                        break
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)
        else:
            raise RuntimeError("gateway did not start")
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def test_rotation_across_gateway_restart(tmp_path):
    source, rotated = tmp_path / "original.db", tmp_path / "rotated.db"
    old, new = os.urandom(32), os.urandom(32)
    owner_account, agent_account = Account.create(), Account.create()
    request_id = str(uuid4())
    with (
        gateway(tmp_path, source, old) as url,
        MemorySealClient(url, owner_account.key, audience="memoryseal-local") as owner,
        MemorySealClient(url, agent_account.key, audience="memoryseal-local") as agent,
    ):
        agent_id = owner.register_agent(agent.address)["id"]
        owner.grant(agent_id, "write", "scope")
        first = agent.write_memory(
            agent_id,
            "scope",
            "private test",
            source_type="agent",
            request_id=request_id,
            source_reference="https://private.example/source?token=secret",
        )
        original_inspection = owner.inspect_memory(first["id"])
        assert (
            original_inspection["source_reference"] == "https://private.example/source?token=secret"
        )
        provenance = owner.list_memories(memory_id=first["id"])["memories"][0]["provenance"]
    with sqlite3.connect(source) as connection:
        reference, encrypted = connection.execute(
            "SELECT source_reference, source_reference_encrypted FROM memories WHERE id = ?",
            (first["id"],),
        ).fetchone()
        assert reference is None
        assert b"private.example" not in encrypted
    env = {k: v for k, v in os.environ.items() if not k.startswith("MEMORYSEAL_")}
    env.update(
        MEMORYSEAL_ROTATION_OLD_KEY=base64.b64encode(old).decode(),
        MEMORYSEAL_ROTATION_NEW_KEY=base64.b64encode(new).decode(),
    )
    for module in ("memoryseal.demo.prepare_rotation", "memoryseal.demo.verify_rotation"):
        result = subprocess.run(
            [sys.executable, "-m", module, str(source), str(rotated)],
            env=env,
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["memory_count"] == 1
    with (
        gateway(tmp_path, rotated, new) as url,
        MemorySealClient(url, owner_account.key, audience="memoryseal-local") as owner,
        MemorySealClient(url, agent_account.key, audience="memoryseal-local") as agent,
    ):
        retry = agent.write_memory(
            agent_id,
            "scope",
            "private test",
            source_type="agent",
            request_id=request_id,
            source_reference="https://private.example/source?token=secret",
        )
        assert retry["id"] == first["id"]
        assert retry["commitment"] == first["commitment"]
        assert owner.inspect_memory(first["id"]) == original_inspection
        after = owner.list_memories(memory_id=first["id"])["memories"][0]["provenance"]
        assert after == provenance


def test_salt_only_snapshot_across_gateway_restart(tmp_path):
    source, protected = tmp_path / "legacy.db", tmp_path / "protected.db"
    master = os.urandom(32)
    owner_account, agent_account = Account.create(), Account.create()
    request_id = str(uuid4())
    with (
        gateway(tmp_path, source, master) as url,
        MemorySealClient(url, owner_account.key, audience="memoryseal-local") as owner,
        MemorySealClient(url, agent_account.key, audience="memoryseal-local") as agent,
    ):
        agent_id = owner.register_agent(agent.address)["id"]
        owner.grant(agent_id, "write", "scope")
        first = agent.write_memory(
            agent_id, "scope", "short private memory", source_type="agent", request_id=request_id
        )
        inspection = owner.inspect_memory(first["id"])
        provenance = owner.list_memories(memory_id=first["id"])["memories"][0]["provenance"]
    # Simulate a legacy row in this temporary database after the gateway is stopped.
    salt = base64.b64decode(inspection["commitment_salt"], validate=True)
    with sqlite3.connect(source) as db:
        db.execute("UPDATE memories SET salt = ? WHERE id = ?", (salt, first["id"]))
    env = {k: v for k, v in os.environ.items() if not k.startswith("MEMORYSEAL_")}
    env["MEMORYSEAL_SNAPSHOT_KEY"] = base64.b64encode(master).decode()
    for operation in ("prepare", "verify"):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "memoryseal.demo.protect_salts",
                operation,
                str(source),
                str(protected),
            ],
            env=env,
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        output = json.loads(result.stdout)
        assert output["memories_checked"] == 1 and output["key_checked_against_memory"] is True
        if operation == "prepare":
            assert output["salts_protected"] == 1
    with sqlite3.connect(source) as db:
        assert (
            db.execute("SELECT salt FROM memories WHERE id = ?", (first["id"],)).fetchone()[0]
            == salt
        )
    with (
        gateway(tmp_path, protected, master) as url,
        MemorySealClient(url, owner_account.key, audience="memoryseal-local") as owner,
        MemorySealClient(url, agent_account.key, audience="memoryseal-local") as agent,
    ):
        retry = agent.write_memory(
            agent_id, "scope", "short private memory", source_type="agent", request_id=request_id
        )
        assert retry["id"] == first["id"] and retry["commitment"] == first["commitment"]
        assert owner.inspect_memory(first["id"]) == inspection
        assert owner.list_memories(memory_id=first["id"])["memories"][0]["provenance"] == provenance
