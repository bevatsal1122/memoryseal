import base64
import hashlib
import json
import sys
from pathlib import Path

import httpx
import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from memoryseal.bridge_runner import BridgeError
from memoryseal.bridge_transport import BridgeTransport
from memoryseal.inference import InferenceError, ZeroGClassifier
from memoryseal.zero_g_verification import (
    verify_bridge_binding,
    verify_bridge_challenge,
    verify_bridge_receipt,
)

PROVIDER = "0x" + "1" * 40
SIGNER = "0x" + "2" * 40
ENDPOINT = "https://provider.example"


def test_bridge_receipt_checks_scheme_and_pinned_signer():
    account, other = Account.create(), Account.create()
    digest = "cd267304498951f9045bd85577a28b1c15f1a1c287987fdcedd81a62e8f507fc"
    text = f"zg-sig-v1/e2ee-ct:{digest}:{digest}"
    signature = Account.sign_message(encode_defunct(text=text), account.key).signature.hex()
    receipt = {"text": text, "signature": "0x" + signature.removeprefix("0x")}
    assert verify_bridge_receipt(receipt, account.address)
    assert not verify_bridge_receipt(receipt, other.address)
    assert not verify_bridge_receipt(
        {**receipt, "text": text.replace("e2ee-ct", "plain")}, account.address
    )
    assert not verify_bridge_receipt({**receipt, "text": text[:-1] + "d"}, account.address)


def test_bridge_binding_recomputes_known_answer_and_rejects_changes():
    # 0G proof/kat_test.go BindingHash("kat-aad", "kat-ct").
    digest = "cd267304498951f9045bd85577a28b1c15f1a1c287987fdcedd81a62e8f507fc"
    encode = lambda value: base64.b64encode(value).decode()
    parts = {
        "request_aad": encode(b"kat-aad"),
        "request_ciphertext": encode(b"kat-ct"),
        "response_aad": encode(b"kat-aad"),
        "response_ciphertext": encode(b"kat-ct"),
    }
    receipt = {"text": f"zg-sig-v1/e2ee-ct:{digest}:{digest}", "artifacts": parts}
    assert verify_bridge_binding(receipt)
    for name, original in list(parts.items()):
        parts[name] = encode(b"different")
        assert not verify_bridge_binding(receipt)
        parts[name] = original
    parts["request_aad"] = "***"
    assert not verify_bridge_binding(receipt)


