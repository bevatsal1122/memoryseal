import pytest
from pydantic import ValidationError

from memoryseal.api import OnchainGrantObservation, OnchainObservation, TokenBalanceObservation

ADDRESS = "0x" + "1" * 40
HASH = "0x" + "a" * 64


@pytest.mark.parametrize(
    "model,base,field",
    [
        (
            OnchainObservation,
            {
                "agent_id": "a",
                "transaction_hash": HASH,
                "token": ADDRESS,
                "recipient": ADDRESS,
                "amount": "1",
                "policy_version": 1,
            },
            "policy_version",
        ),
        (
            OnchainGrantObservation,
            {
                "agent_id": "a",
                "transaction_hash": HASH,
                "token": ADDRESS,
                "max_amount": "1",
                "expires_at": 1,
                "policy_version": 1,
            },
            "expires_at",
        ),
        (
            OnchainGrantObservation,
            {
                "agent_id": "a",
                "transaction_hash": HASH,
                "token": ADDRESS,
                "max_amount": "1",
                "expires_at": 1,
                "policy_version": 1,
            },
            "policy_version",
        ),
        (
            TokenBalanceObservation,
            {"token": ADDRESS, "recipient": ADDRESS, "block_number": 1},
            "block_number",
        ),
    ],
)
@pytest.mark.parametrize("invalid", [True, 1.0, "1.0"])
def test_observation_integer_fields_reject_coercion(model, base, field, invalid):
    with pytest.raises(ValidationError):
        model.model_validate({**base, field: invalid})
    assert getattr(model.model_validate({**base, field: "1"}), field) == 1
