"""Cross-check Python response verification against ethers personal signatures."""

import json
import subprocess
from pathlib import Path

import httpx
from eth_account import Account

from memoryseal.zero_g_verification import verify_pinned_response


def test_ethers_signature_interoperates_with_python_verifier():
    root = Path(__file__).resolve().parents[1]
    key = "0x" + "11" * 32  # Public test key, never use for assets.
    content = '{"message":"café 🛡️"}'
    script = """
import { Wallet } from 'ethers';
const wallet = new Wallet(process.argv[1]);
console.log(JSON.stringify({ signer: wallet.address, signature: await wallet.signMessage(process.argv[2]) }));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, key, content],
        cwd=root / "contracts",
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    signed = json.loads(result.stdout)
    provider = Account.create().address

    def verify(receipt_text, signer):
        def response(request):
            assert request.url.params["model"] == "example/model"
            return httpx.Response(
                200, json={"text": receipt_text, "signature": signed["signature"]}
            )

        return verify_pinned_response(
            provider=provider,
            response_key="chat-1",
            response_text=content,
            model="example/model",
            expected_provider=provider,
            signer=signer,
            base_url="https://provider.example",
            transport=httpx.MockTransport(response),
        )

    assert verify(content, signed["signer"])
    assert not verify(content + " ", signed["signer"])
    assert not verify(content, Account.create().address)
