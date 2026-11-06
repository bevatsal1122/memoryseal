"""Experimental classifier transport for an operator-trusted 0G bridge.

The bridge's output is not independent evidence of provider attestation.
"""

import base64
import hmac
import importlib.util
import json
import os
import re
import secrets
from pathlib import Path

import httpx

from memoryseal.bridge_response import verify_bridge_request, verify_bridge_response
from memoryseal.bridge_runner import BridgeError, run_bridge
from memoryseal.zero_g_verification import (
    valid_pins,
    verify_bridge_binding,
    verify_bridge_challenge,
    verify_bridge_receipt,
)


def bridge_configured(binary: str | None, digest: str | None, pins: tuple) -> bool:
    if not binary or not digest or not re.fullmatch(r"[a-f0-9]{64}", digest):
        return False
    path = Path(binary)
    return (
        path.is_absolute()
        and path.is_file()
        and os.access(path, os.X_OK)
        and valid_pins(*pins)
        and importlib.util.find_spec("pyhpke") is not None
    )


class BridgeTransport(httpx.BaseTransport):
    def __init__(
        self,
        binary: Path,
        sha256: str,
        network: str,
        *,
        provider: str,
        signer: str,
        endpoint: str,
        recipient_key: str | None = None,
        timeout: float = 120,
    ):
        if network not in ("testnet", "mainnet"):
            raise ValueError("unsupported 0G network")
        if not valid_pins(provider, signer, endpoint):
            raise ValueError("invalid 0G provider pins")
        if recipient_key is not None and (
            not isinstance(recipient_key, str)
            or not re.fullmatch(r"[0-9a-f]{64}", recipient_key)
            or int(recipient_key, 16) == 0
        ):
            raise ValueError("invalid 0G recipient key")
        self.binary = binary
        self.sha256 = sha256
        self.network = network
        self.timeout = timeout
        self.provider = "0x" + provider.removeprefix("0x").removeprefix("0X")
        self.signer = "0x" + signer.removeprefix("0x").removeprefix("0X")
        self.endpoint = endpoint
        self.recipient_key = recipient_key
        self.reported_provider = None
        self.receipt_signer_matched = None
        self.receipt_binding_matched = None
        self.receipt_challenge_matched = None
        self.receipt_response_choices_matched = None
        self.receipt_request_messages_matched = None

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.reported_provider = None
        self.receipt_signer_matched = None
        self.receipt_binding_matched = None
        self.receipt_challenge_matched = None
        self.receipt_response_choices_matched = None
        self.receipt_request_messages_matched = None
        hosts = {
            "testnet": "router-api-testnet.integratenetwork.work",
            "mainnet": "router-api.0g.ai",
        }
        auth = request.headers.get("authorization", "")
        if (
            request.method != "POST"
            or request.url.scheme != "https"
            or request.url.host != hosts[self.network]
            or request.url.port not in (None, 443)
            or request.url.path != "/v1/chat/completions"
            or request.url.query
            or request.headers.get("x-0g-provider-trust-mode") != "private"
            or request.headers.get("x-0g-provider-address", "").lower() != self.provider.lower()
            or request.headers.get("x-0g-provider-allow-fallbacks") != "false"
            or not auth.startswith("Bearer ")
            or not auth[7:]
        ):
            raise httpx.RequestError("unsupported bridge request", request=request)
        try:
            body = json.loads(request.content)
            if not isinstance(body, dict):
                raise TypeError("invalid request body")
            if "user" in body:
                raise ValueError("classifier request must not supply a user field")
            challenge = "memoryseal-" + secrets.token_hex(32)
            body["user"] = challenge
            bridge_input = {
                "network": self.network,
                "api_key": auth[7:],
                "body": body,
                "provider": self.provider,
                "signer": self.signer,
                "endpoint": self.endpoint,
            }
            if self.recipient_key is not None:
                bridge_input["recipient_key"] = self.recipient_key
            result = run_bridge(
                self.binary,
                self.sha256,
                bridge_input,
                timeout=self.timeout,
            )
            selected = result.get("provider")
            if not isinstance(selected, str) or selected.lower() != self.provider.lower():
                raise ValueError("bridge returned a mismatched provider")
            receipt = result.get("receipt")
            if receipt is not None and not verify_bridge_receipt(receipt, self.signer):
                raise ValueError("bridge returned an invalid receipt signature")
            has_artifacts = isinstance(receipt, dict) and "artifacts" in receipt
            if has_artifacts and not verify_bridge_binding(receipt):
                raise ValueError("bridge returned inconsistent receipt artifacts")
            if has_artifacts and not verify_bridge_challenge(
                receipt, challenge, temperature=body.get("temperature"), model=body.get("model")
            ):
                raise ValueError("bridge receipt does not bind the request challenge and settings")
            has_response_key = isinstance(receipt, dict) and "response_private_key" in receipt
            if has_response_key and (
                not has_artifacts or not verify_bridge_response(receipt, result["body"])
            ):
                raise ValueError("bridge response does not match its signed ciphertext")
            request_parts = {"request_seed", "request_recipient_key", "request_plaintext"}
            supplied = request_parts.intersection(receipt) if isinstance(receipt, dict) else set()
            if supplied and (
                supplied != request_parts
                or not has_artifacts
                or not verify_bridge_request(receipt, body)
            ):
                raise ValueError("bridge request does not match its signed ciphertext")
            if self.recipient_key is not None and (
                not supplied
                or not hmac.compare_digest(
                    base64.b64decode(receipt["request_recipient_key"], validate=True),
                    bytes.fromhex(self.recipient_key),
                )
            ):
                raise ValueError("bridge receipt does not match the pinned recipient key")
        except (BridgeError, ValueError, TypeError) as exc:
            raise httpx.RequestError("bridge inference failed", request=request) from exc
        self.reported_provider = selected
        self.receipt_signer_matched = True if receipt is not None else None
        self.receipt_binding_matched = True if has_artifacts else None
        self.receipt_challenge_matched = True if has_artifacts else None
        self.receipt_response_choices_matched = True if has_response_key else None
        self.receipt_request_messages_matched = True if supplied else None
        return httpx.Response(
            200,
            json=result["body"],
            headers={"ZG-Res-Key": result["response_key"]},
            request=request,
        )
