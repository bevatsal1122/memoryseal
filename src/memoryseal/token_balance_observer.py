"""Observe token-reported balances around a block, not a transaction trace."""

import re

import httpx
from eth_abi import encode
from eth_utils import is_address, keccak

from memoryseal.http_limits import read_json_limited
from memoryseal.onchain import RpcError


def observe_balance_delta(*, rpc_url, chain_id, token, recipient, block_number, transport=None):
    if chain_id <= 0 or not is_address(token) or not is_address(recipient) or block_number <= 0:
        raise ValueError("invalid token balance observation")
    data = "0x" + (keccak(text="balanceOf(address)")[:4] + encode(["address"], [recipient])).hex()
    with httpx.Client(
        base_url=rpc_url, transport=transport, timeout=10, follow_redirects=False
    ) as client:

        def rpc(method, params, number):
            with client.stream(
                "POST",
                "",
                json={"jsonrpc": "2.0", "id": number, "method": method, "params": params},
            ) as response:
                payload = read_json_limited(response, max_bytes=131_072)
            if (
                not isinstance(payload, dict)
                or payload.get("id") != number
                or "error" in payload
                or "result" not in payload
            ):
                raise RpcError("invalid balance RPC response")
            return payload["result"]

        try:
            if int(rpc("eth_chainId", [], 1), 16) != chain_id:
                raise RpcError("chain ID mismatch")
            previous, current = hex(block_number - 1), hex(block_number)
            before_block = rpc("eth_getBlockByNumber", [previous, False], 2)
            after_block = rpc("eth_getBlockByNumber", [current, False], 3)
            if after_block["parentHash"].lower() != before_block["hash"].lower():
                raise RpcError("blocks are not linked")

            def balance(tag, number):
                raw = rpc("eth_call", [{"to": token, "data": data}, tag], number)
                if not isinstance(raw, str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", raw):
                    raise RpcError("invalid token balance result")
                return int(raw, 16)

            before, after = balance(previous, 4), balance(current, 5)
            if (
                rpc("eth_getBlockByNumber", [previous, False], 6)["hash"].lower()
                != before_block["hash"].lower()
                or rpc("eth_getBlockByNumber", [current, False], 7)["hash"].lower()
                != after_block["hash"].lower()
            ):
                raise RpcError("balance observation block reorganized")
            return {
                "before": str(before),
                "after": str(after),
                "delta": str(after - before),
                "block_number": block_number,
                "block_hash": after_block["hash"],
                "previous_block_hash": before_block["hash"],
            }
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as exc:
            raise RpcError("could not observe token balances") from exc
