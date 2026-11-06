"""Optional smoke checks for an operator-built experimental upstream bridge."""

import os
import subprocess

import pytest


@pytest.mark.parametrize(
    "body",
    [
        b"{}",
        b'{"network":"invalid","api_key":"dummy","body":{}}',
        b'{"network":"testnet","api_key":"dummy","body":{"stream":true}}',
        b'{"network":"testnet","api_key":"dummy","body":{"model":"x","temperature":0,"verify_tee":true,"messages":[{"role":"system","content":"x"},{"role":"user","content":"secret"}],"extra":"private"}}',
        b'{"network":"testnet","api_key":"dummy","body":{}} {}',
    ],
)
def test_bridge_rejects_invalid_input_before_network(body):
    binary = os.environ.get("MEMORYSEAL_TEST_0G_BRIDGE")
    if not binary:
        pytest.skip("operator-built bridge not supplied")
    env = {key: value for key, value in os.environ.items() if key in ("PATH", "HOME", "TMPDIR")}
    result = subprocess.run(
        [binary], input=body, capture_output=True, env=env, timeout=5, check=False
    )
    assert result.returncode != 0
    assert not result.stdout
    assert b"dummy" not in result.stderr
