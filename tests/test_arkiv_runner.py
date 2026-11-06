import os
import subprocess
import sys

import pytest

from memoryseal.arkiv_runner import run_arkiv


def invoke(program, *, timeout=2):
    return run_arkiv(
        [sys.executable, "-c", program],
        input='{"event_id":"test"}',
        text=True,
        capture_output=True,
        timeout=timeout,
        check=True,
        env={"PATH": os.environ.get("PATH", "")},
    )


def test_publisher_uses_bounded_pipes_and_suppresses_stderr():
    result = invoke("import sys; print(sys.stdin.read()); print('secret', file=sys.stderr)")
    assert result.stdout.strip() == '{"event_id":"test"}'
    assert result.stderr == ""


@pytest.mark.parametrize(
    "program,timeout",
    [
        ("print('x' * 1600000)", 2),
        ("import time; time.sleep(5)", 0.2),
        ("raise SystemExit(1)", 2),
    ],
)
def test_publisher_fails_closed_for_large_output_timeout_and_failure(program, timeout):
    with pytest.raises(subprocess.SubprocessError):
        invoke(program, timeout=timeout)
