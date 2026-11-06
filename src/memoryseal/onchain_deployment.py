"""Observe whether an executor points at the configured policy registry."""

import httpx
from eth_abi import decode
from eth_abi.exceptions import DecodingError
from eth_utils import is_address, keccak

from memoryseal.contract_artifacts import matches_local_runtime
from memoryseal.http_limits import read_json_limited
from memoryseal.onchain import RpcError


def observe_deployment(*, rpc_url, chain_id, registry, executor, transport=None):
    if chain_id <= 0 or not all(
        is_address(value) and int(value, 16) != 0 for value in (registry, executor)
    ):
        raise ValueError("Invalid deployment configuration")
    with httpx.Client(
        base_url=rpc_url, transport=transport, timeout=10, follow_redirects=False
    ) as client:

        def rpc(method, params, request_id):
            with client.stream(
                "POST",
                "",
                json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
            ) as response:
                payload = read_json_limited(response, max_bytes=131_072)
            if (
                not isinstance(payload, dict)
                or payload.get("id") != request_id
                or "error" in payload
                or "result" not in payload
            ):
                raise RpcError("Invalid RPC response")
            return payload["result"]

        try:
            if int(rpc("eth_chainId", [], 1), 16) != chain_id:
                raise RpcError("chain ID mismatch")
            block = rpc("eth_getBlockByNumber", ["latest", False], 2)
            number, block_hash = block["number"], block["hash"]
            codes = []
            for index, address in enumerate((registry, executor), 3):
                code = rpc("eth_getCode", [address, number], index)
                if not isinstance(code, str) or code in ("0x", "0x0"):
                    raise RpcError("configured contract has no code")
                codes.append(code)
            selector = "0x" + keccak(text="registry()")[:4].hex()
            raw = rpc("eth_call", [{"to": executor, "data": selector}, number], 5)
            if not isinstance(raw, str) or not raw.startswith("0x") or len(raw) != 66:
                raise RpcError("Invalid executor registry response")
            observed = decode(["address"], bytes.fromhex(raw[2:]))[0]
            checked = rpc("eth_getBlockByNumber", [number, False], 6)
            if checked["hash"].lower() != block_hash.lower():
                raise RpcError("block reorganized")
            return {
                "chain_id": chain_id,
                "registry": registry,
                "executor": executor,
                "executor_registry": observed,
                "matches": observed.lower() == registry.lower(),
                "registry_code_matches_local": matches_local_runtime(
                    "MemoryPolicyRegistry", codes[0], registry
                ),
                "executor_code_matches_local": matches_local_runtime(
                    "ProtectedTransfer", codes[1], registry
                ),
                "block_number": int(number, 16),
                "block_hash": block_hash,
            }
        except (
            httpx.HTTPError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            DecodingError,
        ) as exc:
            raise RpcError("Could not observe deployment") from exc
