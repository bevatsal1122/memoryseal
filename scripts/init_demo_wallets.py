"""Create dedicated demo wallets once; never print or overwrite private keys."""

import argparse
import json
import os
from pathlib import Path

from eth_account import Account

NAMES = ("OWNER", "BROWSER", "RESEARCH", "FINANCE")


def create(path: Path) -> dict[str, str]:
    accounts = {name: Account.create() for name in NAMES}
    # Atomically claim the file name before writing secrets. Existing files are never overwritten.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write("# Dedicated test-only MemorySeal wallets. Keep this file private.\n")
            for name, account in accounts.items():
                output.write(
                    f"MEMORYSEAL_DEMO_{name}_KEY=0x{account.key.hex().removeprefix('0x')}\n"
                )
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {name.lower(): account.address for name, account in accounts.items()}


def main():
    parser = argparse.ArgumentParser(description="Create dedicated demo wallets once")
    parser.add_argument("--path", type=Path, default=Path(".demo.env"))
    args = parser.parse_args()
    try:
        addresses = create(args.path)
    except FileExistsError:
        parser.exit(1, "Wallet file already exists; it was not changed.\n")
    print(
        json.dumps(
            {"wallet_file": str(args.path), "addresses": addresses, "funded": False}, indent=2
        )
    )


if __name__ == "__main__":
    main()
