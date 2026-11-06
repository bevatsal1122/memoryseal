"""Compare observed runtime bytecode against local build artifacts."""

import json
from pathlib import Path

ARTIFACTS = Path(__file__).resolve().parents[2] / "contracts" / "artifacts"


def matches_local_runtime(name: str, code: str, registry: str) -> bool | None:
    """Compare exact runtime against a local artifact, substituting its immutable registry."""
    path = ARTIFACTS / f"{name}.json"
    if not path.is_file():
        return None
    try:
        artifact = json.loads(path.read_text())
        runtime = artifact["deployedBytecode"]
        refs = artifact["immutableReferences"]
        if (
            not isinstance(runtime, str)
            or not runtime.startswith("0x")
            or not isinstance(refs, dict)
        ):
            return None
        if not isinstance(code, str) or not code.startswith("0x"):
            return None
        expected = bytearray.fromhex(runtime[2:])
        actual = bytes.fromhex(code[2:])
        if name == "ProtectedTransfer":
            if len(refs) != 1:
                return None
            entries = next(iter(refs.values()))
            if not isinstance(entries, list) or not entries:
                return None
            for entry in entries:
                start, length = entry["start"], entry["length"]
                if (
                    not isinstance(start, int)
                    or length != 32
                    or start < 0
                    or start + length > len(expected)
                ):
                    return None
                expected[start : start + length] = bytes.fromhex(registry[2:]).rjust(32, b"\x00")
        elif name == "MemoryPolicyRegistry":
            if refs:
                return None
        else:
            return None
        return actual == expected
    except (OSError, ValueError, TypeError, KeyError):
        return None
