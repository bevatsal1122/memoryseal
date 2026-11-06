"""Prepare a rotated SQLite snapshot; does not switch the live database or key."""

import argparse
import base64
import binascii
import json
import os
import sqlite3
from pathlib import Path

from cryptography.exceptions import InvalidTag
from sqlalchemy.exc import SQLAlchemyError

from memoryseal.key_rotation import prepare_rotated_snapshot


def rotation_key(name: str) -> bytes:
    try:
        value = base64.b64decode(os.environ.get(name, ""), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("invalid rotation key") from exc
    if len(value) != 32:
        raise ValueError("invalid rotation key")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="existing SQLite database")
    parser.add_argument("destination", type=Path, help="new snapshot path; must not exist")
    args = parser.parse_args()
    try:
        old = rotation_key("MEMORYSEAL_ROTATION_OLD_KEY")
        new = rotation_key("MEMORYSEAL_ROTATION_NEW_KEY")
        count = prepare_rotated_snapshot(args.source, args.destination, old, new)
    except (ValueError, OSError, InvalidTag, sqlite3.Error, SQLAlchemyError, UnicodeError):
        parser.exit(1, "Snapshot preparation failed; source and configuration were not replaced.\n")
    print(
        json.dumps(
            {
                "status": "prepared",
                "memory_count": count,
                "source_key_checked_against_memory": count > 0,
                "cutover_performed": False,
                "warning": "Stop all writers and verify the snapshot before any database and key switch.",
            }
        )
    )


if __name__ == "__main__":
    main()
