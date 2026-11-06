import base64
import os
import subprocess
import sys
from pathlib import Path


def test_local_configuration_creation_never_overwrites(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "init_local.py"
    path = tmp_path / ".env"
    first = subprocess.run(
        [sys.executable, str(script), "--path", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 0
    contents = path.read_text()
    key = next(
        line.split("=", 1)[1]
        for line in contents.splitlines()
        if line.startswith("MEMORYSEAL_ENCRYPTION_KEY=")
    )
    assert len(base64.b64decode(key, validate=True)) == 32
    assert key not in first.stdout and key not in first.stderr
    assert os.stat(path).st_mode & 0o077 == 0
    second = subprocess.run(
        [sys.executable, str(script), "--path", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert second.returncode != 0
    assert path.read_text() == contents
    assert key not in second.stdout and key not in second.stderr
