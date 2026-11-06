import httpx
import pytest
from eth_account import Account

from memoryseal.demo.transfer_context import parse_uint256
from memoryseal.onchain import ProtectedTransferClient


@pytest.mark.parametrize(
    "value", [True, False, 1.5, 2.0, "-1", "+1", "1.0", "", " 1", "９", 2**256]
)
def test_action_rejects_inexact_or_out_of_range_amounts(value):
    with pytest.raises(ValueError):
        parse_uint256(value)


def test_action_accepts_exact_integer_and_decimal_string():
    assert parse_uint256("2000000000000000000") == 2 * 10**18
    assert parse_uint256(42) == 42
    assert parse_uint256("0", allow_zero=True) == 0
    with pytest.raises(ValueError):
        parse_uint256("0")


@pytest.mark.parametrize(
    "changes",
    [
        {"amount": 1.5},
        {"amount": True},
        {"policy_version": False},
        {"max_gas": 300000.0},
        {"gas_limit": True},
        {"gas_limit": 20999},
    ],
)
def test_invalid_action_is_rejected_before_rpc(changes):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500)

    client = ProtectedTransferClient(
        "https://rpc.example",
        Account.create().key,
        chain_id=11155111,
        executor="0x" + "1" * 40,
        max_gas_price_wei=1,
        transport=httpx.MockTransport(handler),
    )
    args = {
        "owner": "0x" + "2" * 40,
        "token": "0x" + "3" * 40,
        "recipient": "0x" + "4" * 40,
        "amount": 10,
        "policy_version": 1,
    }
    try:
        with pytest.raises(ValueError):
            client.execute(**(args | changes))
        assert calls == []
    finally:
        client.close()
