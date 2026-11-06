"""Experimental TLS certificate binding for the 0G gateway.

The verifier executable and its trust roots must be independently reviewed. A
passing gateway check is not independent verification of a provider response.
"""

import hashlib
import http.client
import re
import ssl
from pathlib import Path

import httpx

from memoryseal.demo.verify_0g_gateway import HOSTS
from memoryseal.gateway_verifier import verify_gateway_bounded
from memoryseal.zero_g_provider_verifier import provider_verifier_configured


def verifier_configured(path: str | None, digest: str | None) -> bool:
    return provider_verifier_configured(path, digest)


class AttestedGatewayTransport(httpx.BaseTransport):
    """Run a strict external verifier, then pin the certificate before sending."""

    def __init__(
        self,
        binary: Path,
        network: str,
        *,
        expected_sha256: str | None = None,
        verifier=None,
        connection_factory=None,
    ):
        if network not in HOSTS or not binary.is_absolute():
            raise ValueError("A supported network and absolute verifier path are required")
        self.verified_fingerprint = None
        self.binary = binary
        self.network = network
        self.verifier = verifier or (
            lambda path, name: verify_gateway_bounded(path, name, expected_sha256=expected_sha256)
        )
        self.connection_factory = connection_factory or http.client.HTTPSConnection

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.verified_fingerprint = None
        host = HOSTS[self.network]
        if (
            request.method != "POST"
            or request.url.scheme != "https"
            or request.url.host != host
            or request.url.port not in (None, 443)
            or request.url.path != "/v1/chat/completions"
            or request.url.query
        ):
            raise httpx.TransportError("Invalid attested inference destination", request=request)
        result = self.verifier(self.binary, self.network)
        lines = re.findall(r"(?m)^  served cert\s+([0-9a-fA-F]{64})\s*$", result.get("output", ""))
        if result.get("status") != "passed" or len(lines) != 1 or int(lines[0], 16) == 0:
            raise httpx.TransportError(
                "Gateway attestation unavailable or invalid", request=request
            )
        expected = bytes.fromhex(lines[0])
        connection = self.connection_factory(
            host, 443, timeout=30, context=ssl.create_default_context()
        )
        try:
            connection.connect()
            # Prevent http.client from reconnecting after the checked connection is lost.
            connection.auto_open = False
            certificate = connection.sock.getpeercert(binary_form=True)
            if not certificate or hashlib.sha256(certificate).digest() != expected:
                raise httpx.TransportError(
                    "Gateway TLS certificate did not match attestation", request=request
                )
            headers = dict(request.headers)
            headers["accept-encoding"] = "identity"
            connection.request(
                request.method,
                request.url.raw_path.decode("ascii"),
                body=request.read(),
                headers=headers,
            )
            response = connection.getresponse()
            response_headers = response.getheaders()
            if any(
                name.lower() == "content-encoding" and value.lower().strip() != "identity"
                for name, value in response_headers
            ):
                raise httpx.TransportError(
                    "Compressed gateway responses are not accepted", request=request
                )
            data = response.read(1_048_577)
            if len(data) > 1_048_576:
                raise httpx.TransportError("Gateway response exceeds size limit", request=request)
            self.verified_fingerprint = expected.hex()
            return httpx.Response(
                response.status, headers=response_headers, content=data, request=request
            )
        except (OSError, http.client.HTTPException, ssl.SSLError, AttributeError) as exc:
            raise httpx.TransportError(
                "Attested inference connection failed", request=request
            ) from exc
        finally:
            connection.close()
