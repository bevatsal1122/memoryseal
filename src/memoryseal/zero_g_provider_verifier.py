"""Experimental adapter for a trusted, operator-built 0G provider verifier.

An isolated pass is not proof of a particular inference request. The executable,
its baselines and trust roots, and the chain RPC remain operator trust inputs.
"""

import hashlib
import hmac
import os
import re
import signal
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from memoryseal.bridge_runner import BridgeError, _exchange
from memoryseal.zero_g_registry import NETWORKS
from memoryseal.zero_g_verification import valid_pins


def provider_verifier_configured(path: str | None, digest: str | None) -> bool:
    """Check configuration shape; the executable digest is checked at invocation."""
    if not path or not digest or not re.fullmatch(r"[0-9a-f]{64}", digest):
        return False
    executable = Path(path)
    return executable.is_absolute() and executable.is_file() and os.access(executable, os.X_OK)


def verify_provider_quote(
    binary: Path,
    *,
    network: str,
    rpc_url: str,
    provider: str,
    signer: str,
    endpoint: str,
    expected_sha256: str,
    timeout: float = 60,
) -> dict | None:
    """Return quote-reported public keys only for an unambiguous strict pass."""
    try:
        rpc = urlsplit(rpc_url)
        if (
            network not in NETWORKS
            or not provider_verifier_configured(str(binary), expected_sha256)
            or not valid_pins(provider, signer, endpoint)
            or rpc.scheme != "https"
            or not rpc.hostname
            or rpc.username
            or rpc.password
            or rpc.fragment
            or not 0 < timeout <= 120
        ):
            return None
        with binary.open("rb") as executable:
            actual_sha256 = hashlib.file_digest(executable, "sha256").hexdigest()
        if not hmac.compare_digest(actual_sha256, expected_sha256):
            return None
        contract = NETWORKS[network][1]
        command = [
            str(binary),
            "-provider",
            provider,
            "-chain-rpc-url",
            rpc_url,
            "-serving-contract",
            contract,
            "-endpoint",
            endpoint,
            "-expect-signer",
            signer,
            "-strict",
            "-timeout",
            "45s",
        ]
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
        keys = re.findall(r"(?m)^  report_data enc  ([0-9a-fA-F]{64})\s*$", output)
        signers = re.findall(r"(?m)^  report_data sgnr (0x[0-9a-fA-F]{40})\s*$", output)
        if len(keys) != 1 or len(signers) != 1 or int(keys[0], 16) == 0:
            return None
        if signers[0].lower() != signer.lower():
            return None
        return {
            "provider": provider.lower(),
            "signer": signer.lower(),
            "encryption_key": keys[0].lower(),
        }
    except (ValueError, OSError, UnicodeError, BridgeError, subprocess.SubprocessError):
        return None
