import gzip
import json

import httpx
import pytest
from eth_account import Account

from memoryseal import MemorySealClient, MemoryWriteOutcomeUnknown
from memoryseal.http_limits import ResponseTooLarge


def test_write_uses_long_timeout_and_does_not_retry_ambiguous_failures():
    requests = []
    response_code = 200

    def handler(request):
        requests.append(request)
        assert request.extensions["timeout"]["read"] == 180.0
        if response_code is None:
            raise httpx.ReadTimeout("response lost", request=request)
        if response_code == "malformed":
            return httpx.Response(200, content=b"{", request=request)
        return httpx.Response(
            response_code,
            json={
                "id": "11111111-1111-1111-1111-111111111111",
                "status": "accepted",
                "lineage_eligible": True,
                "request_id": json.loads(request.content)["request_id"],
            },
            request=request,
        )

    with MemorySealClient(
        "http://gateway",
        Account.create().key,
        audience="test",
        transport=httpx.MockTransport(handler),
    ) as client:
        assert (
            client.write_memory("agent", "scope", "content", source_type="agent")["id"]
            == "11111111-1111-1111-1111-111111111111"
        )
        response_code = None
        with pytest.raises(MemoryWriteOutcomeUnknown, match="may have committed"):
            client.write_memory("agent", "scope", "content", source_type="agent")
        assert len(requests) == 2
        response_code = 500
        with pytest.raises(MemoryWriteOutcomeUnknown):
            client.write_memory("agent", "scope", "content", source_type="agent")
        response_code = "malformed"
        with pytest.raises(MemoryWriteOutcomeUnknown):
            client.write_memory("agent", "scope", "content", source_type="agent")
        response_code = 403
        with pytest.raises(httpx.HTTPStatusError):
            client.write_memory("agent", "scope", "content", source_type="agent")
        assert len(requests) == 5


def test_write_timeout_can_be_configured():
    with MemorySealClient(
        "http://gateway",
        Account.create().key,
        audience="test",
        write_timeout=45,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "id": "11111111-1111-1111-1111-111111111111",
                    "status": "accepted",
                    "lineage_eligible": True,
                    "timeout": request.extensions["timeout"]["read"],
                    "request_id": json.loads(request.content)["request_id"],
                },
            )
        ),
    ) as client:
        assert (
            client.write_memory("agent", "scope", "content", source_type="agent")["timeout"] == 45
        )
    with pytest.raises(ValueError):
        MemorySealClient("http://gateway", Account.create().key, audience="test", write_timeout=0)


def test_gateway_url_requires_tls_for_remote_connections():
    key = Account.create().key
    for url in (
        "http://gateway.example",
        "http://localhost.evil.example",
        "https://user:password@gateway.example",
        "https://gateway.example?token=secret",
        "https://gateway.example#fragment",
        "file:///tmp/gateway",
    ):
        with pytest.raises(ValueError):
            MemorySealClient(url, key, audience="test")
    for url in (
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://[::1]:8000",
        "https://gateway.example",
    ):
        with MemorySealClient(url, key, audience="test"):
            pass


def test_oversized_gateway_response_is_bounded_and_write_outcome_is_unknown():
    compressed = gzip.compress(b"x" * (24 * 1024 * 1024 + 1))
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, content=compressed, headers={"Content-Encoding": "gzip"}, request=request
        )
    )
    with MemorySealClient(
        "https://gateway.example", Account.create().key, audience="test", transport=transport
    ) as client:
        with pytest.raises(ResponseTooLarge):
            client.list_agents()
        with pytest.raises(MemoryWriteOutcomeUnknown) as unknown:
            client.write_memory("agent", "scope", "content", source_type="agent")
        assert unknown.value.request_id
        assert isinstance(unknown.value.__cause__, ResponseTooLarge)


def test_gateway_error_details_are_available_and_bounded():
    response = [gzip.compress(b'{"detail":"namespace denied"}')]
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            403, content=response[0], headers={"Content-Encoding": "gzip"}, request=request
        )
    )
    with MemorySealClient(
        "https://gateway.example", Account.create().key, audience="test", transport=transport
    ) as client:
        with pytest.raises(httpx.HTTPStatusError) as error:
            client.list_agents()
        assert error.value.response.json() == {"detail": "namespace denied"}
        response[0] = gzip.compress(b"x" * 65_537)
        with pytest.raises(httpx.HTTPStatusError) as oversized:
            client.list_agents()
        assert oversized.value.response.status_code == 403
        assert oversized.value.response.content == b""


def test_invalid_compressed_write_response_preserves_request_id():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            stream=httpx.ByteStream(b"not a gzip stream"),
            headers={"Content-Encoding": "gzip"},
            request=request,
        )

    with MemorySealClient(
        "https://gateway.example",
        Account.create().key,
        audience="test",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(MemoryWriteOutcomeUnknown) as unknown:
            client.write_memory("agent", "scope", "content", source_type="agent")
        assert unknown.value.request_id == requests[0]["request_id"]
        assert isinstance(unknown.value.__cause__, httpx.DecodingError)
