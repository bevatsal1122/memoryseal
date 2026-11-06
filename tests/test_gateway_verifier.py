import hashlib
import sys

from memoryseal.gateway_verifier import verify_gateway_bounded


def verifier(tmp_path, body):
    binary = tmp_path / "pcverify"
    binary.write_text(f"#!{sys.executable}\n" + body)
    binary.chmod(0o700)
    return binary


def test_bounded_verifier_passes_strict_arguments_without_application_secrets(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MEMORYSEAL_ZERO_G_API_KEY", "secret")
    binary = verifier(
        tmp_path,
        "import os, sys\n"
        "assert 'MEMORYSEAL_ZERO_G_API_KEY' not in os.environ\n"
        "assert '-strict' in sys.argv and '-gateway' in sys.argv\n"
        "print('  served cert      ' + 'ab' * 32)\n",
    )
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    result = verify_gateway_bounded(binary, "testnet", expected_sha256=digest, timeout=5)
    assert result["status"] == "passed"
    assert "ab" * 32 in result["output"]


def test_bounded_verifier_rejects_failed_large_and_stuck_processes(tmp_path):
    for body in (
        "raise SystemExit(3)\n",
        "print('x' * 1600000)\n",
        "import time\ntime.sleep(5)\n",
    ):
        binary = verifier(tmp_path, body)
        digest = hashlib.sha256(binary.read_bytes()).hexdigest()
        result = verify_gateway_bounded(binary, "testnet", expected_sha256=digest, timeout=0.2)
        assert result == {"status": "failed", "output": ""}


def test_digest_mismatch_prevents_verifier_execution(tmp_path):
    marker = tmp_path / "executed"
    binary = verifier(tmp_path, f"open({str(marker)!r}, 'w').close()\n")
    assert verify_gateway_bounded(binary, "testnet", expected_sha256="0" * 64) == {
        "status": "failed",
        "output": "",
    }
    assert not marker.exists()
