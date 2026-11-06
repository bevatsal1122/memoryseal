"""Bound the Arkiv publisher process without assuming a failed write was absent."""

import os
import signal
import subprocess

from memoryseal.bridge_runner import BridgeError, _exchange


def run_arkiv(command, *, input, text, capture_output, timeout, check, env):
    """Return stdout for a successful child; fail without exposing stderr."""
    if not text or not capture_output or not check or not 0 < timeout <= 120:
        raise ValueError("invalid Arkiv subprocess options")
    encoded = input.encode("utf-8")
    if len(encoded) > 65_536:
        raise ValueError("Arkiv event exceeds input limit")
    try:
        with subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        ) as process:
            try:
                stdout = _exchange(process, encoded, timeout=timeout).decode("utf-8")
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                if process.poll() is None:
                    process.wait()
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")
    except (BridgeError, UnicodeError) as exc:
        raise subprocess.SubprocessError("Arkiv process failed or returned invalid output") from exc
