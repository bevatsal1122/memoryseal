import os

import pytest
from cryptography.exceptions import InvalidTag

from memoryseal.encryption import (
    SealedMemory,
    content_commitment,
    open_memory,
    protect_source_reference,
    reveal_salt,
    reveal_source_reference,
    rewrap_memory,
    seal,
)


def test_source_reference_encryption_is_context_bound_and_legacy_readable():
    key = os.urandom(32)
    reference = "https://example.test/private?token=secret"
    encrypted = protect_source_reference(key, reference, context=b"memory-1")
    assert reference.encode() not in encrypted
    assert reveal_source_reference(key, None, encrypted, context=b"memory-1") == reference
    assert reveal_source_reference(key, reference, None, context=b"memory-1") == reference
    with pytest.raises(InvalidTag):
        reveal_source_reference(key, None, encrypted, context=b"memory-2")
    with pytest.raises(InvalidTag):
        reveal_source_reference(
            key, None, encrypted[:-1] + bytes([encrypted[-1] ^ 1]), context=b"memory-1"
        )
    with pytest.raises(ValueError):
        reveal_source_reference(key, reference, encrypted, context=b"memory-1")


def test_payload_encryption_binds_context_and_uses_random_salt():
    key = os.urandom(32)
    a = seal(key, b"private memory", context=b"owner:namespace")
    b = seal(key, b"private memory", context=b"owner:namespace")
    assert b"private memory" not in a.ciphertext
    assert a.commitment != b.commitment
    assert len(a.salt) == 60
    salt = reveal_salt(key, a.salt, context=b"owner:namespace")
    assert salt not in a.salt
    assert content_commitment(b"private memory", salt) == a.commitment
    assert open_memory(key, a, context=b"owner:namespace") == b"private memory"
    with pytest.raises(InvalidTag):
        open_memory(key, a, context=b"different namespace")


def test_rewrap_preserves_commitment_and_requires_valid_original():
    old, new = os.urandom(32), os.urandom(32)
    sealed = seal(old, b"private memory", context=b"owner:namespace")
    rotated = rewrap_memory(old, new, sealed, context=b"owner:namespace")
    assert rotated.commitment == sealed.commitment
    assert rotated.salt != sealed.salt
    assert reveal_salt(new, rotated.salt, context=b"owner:namespace") == reveal_salt(
        old, sealed.salt, context=b"owner:namespace"
    )
    assert rotated.nonce != sealed.nonce
    assert open_memory(new, rotated, context=b"owner:namespace") == b"private memory"
    with pytest.raises(InvalidTag):
        open_memory(old, rotated, context=b"owner:namespace")
    with pytest.raises(InvalidTag):
        rewrap_memory(os.urandom(32), new, sealed, context=b"owner:namespace")
    tampered = SealedMemory(sealed.ciphertext, sealed.nonce, sealed.salt, "0" * 64)
    with pytest.raises(ValueError, match="commitment"):
        rewrap_memory(old, new, tampered, context=b"owner:namespace")


def test_legacy_salt_read_and_rewrap_upgrade():
    key, new_key, salt = os.urandom(32), os.urandom(32), os.urandom(32)
    payload = b"short guessable memory"
    current = seal(key, payload, context=b"scope")
    legacy = SealedMemory(
        current.ciphertext, current.nonce, salt, content_commitment(payload, salt)
    )
    assert open_memory(key, legacy, context=b"scope") == payload
    rotated = rewrap_memory(key, new_key, legacy, context=b"scope")
    assert len(rotated.salt) == 60
    assert reveal_salt(new_key, rotated.salt, context=b"scope") == salt
    assert rotated.commitment == legacy.commitment
    assert open_memory(new_key, rotated, context=b"scope") == payload


def test_protected_salt_rejects_tampering_and_wrong_context():
    key = os.urandom(32)
    sealed = seal(key, b"private", context=b"scope")
    corrupt = sealed.salt[:-1] + bytes([sealed.salt[-1] ^ 1])
    with pytest.raises(InvalidTag):
        open_memory(
            key,
            SealedMemory(sealed.ciphertext, sealed.nonce, corrupt, sealed.commitment),
            context=b"scope",
        )
    with pytest.raises(InvalidTag):
        reveal_salt(key, sealed.salt, context=b"other scope")
