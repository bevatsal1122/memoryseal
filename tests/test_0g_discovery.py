import json

import httpx
import pytest
from eth_abi import encode

from memoryseal.demo.discover_0g import discover
from memoryseal.zero_g_registry import SERVICE_TYPE


def test_discovery_reports_candidate_without_attestation_and_checks_reorg():
    provider, signer = "0x" + "1" * 40, "0x" + "2" * 40
    service = (
        provider,
        "chatbot",
        "https://provider.example",
        1,
        2,
        3,
        "model",
        "TeeML",
        "{}",
        signer,
        True,
    )
    raw = "0x" + encode([f"{SERVICE_TYPE}[]", "uint256"], [[service], 1]).hex()
    reorg = False

    def handler(request):
        req = json.loads(request.content)
        result = {
            1: "0x40da",
            2: {"number": "0x10", "hash": "0xabc"},
            3: "0x60",
            4: raw,
            5: {"hash": "0xdef" if reorg else "0xabc"},
        }[req["id"]]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": req["id"], "result": result})

    result = discover("https://rpc.example", "testnet", transport=httpx.MockTransport(handler))
    assert result["services"][0]["compatible_with_pinned_check"] is True
    assert result["services"][0]["signer"].lower() == signer.lower()
    assert "not attestation" in result["note"]
    reorg = True
    with pytest.raises(ValueError, match="reorganized"):
        discover("https://rpc.example", "testnet", transport=httpx.MockTransport(handler))
