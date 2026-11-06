"""Validate explicitly configured dashboard origins for browser access."""

from urllib.parse import urlsplit


def dashboard_origins(value: str) -> list[str]:
    """Return exact allowed origins, rejecting wildcard and insecure remote origins."""
    origins = []
    for raw in value.split(","):
        origin = raw.strip()
        try:
            parsed = urlsplit(origin)
            port = parsed.port  # Validate port before configuring the middleware.
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
                or "*" in origin
                or (
                    parsed.scheme == "http"
                    and parsed.hostname not in ("localhost", "127.0.0.1", "::1")
                )
                or port == 0
                or (parsed.scheme == "https" and port == 443)
                or (parsed.scheme == "http" and port == 80)
            ):
                raise ValueError("invalid dashboard origin")
            # Origin comparisons are exact; normalization prevents an invalid
            # configuration from silently allowing a different spelling.
            host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
            normalized = f"{parsed.scheme}://{host}" + (f":{port}" if port else "")
            if origin != normalized:
                raise ValueError("dashboard origin must use canonical spelling")
        except (ValueError, TypeError) as exc:
            raise ValueError("invalid dashboard origin configuration") from exc
        if origin not in origins:
            origins.append(origin)
    return origins
