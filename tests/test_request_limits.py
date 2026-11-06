import asyncio

from memoryseal.request_limits import RequestBodyLimit


def test_chunked_request_is_limited_before_application():
    async def exercise(chunks):
        received = iter(chunks)
        sent = []
        calls = []

        async def receive():
            return next(received)

        async def send(message):
            sent.append(message)

        async def app(scope, receive, send):
            calls.append((await receive())["body"])

        await RequestBodyLimit(app, max_bytes=4)({"type": "http"}, receive, send)
        return calls, sent

    calls, sent = asyncio.run(exercise([
        {"type": "http.request", "body": b"ab", "more_body": True},
        {"type": "http.request", "body": b"cde", "more_body": False},
    ]))
    assert calls == []
    assert sent[0]["status"] == 413

    calls, sent = asyncio.run(exercise([
        {"type": "http.request", "body": b"ab", "more_body": True},
        {"type": "http.request", "body": b"cd", "more_body": False},
    ]))
    assert calls == [b"abcd"]
    assert sent == []
