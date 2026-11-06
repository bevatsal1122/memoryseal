import hashlib
import sys

from memoryseal.zero_g_provider_verifier import verify_provider_quote

PROVIDER = "0x" + "1" * 40
SIGNER = "0x" + "2" * 40
KEY = "ab" * 32


def executable(tmp_path, body):
    path = tmp_path / "pcverify"
    path.write_text(f"#!{sys.executable}\n" + body)
    path.chmod(0o700)
    return path


def verify(binary):
    return verify_provider_quote(
        binary,
        network="testnet",
        rpc_url="https://rpc.example",
        provider=PROVIDER,
        signer=SIGNER,
        endpoint="https://provider.example",
        expected_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        timeout=5,
    )


def test_strict_provider_result_extracts_quote_keys_without_inheriting_secrets(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("MEMORYSEAL_ZERO_G_API_KEY", "must-not-leak")
    binary = executable(
        tmp_path,
        "import os, sys\n"
        "assert 'MEMORYSEAL_ZERO_G_API_KEY' not in os.environ\n"
        "assert '-strict' in sys.argv and '-expect-signer' in sys.argv\n"
        f"print('  report_data enc  {KEY}')\n"
        f"print('  report_data sgnr {SIGNER}')\n",
    )
    assert verify(binary) == {"provider": PROVIDER, "signer": SIGNER, "encryption_key": KEY}


def test_provider_result_rejects_failed_ambiguous_or_mismatched_reports(tmp_path):
    base = f"print('  report_data enc  {KEY}')\nprint('  report_data sgnr {SIGNER}')\n"
    for suffix in (
        "raise SystemExit(1)\n",
        f"print('  report_data enc  {KEY}')\n",
        "print('  report_data sgnr 0x' + '3' * 40)\n",
    ):
        assert verify(executable(tmp_path, base + suffix)) is None
    wrong = executable(
        tmp_path, f"print('  report_data enc  {'00' * 32}')\nprint('  report_data sgnr {SIGNER}')\n"
    )
    assert verify(wrong) is None
    assert (
        verify_provider_quote(
            wrong,
            network="testnet",
            rpc_url="http://rpc.example",
            provider=PROVIDER,
            signer=SIGNER,
            endpoint="https://provider.example",
            expected_sha256=hashlib.sha256(wrong.read_bytes()).hexdigest(),
        )
        is None
    )


def test_provider_timeout_fails_closed(tmp_path):
    binary = executable(tmp_path, "import time\ntime.sleep(5)\n")
    assert (
        verify_provider_quote(
            binary,
            network="testnet",
            rpc_url="https://rpc.example",
            provider=PROVIDER,
            signer=SIGNER,
            endpoint="https://provider.example",
            expected_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
            timeout=0.1,
        )
        is None
    )


def test_changed_executable_is_not_invoked(tmp_path):
    marker = tmp_path / "invoked"
    binary = executable(tmp_path, f"open({str(marker)!r}, 'w').close()\n")
    assert (
        verify_provider_quote(
            binary,
            network="testnet",
            rpc_url="https://rpc.example",
            provider=PROVIDER,
            signer=SIGNER,
            endpoint="https://provider.example",
            expected_sha256="0" * 64,
        )
        is None
    )
    assert not marker.exists()
