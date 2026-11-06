"""Prepare or verify an isolated snapshot with protected legacy commitment salts."""

import argparse
import json
import sqlite3
from pathlib import Path

from cryptography.exceptions import InvalidTag
from sqlalchemy.exc import SQLAlchemyError

from memoryseal.demo.prepare_rotation import rotation_key
from memoryseal.key_rotation import prepare_salt_snapshot, verify_salt_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "verify"))
    parser.add_argument("source", type=Path)
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    try:
        key = rotation_key("MEMORYSEAL_SNAPSHOT_KEY")
        if args.operation == "prepare":
            checked, protected = prepare_salt_snapshot(args.source, args.snapshot, key)
            result = {
                "status": "prepared",
                "memories_checked": checked,
                "salts_protected": protected,
            }
        else:
            checked = verify_salt_snapshot(args.source, args.snapshot, key)
            result = {"status": "matched", "memories_checked": checked}
    except (ValueError, OSError, InvalidTag, sqlite3.Error, SQLAlchemyError, UnicodeError):
        parser.exit(1, "Snapshot operation failed; source was not replaced.\n")
    result.update(
        key_checked_against_memory=checked > 0,
        cutover_performed=False,
        warning="Keep writers stopped through verification and any cutover; old copies retain legacy salts.",
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
