"""Deployment checks without Docker, remote services, credentials or funded wallets."""

import base64
import os
import runpy
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
START = ROOT / "deploy/start_gateway.py"
validate = runpy.run_path(str(START))["validate_environment"]


def configuration(tmp_path):
    return {
        "MEMORYSEAL_ENCRYPTION_KEY": base64.b64encode(os.urandom(32)).decode(),
        "MEMORYSEAL_DATABASE_URL": f"sqlite:///{tmp_path}/memoryseal.db",
        "MEMORYSEAL_DASHBOARD_ORIGINS": "https://sealmemory.vercel.app",
        "RAILWAY_ENVIRONMENT_ID": "isolated-test",
        "RAILWAY_VOLUME_MOUNT_PATH": str(tmp_path),
    }


def test_rejects_missing_key_volume_and_ephemeral_database(tmp_path):
    env = configuration(tmp_path)
    assert validate(env) == 8000
    for changed in (
        {"MEMORYSEAL_ENCRYPTION_KEY": "invalid"},
        {"RAILWAY_VOLUME_MOUNT_PATH": ""},
        {"MEMORYSEAL_DATABASE_URL": "sqlite:///./ephemeral.db"},
        {"MEMORYSEAL_DATABASE_URL": "sqlite:////tmp/outside-volume.db"},
        {"PORT": "70000"},
    ):
        with pytest.raises(ValueError):
            validate(env | changed)


def test_start_health_cors_and_restart_preserves_database(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("MEMORYSEAL_", "RAILWAY_"))}
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env.update(configuration(tmp_path), PORT=str(port), PYTHONPATH=str(ROOT / "src"))
    for iteration in range(2):
        process = subprocess.Popen(
            [sys.executable, str(START)],
            cwd=tmp_path,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
                for _ in range(300):
                    assert process.poll() is None, "gateway exited before becoming healthy"
                    try:
                        health = client.get("/health", timeout=1)
                        if health.status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                else:
                    pytest.fail("gateway did not become healthy")
                assert health.json() == {"status": "ok"}
                preflight = client.options(
                    "/agents",
                    headers={
                        "Origin": "https://sealmemory.vercel.app",
                        "Access-Control-Request-Method": "GET",
                        "Access-Control-Request-Headers": "x-memoryseal-signature",
                    },
                )
                assert preflight.status_code == 200
                assert preflight.headers["access-control-allow-origin"] == (
                    "https://sealmemory.vercel.app"
                )
                assert client.get("/agents").status_code in (401, 422)
                with sqlite3.connect(tmp_path / "memoryseal.db") as db:
                    assert db.execute("SELECT count(*) FROM agents").fetchone()[0] == 0
                    if iteration == 0:
                        db.execute("CREATE TABLE deployment_probe (value TEXT)")
                        db.execute("INSERT INTO deployment_probe VALUES ('retained')")
                    else:
                        assert db.execute("SELECT value FROM deployment_probe").fetchone() == (
                            "retained",
                        )
        finally:
            process.terminate()
            process.wait(timeout=10)
            process.stderr.close()
