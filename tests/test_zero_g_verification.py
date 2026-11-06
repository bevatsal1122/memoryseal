import httpx
from eth_account import Account
from eth_account.messages import encode_defunct

from memoryseal.zero_g_verification import verify_pinned_response


def test_pinned_signature_requires_exact_response_and_expected_provider():
    signer = Account.create()
    provider = Account.create().address
    text = '{"risk":"low"}'
    signature = Account.sign_message(encode_defunct(text=text), signer.key).signature.hex()
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "provider.example"
        assert request.headers.get("authorization") is None
        assert request.url.params["model"] == "model-name"
        return httpx.Response(200, json={"text": text, "signature": signature})

    args = {
        "provider": provider,
        "response_key": "response-1",
        "response_text": text,
        "model": "model-name",
        "expected_provider": provider,
        "signer": signer.address,
        "base_url": "https://provider.example",
        "transport": httpx.MockTransport(handler),
    }
    assert verify_pinned_response(**args)
    assert not verify_pinned_response(**(args | {"response_text": text + " "}))
    assert not verify_pinned_response(**(args | {"signer": Account.create().address}))
    assert not verify_pinned_response(**(args | {"provider": Account.create().address}))
    assert not verify_pinned_response(**(args | {"base_url": "http://provider.example"}))
    assert len(calls) == 3
    invalid = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"text": text, "signature": "0x00"})
    )
    assert not verify_pinned_response(**(args | {"transport": invalid}))


def test_versioned_e2ee_receipt_is_not_mistaken_for_legacy_text_signature():
    signer = Account.create()
    provider = Account.create().address
    signed_text = "zg-sig-v1/e2ee-ct:" + "a" * 64 + ":" + "b" * 64
    signature = Account.sign_message(encode_defunct(text=signed_text), signer.key).signature.hex()
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"text": signed_text, "signature": signature})
    )
    assert not verify_pinned_response(
        provider=provider,
        response_key="key",
        response_text='{"risk":"low"}',
        model="model",
        expected_provider=provider,
        signer=signer.address,
        base_url="https://provider.example",
        transport=transport,
    )
