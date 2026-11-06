import hashlib
import sys
from pathlib import Path

import pytest

from memoryseal.bridge_runner import BridgeError, run_bridge


def executable(tmp_path: Path, code: str) -> tuple[Path, str]:
    path = tmp_path / "bridge"
    path.write_text(f"#!{sys.executable}\n" + code)
    path.chmod(0o700)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_bridge_exchanges_request_and_limits_environment(tmp_path, monkeypatch):
    binary, pin = executable(
        tmp_path,
        """import json, os, sys
request = json.load(sys.stdin)
assert request == {"api_key": "private", "body": {"model": "example"}}
assert "MEMORYSEAL_TEST_SECRET" not in os.environ
print(json.dumps({"status": 200, "body": {"answer": "ok"}, "response_key": "abc_123"}))
""",
    )
    monkeypatch.setenv("MEMORYSEAL_TEST_SECRET", "do-not-inherit")
    assert run_bridge(binary, pin, {"api_key": "private", "body": {"model": "example"}})[
        "body"
    ] == {"answer": "ok"}


def test_bridge_rejects_unpinned_binary_before_execution(tmp_path):
    marker = tmp_path / "executed"
    binary, _ = executable(tmp_path, f'open({str(marker)!r}, "w").close()\n')
    with pytest.raises(BridgeError, match="pin"):
        run_bridge(binary, "0" * 64, {})
    assert not marker.exists()


@pytest.mark.parametrize(
    "code",
    [
        "raise SystemExit(1)",
        'print("not json")',
        'print(\'{"status": 200, "body": {}, "response_key": "bad key"}\')',
        'print(\'{"status": 500, "body": {}, "response_key": "key"}\')',
        'print("x" * 1500001)',
    ],
)
def test_bridge_rejects_bad_outputs(tmp_path, code):
    binary, pin = executable(tmp_path, code + "\n")
    with pytest.raises(BridgeError):
        run_bridge(binary, pin, {"api_key": "secret"}, timeout=5)


def test_bridge_times_out_and_does_not_expose_stderr(tmp_path):
    binary, pin = executable(
        tmp_path, 'import sys, time\nprint("secret", file=sys.stderr, flush=True)\ntime.sleep(10)\n'
    )
    with pytest.raises(BridgeError, match="timed out") as error:
        run_bridge(binary, pin, {"api_key": "secret"}, timeout=0.2)
    assert "secret" not in str(error.value)


def test_bridge_rejects_oversized_input(tmp_path):
    binary, pin = executable(tmp_path, "raise SystemExit(1)\n")
    with pytest.raises(BridgeError, match="input exceeds"):
        run_bridge(binary, pin, {"content": "x" * 1_048_576})
