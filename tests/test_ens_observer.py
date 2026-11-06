import json
from types import SimpleNamespace

import pytest

from memoryseal.config import settings
from memoryseal.ens_observer import EnsObservationError, observe


def test_observer_validates_rpc_output_and_hides_other_secrets(monkeypatch):
    monkeypatch.setattr(settings, "ens_rpc_url", "https://rpc.example")
    monkeypatch.setattr(settings, "ens_network", "sepolia")
    monkeypatch.setenv("MEMORYSEAL_ZERO_G_API_KEY", "private")
    address = "0x" + "1" * 40
    data = {
        "name": "agent.example.eth",
        "resolvedAddress": address,
        "matches": True,
        "chainId": 11155111,
        "blockNumber": "42",
        "blockHash": "0x" + "a" * 64,
    }

    def runner(*_args, **kwargs):
        assert "MEMORYSEAL_ZERO_G_API_KEY" not in kwargs["env"]
        return SimpleNamespace(stdout=json.dumps(data))

    assert observe("agent.example.eth", address, runner=runner)["matches"]
    data["matches"] = False
    with pytest.raises(EnsObservationError):
        observe("agent.example.eth", address, runner=runner)
