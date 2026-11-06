"""Experimental independent opening of a bridge-reported 0G response.

This checks response choices against signed ciphertext after the caller verifies
the receipt, binding hashes and request challenge. It is not request-plaintext
verification or provider attestation. The ephemeral private key is sensitive.
"""

import base64
import binascii
import hashlib
import hmac
import json
import re

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _b64url(value):
    if not isinstance(value, str) or len(value) > 256 or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("invalid base64url")
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


def verify_bridge_response(receipt: dict, body: dict) -> bool:
    """Compare decrypted signed choices to the bridge's returned choices."""
    try:
        from pyhpke import AEADId, CipherSuite, KDFId, KEMId, KEMKey

        artifacts = receipt["artifacts"]
        if not isinstance(body, dict) or any(
            not isinstance(artifacts.get(name), str) or len(artifacts[name]) > 266_668
            for name in ("request_aad", "response_aad", "response_ciphertext")
        ):
            return False
        if (
            not isinstance(receipt["response_private_key"], str)
            or len(receipt["response_private_key"]) != 44
        ):
            return False
        key_bytes = base64.b64decode(receipt["response_private_key"], validate=True)
        if len(key_bytes) != 32:
            return False
        private = X25519PrivateKey.from_private_bytes(key_bytes)
        public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        request_aad = json.loads(
            base64.b64decode(artifacts["request_aad"], validate=True),
            object_pairs_hook=_unique_object,
        )
        response_aad_bytes = base64.b64decode(artifacts["response_aad"], validate=True)
        response_aad = json.loads(response_aad_bytes, object_pairs_hook=_unique_object)
        request_meta = request_aad["_e2ee"]
        request_sealed_fields = request_meta.get("sealed_fields")
        if not isinstance(request_sealed_fields, list):
            return False
        bound_response = "_bind" in request_sealed_fields
        if "_bind" in request_aad or "_bind" in request_meta.get("unbound_fields", []):
            return False
        response_meta = response_aad["_e2ee"]
        if not isinstance(response_meta, dict):
            return False
        sealed_fields = response_meta.get("sealed_fields")
        unbound_fields = response_meta.get("unbound_fields", [])
        if (
            public != _b64url(request_meta["client_eph_pub"])
            or response_meta.get("v") != 1
            or response_meta.get("final") is not True
            or not isinstance(sealed_fields, list)
            or not isinstance(unbound_fields, list)
            or "choices" not in sealed_fields
            or "choices" in response_aad
            or "choices" in unbound_fields
        ):
            return False
        suite = CipherSuite.new(
            KEMId.DHKEM_X25519_HKDF_SHA256, KDFId.HKDF_SHA256, AEADId.CHACHA20_POLY1305
        )
        psk = (
            HKDF(algorithm=SHA256(), length=32, salt=None, info=b"0g-pc/v1/resp-bind").derive(
                key_bytes
            )
            if bound_response
            else b""
        )
        recipient = suite.create_recipient_context(
            _b64url(response_meta["enc"]),
            KEMKey.from_pyca_cryptography_key(private),
            info=b"0g-pc/v1/resp",
            psk=psk,
            psk_id=b"0g-pc/v1/resp-bind" if bound_response else b"",
        )
        ciphertext = base64.b64decode(artifacts["response_ciphertext"], validate=True)
        plaintext = recipient.open(ciphertext, response_aad_bytes)
        sealed = json.loads(plaintext, object_pairs_hook=_unique_object)
        if not isinstance(sealed, dict) or "choices" not in sealed or "choices" not in body:
            return False
        canonical = lambda value: json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        return canonical(sealed["choices"]) == canonical(body["choices"])
    except (ImportError, ValueError, TypeError, KeyError, binascii.Error, AttributeError):
        return False
    except Exception:  # noqa: BLE001 - fail closed on cryptographic backend errors
        return False


def verify_bridge_request(receipt: dict, body: dict) -> bool:
    """Recompute the signed ciphertext and compare its messages to the local input.

    This trusts neither reported plaintext nor sealing seed for the comparison,
    but does not establish that the reported recipient key is attested.
    """
    try:
        from pyhpke import AEADId, CipherSuite, KDFId, KEMId

        if not isinstance(body, dict) or not isinstance(body.get("messages"), list):
            return False
        artifacts = receipt["artifacts"]
        for key in ("request_seed", "request_recipient_key", "request_plaintext"):
            if not isinstance(receipt.get(key), str) or len(receipt[key]) > 266_668:
                return False
        seed = base64.b64decode(receipt["request_seed"], validate=True)
        recipient = base64.b64decode(receipt["request_recipient_key"], validate=True)
        plaintext = base64.b64decode(receipt["request_plaintext"], validate=True)
        if len(seed) != 32 or len(recipient) != 32 or not 0 < len(plaintext) <= 200_000:
            return False
        aad = base64.b64decode(artifacts["request_aad"], validate=True)
        ciphertext = base64.b64decode(artifacts["request_ciphertext"], validate=True)
        if not 0 < len(aad) <= 200_000 or not 0 < len(ciphertext) <= 200_000:
            return False
        envelope = json.loads(aad, object_pairs_hook=_unique_object)
        sealed = json.loads(plaintext, object_pairs_hook=_unique_object)
        metadata = envelope["_e2ee"]
        fields = metadata["sealed_fields"]
        if (
            not isinstance(sealed, dict)
            or not isinstance(fields, list)
            or not all(isinstance(field, str) for field in fields)
            or set(fields) != set(sealed)
            or len(set(fields)) != len(fields)
            or set(fields) not in ({"messages"}, {"messages", "_bind"})
            or metadata.get("v") != 1
            or metadata.get("kem_id") != "0x0020"
            or not hmac.compare_digest(
                _b64url(metadata["key_id"]), hashlib.sha256(recipient).digest()[:8]
            )
        ):
            return False
        canonical = lambda value: json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        if canonical(sealed["messages"]) != canonical(body["messages"]):
            return False
        if "_bind" in sealed:
            response_key = base64.b64decode(receipt["response_private_key"], validate=True)
            if len(response_key) != 32:
                return False
            bind = HKDF(
                algorithm=SHA256(), length=32, salt=None, info=b"0g-pc/v1/resp-bind"
            ).derive(response_key)
            if not hmac.compare_digest(_b64url(sealed["_bind"]), bind):
                return False
        suite = CipherSuite.new(
            KEMId.DHKEM_X25519_HKDF_SHA256, KDFId.HKDF_SHA256, AEADId.CHACHA20_POLY1305
        )
        enc, sender = suite.create_sender_context(
            suite.kem.deserialize_public_key(recipient),
            info=b"0g-pc/v1/seal",
            eks=suite.kem.derive_key_pair(seed),
        )
        return hmac.compare_digest(enc, _b64url(metadata["enc"])) and hmac.compare_digest(
            sender.seal(plaintext, aad), ciphertext
        )
    except Exception:  # noqa: BLE001 - untrusted evidence and crypto backends fail closed
        return False
