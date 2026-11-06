"""Read a bounded page of public 0G provider records without selecting a provider."""

import argparse
import json

import httpx
from eth_abi import decode, encode
from eth_utils import keccak

from memoryseal.http_limits import read_json_limited
from memoryseal.zero_g_registry import NETWORKS, SERVICE_TYPE
from memoryseal.zero_g_verification import valid_pins


def discover(rpc_url, network, *, offset=0, limit=20, transport=None):
    if (
        network not in NETWORKS
        or not isinstance(offset, int)
        or not 0 <= offset < 2**64
        or not 1 <= limit <= 50
    ):
        raise ValueError("Invalid network, offset or limit")
    chain_id, registry = NETWORKS[network]
    with httpx.Client(
        base_url=rpc_url, transport=transport, timeout=15, follow_redirects=False
    ) as client:

        def rpc(method, params, request_id):
            with client.stream(
                "POST",
                "",
                json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
            ) as response:
                body = read_json_limited(response, max_bytes=1_048_576)
            if (
                not isinstance(body, dict)
                or body.get("id") != request_id
                or "error" in body
                or "result" not in body
            ):
                raise ValueError("Invalid RPC response")
            return body["result"]

        if int(rpc("eth_chainId", [], 1), 16) != chain_id:
            raise ValueError("RPC chain ID mismatch")
        block = rpc("eth_getBlockByNumber", ["latest", False], 2)
        number, block_hash = block["number"], block["hash"]
        if rpc("eth_getCode", [registry, number], 3) in ("0x", "0x0"):
            raise ValueError("Registry has no code")
        data = (
            "0x"
            + (
                keccak(text="getAllServices(uint256,uint256)")[:4]
                + encode(["uint256", "uint256"], [offset, limit])
            ).hex()
        )
        raw = rpc("eth_call", [{"to": registry, "data": data}, number], 4)
        if not isinstance(raw, str) or not raw.startswith("0x") or len(raw) > 900_000:
            raise ValueError("Invalid service response")
        services, total = decode([f"{SERVICE_TYPE}[]", "uint256"], bytes.fromhex(raw[2:]))
        if len(services) > limit:
            raise ValueError("Provider page exceeds requested limit")
        checked = rpc("eth_getBlockByNumber", [number, False], 5)
        if checked["hash"].lower() != block_hash.lower():
            raise ValueError("Registry observation reorganized")
    records = []
    for (
        address,
        kind,
        url,
        input_price,
        output_price,
        updated,
        model,
        mode,
        extra,
        signer,
        acknowledged,
    ) in services:
        try:
            info = json.loads(extra)
            info_valid = isinstance(info, dict)
            if not info_valid:
                info = {}
        except (TypeError, ValueError):
            info, info_valid = {}, False
        provider_type = info.get("ProviderType", "decentralized")
        effective_signer = (
            info.get("TargetTeeAddress")
            if info.get("TargetSeparated") is True and provider_type == "decentralized"
            else signer
        )
        candidate = (
            info_valid
            and provider_type in ("centralized", "decentralized")
            and acknowledged
            and mode == "TeeML"
            and valid_pins(address, effective_signer, url)
        )
        records.append(
            {
                "provider": address,
                "service_type": kind,
                "url": url,
                "model": model,
                "mode": mode,
                "signer": effective_signer,
                "acknowledged": acknowledged,
                "input_price": str(input_price),
                "output_price": str(output_price),
                "updated_at": str(updated),
                "compatible_with_pinned_check": bool(candidate),
            }
        )
    return {
        "network": network,
        "chain_id": chain_id,
        "registry": registry,
        "block_number": int(number, 16),
        "block_hash": block_hash,
        "offset": offset,
        "total": str(total),
        "services": records,
        "note": "RPC observations are not attestation, provider health, price acceptance, or endorsement.",
    }


def main():
    parser = argparse.ArgumentParser(description="Read a page of 0G provider records")
    parser.add_argument("rpc_url")
    parser.add_argument("--network", choices=NETWORKS, default="testnet")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    print(
        json.dumps(
            discover(args.rpc_url, args.network, offset=args.offset, limit=args.limit), indent=2
        )
    )


if __name__ == "__main__":
    main()
