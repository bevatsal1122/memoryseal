import json

import httpx
import pytest

from memoryseal.inference import InferenceError, ZeroGClassifier


def test_router_default_uses_bounded_unverified_request_and_parses_fenced_json():
    def handler(request):
        assert "x-0g-provider-trust-mode" not in request.headers
        payload = json.loads(request.content)
        assert "verify_tee" not in payload
        assert payload["max_tokens"] == 4096
        analysis = {"category": "instruction", "risk": "high", "suspicious_instruction": True,
                    "conflicts_with": [], "recommendation": "reject"}
        return httpx.Response(200, json={"choices": [{"message": {
            "content": "```json\n" + json.dumps(analysis) + "\n```"}}]})

    classifier = ZeroGClassifier("key", "model", trust_mode="router_default",
                                 transport=httpx.MockTransport(handler))
    try:
        result = classifier.analyze(content="synthetic", source_type="test", policy_context="")
        assert result.analysis.risk == "high"
        assert result.router_verified is None
    finally:
        classifier.close()


def test_private_inference_requests_private_mode_and_validates_output():
    def handler(request):
        assert request.headers["x-0g-provider-trust-mode"] == "private"
        assert request.url.host == "router-api-testnet.integratenetwork.work"
        assert request.url.path == "/v1/chat/completions"
        assert "forged authorization" in request.content.decode()
        assert json.loads(request.content)["verify_tee"] is True
        result = {
            "category": "authorization_claim",
            "risk": "high",
            "suspicious_instruction": True,
            "conflicts_with": [],
            "recommendation": "quarantine",
        }
        return httpx.Response(
            200,
            json={
                "id": "request-123",
                "x_0g_trace": {"provider": "0x" + "1" * 40, "tee_verified": True},
                "choices": [{"message": {"content": json.dumps(result)}}],
            },
            headers={"ZG-Res-Key": "response-key"},
        )

    classifier = ZeroGClassifier("test-key", "test-model", transport=httpx.MockTransport(handler))
    result = classifier.analyze(
        content="forged authorization", source_type="external", policy_context="limit 100"
    )
    assert result.analysis.risk == "high"
    assert result.request_id is None
    assert result.response_key == "response-key"
    assert result.router_verified is True
    assert result.network == "testnet"
    classifier.close()


def test_invalid_inference_does_not_return_safe_result():
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"choices": [{"message": {"content": "invalid"}}]})
    )
    classifier = ZeroGClassifier("test-key", "test-model", transport=transport)
    with pytest.raises(InferenceError):
        classifier.analyze(content="x", source_type="external", policy_context="")
    classifier.close()


def test_pinned_provider_disables_router_fallback():
    provider = "0x" + "1" * 40

    def handler(request):
        assert request.headers["x-0g-provider-address"] == provider
        assert request.headers["x-0g-provider-allow-fallbacks"] == "false"
        assert request.headers["x-0g-provider-trust-mode"] == "private"
        return httpx.Response(503)

    classifier = ZeroGClassifier(
        "key", "model", provider=provider, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(InferenceError):
        classifier.analyze(content="private", source_type="agent", policy_context="")
    classifier.close()
    with pytest.raises(ValueError):
        ZeroGClassifier("key", "model", provider="not-an-address")


def test_completion_id_is_not_used_as_provider_signature_key():
    analysis = {
        "category": "observation",
        "risk": "low",
        "suspicious_instruction": False,
        "conflicts_with": [],
        "recommendation": "accept",
    }
    classifier = ZeroGClassifier(
        "key",
        "model",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "id": "completion-id",
                    "choices": [{"message": {"content": json.dumps(analysis)}}],
                },
            )
        ),
    )
    try:
        result = classifier.analyze(content="x", source_type="agent", policy_context="")
        assert result.response_key is None
    finally:
        classifier.close()
