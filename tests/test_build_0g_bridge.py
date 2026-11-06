import subprocess
from types import SimpleNamespace

import pytest

from scripts import build_0g_bridge


def test_refuses_existing_destination_and_wrong_commit(tmp_path, monkeypatch):
    go = tmp_path / "go"
    go.write_text("not executed")
    go.chmod(0o700)
    target = tmp_path / "bridge"
    target.write_text("keep")
    with pytest.raises(FileExistsError):
        build_0g_bridge.build_bridge(tmp_path, go, target)
    assert target.read_text() == "keep"
    target.unlink()
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(stdout="wrong-commit\n")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(ValueError, match="pinned commit"):
        build_0g_bridge.build_bridge(tmp_path, go, target)
    assert len(calls) == 1
    assert not target.exists()


def test_resolver_hook_requires_exact_upstream_shape(tmp_path):
    directory = tmp_path / "client/cmd/internal/proxycli"
    directory.mkdir(parents=True)
    source = directory / "proxycli.go"
    source.write_text(
        "type buildConfig struct{ serves []endpoint.Endpoint }\n"
        "Clients: sealingClients(router, served, coreOpts)\n"
        "core.WithDebugLogger(logger),\n"
    )
    build_0g_bridge.patch_proxycli(tmp_path)
    assert "memorySealWrap(bc, router)" in source.read_text()
    assert "core.WithUnboundFields([]string{})" in source.read_text()
    assert (directory / "memoryseal_resolver_hook.go").is_file()
    with pytest.raises(ValueError, match="does not match"):
        build_0g_bridge.patch_proxycli(tmp_path)


def test_response_limit_patch_requires_exact_upstream_shape(tmp_path):
    directory = tmp_path / "client/core"
    directory.mkdir(parents=True)
    source = directory / "client.go"
    source.write_text(
        "respBody, err := io.ReadAll(resp.Body)\n\trecordMeta(ctx, provider, resp.Header)\n\treturn out, false, nil"
    )
    (directory / "verify.go").write_text(
        '\treturn "", nil\n}\n\n// verifyStream verifies a streamed E2EE response'
    )
    build_0g_bridge.patch_core(tmp_path)
    assert "memorySealReadResponse(resp.Body)" in source.read_text()
    assert (directory / "memoryseal_bounded_response.go").is_file()
    assert (directory / "memoryseal_receipt.go").is_file()
    with pytest.raises(ValueError, match="does not match"):
        build_0g_bridge.patch_core(tmp_path)


def test_request_seal_patch_requires_exact_upstream_shape(tmp_path):
    crypto = tmp_path / "protocol/crypto"
    wire = tmp_path / "protocol/wire"
    crypto.mkdir(parents=True)
    wire.mkdir(parents=True)
    (crypto / "seal.go").write_text("enc, sealer, err := sender.Setup(rand.Reader)\n")
    (wire / "envelope.go").write_text(
        "\t// 2. HPKE setup — enc is needed before the AAD (it lives inside `_e2ee`).\n"
    )
    build_0g_bridge.patch_protocol(tmp_path)
    assert "memorySealSetupSender" in (crypto / "seal.go").read_text()
    assert "MemorySealRecordRequestPlaintext(pt)" in (wire / "envelope.go").read_text()
    with pytest.raises(ValueError, match="does not match"):
        build_0g_bridge.patch_protocol(tmp_path)