def test_transport_checks_reported_receipt_without_claiming_attestation(monkeypatch):
    signer = Account.create()
    monkeypatch.setattr("memoryseal.bridge_transport.secrets.token_hex", lambda _: "a" * 64)
    aad = json.dumps(
        {
            "user": "memoryseal-" + "a" * 64,
            "temperature": 0,
            "model": "model",
            "_e2ee": {"sealed_fields": ["messages"]},
        }
    ).encode()
    digest = lambda a, c: hashlib.sha256(
        hashlib.sha256(a).digest() + hashlib.sha256(c).digest()
    ).hexdigest()
    text = f"zg-sig-v1/e2ee-ct:{digest(aad, b'kat-ct')}:{digest(b'kat-aad', b'kat-ct')}"
    signature = Account.sign_message(encode_defunct(text=text), signer.key).signature.hex()
    receipt = {
        "text": text,
        "signature": "0x" + signature.removeprefix("0x"),
        "artifacts": {
            "request_aad": base64.b64encode(aad).decode(),
            "request_ciphertext": base64.b64encode(b"kat-ct").decode(),
            "response_aad": base64.b64encode(b"kat-aad").decode(),
            "response_ciphertext": base64.b64encode(b"kat-ct").decode(),
        },
    }
    analysis = {
        "category": "observation",
        "risk": "low",
        "suspicious_instruction": False,
        "conflicts_with": [],
        "recommendation": "accept",
    }
    bridge_inputs = []

    def mock_bridge(_path, _digest, request, **_kwargs):
        bridge_inputs.append(request)
        return {
            "provider": PROVIDER,
            "body": {"choices": [{"message": {"content": json.dumps(analysis)}}]},
            "response_key": "key",
            "receipt": receipt,
        }

    monkeypatch.setattr(
        "memoryseal.bridge_transport.run_bridge",
        mock_bridge,
    )
    bridge = BridgeTransport(
        Path("/trusted/bridge"),
        "a" * 64,
        "testnet",
        provider=PROVIDER,
        signer=signer.address,
        endpoint=ENDPOINT,
    )
    classifier = ZeroGClassifier("secret", "model", provider=PROVIDER, transport=bridge)
    try:
        assert (
            classifier.analyze(
                content="private", source_type="agent", policy_context=""
            ).router_verified
            is None
        )
        assert bridge.receipt_signer_matched is True
        assert bridge.receipt_binding_matched is True
        assert bridge.receipt_challenge_matched is True
        bridge.recipient_key = "11" * 32
        monkeypatch.setattr("memoryseal.bridge_transport.verify_bridge_request", lambda *_: True)
        receipt.update(
            request_seed="unused",
            request_plaintext="unused",
            request_recipient_key=base64.b64encode(bytes.fromhex(bridge.recipient_key)).decode(),
        )
        classifier.analyze(content="private", source_type="agent", policy_context="")
        assert bridge_inputs[-1]["recipient_key"] == bridge.recipient_key
        receipt["request_recipient_key"] = base64.b64encode(b"x" * 32).decode()
        with pytest.raises(InferenceError):
            classifier.analyze(content="private", source_type="agent", policy_context="")
        for field in ("request_seed", "request_plaintext", "request_recipient_key"):
            del receipt[field]
        with pytest.raises(InferenceError):
            classifier.analyze(content="private", source_type="agent", policy_context="")
        bridge.recipient_key = None
        receipt["response_private_key"] = base64.b64encode(b"x" * 32).decode()
        with pytest.raises(InferenceError):
            classifier.analyze(content="private", source_type="agent", policy_context="")
        assert bridge.receipt_response_choices_matched is None
        del receipt["response_private_key"]
        receipt["request_seed"] = base64.b64encode(b"x" * 32).decode()
        with pytest.raises(InferenceError):
            classifier.analyze(content="private", source_type="agent", policy_context="")
        assert bridge.receipt_request_messages_matched is None
        del receipt["request_seed"]
        receipt["artifacts"]["request_aad"] = base64.b64encode(b"altered").decode()
        with pytest.raises(InferenceError):
            classifier.analyze(content="private", source_type="agent", policy_context="")
        assert bridge.receipt_binding_matched is None
        receipt["artifacts"]["request_aad"] = base64.b64encode(aad).decode()
        monkeypatch.setattr("memoryseal.bridge_transport.secrets.token_hex", lambda _: "b" * 64)
        with pytest.raises(InferenceError):
            classifier.analyze(content="private", source_type="agent", policy_context="")
        assert bridge.receipt_challenge_matched is None
    finally:
        classifier.close()


