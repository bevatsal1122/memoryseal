import json

import httpx
import pytest
from eth_abi import encode

from memoryseal.onchain import RpcError
from memoryseal.token_balance_observer import observe_balance_delta


def test_balance_observer_rejects_reorg_and_unavailable_archive():
    hashes = {"0x9": "0x" + "a" * 64, "0xa": "0x" + "b" * 64}
    state = {"mode": "ok"}

    def handler(request):
        call = json.loads(request.content)
        if call["method"] == "eth_chainId":
            result = "0xaa36a7"
        elif call["method"] == "eth_getBlockByNumber":
            tag = call["params"][0]
            value = "0x" + "c" * 64 if state["mode"] == "reorg" and call["id"] == 7 else hashes[tag]
            result = {"hash": value, "parentHash": hashes["0x9"]}
        elif state["mode"] == "archive_missing":
            return httpx.Response(200, json={"id": call["id"], "error": {"code": -32000}})
        else:
            amount = 5 if call["params"][1] == "0x9" else 10
            result = "0x" + encode(["uint256"], [amount]).hex()
        return httpx.Response(200, json={"id": call["id"], "result": result})

    kwargs = {
        "rpc_url": "https://rpc.example",
        "chain_id": 11155111,
        "token": "0x" + "1" * 40,
        "recipient": "0x" + "2" * 40,
        "block_number": 10,
        "transport": httpx.MockTransport(handler),
    }
    assert observe_balance_delta(**kwargs)["delta"] == "5"
    state["mode"] = "reorg"
    with pytest.raises(RpcError, match="reorganized"):
        observe_balance_delta(**kwargs)
    state["mode"] = "archive_missing"
    with pytest.raises(RpcError):
        observe_balance_delta(**kwargs)
