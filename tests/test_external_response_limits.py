"""Untrusted inference and signature responses must be bounded and fail closed."""

import gzip

import httpx
import pytest
from eth_account import Account

from memoryseal.inference import InferenceError, ZeroGClassifier
from memoryseal.zero_g_verification import verify_pinned_response


def test_classifier_rejects_oversized_decompressed_response():
    payload = gzip.compress(b" " * 1_048_577)
    client = ZeroGClassifier(
        "test",
        "model",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=payload, headers={"Content-Encoding": "gzip"}
            )
        ),
    )
    try:
        with pytest.raises(InferenceError):
            client.analyze(content="test", source_type="external", policy_context="")
    finally:
        client.close()


def test_oversized_signature_response_is_unverified():
    provider, signer = Account.create().address, Account.create().address
    assert not verify_pinned_response(
        provider=provider,
        response_key="test",
        response_text="test",
        model="model",
        expected_provider=provider,
        signer=signer,
        base_url="https://provider.example",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b" " * 1_048_577)
        ),
    )
