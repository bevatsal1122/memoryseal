import pytest
from eth_account import Account

from memoryseal.signatures import InvalidSignature, sign_request, verify_request


def test_signature_binds_body_target_audience_and_time():
    account = Account.create()
    fields = {
        "audience": "local.example",
        "method": "POST",
        "target": "/memory/write",
        "body": b'{"content":"hello"}',
        "timestamp": 1000,
        "nonce": "a" * 32,
    }
    signature = sign_request(account.key, **fields)
    assert verify_request(address=account.address, signature=signature, now=1000, **fields)
    for change in (
        {"body": b"{}"},
        {"target": "/capabilities/grant"},
        {"audience": "other.example"},
    ):
        with pytest.raises(InvalidSignature):
            verify_request(
                address=account.address, signature=signature, now=1000, **(fields | change)
            )
    with pytest.raises(InvalidSignature):
        verify_request(address=account.address, signature=signature, now=1301, **fields)
