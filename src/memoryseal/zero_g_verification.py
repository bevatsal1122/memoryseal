"""Check legacy and bridge-reported receipts against operator-configured pins.

The legacy response-text check does not bind a request. Bridge checks use
bridge-reported artifacts and do not independently establish wire traffic,
plaintext binding, or attestation. Pins are trust assumptions.
"""

import base64
import binascii
import hashlib
import hmac
import json
import re
from urllib.parse import quote, urlsplit

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_keys.exceptions import BadSignature
from eth_utils import is_address
from eth_utils.exceptions import ValidationError

from memoryseal.http_limits import read_json_limited


def verify_bridge_receipt(receipt: object, signer: str) -> bool:
    """Check a bridge-reported signature, not its relationship to plaintext or attestation."""
    try:
        if (
            not isinstance(receipt, dict)
            or not {"text", "signature"} <= set(receipt)
            or set(receipt)
            - {
                "text",
                "signature",
                "artifacts",
                "response_private_key",
                "request_seed",
                "request_recipient_key",
                "request_plaintext",
            }
        ):
            return False
        text, signature = receipt["text"], receipt["signature"]
        if (
            not isinstance(text, str)
            or not re.fullmatch(r"zg-sig-v1/e2ee-ct:[0-9a-f]{64}:[0-9a-f]{64}", text)
            or not isinstance(signature, str)
            or not re.fullmatch(r"0x[0-9a-fA-F]{130}", signature)
            or not is_address(signer)
            or int(signer, 16) == 0
        ):
            return False
        recovered = Account.recover_message(encode_defunct(text=text), signature=signature)
        return recovered.lower() == signer.lower()
    except (ValueError, TypeError, BadSignature, ValidationError):
        return False


def verify_bridge_binding(receipt: object) -> bool:
    """Recompute signed hashes over bridge-reported bytes, not actual wire traffic."""
    try:
        if not isinstance(receipt, dict) or not isinstance(receipt.get("text"), str):
            return False
        artifacts = receipt.get("artifacts")
        names = ("request_aad", "request_ciphertext", "response_aad", "response_ciphertext")
        if not isinstance(artifacts, dict) or set(artifacts) != set(names):
            return False
        parts = []
        for name in names:
            encoded = artifacts[name]
            if not isinstance(encoded, str) or len(encoded) > 266_668:
                return False
            part = base64.b64decode(encoded, validate=True)
            if not part:
                return False
            parts.append(part)
        if sum(map(len, parts)) > 200_000:
            return False

        def binding(aad: bytes, ciphertext: bytes) -> str:
            return hashlib.sha256(
                hashlib.sha256(aad).digest() + hashlib.sha256(ciphertext).digest()
            ).hexdigest()

        expected = f"zg-sig-v1/e2ee-ct:{binding(*parts[:2])}:{binding(*parts[2:])}"
        return hmac.compare_digest(receipt["text"], expected)
    except (ValueError, TypeError, binascii.Error):
        return False


def verify_bridge_challenge(
    receipt: object, challenge: str, *, temperature: float, model: str
) -> bool:
    """Check the challenge and settings in bridge-reported, signed request AAD."""

    def unique_object(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate JSON key")
            obj[key] = value
        return obj

    try:
        if not re.fullmatch(r"memoryseal-[0-9a-f]{64}", challenge):
            return False
        encoded = receipt["artifacts"]["request_aad"]
        if not isinstance(encoded, str) or len(encoded) > 266_668:
            return False
        aad = json.loads(base64.b64decode(encoded, validate=True), object_pairs_hook=unique_object)
        if not isinstance(aad, dict) or aad.get("user") != challenge:
            return False
        metadata = aad.get("_e2ee")
        if not isinstance(metadata, dict):
            return False
        unbound = metadata.get("unbound_fields", [])
        sealed = metadata.get("sealed_fields")
        return (
            isinstance(unbound, list)
            and all(isinstance(item, str) for item in unbound)
            and "user" not in unbound
            and isinstance(sealed, list)
            and all(isinstance(item, str) for item in sealed)
            and "user" not in sealed
            and "temperature" not in unbound
            and "temperature" not in sealed
            and type(aad.get("temperature")) in (int, float)
            and aad["temperature"] == temperature
            and isinstance(model, str)
            and bool(model)
            and aad.get("model") == model
            and "model" not in unbound
            and "model" not in sealed
            and "messages" in sealed
            and "messages" not in aad
        )
    except (KeyError, TypeError, ValueError, binascii.Error):
        return False


def valid_pins(provider: str | None, signer: str | None, base_url: str | None) -> bool:
    if not provider or not signer or not base_url:
        return False
    try:
        url = urlsplit(base_url)
        return bool(
            url.scheme == "https"
            and url.hostname
            and not url.username
            and not url.password
            and not url.query
            and not url.fragment
            and is_address(provider)
            and is_address(signer)
            and int(provider, 16) != 0
            and int(signer, 16) != 0
        )
    except ValueError:
        return False


def verify_pinned_response(
    *,
    provider: str | None,
    response_key: str | None,
    response_text: str | None,
    model: str,
    expected_provider: str,
    signer: str,
    base_url: str,
    transport=None,
) -> bool:
    """Return false for missing, malformed, unavailable, or mismatched evidence."""
    try:
        if not valid_pins(expected_provider, signer, base_url):
            return False
        if not provider or provider.lower() != expected_provider.lower():
            return False
        if (
            not isinstance(response_key, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", response_key)
            or not isinstance(response_text, str)
        ):
            return False
        # The base URL is operator-configured. Neither the router nor the provider
        # chooses an outgoing host. The client does not follow redirects or inherit
        # the router's bearer token.
        endpoint = base_url.rstrip("/") + "/v1/proxy/signature/" + quote(response_key, safe="")
        with (
            httpx.Client(transport=transport, timeout=10, follow_redirects=False) as client,
            client.stream("GET", endpoint, params={"model": model}) as response,
        ):
            receipt = read_json_limited(response, max_bytes=1_048_576)
        if not isinstance(receipt, dict) or receipt.get("text") != response_text:
            return False
        signature = receipt.get("signature")
        if not isinstance(signature, str):
            return False
        recovered = Account.recover_message(encode_defunct(text=response_text), signature=signature)
        return recovered.lower() == signer.lower()
    except (
        httpx.HTTPError,
        ValueError,
        TypeError,
        KeyError,
        OverflowError,
        BadSignature,
        ValidationError,
    ):
        return False
