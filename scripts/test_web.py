"""Run dashboard tests against an isolated, temporary local gateway."""

import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="memoryseal-web-test-") as directory:
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/init_local.py"),
                "--path",
                str(Path(directory) / ".env"),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        # The child runs outside the workspace so it cannot read the user's .env or database.
        gateway = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "memoryseal.api:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=directory,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={
                key: value for key, value in os.environ.items() if not key.startswith("MEMORYSEAL_")
            },
        )
        try:
            for _ in range(100):
                if gateway.poll() is not None:
                    raise RuntimeError("Temporary gateway exited before startup")
                try:
                    with urllib.request.urlopen(url + "/openapi.json", timeout=0.2) as response:
                        if response.status == 200:
                            break
                except (OSError, urllib.error.URLError):
                    time.sleep(0.1)
            else:
                raise RuntimeError("Temporary gateway did not start")
            env = os.environ.copy()
            env["MEMORYSEAL_TEST_GATEWAY"] = url
            tests = sorted(str(path) for path in (ROOT / "web/test").glob("*.test.mjs"))
            return subprocess.run(
                ["node", "--test", *tests], cwd=ROOT, env=env, check=False
            ).returncode
        finally:
            gateway.terminate()
            try:
                gateway.wait(timeout=5)
            except subprocess.TimeoutExpired:
                gateway.kill()
                gateway.wait()


if __name__ == "__main__":
    raise SystemExit(main())
