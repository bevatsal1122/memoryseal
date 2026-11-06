"""Observe dedicated demo wallet balances on Sepolia without sending keys."""

import json
import os
import re

import httpx
from eth_account import Account

from memoryseal.config import settings
from memoryseal.http_limits import read_json_limited


class BalanceObservationError(RuntimeError):
    pass


def observe_balances(rpc_url: str, keys: dict[str, str], *, transport=None) -> dict:
    if set(keys) != {"owner", "browser", "research", "finance"}:
        raise ValueError("Four dedicated demo keys are required")
    addresses = {role: Account.from_key(key).address for role, key in keys.items()}
    if len({address.lower() for address in addresses.values()}) != 4:
        raise ValueError("Demo wallets must be distinct")
    with httpx.Client(
        base_url=rpc_url, timeout=8, transport=transport, follow_redirects=False
    ) as client:

        def rpc(method, params, number):
            with client.stream(
                "POST",
                "",
                json={"jsonrpc": "2.0", "id": number, "method": method, "params": params},
            ) as response:
                result = read_json_limited(response, max_bytes=131_072)
            if (
                not isinstance(result, dict)
                or result.get("id") != number
                or "error" in result
                or "result" not in result
            ):
                raise BalanceObservationError("Invalid RPC response")
            return result["result"]

        try:
            if int(rpc("eth_chainId", [], 1), 16) != 11155111:
                raise BalanceObservationError("RPC is not Sepolia")
            block = rpc("eth_getBlockByNumber", ["latest", False], 2)
            block_number, block_hash = block["number"], block["hash"]
            if (
                not isinstance(block_number, str)
                or not re.fullmatch(r"0x[0-9a-fA-F]+", block_number)
                or not isinstance(block_hash, str)
                or not re.fullmatch(r"0x[0-9a-fA-F]{64}", block_hash)
            ):
                raise BalanceObservationError("Invalid block reference")
            balances = {}
            for index, (role, address) in enumerate(addresses.items(), 3):
                raw = rpc("eth_getBalance", [address, block_number], index)
                if not isinstance(raw, str) or not re.fullmatch(r"0x[0-9a-fA-F]{1,64}", raw):
                    raise BalanceObservationError("Invalid balance")
                balances[role] = str(int(raw, 16))
            rechecked = rpc("eth_getBlockByNumber", [block_number, False], 7)
            if rechecked["hash"].lower() != block_hash.lower():
                raise BalanceObservationError("Observed block reorganized")
            return {
                "chain_id": 11155111,
                "block_number": int(block_number, 16),
                "block_hash": block_hash,
                "balances_wei": balances,
                "scope": "Configured RPC observation only; balances do not guarantee sufficient funds or finality.",
            }
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as exc:
            raise BalanceObservationError("Could not observe wallet balances") from exc


def main():
    keys = {
        role: os.environ.get(f"MEMORYSEAL_DEMO_{role.upper()}_KEY", "")
        for role in ("owner", "browser", "research", "finance")
    }
    if not settings.ens_rpc_url:
        raise SystemExit("Configure MEMORYSEAL_ENS_RPC_URL with a Sepolia RPC")
    try:
        result = observe_balances(settings.ens_rpc_url, keys)
    except (ValueError, BalanceObservationError):
        raise SystemExit(
            "Balance check failed; verify the dedicated keys and Sepolia RPC configuration"
        ) from None
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
