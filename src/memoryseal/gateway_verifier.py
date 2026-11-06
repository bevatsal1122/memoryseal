"""Bounded runtime invocation of the operator-trusted 0G gateway verifier."""

import hashlib
import hmac
import os
import signal
import subprocess
from pathlib import Path

from memoryseal.bridge_runner import BridgeError, _exchange
from memoryseal.demo.verify_0g_gateway import HOSTS
from memoryseal.zero_g_provider_verifier import provider_verifier_configured


def verify_gateway_bounded(
    binary: Path, network: str, *, expected_sha256: str | None, timeout: float = 60
) -> dict:
    """Run strict verification without retaining stderr or unbounded subprocess output."""
    if (
        network not in HOSTS
        or not 0 < timeout <= 120
        or not provider_verifier_configured(str(binary), expected_sha256)
    ):
        return {"status": "failed", "output": ""}
    allowed = (
        "PATH",
        "HOME",
        "TMPDIR",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
        "SSL_CERT_FILE",
    )
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    command = [
        str(binary),
        "-gateway",
        HOSTS[network],
        "-expect-network",
        network,
        "-strict",
        "-timeout",
        "45s",
    ]
    try:
        with binary.open("rb") as executable:
            digest = hashlib.file_digest(executable, "sha256").hexdigest()
        if not hmac.compare_digest(digest, expected_sha256):
            return {"status": "failed", "output": ""}
        with subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        ) as process:
            try:
                output = _exchange(process, b"", timeout=timeout).decode("utf-8")
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                if process.poll() is None:
                    process.wait()
        return {"status": "passed", "output": output}
    except (OSError, ValueError, UnicodeError, BridgeError, subprocess.SubprocessError):
        return {"status": "failed", "output": ""}
