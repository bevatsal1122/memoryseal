"""Start the persistent single-worker gateway; never print configuration secrets."""

import base64
import binascii
import os
import sys
from pathlib import Path


def validate_environment(env):
    try:
        key = base64.b64decode(env.get("MEMORYSEAL_ENCRYPTION_KEY", ""), validate=True)
    except (ValueError, binascii.Error):
        key = b""
    if len(key) != 32:
        raise ValueError("Set MEMORYSEAL_ENCRYPTION_KEY to a base64-encoded 32-byte key.")
    try:
        port = int(env.get("PORT", "8000"))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise ValueError("PORT must be an integer between 1 and 65535.") from None
    if not env.get("MEMORYSEAL_DASHBOARD_ORIGINS"):
        raise ValueError("Set MEMORYSEAL_DASHBOARD_ORIGINS to the exact frontend HTTPS origin.")
    mount = Path(env.get("RAILWAY_VOLUME_MOUNT_PATH", "/data")).resolve()
    if env.get("RAILWAY_ENVIRONMENT_ID") and not env.get("RAILWAY_VOLUME_MOUNT_PATH"):
        raise ValueError("Attach a persistent Railway volume at /data before starting.")
    url = env.get("MEMORYSEAL_DATABASE_URL", "sqlite:////data/memoryseal.db")
    if not url.startswith("sqlite:////") or "?" in url or "#" in url:
        raise ValueError("Use an absolute SQLite database path on the persistent volume.")
    database = Path(url.removeprefix("sqlite:///")).resolve()
    if not database.is_relative_to(mount) or not mount.is_dir():
        raise ValueError("The database must be inside the mounted persistent volume.")
    if not database.parent.is_dir() or not os.access(database.parent, os.W_OK):
        raise ValueError("The persistent database directory must exist and be writable.")
    return port


if __name__ == "__main__":
    try:
        port = validate_environment(os.environ)
    except ValueError as error:
        sys.exit(str(error))
    os.execv(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "memoryseal.api:app",
            "--host",
            "0.0.0.0",
            "--port",
            str(port),
            "--workers",
            "1",
        ],
    )
