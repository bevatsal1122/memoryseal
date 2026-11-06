"""Build the experimental bridge from a pinned upstream Git archive."""

import argparse
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

PINNED_COMMIT = "c0e7d23f03adea19cbac36223bbeabe05cc8eaad"
BRIDGE = Path(__file__).resolve().parents[1] / "integrations/zero_g/bridge.go"
PINNED_RESOLVER = BRIDGE.with_name("pinned_resolver.go")
HOOK = BRIDGE.with_name("proxycli_resolver_hook.go")
BOUNDED_CORE = BRIDGE.with_name("bounded_upstream.go")
RECEIPT_CORE = BRIDGE.with_name("receipt_upstream.go")
REQUEST_SEAL = BRIDGE.with_name("request_seal_upstream.go")


def patch_protocol(root: Path) -> None:
    """Capture one request's sealing inputs without changing its random source."""
    crypto = root / "protocol/crypto/seal.go"
    wire = root / "protocol/wire/envelope.go"
    crypto_text, wire_text = crypto.read_text(), wire.read_text()
    sender = "enc, sealer, err := sender.Setup(rand.Reader)"
    marker = "\t// 2. HPKE setup — enc is needed before the AAD (it lives inside `_e2ee`)."
    if crypto_text.count(sender) != 1 or wire_text.count(marker) != 1:
        raise ValueError("pinned upstream request sealing does not match")
    crypto.write_text(
        crypto_text.replace(
            sender, "enc, sealer, err := memorySealSetupSender(sender, pub, info)", 1
        )
    )
    wire.write_text(
        wire_text.replace(marker, "\tcrypto.MemorySealRecordRequestPlaintext(pt)\n\n" + marker, 1)
    )
    shutil.copyfile(REQUEST_SEAL, crypto.with_name("memoryseal_request_seal.go"))


def patch_proxycli(root: Path) -> None:
    """Apply a narrow, fail-closed hook to the exact archived upstream source."""
    source = root / "client/cmd/internal/proxycli/proxycli.go"
    text = source.read_text()
    replacements = {
        "type buildConfig struct{ serves []endpoint.Endpoint }": (
            "type buildConfig struct { serves []endpoint.Endpoint; "
            "memorySealWrap func(core.Resolver) core.Resolver }"
        ),
        "Clients: sealingClients(router, served, coreOpts)": (
            "Clients: sealingClients(memorySealWrap(bc, router), served, coreOpts)"
        ),
        "core.WithDebugLogger(logger),": (
            "core.WithDebugLogger(logger),\n\t\tcore.WithUnboundFields([]string{}),"
        ),
    }
    for old, new in replacements.items():
        if text.count(old) != 1:
            raise ValueError("pinned upstream resolver hook does not match")
        text = text.replace(old, new, 1)
    source.write_text(text)
    shutil.copyfile(HOOK, source.with_name("memoryseal_resolver_hook.go"))


def patch_core(root: Path) -> None:
    """Bound buffered sealed responses before upstream decoding and decryption."""
    source = root / "client/core/client.go"
    text = source.read_text()
    old = "respBody, err := io.ReadAll(resp.Body)"
    if text.count(old) != 1:
        raise ValueError("pinned upstream response read does not match")
    metadata = "\trecordMeta(ctx, provider, resp.Header)\n\treturn out, false, nil"
    if text.count(metadata) != 1:
        raise ValueError("pinned upstream response metadata does not match")
    verify = root / "client/core/verify.go"
    verify_text = verify.read_text()
    expected = '\treturn "", nil\n}\n\n// verifyStream verifies a streamed E2EE response'
    if verify_text.count(expected) != 1:
        raise ValueError("pinned upstream receipt verification does not match")
    text = text.replace(old, "respBody, err := memorySealReadResponse(resp.Body)", 1)
    source.write_text(
        text.replace(metadata, "\tmemorySealRecordResponseKey(ephPriv)\n" + metadata, 1)
    )
    verify.write_text(
        verify_text.replace(
            expected, "\tmemorySealRecordReceipt(sig, reqEnv, respFrame)\n" + expected, 1
        )
    )
    shutil.copyfile(BOUNDED_CORE, source.with_name("memoryseal_bounded_response.go"))
    shutil.copyfile(RECEIPT_CORE, source.with_name("memoryseal_receipt.go"))


def build_bridge(checkout: Path, go: Path, destination: Path) -> None:
    checkout, go, destination = checkout.resolve(), go.resolve(), destination.absolute()
    if not go.is_file() or not os.access(go, os.X_OK):
        raise ValueError("Go executable unavailable")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("destination already exists")
    actual = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=checkout, capture_output=True, text=True, check=True
    ).stdout.strip()
    if actual != PINNED_COMMIT:
        raise ValueError("upstream checkout does not match the pinned commit")
    # Archive HEAD rather than copying the worktree: local untracked or modified
    # upstream files cannot silently enter the build.
    with tempfile.TemporaryDirectory(prefix="memoryseal-0g-build-") as directory:
        root = Path(directory)
        archive = root / "source.tar"
        with archive.open("wb") as out:
            subprocess.run(
                ["git", "archive", "--format=tar", "HEAD", "client", "protocol"],
                cwd=checkout,
                stdout=out,
                check=True,
            )
        with tarfile.open(archive) as tar:
            tar.extractall(root, filter="data")
        patch_proxycli(root)
        patch_protocol(root)
        patch_core(root)
        command_dir = root / "client/cmd/memorysealbridge"
        command_dir.mkdir(parents=True)
        shutil.copyfile(BRIDGE, command_dir / "main.go")
        shutil.copyfile(PINNED_RESOLVER, command_dir / "pinned_resolver.go")
        binary = root / "memoryseal-0g-bridge"
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
        env["GOTOOLCHAIN"] = "local"
        subprocess.run(
            [
                str(go),
                "build",
                "-trimpath",
                "-buildvcs=false",
                "-o",
                str(binary),
                "./cmd/memorysealbridge",
            ],
            cwd=root / "client",
            env=env,
            check=True,
        )
        # Exclusive creation preserves an existing operator-supplied executable.
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
        try:
            with os.fdopen(fd, "wb") as out, binary.open("rb") as source:
                shutil.copyfileobj(source, out)
        except Exception:
            destination.unlink(missing_ok=True)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    parser.add_argument("go", type=Path, help="absolute path to the reviewed Go executable")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build_bridge(args.checkout, args.go, args.output)
    print("Experimental bridge built; operator review and live verification remain required.")


if __name__ == "__main__":
    main()
