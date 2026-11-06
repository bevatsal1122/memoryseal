"""Compare a source database and prepared rotation snapshot without changing either."""

import argparse
import json
import sqlite3
from pathlib import Path

from cryptography.exceptions import InvalidTag

from memoryseal.demo.prepare_rotation import rotation_key
from memoryseal.key_rotation import verify_rotated_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    try:
        count = verify_rotated_snapshot(
            args.source,
            args.snapshot,
            rotation_key("MEMORYSEAL_ROTATION_OLD_KEY"),
            rotation_key("MEMORYSEAL_ROTATION_NEW_KEY"),
        )
    except (ValueError, OSError, InvalidTag, sqlite3.Error, UnicodeError):
        parser.exit(1, "Snapshot verification failed; neither database was changed.\n")
    print(
        json.dumps(
            {
                "status": "matched" if count else "matched_no_encrypted_memories",
                "memory_count": count,
                "keys_verified_against_memory": count > 0,
                "cutover_performed": False,
                "scope": "Point-in-time comparison only; keep all writers stopped through cutover.",
            }
        )
    )


if __name__ == "__main__":
    main()
