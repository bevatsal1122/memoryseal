"""Compare operator pins with an observed 0G inference service record.

Addresses and ABI are from the 0G compute TypeScript SDK; the RPC is trusted and
this observation does not verify attestation or future registry state.
"""

import json
import re

import httpx
from eth_abi import decode, encode
from eth_abi.exceptions import DecodingError
from eth_utils import keccak

from memoryseal.http_limits import read_json_limited

NETWORKS = {
    "testnet": (16602, "0xa79F4c8311FF93C06b8CfB403690cc987c93F91E"),
    "mainnet": (16661, "0x47340d900bdFec2BD393c626E12ea0656F938d84"),
}
SERVICE_TYPE = "(address,string,string,uint256,uint256,uint256,string,string,string,address,bool)"


def registry_pins_match(*, rpc_url, network, provider, signer, base_url, transport=None):
    """Fail closed unless a stable-block provider record matches all pins."""
    try:
        chain_id, registry = NETWORKS[network]
        data = (
            "0x" + (keccak(text="getService(address)")[:4] + encode(["address"], [provider])).hex()
        )
        with httpx.Client(
            base_url=rpc_url, transport=transport, timeout=8, follow_redirects=False
        ) as client:

            def rpc(method, params, request_id):
                with client.stream(
                    "POST",
                    "",
                    json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
                ) as response:
                    result = read_json_limited(response, max_bytes=1_048_576)
                if (
                    not isinstance(result, dict)
                    or result.get("id") != request_id
                    or "error" in result
                    or "result" not in result
                ):
                    raise ValueError("invalid RPC response")
                return result["result"]

            if int(rpc("eth_chainId", [], 1), 16) != chain_id:
                return False
            block = rpc("eth_getBlockByNumber", ["latest", False], 2)
            number, block_hash = block["number"], block["hash"]
            if (
                not isinstance(number, str)
                or not re.fullmatch(r"0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)", number)
                or not isinstance(block_hash, str)
                or not re.fullmatch(r"0x[0-9a-fA-F]{64}", block_hash)
            ):
                return False
            code = rpc("eth_getCode", [registry, number], 3)
            if not isinstance(code, str) or not re.fullmatch(r"0x(?:[0-9a-fA-F]{2})+", code):
                return False
            raw = rpc("eth_call", [{"to": registry, "data": data}, number], 4)
            if not isinstance(raw, str) or not raw.startswith("0x") or len(raw) > 131_074:
                return False
            service = decode([SERVICE_TYPE], bytes.fromhex(raw[2:]))[0]
            checked = rpc("eth_getBlockByNumber", [number, False], 5)
            if (
                not isinstance(checked, dict)
                or checked.get("number") != number
                or not isinstance(checked.get("hash"), str)
                or checked["hash"].lower() != block_hash.lower()
            ):
                return False
        address, _, url, _, _, _, _, verifiability, extra, tee_signer, acknowledged = service
        if (
            address.lower() != provider.lower()
            or url.rstrip("/") != base_url.rstrip("/")
            or verifiability != "TeeML"
            or acknowledged is not True
        ):
            return False
        info = json.loads(extra)
        if not isinstance(info, dict):
            return False
        provider_type = info.get("ProviderType", "decentralized")
        if provider_type not in ("decentralized", "centralized"):
            return False
        effective_signer = tee_signer
        if info.get("TargetSeparated") is True and provider_type == "decentralized":
            effective_signer = info.get("TargetTeeAddress")
        return isinstance(effective_signer, str) and effective_signer.lower() == signer.lower()
    except (
        httpx.HTTPError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        DecodingError,
        OverflowError,
    ):
        return False
