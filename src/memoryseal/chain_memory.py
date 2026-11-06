"""Fresh registry check for protected memory operations."""

import re

import httpx
from eth_abi import encode
from eth_utils import is_address, keccak, to_checksum_address

from memoryseal.http_limits import read_json_limited


class ChainPolicyError(Exception):
    pass


def is_allowed(
    *,
    rpc_url: str,
    chain_id: int,
    registry: str,
    owner: str,
    agent: str,
    namespace: str,
    operation: str,
    transport=None,
) -> bool:
    if (
        chain_id <= 0
        or operation not in ("read", "write")
        or not namespace
        or any(not is_address(value) for value in (registry, owner, agent))
    ):
        raise ChainPolicyError("invalid chain policy configuration")
    registry = to_checksum_address(registry)
    selector = keccak(text="canAccessMemory(address,address,bytes32,bool)")[:4]
    data = (
        "0x"
        + (
            selector
            + encode(
                ["address", "address", "bytes32", "bool"],
                [owner, agent, keccak(text=namespace), operation == "write"],
            )
        ).hex()
    )
    try:
        with httpx.Client(
            base_url=rpc_url, transport=transport, timeout=8, follow_redirects=False
        ) as client:

            def rpc(method, params, request_id):
                with client.stream(
                    "POST",
                    "",
                    json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
                ) as response:
                    payload = read_json_limited(response, max_bytes=1_048_576)
                if (
                    not isinstance(payload, dict)
                    or payload.get("id") != request_id
                    or "error" in payload
                    or "result" not in payload
                ):
                    raise ChainPolicyError("chain policy RPC failed")
                return payload["result"]

            if int(rpc("eth_chainId", [], 1), 16) != chain_id:
                raise ChainPolicyError("chain ID mismatch")
            block = rpc("eth_getBlockByNumber", ["latest", False], 2)
            if not isinstance(block, dict):
                raise ChainPolicyError("invalid policy block")
            number, block_hash = block.get("number"), block.get("hash")
            if (
                not isinstance(number, str)
                or not re.fullmatch(r"0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)", number)
                or not isinstance(block_hash, str)
                or not re.fullmatch(r"0x[0-9a-fA-F]{64}", block_hash)
            ):
                raise ChainPolicyError("invalid policy block")
            code = rpc("eth_getCode", [registry, number], 3)
            if not isinstance(code, str) or not re.fullmatch(r"0x(?:[0-9a-fA-F]{2})+", code):
                raise ChainPolicyError("registry has no code")
            result = rpc("eth_call", [{"to": registry, "data": data}, number], 4)
            if not isinstance(result, str) or len(result) != 66 or not result.startswith("0x"):
                raise ChainPolicyError("invalid registry result")
            value = int(result, 16)
            if value not in (0, 1):
                raise ChainPolicyError("invalid registry result")
            checked = rpc("eth_getBlockByNumber", [number, False], 5)
            if (
                not isinstance(checked, dict)
                or checked.get("number") != number
                or not isinstance(checked.get("hash"), str)
                or checked["hash"].lower() != block_hash.lower()
            ):
                raise ChainPolicyError("policy block changed")
            return value == 1
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        raise ChainPolicyError("chain policy RPC failed") from exc
