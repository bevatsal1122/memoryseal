"""Test the experimental bridge against an archive of the pinned 0G checkout."""

import argparse
import base64
import copy
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from memoryseal.bridge_response import verify_bridge_request, verify_bridge_response
from memoryseal.zero_g_verification import (
    verify_bridge_binding,
    verify_bridge_challenge,
    verify_bridge_receipt,
)
from scripts.build_0g_bridge import PINNED_COMMIT, patch_core, patch_protocol, patch_proxycli

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    "bridge.go": "main.go",
    "bridge_test.go": "main_test.go",
    "bridge_integration_test.go": "integration_test.go",
    "pinned_resolver.go": "pinned_resolver.go",
    "pinned_resolver_test.go": "pinned_resolver_test.go",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    parser.add_argument("go", type=Path)
    parser.add_argument("--race", action="store_true", help="enable Go's race detector")
    args = parser.parse_args()
    checkout, go = args.checkout.resolve(), args.go.resolve()
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=checkout, check=True, capture_output=True, text=True
    ).stdout.strip()
    if commit != PINNED_COMMIT:
        raise ValueError("upstream checkout does not match the pinned commit")
    with tempfile.TemporaryDirectory(prefix="memoryseal-0g-test-") as temp:
        root = Path(temp)
        archive = root / "source.tar"
        with archive.open("wb") as output:
            subprocess.run(
                ["git", "archive", "--format=tar", "HEAD", "client", "protocol"],
                cwd=checkout,
                stdout=output,
                check=True,
            )
        with tarfile.open(archive) as tar:
            tar.extractall(root, filter="data")
        patch_proxycli(root)
        patch_protocol(root)
        patch_core(root)
        shutil.copyfile(
            ROOT / "integrations/zero_g/bounded_upstream_test.go",
            root / "client/core/memoryseal_bounded_response_test.go",
        )
        target = root / "client/cmd/memorysealbridge"
        target.mkdir(parents=True)
        for source, name in FILES.items():
            shutil.copyfile(ROOT / "integrations/zero_g" / source, target / name)
        allowed = (
            "PATH",
            "HOME",
            "TMPDIR",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
            "SSL_CERT_FILE",
        )
        env = {key: os.environ[key] for key in allowed if key in os.environ}
        env["GOTOOLCHAIN"] = "local"
        fixture_path = root / "synthetic-binding-fixture.json"
        env["MEMORYSEAL_TEST_BINDING_FIXTURE"] = str(fixture_path)
        subprocess.run(
            [
                str(go),
                "test",
                *(["-race"] if args.race else []),
                "-count=1",
                "./cmd/memorysealbridge",
            ],
            cwd=root / "client",
            env=env,
            check=True,
        )
        fixture = json.loads(fixture_path.read_text())
        request_body = {
            "messages": [
                {"role": "system", "content": "rules"},
                {"role": "user", "content": "sensitive marker"},
            ]
        }
        receipt, signer, challenge = fixture["receipt"], fixture["signer"], fixture["challenge"]
        if not (
            verify_bridge_receipt(receipt, signer)
            and verify_bridge_binding(receipt)
            and verify_bridge_challenge(receipt, challenge, temperature=0, model="model")
            and verify_bridge_response(receipt, fixture["body"])
            and verify_bridge_request(receipt, request_body)
            and not verify_bridge_challenge(
                receipt, "memoryseal-" + "b" * 64, temperature=0, model="model"
            )
        ):
            raise ValueError("cross-language receipt verification failed")
        if verify_bridge_request(receipt, {"messages": [{"role": "user", "content": "changed"}]}):
            raise ValueError("cross-language receipt accepted altered request")
        for field in ("request_seed", "request_recipient_key", "request_plaintext"):
            modified = copy.deepcopy(receipt)
            material = bytearray(base64.b64decode(modified[field], validate=True))
            material[1] ^= 1
            modified[field] = base64.b64encode(material).decode()
            if verify_bridge_request(modified, request_body):
                raise ValueError("cross-language receipt accepted altered request material")
        altered_body = dict(fixture["body"])
        altered_body["choices"] = []
        if verify_bridge_response(receipt, altered_body):
            raise ValueError("cross-language receipt accepted altered response")
        altered_receipt = copy.deepcopy(receipt)
        key = bytearray(base64.b64decode(altered_receipt["response_private_key"], validate=True))
        key[1] ^= 1
        altered_receipt["response_private_key"] = base64.b64encode(key).decode()
        if verify_bridge_response(altered_receipt, fixture["body"]):
            raise ValueError("cross-language receipt accepted altered private key")
        altered_receipt = copy.deepcopy(receipt)
        ciphertext = bytearray(
            base64.b64decode(altered_receipt["artifacts"]["response_ciphertext"])
        )
        ciphertext[-1] ^= 1
        altered_receipt["artifacts"]["response_ciphertext"] = base64.b64encode(ciphertext).decode()
        if verify_bridge_response(altered_receipt, fixture["body"]):
            raise ValueError("cross-language receipt accepted altered response ciphertext")
        bound = json.loads(Path(str(fixture_path) + ".bound").read_text())
        bound_receipt = bound["receipt"]
        if not (
            verify_bridge_receipt(bound_receipt, bound["signer"])
            and verify_bridge_binding(bound_receipt)
            and verify_bridge_challenge(
                bound_receipt, bound["challenge"], temperature=0, model="model"
            )
            and verify_bridge_response(bound_receipt, bound["body"])
            and verify_bridge_request(bound_receipt, request_body)
        ):
            raise ValueError("cross-language bound response verification failed")
        altered_bound = dict(bound["body"])
        altered_bound["choices"] = []
        if verify_bridge_response(bound_receipt, altered_bound):
            raise ValueError("bound response accepted altered choices")
        changed_mode = copy.deepcopy(bound_receipt)
        aad = json.loads(base64.b64decode(changed_mode["artifacts"]["request_aad"], validate=True))
        aad["_e2ee"]["sealed_fields"].remove("_bind")
        changed_mode["artifacts"]["request_aad"] = base64.b64encode(
            json.dumps(aad).encode()
        ).decode()
        if verify_bridge_response(changed_mode, bound["body"]):
            raise ValueError("bound response accepted a base-mode downgrade")
        artifact = receipt["artifacts"]["request_ciphertext"]
        raw = bytearray(base64.b64decode(artifact, validate=True))
        raw[0] ^= 1
        receipt["artifacts"]["request_ciphertext"] = base64.b64encode(raw).decode()
        if verify_bridge_binding(receipt):
            raise ValueError("cross-language receipt accepted tampered ciphertext")
        print("Synthetic Go receipt verified independently in Python; tampering rejected.")
        subprocess.run(
            [
                str(go),
                "test",
                *(["-race"] if args.race else []),
                "./core",
                "-run",
                "^TestMemorySealBoundedResponse$",
            ],
            cwd=root / "client",
            env=env,
            check=True,
        )


if __name__ == "__main__":
    main()
