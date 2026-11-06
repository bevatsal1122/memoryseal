"""Run an operator-pinned experimental 0G bridge over bounded pipes.

The pin and binary are operator trust inputs; this does not audit the binary or
prove the upstream implementation's behavior.
"""

import hashlib
import json
import os
import re
import selectors
import signal
import subprocess
import time
from pathlib import Path


class BridgeError(RuntimeError):
    pass


def run_bridge(binary: Path, expected_sha256: str, request: dict, *, timeout: float = 120) -> dict:
    if (
        not binary.is_absolute()
        or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256)
        or timeout <= 0
    ):
        raise BridgeError("invalid bridge configuration")
    try:
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise BridgeError("bridge executable unavailable")
        with binary.open("rb") as executable:
            digest = hashlib.file_digest(executable, "sha256").hexdigest()
        if digest != expected_sha256:
            raise BridgeError("bridge executable does not match configured pin")
        encoded = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode()
        if len(encoded) > 1_048_576:
            raise BridgeError("bridge input exceeds limit")
        allowed = (
            "PATH",
            "HOME",
            "TMPDIR",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
            "SSL_CERT_FILE",
        )
        env = {key: os.environ[key] for key in allowed if key in os.environ}
        with subprocess.Popen(
            [str(binary)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        ) as process:
            try:
                output = _exchange(process, encoded, timeout=timeout)
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                if process.poll() is None:
                    process.wait()
        payload = json.loads(output)
        if (
            not isinstance(payload, dict)
            or payload.get("status") != 200
            or not isinstance(payload.get("body"), dict)
        ):
            raise BridgeError("bridge returned invalid response")
        key = payload.get("response_key")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", key):
            raise BridgeError("bridge returned invalid response key")
        return payload
    except (
        OSError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        raise BridgeError("bridge execution failed") from exc


def _exchange(process: subprocess.Popen, encoded: bytes, *, timeout: float) -> bytes:
    deadline = time.monotonic() + timeout
    output = bytearray()
    remaining = memoryview(encoded)
    with selectors.DefaultSelector() as selector:
        for stream in (process.stdin, process.stdout):
            os.set_blocking(stream.fileno(), False)
        selector.register(process.stdin, selectors.EVENT_WRITE)
        selector.register(process.stdout, selectors.EVENT_READ)
        while selector.get_map():
            left = deadline - time.monotonic()
            if left <= 0:
                raise BridgeError("bridge timed out")
            for key, _ in selector.select(left):
                if key.fileobj is process.stdin:
                    if remaining:
                        written = os.write(process.stdin.fileno(), remaining[:65536])
                        remaining = remaining[written:]
                    if not remaining:
                        selector.unregister(process.stdin)
                        process.stdin.close()
                else:
                    chunk = os.read(process.stdout.fileno(), 65536)
                    if not chunk:
                        selector.unregister(process.stdout)
                    else:
                        output.extend(chunk)
                        if len(output) > 1_500_000:
                            raise BridgeError("bridge output exceeds limit")
        left = deadline - time.monotonic()
        if left <= 0:
            raise BridgeError("bridge timed out")
        try:
            code = process.wait(timeout=left)
        except subprocess.TimeoutExpired as exc:
            raise BridgeError("bridge timed out") from exc
        if code != 0:
            raise BridgeError("bridge failed")
    return bytes(output)
