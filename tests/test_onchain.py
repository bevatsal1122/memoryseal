import json

import httpx
import pytest
from eth_account import Account
from eth_utils import keccak

from memoryseal.onchain import ProtectedTransferClient, RpcError


def test_protected_transfer_signed_by_agent_and_checks_chain():
    agent = Account.create()
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        method, params = payload["method"], payload["params"]
        calls.append(method)
        values = {
            "eth_chainId": "0xaa36a7",
            "eth_getCode": "0x6000",
            "eth_getTransactionCount": "0x0",
            "eth_gasPrice": "0x1",
            "eth_estimateGas": "0x186a0",
        }
        if method == "eth_sendRawTransaction":
            raw = bytes.fromhex(params[0][2:])
            assert Account.recover_transaction(raw) == agent.address
            result = "0x" + keccak(raw).hex()
        else:
            result = values[method]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": result})

    client = ProtectedTransferClient(
        "https://rpc.example",
        agent.key,
        chain_id=11155111,
        executor="0x" + "1" * 40,
        max_gas_price_wei=2,
        transport=httpx.MockTransport(handler),
    )
    tx = client.execute(
        owner="0x" + "2" * 40,
        token="0x" + "3" * 40,
        recipient="0x" + "4" * 40,
        amount=100,
        policy_version=1,
    )
    assert tx.startswith("0x")
    assert calls[-1] == "eth_sendRawTransaction"
    client.chain_id = 1
    with pytest.raises(RpcError, match="chain ID"):
        client.execute(
            owner="0x" + "2" * 40,
            token="0x" + "3" * 40,
            recipient="0x" + "4" * 40,
            amount=100,
            policy_version=1,
        )
    assert calls[-1] == "eth_chainId"
    client.close()


@pytest.mark.parametrize("failure", ["timeout", "wrong_hash", "invalid_response", "rpc_error"])
def test_ambiguous_submission_exposes_locally_derived_hash_without_retry(failure):
    from memoryseal.onchain import SubmissionOutcomeUnknown

    agent = Account.create()
    submitted = []

    def handler(request):
        call = json.loads(request.content)
        method = call["method"]
        if method == "eth_sendRawTransaction":
            raw = bytes.fromhex(call["params"][0][2:])
            submitted.append(raw)
            if failure == "timeout":
                raise httpx.ReadTimeout("lost response", request=request)
            if failure == "invalid_response":
                return httpx.Response(200, json=[], request=request)
            if failure == "rpc_error":
                return httpx.Response(200, json={"id": call["id"], "error": {"code": -32000}})
            result = "0x" + "f" * 64
        else:
            result = {
                "eth_chainId": "0xaa36a7",
                "eth_getCode": "0x6000",
                "eth_getTransactionCount": "0x0",
                "eth_gasPrice": "0x1",
                "eth_estimateGas": "0x186a0",
            }[method]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": call["id"], "result": result})

    client = ProtectedTransferClient(
        "https://rpc.example",
        agent.key,
        chain_id=11155111,
        executor="0x" + "1" * 40,
        max_gas_price_wei=2,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(SubmissionOutcomeUnknown) as exc:
            client.execute(
                owner="0x" + "2" * 40,
                token="0x" + "3" * 40,
                recipient="0x" + "4" * 40,
                amount=100,
                policy_version=1,
            )
        assert len(submitted) == 1
        assert exc.value.transaction_hash == "0x" + keccak(submitted[0]).hex()
        assert Account.recover_transaction(submitted[0]) == agent.address
    finally:
        client.close()


def test_observe_owner_transfer_grant_checks_call_and_event():
    from eth_abi import encode

    from memoryseal.onchain import OnchainReceiptVerifier

    owner, agent, token, registry = ("0x" + c * 40 for c in "1234")
    tx_hash, block_hash = "0x" + "a" * 64, "0x" + "b" * 64
    calldata = (
        "0x"
        + (
            keccak(text="setTransferCapability(address,address,uint256,uint64)")[:4]
            + encode(["address", "address", "uint256", "uint64"], [agent, token, 2000, 0])
        ).hex()
    )
    topics = [
        "0x"
        + keccak(
            text="TransferCapabilityChanged(address,address,address,uint256,uint64,bool,uint256)"
        ).hex(),
        *("0x" + address[2:].zfill(64) for address in (owner, agent, token)),
    ]
    transaction = {
        "hash": tx_hash,
        "from": owner,
        "to": registry,
        "input": calldata,
        "value": "0x0",
        "blockHash": block_hash,
        "blockNumber": "0x1",
    }
    receipt = {
        "transactionHash": tx_hash,
        "from": owner,
        "to": registry,
        "status": "0x1",
        "blockHash": block_hash,
        "blockNumber": "0x1",
        "logs": [
            {
                "address": registry,
                "topics": topics,
                "data": "0x"
                + encode(["uint256", "uint64", "bool", "uint256"], [2000, 0, False, 2]).hex(),
            }
        ],
    }
    values = {
        "eth_chainId": "0xaa36a7",
        "eth_getTransactionReceipt": receipt,
        "eth_getTransactionByHash": transaction,
        "eth_getBlockByNumber": {"hash": block_hash},
        "eth_blockNumber": "0x1",
    }

    def handler(request):
        call = json.loads(request.content)
        return httpx.Response(200, json={"id": call["id"], "result": values[call["method"]]})

    verifier = OnchainReceiptVerifier(
        "https://rpc.example",
        owner,
        chain_id=11155111,
        executor=registry,
        transport=httpx.MockTransport(handler),
    )
    try:
        args = {"agent": agent, "token": token, "max_amount": 2000, "expires_at": 0, "version": 2}
        assert verifier.verify_transfer_grant(tx_hash, **args)["grant_verified"] is True
        assert (
            verifier.verify_transfer_grant(tx_hash, **{**args, "version": 3})["grant_verified"]
            is False
        )
        transaction["from"] = agent
        assert verifier.verify_transfer_grant(tx_hash, **args)["grant_verified"] is False
    finally:
        verifier.close()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b" " * 1_048_577),
        httpx.Response(200, json=[]),
        httpx.Response(302, headers={"location": "https://other.example"}),
    ],
)
def test_onchain_rpc_fails_closed_for_untrusted_response(response):
    calls = []

    def handler(request):
        calls.append(request)
        return response

    client = ProtectedTransferClient(
        "https://rpc.example",
        Account.create().key,
        chain_id=1,
        executor="0x" + "1" * 40,
        max_gas_price_wei=1,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(RpcError):
            client.receipt("0x" + "a" * 64)
        assert len(calls) == 1
    finally:
        client.close()
