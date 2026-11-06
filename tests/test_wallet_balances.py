import json

import httpx
import pytest
from eth_account import Account

from memoryseal.demo.wallet_balances import BalanceObservationError, observe_balances


def test_balance_observation_pins_block_and_rejects_reorg():
    keys = {
        role: Account.create().key.hex() for role in ("owner", "browser", "research", "finance")
    }
    calls = []
    state = {"reorg": False}

    def handler(request):
        call = json.loads(request.content)
        calls.append(call)
        if call["method"] == "eth_chainId":
            result = "0xaa36a7"
        elif call["method"] == "eth_getBlockByNumber":
            result = {
                "number": "0x10",
                "hash": "0x" + ("b" if state["reorg"] and call["id"] == 7 else "a") * 64,
            }
        else:
            assert call["params"][1] == "0x10"
            result = "0x64"
        return httpx.Response(200, json={"id": call["id"], "result": result})

    result = observe_balances("https://rpc.example", keys, transport=httpx.MockTransport(handler))
    assert result["balances_wei"] == {role: "100" for role in keys}
    assert result["block_number"] == 16
    assert all(key not in json.dumps(calls) for key in keys.values())
    state["reorg"] = True
    with pytest.raises(BalanceObservationError, match="reorganized"):
        observe_balances("https://rpc.example", keys, transport=httpx.MockTransport(handler))
