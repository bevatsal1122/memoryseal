"""Create a private local configuration once; never replace an existing file."""

import argparse
import base64
import os
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / ".env.example"


def create(path: Path) -> None:
    template = TEMPLATE.read_text()
    marker = "MEMORYSEAL_ENCRYPTION_KEY="
    if template.count(marker) != 1:
        raise RuntimeError("configuration template has an unexpected encryption key field")
    key = base64.b64encode(os.urandom(32)).decode("ascii")
    content = template.replace(marker, marker + key, 1)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Create a new local .env with a random encryption key"
    )
    parser.add_argument("--path", type=Path, default=Path(".env"))
    args = parser.parse_args()
    try:
        create(args.path)
    except FileExistsError:
        parser.exit(1, "Configuration already exists; it was not changed.\n")
    print(f"Created {args.path} with a new encryption key. Keep it private and back it up.")


if __name__ == "__main__":
    main()
