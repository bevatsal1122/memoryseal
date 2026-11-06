"""Request signing for the gateway and its Python client.

The signature binds the exact bytes sent on the wire, the deployment audience,
and a single-use nonce. It does not itself confer authorization.
"""

import hashlib
import re
import time

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import is_address


class InvalidSignature(ValueError):
    pass


def request_message(
    *, audience: str, method: str, target: str, body: bytes, timestamp: int, nonce: str
) -> str:
    if not audience or "\n" in audience or not target.startswith("/") or "\n" in target:
        raise ValueError("invalid request domain or target")
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", nonce):
        raise ValueError("invalid nonce")
    if not re.fullmatch(r"[A-Z]+", method):
        raise ValueError("invalid method")
    digest = hashlib.sha256(body).hexdigest()
    return f"MemorySeal request v1\n{audience}\n{method}\n{target}\n{digest}\n{timestamp}\n{nonce}"


def sign_request(private_key: str, **fields) -> str:
    message = request_message(**fields)
    return Account.sign_message(encode_defunct(text=message), private_key).signature.hex()


def verify_request(
    *, address: str, signature: str, max_skew: int = 300, now: int | None = None, **fields
) -> str:
    current = int(time.time()) if now is None else now
    if abs(current - fields["timestamp"]) > max_skew:
        raise InvalidSignature("request timestamp outside allowed window")
    try:
        message = request_message(**fields)
        recovered = Account.recover_message(encode_defunct(text=message), signature=signature)
        if not is_address(address) or recovered.lower() != address.lower():
            raise InvalidSignature("signer does not match identity")
    except (ValueError, TypeError, KeyError) as exc:
        raise InvalidSignature("invalid signed request") from exc
    return recovered.lower()
