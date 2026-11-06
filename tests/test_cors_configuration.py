import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from memoryseal.cors import dashboard_origins


def test_explicit_dashboard_origins_allow_only_configured_browser_origin():
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=dashboard_origins("http://localhost:3000, https://dashboard.example"),
        allow_methods=["GET", "POST"],
        allow_headers=["X-Memoryseal-Signature"],
    )
    with TestClient(app) as client:
        for origin, allowed in (
            ("https://dashboard.example", True),
            ("https://attacker.example", False),
        ):
            response = client.options(
                "/agents",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "X-Memoryseal-Signature",
                },
            )
            assert (response.status_code == 200) is allowed
            assert response.headers.get("access-control-allow-origin") == (
                origin if allowed else None
            )


@pytest.mark.parametrize(
    "value",
    [
        "",
        "*",
        "https://*.example",
        "http://remote.example",
        "https://user:pass@example.com",
        "https://example.com/",
        "https://example.com/path",
        "https://example.com?x=1",
        "https://example.com#fragment",
        "http://localhost:0",
        "http://localhost:80",
        "https://example.com:443",
        "https://example.com,",
    ],
)
def test_invalid_dashboard_origins_are_rejected(value):
    with pytest.raises(ValueError):
        dashboard_origins(value)
