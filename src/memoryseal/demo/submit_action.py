"""Submit one explicit Sepolia demo action with a dedicated finance key."""

import argparse
import json
import os
from pathlib import Path

from memoryseal.demo.transfer_context import parse_uint256
from memoryseal.onchain import ProtectedTransferClient, SubmissionOutcomeUnknown


def main():
    parser = argparse.ArgumentParser(description="Submit one protected transfer on Sepolia")
    parser.add_argument(
        "action",
        type=Path,
        help="JSON with registry, executor, owner, token, recipient, amount and policy_version",
    )
    parser.add_argument(
        "--gas-limit", type=int, help="Explicit gas; bypasses estimation and can succeed or revert"
    )
    parser.add_argument("--max-gas", type=int, default=300_000)
    parser.add_argument("--max-gas-price-wei", type=int, required=True)
    args = parser.parse_args()
    rpc, key = (
        os.environ.get("MEMORYSEAL_DEMO_RPC_URL"),
        os.environ.get("MEMORYSEAL_DEMO_FINANCE_KEY"),
    )
    if not rpc or not key:
        parser.error("Set MEMORYSEAL_DEMO_RPC_URL and MEMORYSEAL_DEMO_FINANCE_KEY")
    action = json.loads(args.action.read_text())
    amount = parse_uint256(action["amount"])
    policy_version = parse_uint256(action["policy_version"], allow_zero=True)
    client = ProtectedTransferClient(
        rpc,
        key,
        chain_id=11155111,
        executor=action["executor"],
        max_gas_price_wei=args.max_gas_price_wei,
    )
    try:
        try:
            transaction_hash = client.execute(
                owner=action["owner"],
                token=action["token"],
                recipient=action["recipient"],
                amount=amount,
                policy_version=policy_version,
                max_gas=args.max_gas,
                gas_limit=args.gas_limit,
                expected_registry=action["registry"],
                verify_runtime=True,
            )
        except SubmissionOutcomeUnknown as exc:
            print(
                json.dumps(
                    {"status": "submission_uncertain", "transaction_hash": exc.transaction_hash}
                )
            )
            raise SystemExit(1) from exc
        print(
            json.dumps(
                {
                    "status": "submitted",
                    "transaction_hash": transaction_hash,
                    "agent": client.account.address,
                }
            )
        )
    finally:
        client.close()


if __name__ == "__main__":
    main()
