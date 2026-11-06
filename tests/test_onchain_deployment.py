import json

import httpx
import pytest
from eth_abi import encode

from memoryseal.onchain import RpcError
from memoryseal.onchain_deployment import observe_deployment


def test_deployment_observation_rejects_reorganization():
    registry, executor = "0x" + "1" * 40, "0x" + "2" * 40

    def handler(request):
        call = json.loads(request.content)
        result = {
            1: "0xaa36a7",
            2: {"number": "0x10", "hash": "0xaaa"},
            3: "0x60",
            4: "0x60",
            5: "0x" + encode(["address"], [registry]).hex(),
            6: {"hash": "0xbbb"},
        }[call["id"]]
        return httpx.Response(200, json={"id": call["id"], "result": result})

    with pytest.raises(RpcError, match="reorganized"):
        observe_deployment(
            rpc_url="https://rpc.example",
            chain_id=11155111,
            registry=registry,
            executor=executor,
            transport=httpx.MockTransport(handler),
        )


def test_runtime_comparison_reports_missing_and_malformed_artifact(tmp_path, monkeypatch):
    from memoryseal.contract_artifacts import matches_local_runtime

    monkeypatch.setattr("memoryseal.contract_artifacts.ARTIFACTS", tmp_path)
    registry = "0x" + "1" * 40
    assert matches_local_runtime("ProtectedTransfer", "0x00", registry) is None
    (tmp_path / "ProtectedTransfer.json").write_text(
        '{"deployedBytecode":"0x00","immutableReferences":{}}'
    )
    assert matches_local_runtime("ProtectedTransfer", "0x00", registry) is None
