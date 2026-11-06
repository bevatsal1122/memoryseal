"""Run SDK and browser HTTP tests against an isolated, unfunded gateway."""

import base64
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

repo = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="memoryseal-sdk-test-") as directory:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if not k.startswith("MEMORYSEAL_")}
    env.update(
        PYTHONPATH=str(repo / "src"),
        MEMORYSEAL_DATABASE_URL=f"sqlite:///{directory}/test.db",
        MEMORYSEAL_ENCRYPTION_KEY=base64.b64encode(os.urandom(32)).decode(),
        MEMORYSEAL_TEST_GATEWAY=f"http://127.0.0.1:{port}",
    )
    subprocess.run(["npm", "run", "build"], cwd=repo / "sdk/typescript", check=True)
    with open(Path(directory) / "server.log", "w") as log:
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "memoryseal.api:app", "--port", str(port)],
            cwd=directory,
            env=env,
            stdout=log,
            stderr=log,
        )
        try:
            for _ in range(100):
                try:
                    with urlopen(env["MEMORYSEAL_TEST_GATEWAY"] + "/health", timeout=1):
                        break
                except OSError:
                    if server.poll() is not None:
                        raise RuntimeError("isolated gateway failed to start")
                    time.sleep(0.1)
            for folder in (repo / "sdk/typescript/test", repo / "web/test"):
                subprocess.run(
                    ["node", "--test", *map(str, folder.glob("*.mjs"))],
                    cwd=repo,
                    env=env,
                    check=True,
                )
            with sqlite3.connect(Path(directory) / "test.db") as database:
                stored = "\n".join(database.iterdump())
                assert "CLIENT_ONLY_SECRET_789" not in stored
                assert "concurrent new write" not in stored
            print("SDK end-to-end passed; plaintext markers absent from isolated database")
        finally:
            server.terminate()
            server.wait(timeout=10)
