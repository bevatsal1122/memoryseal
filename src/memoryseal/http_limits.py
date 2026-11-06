"""Bound untrusted external responses before parsing them."""

import json

import httpx


class ResponseTooLarge(ValueError):
    """The decompressed response exceeds the caller's configured limit."""


def read_json_limited(response: httpx.Response, *, max_bytes: int) -> object:
    """Read decompressed bytes with a hard limit; callers own the response stream."""
    response.raise_for_status()
    data = bytearray()
    for chunk in response.iter_bytes(chunk_size=16_384):
        if len(data) + len(chunk) > max_bytes:
            raise ResponseTooLarge("External response exceeds size limit")
        data.extend(chunk)
    return json.loads(data)
