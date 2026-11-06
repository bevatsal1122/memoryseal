"""Authenticated encryption and salted commitments for memory payloads."""

import hashlib
import hmac
import json
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


@dataclass(frozen=True)
class SealedMemory:
    ciphertext: bytes
    nonce: bytes
    salt: bytes
    commitment: str


def namespace_key(master: bytes, owner: str, namespace: str) -> bytes:
    if len(master) != 32:
        raise ValueError("master key must be 32 bytes")
    info = json.dumps(["memoryseal-namespace-v1", owner, namespace], separators=(",", ":")).encode()
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(master)


def write_digest(
    key: bytes,
    namespace: str,
    content: str,
    source_type: str,
    source_reference: str | None,
    parent_id: str | None,
) -> str:
    fields = json.dumps(
        [namespace, content, source_type, source_reference, parent_id],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return hmac.new(key, b"memoryseal:request:v1\0" + fields, hashlib.sha256).hexdigest()


def content_commitment(plaintext: bytes, salt: bytes) -> str:
    """Compute the v1 commitment; salt is private unless the owner chooses to disclose it."""
    if len(salt) != 32:
        raise ValueError("commitment salt must be 32 bytes")
    return hashlib.sha256(b"memoryseal:commitment:v1\0" + salt + plaintext).hexdigest()


def protect_salt(key: bytes, salt: bytes, *, context: bytes) -> bytes:
    """Encrypt a commitment salt independently from the memory ciphertext."""
    if len(key) != 32 or len(salt) != 32:
        raise ValueError("invalid key or commitment salt")
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, salt, b"memoryseal:salt:v1\0" + context)


def reveal_salt(key: bytes, stored_salt: bytes, *, context: bytes) -> bytes:
    """Read legacy plaintext salts or authenticated salts written by current code."""
    if len(key) != 32:
        raise ValueError("AES-256 key must be 32 bytes")
    if len(stored_salt) == 32:
        return stored_salt  # Legacy records have a plaintext salt.
    if len(stored_salt) != 60:
        raise ValueError("invalid stored salt")
    return AESGCM(key).decrypt(
        stored_salt[:12], stored_salt[12:], b"memoryseal:salt:v1\0" + context
    )


def protect_source_reference(key: bytes, reference: str | None, *, context: bytes) -> bytes | None:
    if reference is None:
        return None
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(
        nonce, reference.encode("utf-8"), b"memoryseal:source-reference:v1\0" + context
    )


def reveal_source_reference(
    key: bytes, legacy: str | None, encrypted: bytes | None, *, context: bytes
) -> str | None:
    if encrypted is None:
        return legacy
    if legacy is not None or len(encrypted) < 28:
        raise ValueError("invalid stored source reference")
    return (
        AESGCM(key)
        .decrypt(encrypted[:12], encrypted[12:], b"memoryseal:source-reference:v1\0" + context)
        .decode("utf-8")
    )


def seal(key: bytes, plaintext: bytes, *, context: bytes) -> SealedMemory:
    if len(key) != 32:
        raise ValueError("AES-256 key must be 32 bytes")
    nonce, salt = os.urandom(12), os.urandom(32)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, context)
    commitment = content_commitment(plaintext, salt)
    return SealedMemory(ciphertext, nonce, protect_salt(key, salt, context=context), commitment)


def open_memory(key: bytes, sealed: SealedMemory, *, context: bytes) -> bytes:
    plaintext = AESGCM(key).decrypt(sealed.nonce, sealed.ciphertext, context)
    salt = reveal_salt(key, sealed.salt, context=context)
    expected = content_commitment(plaintext, salt)
    if not hmac.compare_digest(expected, sealed.commitment):
        raise ValueError("memory commitment mismatch")
    return plaintext


def rewrap_memory(
    old_key: bytes, new_key: bytes, sealed: SealedMemory, *, context: bytes
) -> SealedMemory:
    """Re-encrypt a verified payload while preserving its public commitment.

    This primitive does not rotate database state, retry digests or key storage.
    """
    if len(new_key) != 32:
        raise ValueError("AES-256 key must be 32 bytes")
    plaintext = open_memory(old_key, sealed, context=context)
    salt = reveal_salt(old_key, sealed.salt, context=context)
    nonce = os.urandom(12)
    ciphertext = AESGCM(new_key).encrypt(nonce, plaintext, context)
    return SealedMemory(
        ciphertext, nonce, protect_salt(new_key, salt, context=context), sealed.commitment
    )