def test_bridge_challenge_rejects_unbound_or_duplicate_user():
    challenge = "memoryseal-" + "a" * 64

    def receipt(aad):
        return {"artifacts": {"request_aad": base64.b64encode(aad.encode()).decode()}}

    valid = json.dumps(
        {
            "user": challenge,
            "temperature": 0,
            "model": "model",
            "_e2ee": {"sealed_fields": ["messages"]},
        }
    )
    assert verify_bridge_challenge(receipt(valid), challenge, temperature=0, model="model")
    assert not verify_bridge_challenge(receipt(valid), challenge, temperature=0, model="other")
    unbound_model = json.dumps(
        {
            "user": challenge,
            "temperature": 0,
            "model": "model",
            "_e2ee": {"sealed_fields": ["messages"], "unbound_fields": ["model"]},
        }
    )
    assert not verify_bridge_challenge(
        receipt(unbound_model), challenge, temperature=0, model="model"
    )
    unbound = json.dumps(
        {
            "user": challenge,
            "temperature": 0,
            "model": "model",
            "_e2ee": {"sealed_fields": ["messages"], "unbound_fields": ["user"]},
        }
    )
    assert not verify_bridge_challenge(receipt(unbound), challenge, temperature=0, model="model")
    unsealed = json.dumps(
        {
            "user": challenge,
            "temperature": 0,
            "model": "model",
            "_e2ee": {"sealed_fields": ["tools"]},
        }
    )
    assert not verify_bridge_challenge(receipt(unsealed), challenge, temperature=0, model="model")
    exposed = json.dumps(
        {
            "user": challenge,
            "temperature": 0,
            "model": "model",
            "messages": ["private"],
            "_e2ee": {"sealed_fields": ["messages"]},
        }
    )
    assert not verify_bridge_challenge(receipt(exposed), challenge, temperature=0, model="model")
    duplicate = (
        '{"user":"other","user":"'
        + challenge
        + '","temperature":0,"model":"model","_e2ee":{"sealed_fields":["messages"]}}'
    )
    assert not verify_bridge_challenge(receipt(duplicate), challenge, temperature=0, model="model")
    for altered in (1, True, None):
        bad = json.dumps(
            {
                "user": challenge,
                "temperature": altered,
                "model": "model",
                "_e2ee": {"sealed_fields": ["messages"]},
            }
        )
        assert not verify_bridge_challenge(receipt(bad), challenge, temperature=0, model="model")
    unbound_temperature = json.dumps(
        {
            "user": challenge,
            "temperature": 0,
            "model": "model",
            "_e2ee": {"sealed_fields": ["messages"], "unbound_fields": ["temperature"]},
        }
    )
    assert not verify_bridge_challenge(
        receipt(unbound_temperature), challenge, temperature=0, model="model"
    )


def transport():
    return BridgeTransport(
        Path("/trusted/bridge"),
        "a" * 64,
        "testnet",
        provider=PROVIDER,
        signer=SIGNER,
        endpoint=ENDPOINT,
    )


def test_classifier_uses_bridge_without_asserting_verified_provider(monkeypatch):
    def run(binary, pin, request, *, timeout):
        assert binary == Path("/trusted/bridge")
        assert pin == "a" * 64
        assert request["network"] == "testnet"
        assert request["api_key"] == "secret"
        assert (request["provider"], request["signer"], request["endpoint"]) == (
            PROVIDER,
            SIGNER,
            ENDPOINT,
        )
        assert request["body"]["verify_tee"] is True
        assert "private content" in request["body"]["messages"][1]["content"]
        analysis = {
            "category": "observation",
            "risk": "low",
            "suspicious_instruction": False,
            "conflicts_with": [],
            "recommendation": "accept",
        }
        return {
            "body": {"choices": [{"message": {"content": json.dumps(analysis)}}]},
            "response_key": "key",
            "provider": PROVIDER,
        }

    monkeypatch.setattr("memoryseal.bridge_transport.run_bridge", run)
    classifier = ZeroGClassifier("secret", "model", provider=PROVIDER, transport=transport())
    try:
        result = classifier.analyze(
            content="private content", source_type="agent", policy_context=""
        )
        assert result.analysis.category == "observation"
        assert result.response_key == "key"
        assert result.router_verified is None
    finally:
        classifier.close()


@pytest.mark.parametrize("provider", [PROVIDER[2:], "0X" + PROVIDER[2:]])
def test_classifier_normalizes_provider_pin_before_bridge(provider, monkeypatch):
    calls = []

    def run(binary, pin, request, *, timeout):
        calls.append(request)
        return {
            "body": {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "category": "observation",
                                    "risk": "low",
                                    "suspicious_instruction": False,
                                    "conflicts_with": [],
                                    "recommendation": "accept",
                                }
                            )
                        }
                    }
                ]
            },
            "response_key": "key",
            "provider": PROVIDER,
        }

    monkeypatch.setattr("memoryseal.bridge_transport.run_bridge", run)
    classifier = ZeroGClassifier("secret", "model", provider=provider, transport=transport())
    try:
        classifier.analyze(content="private", source_type="agent", policy_context="")
        assert len(calls) == 1
        assert calls[0]["provider"] == PROVIDER
    finally:
        classifier.close()


