"""Server-side ENS observations; values are observations, not credentials."""

import json
import os
import re
import subprocess
from pathlib import Path

from eth_utils import is_address

from memoryseal.config import settings

SCRIPT = Path(__file__).resolve().parents[2] / "integrations/ens/observe.mjs"


class EnsObservationError(Exception):
    pass


def observe(name: str, address: str, *, runner=subprocess.run) -> dict:
    chain_id = {"mainnet": 1, "sepolia": 11155111}.get(settings.ens_network)
    if not settings.ens_rpc_url or chain_id is None:
        raise EnsObservationError("ENS observer not configured")
    allow = (
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
        "NODE_EXTRA_CA_CERTS",
    )
    env = {key: os.environ[key] for key in allow if key in os.environ}
    env.update(
        MEMORYSEAL_ENS_RPC_URL=settings.ens_rpc_url, MEMORYSEAL_ENS_NETWORK=settings.ens_network
    )
    try:
        response = runner(
            ["node", str(SCRIPT)],
            input=json.dumps({"name": name, "expectedAddress": address}),
            text=True,
            capture_output=True,
            timeout=30,
            check=True,
            env=env,
        )
        result = json.loads(response.stdout)
        resolved = result["resolvedAddress"]
        if (
            result["chainId"] != chain_id
            or not isinstance(result["name"], str)
            or (resolved is not None and not is_address(resolved))
            or not isinstance(result["matches"], bool)
            or result["matches"] != (resolved is not None and resolved.lower() == address.lower())
            or not re.fullmatch(r"[0-9]+", result["blockNumber"])
            or not re.fullmatch(r"0x[0-9a-fA-F]{64}", result["blockHash"])
        ):
            raise ValueError("invalid observation")
        return result
    except (subprocess.SubprocessError, OSError, ValueError, KeyError, TypeError) as exc:
        raise EnsObservationError("ENS resolution failed") from exc
