"""Test-only bridge between httpx SDK requests and Starlette's test client."""

import httpx
import pytest


@pytest.fixture
def gateway_transport():
    def create(server):
        def handle(request):
            response = server.request(
                request.method,
                str(request.url),
                headers=list(request.headers.multi_items()),
                content=request.content,
                follow_redirects=False,
            )
            return httpx.Response(
                response.status_code,
                headers=list(response.headers.multi_items()),
                content=response.content,
                request=request,
            )

        return httpx.MockTransport(handle)

    return create