def test_mismatched_provider_is_refused_without_calling_bridge(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("bridge must not receive a request with an unsupported provider pin")

    monkeypatch.setattr("memoryseal.bridge_transport.run_bridge", fail)
    classifier = ZeroGClassifier(
        "secret",
        "model",
        provider="0x" + "3" * 40,
        transport=transport(),
    )
    try:
        with pytest.raises(InferenceError):
            classifier.analyze(content="private", source_type="agent", policy_context="")
    finally:
        classifier.close()


def test_bridge_failure_is_reported_as_inference_failure(monkeypatch):
    def fail(*args, **kwargs):
        raise BridgeError("failed")

    monkeypatch.setattr("memoryseal.bridge_transport.run_bridge", fail)
    classifier = ZeroGClassifier("secret", "model", provider=PROVIDER, transport=transport())
    try:
        with pytest.raises(InferenceError):
            classifier.analyze(content="private", source_type="agent", policy_context="")
    finally:
        classifier.close()


@pytest.mark.parametrize("reported", [None, "0x" + "3" * 40])
def test_bridge_must_report_the_configured_provider(monkeypatch, reported):
    monkeypatch.setattr(
        "memoryseal.bridge_transport.run_bridge",
        lambda *_args, **_kwargs: {"provider": reported, "body": {}, "response_key": "key"},
    )
    bridge = transport()
    classifier = ZeroGClassifier("secret", "model", provider=PROVIDER, transport=bridge)
    try:
        with pytest.raises(InferenceError):
            classifier.analyze(content="private", source_type="agent", policy_context="")
        assert bridge.reported_provider is None
    finally:
        classifier.close()


def test_transport_rejects_other_destinations(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("bridge must not run")

    monkeypatch.setattr("memoryseal.bridge_transport.run_bridge", fail)
    bridge_transport = transport()
    request = httpx.Request(
        "POST",
        "https://attacker.example/v1/chat/completions",
        headers={"Authorization": "Bearer secret", "X-0G-Provider-Trust-Mode": "private"},
        json={},
    )
    with pytest.raises(httpx.RequestError):
        bridge_transport.handle_request(request)


def test_classifier_reaches_pinned_subprocess(tmp_path):
    binary = tmp_path / "bridge"
    binary.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        "r = json.load(sys.stdin)\n"
        f"assert r['provider'] == {PROVIDER!r}\n"
        f"assert r['signer'] == {SIGNER!r}\n"
        f"assert r['endpoint'] == {ENDPOINT!r}\n"
        "assert r['api_key'] == 'secret'\n"
        "assert 'private content' in r['body']['messages'][1]['content']\n"
        "analysis = {'category':'observation','risk':'low','suspicious_instruction':False,"
        "'conflicts_with':[],'recommendation':'accept'}\n"
        "print(json.dumps({'status':200,'response_key':'key','provider':r['provider'],'body':"
        "{'choices':[{'message':{'content':json.dumps(analysis)}}]}}))\n"
    )
    binary.chmod(0o700)
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    classifier = ZeroGClassifier(
        "secret",
        "model",
        provider=PROVIDER,
        transport=BridgeTransport(
            binary, digest, "testnet", provider=PROVIDER, signer=SIGNER, endpoint=ENDPOINT
        ),
    )
    try:
        result = classifier.analyze(
            content="private content", source_type="agent", policy_context=""
        )
        assert result.analysis.category == "observation"
        assert result.router_verified is None
    finally:
        classifier.close()


@pytest.mark.parametrize(
    "headers",
    [
        {"X-0G-Provider-Trust-Mode": "private"},
        {"X-0G-Provider-Trust-Mode": "private", "X-0G-Provider-Address": PROVIDER},
        {
            "X-0G-Provider-Trust-Mode": "private",
            "X-0G-Provider-Address": PROVIDER,
            "X-0G-Provider-Allow-Fallbacks": "true",
        },
    ],
)
def test_unpinned_or_fallback_request_rejected_before_subprocess(headers, monkeypatch):
    monkeypatch.setattr(
        "memoryseal.bridge_transport.run_bridge", lambda *a, **kw: pytest.fail("executed")
    )
    request = httpx.Request(
        "POST",
        "https://router-api-testnet.integratenetwork.work/v1/chat/completions",
        headers={"Authorization": "Bearer secret", **headers},
        json={},
    )
    with pytest.raises(httpx.RequestError):
        transport().handle_request(request)
