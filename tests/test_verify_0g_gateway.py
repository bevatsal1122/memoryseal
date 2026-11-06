import subprocess
from pathlib import Path
from types import SimpleNamespace

from memoryseal.demo.verify_0g_gateway import verify_gateway


def test_verifier_is_strict_and_does_not_inherit_secrets(monkeypatch):
    monkeypatch.setenv("MEMORYSEAL_ZERO_G_API_KEY", "private")

    def run(command, **kwargs):
        assert "-strict" in command
        assert command[command.index("-expect-network") + 1] == "testnet"
        assert "MEMORYSEAL_ZERO_G_API_KEY" not in kwargs["env"]
        return SimpleNamespace(returncode=3, stdout="partial", stderr="")

    assert verify_gateway(Path("/tmp/pcverify"), "testnet", runner=run)["status"] == "incomplete"

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 60)

    assert verify_gateway(Path("/tmp/pcverify"), "testnet", runner=timeout)["status"] == "timeout"
