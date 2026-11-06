import json

import httpx
import pytest
from eth_account import Account

from memoryseal.client import MemorySealClient


def client_for(responses):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=responses[len(calls) - 1])

    return MemorySealClient(
        "http://gateway",
        Account.create().key,
        audience="test",
        transport=httpx.MockTransport(handler),
    ), calls


def test_empty_page_with_cursor_is_followed():
    client, calls = client_for(
        [
            {"memories": [], "next_offset": 100},
            {"memories": [{"id": "record", "content": "visible"}], "next_offset": None},
        ]
    )
    with client:
        assert client.read_memory("agent", "namespace")["memories"][0]["id"] == "record"
    assert [call["offset"] for call in calls] == [0, 100]


@pytest.mark.parametrize(
    "page",
    [
        [],
        {},
        {"memories": "text", "next_offset": None},
        {"memories": ["text"], "next_offset": None},
        {"memories": [], "next_offset": True},
        {"memories": [], "next_offset": 1},
        {"memories": [], "next_offset": 101},
        {"memories": [{}] * 101, "next_offset": None},
    ],
)
def test_invalid_page_is_rejected(page):
    client, calls = client_for([page])
    with client, pytest.raises(ValueError, match="Invalid memory page response"):
        client.read_memory("agent", "namespace")
    assert len(calls) == 1


@pytest.mark.parametrize("offset,limit", [(-1, 100), (True, 100), (0, 0), (0, 101), (0, False)])
def test_invalid_page_request_is_rejected_before_network(offset, limit):
    client, calls = client_for([])
    with client, pytest.raises(ValueError, match="Invalid memory page request"):
        client.read_memory_page("agent", "namespace", offset=offset, limit=limit)
    assert not calls
