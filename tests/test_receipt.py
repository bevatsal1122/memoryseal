import json

import httpx
import pytest
from eth_abi import encode
from eth_account import Account
from eth_utils import keccak

from memoryseal.onchain import ProtectedTransferClient, RpcError


def test_receipt_checks_status_context_and_canonical_block():
    agent = Account.create()
    executor, tx_hash, block_hash = "0x" + "1" * 40, "0x" + "2" * 64, "0x" + "3" * 64
    state = {"receipt": None, "block_hash": block_hash}

    def handler(request):
        call = json.loads(request.content)
        result = {
            "eth_chainId": "0x1",
            "eth_getTransactionReceipt": state["receipt"],
            "eth_getBlockByNumber": {"hash": state["block_hash"]},
            "eth_blockNumber": "0xc",
        }[call["method"]]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": call["id"], "result": result})

    client = ProtectedTransferClient(
        "https://rpc.example",
        agent.key,
        chain_id=1,
        executor=executor,
        max_gas_price_wei=1,
        transport=httpx.MockTransport(handler),
    )
    assert client.receipt(tx_hash)["status"] == "pending"
    state["receipt"] = {
        "transactionHash": tx_hash,
        "from": agent.address,
        "to": executor,
        "status": "0x1",
        "blockNumber": "0xa",
        "blockHash": block_hash,
    }
    assert client.receipt(tx_hash)["confirmations"] == 3
    assert client.receipt(tx_hash)["status"] == "success"
    owner, token, recipient = ["0x" + str(i) * 40 for i in (6, 7, 8)]
    topic = lambda addr: "0x" + addr[2:].lower().zfill(64)
    state["receipt"]["logs"] = [
        {
            "address": executor,
            "topics": [
                "0x"
                + keccak(
                    text="TransferExecuted(address,address,address,address,uint256,uint256)"
                ).hex(),
                topic(owner),
                topic(agent.address),
                topic(token),
            ],
            "data": "0x" + encode(["address", "uint256", "uint256"], [recipient, 100, 1]).hex(),
        }
    ]
    assert client.verify_transfer(
        tx_hash, owner=owner, token=token, recipient=recipient, amount=100, policy_version=1
    )["transfer_verified"]
    assert not client.verify_transfer(
        tx_hash, owner=owner, token=token, recipient=recipient, amount=101, policy_version=1
    )["transfer_verified"]
    state["receipt"]["status"] = "0x0"
    assert client.receipt(tx_hash)["status"] == "reverted"
    state["block_hash"] = "0x" + "4" * 64
    assert client.receipt(tx_hash)["status"] == "reorged"
    state["receipt"]["to"] = "0x" + "5" * 40
    with pytest.raises(RpcError, match="context"):
        client.receipt(tx_hash)
    client.close()
