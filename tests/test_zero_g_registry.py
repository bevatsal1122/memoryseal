import json

import httpx
from eth_abi import encode
from eth_account import Account

from memoryseal.zero_g_registry import NETWORKS, SERVICE_TYPE, registry_pins_match


def test_registry_matching_checks_chain_signer_url_and_reorg():
    provider, signer = Account.create().address, Account.create().address
    url = "https://provider.example"
    service = [provider, "chatbot", url, 0, 0, 1, "model", "TeeML", "{}", signer, True]
    calls = []

    def transport(values, *, chain_id=16602, reorg=False):
        def handler(request):
            call = json.loads(request.content)
            method = call["method"]
            calls.append(method)
            if method == "eth_chainId":
                result = hex(chain_id)
            elif method == "eth_getBlockByNumber":
                result = {
                    "number": "0x10",
                    "hash": "0x" + ("b" if reorg and call["id"] == 5 else "a") * 64,
                }
            elif method == "eth_getCode":
                result = "0x1234"
            elif method == "eth_call":
                assert call["params"][0]["to"] == NETWORKS["testnet"][1]
                assert call["params"][1] == "0x10"
                result = "0x" + encode([SERVICE_TYPE], [values]).hex()
            else:
                raise AssertionError(method)
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": call["id"], "result": result})

        return httpx.MockTransport(handler)

    args = {
        "rpc_url": "https://rpc.example",
        "network": "testnet",
        "provider": provider,
        "signer": signer,
        "base_url": url,
    }
    assert registry_pins_match(**args, transport=transport(service))
    assert not registry_pins_match(**args, transport=transport(service, reorg=True))
    assert not registry_pins_match(**args, transport=transport(service, chain_id=1))
    for index, value in [
        (2, "https://other.example"),
        (7, "OpML"),
        (10, False),
        (9, Account.create().address),
    ]:
        changed = service.copy()
        changed[index] = value
        assert not registry_pins_match(**args, transport=transport(changed))
    target = Account.create().address
    separated = service.copy()
    separated[8] = json.dumps(
        {"TargetSeparated": True, "ProviderType": "decentralized", "TargetTeeAddress": target}
    )
    assert not registry_pins_match(**args, transport=transport(separated))
    assert registry_pins_match(**(args | {"signer": target}), transport=transport(separated))


def test_registry_rejects_oversized_and_non_object_responses():
    import gzip

    args = {
        "rpc_url": "https://rpc.example",
        "network": "testnet",
        "provider": Account.create().address,
        "signer": Account.create().address,
        "base_url": "https://provider.example",
    }
    bodies = [
        httpx.Response(200, content=b" " * 1_048_577),
        httpx.Response(
            200, content=gzip.compress(b" " * 1_048_577), headers={"Content-Encoding": "gzip"}
        ),
        httpx.Response(200, json=[]),
    ]
    for response in bodies:
        assert not registry_pins_match(
            **args, transport=httpx.MockTransport(lambda _request, result=response: result)
        )


def test_registry_rejects_malformed_block_and_contract_code():
    provider, signer = Account.create().address, Account.create().address
    service = [
        provider,
        "chatbot",
        "https://provider.example",
        0,
        0,
        1,
        "model",
        "TeeML",
        "{}",
        signer,
        True,
    ]
    args = {
        "rpc_url": "https://rpc.example",
        "network": "testnet",
        "provider": provider,
        "signer": signer,
        "base_url": "https://provider.example",
    }

    def observe(*, number="0x10", block_hash="0x" + "a" * 64, code="0x1234", final_number=None):
        def handler(request):
            call = json.loads(request.content)
            method = call["method"]
            if method == "eth_chainId":
                result = hex(16602)
            elif method == "eth_getBlockByNumber":
                result = {
                    "number": final_number if call["id"] == 5 and final_number else number,
                    "hash": block_hash,
                }
            elif method == "eth_getCode":
                result = code
            else:
                result = "0x" + encode([SERVICE_TYPE], [service]).hex()
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": call["id"], "result": result})

        return registry_pins_match(**args, transport=httpx.MockTransport(handler))

    assert observe()
    assert not observe(number="latest")
    assert not observe(number="0x01")
    assert not observe(block_hash="0x1234")
    assert not observe(code="0xzz")
    assert not observe(code="0x1")
    assert not observe(final_number="0x11")
