import json

import httpx
import pytest
from eth_abi import decode
from eth_utils import keccak

from memoryseal.chain_memory import ChainPolicyError, is_allowed


def test_registry_call_scopes_owner_agent_namespace_and_operation():
    owner, agent, registry = ("0x" + str(i) * 40 for i in (1, 2, 3))
    state = {"chain": "0x1", "result": "0x" + "0" * 63 + "1", "reorg": False}

    def handler(request):
        call = json.loads(request.content)
        if call["method"] == "eth_chainId":
            result = state["chain"]
        elif call["method"] == "eth_getBlockByNumber":
            result = {
                "number": "0x10",
                "hash": "0x" + ("b" if state["reorg"] and call["id"] == 5 else "a") * 64,
            }
        elif call["method"] == "eth_getCode":
            assert call["params"][1] == "0x10"
            result = "0x6000"
        else:
            assert call["params"][1] == "0x10"
            raw = bytes.fromhex(call["params"][0]["data"][2:])
            assert raw[:4] == keccak(text="canAccessMemory(address,address,bytes32,bool)")[:4]
            decoded = decode(["address", "address", "bytes32", "bool"], raw[4:])
            assert decoded == (owner.lower(), agent.lower(), keccak(text="research"), True)
            result = state["result"]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": call["id"], "result": result})

    kwargs = {
        "rpc_url": "https://rpc.example",
        "chain_id": 1,
        "registry": registry,
        "owner": owner,
        "agent": agent,
        "namespace": "research",
        "operation": "write",
        "transport": httpx.MockTransport(handler),
    }
    assert is_allowed(**kwargs)
    state["result"] = "0x" + "0" * 64
    assert not is_allowed(**kwargs)
    state["result"] = "0x" + "0" * 63 + "1"
    state["reorg"] = True
    with pytest.raises(ChainPolicyError, match="block changed"):
        is_allowed(**kwargs)
    state["reorg"] = False
    state["result"] = "0x02"
    with pytest.raises(ChainPolicyError):
        is_allowed(**kwargs)
    state["chain"] = "0x2"
    with pytest.raises(ChainPolicyError, match="chain ID"):
        is_allowed(**kwargs)


@pytest.mark.parametrize(
    "block,code",
    [
        ({"number": "latest", "hash": "0x" + "a" * 64}, "0x6000"),
        ({"number": "0x10", "hash": "0x1234"}, "0x6000"),
        ({"number": "0x10", "hash": "0x" + "a" * 64}, "0xzz"),
        ({"number": "0x10", "hash": "0x" + "a" * 64}, "0x"),
    ],
)
def test_registry_rejects_malformed_block_and_code(block, code):
    def handler(request):
        call = json.loads(request.content)
        result = {"eth_chainId": "0x1", "eth_getBlockByNumber": block, "eth_getCode": code}.get(
            call["method"]
        )
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": call["id"], "result": result})

    with pytest.raises(ChainPolicyError):
        is_allowed(
            rpc_url="https://rpc.example",
            chain_id=1,
            registry="0x" + "3" * 40,
            owner="0x" + "1" * 40,
            agent="0x" + "2" * 40,
            namespace="research",
            operation="read",
            transport=httpx.MockTransport(handler),
        )


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json=[]),
        httpx.Response(200, content=b" " * 1_048_577),
        httpx.Response(302, headers={"location": "https://other.example"}),
    ],
)
def test_registry_rpc_rejects_untrusted_responses(response):
    calls = []

    def handler(request):
        calls.append(request)
        return response

    with pytest.raises(ChainPolicyError):
        is_allowed(
            rpc_url="https://rpc.example",
            chain_id=1,
            registry="0x" + "3" * 40,
            owner="0x" + "1" * 40,
            agent="0x" + "2" * 40,
            namespace="research",
            operation="read",
            transport=httpx.MockTransport(handler),
        )
    assert len(calls) == 1
