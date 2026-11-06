"""Run an operator-built 0G gateway verifier without passing MemorySeal credentials."""

import argparse
import json
import os
import subprocess
from pathlib import Path

HOSTS = {"testnet": "router-api-testnet.integratenetwork.work", "mainnet": "router-api.0g.ai"}


def verify_gateway(binary: Path, network: str, *, runner=subprocess.run, timeout=60):
    if network not in HOSTS or timeout <= 0:
        raise ValueError("Invalid network or timeout")
    # Do not pass router, wallet, encryption or other MemorySeal credentials.
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
        result = runner(
            command, capture_output=True, text=True, timeout=timeout, check=False, env=env
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "network": network, "endpoint": HOSTS[network]}
    except OSError:
        return {"status": "unavailable", "network": network, "endpoint": HOSTS[network]}
    status = {0: "passed", 1: "failed", 2: "invalid_invocation", 3: "incomplete"}.get(
        result.returncode, "error"
    )
    return {
        "status": status,
        "network": network,
        "endpoint": HOSTS[network],
        "exit_code": result.returncode,
        "output": result.stdout[-16000:],
        "error_output": result.stderr[-4000:],
        "scope": "A separate verifier run only; it is not bound to a MemorySeal inference connection or request.",
    }


def main():
    parser = argparse.ArgumentParser(
        description="Run a trusted, operator-built 0G pcverify binary in strict mode"
    )
    parser.add_argument("binary", type=Path)
    parser.add_argument("--network", choices=HOSTS, default="testnet")
    args = parser.parse_args()
    result = verify_gateway(args.binary.resolve(), args.network)
    print(json.dumps(result, indent=2))
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
