"""Experimental re-encryption of an isolated database snapshot.

This is not an online rotation protocol. Never call it on a live database: callers
must make an isolated consistent copy and coordinate the database and key switch.
"""

import hmac
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from memoryseal.encryption import (
    SealedMemory,
    namespace_key,
    open_memory,
    protect_salt,
    protect_source_reference,
    reveal_salt,
    reveal_source_reference,
    rewrap_memory,
    write_digest,
)
from memoryseal.memory_service import context
from memoryseal.migrations import SCHEMA_VERSION
from memoryseal.models import Memory, ProvenanceOutbox


def reencrypt_snapshot(session: Session, old_master: bytes, new_master: bytes) -> int:
    """Atomically re-encrypt memory rows in a disposable, isolated snapshot.

    Preserve salts, commitments, provenance and IDs; recompute keyed retry digests.
    Commit only after all original ciphertext, commitments and retry digests verify.
    The caller is responsible for proving isolation and securely switching the key.
    """
    if (
        len(old_master) != 32
        or len(new_master) != 32
        or hmac.compare_digest(old_master, new_master)
    ):
        raise ValueError("two distinct 32-byte master keys are required")
    if session.in_transaction():
        raise ValueError("a clean session is required")
    try:
        session.execute(text("BEGIN IMMEDIATE"))
        count = 0
        rows = session.scalars(select(Memory).order_by(Memory.id).execution_options(yield_per=200))
        for item in rows:
            old_key = namespace_key(old_master, item.owner_address, item.namespace)
            new_key = namespace_key(new_master, item.owner_address, item.namespace)
            sealed = SealedMemory(
                item.ciphertext, item.encryption_nonce, item.salt, item.commitment
            )
            binding = context(item.id, item.owner_address, item.namespace)
            plaintext = open_memory(old_key, sealed, context=binding).decode("utf-8")
            source_reference = reveal_source_reference(
                old_key, item.source_reference, item.source_reference_encrypted, context=binding
            )
            if bool(item.request_id) != bool(item.request_digest):
                raise ValueError("incomplete write retry metadata")
            if item.request_id:
                args = (
                    item.namespace,
                    plaintext,
                    item.source_type,
                    source_reference,
                    item.parent_id,
                )
                old_digest = write_digest(old_key, *args)
                if not hmac.compare_digest(old_digest, item.request_digest):
                    raise ValueError("write retry digest mismatch")
                item.request_digest = write_digest(new_key, *args)
            rotated = rewrap_memory(old_key, new_key, sealed, context=binding)
            item.source_reference_encrypted = protect_source_reference(
                new_key, source_reference, context=binding
            )
            item.source_reference = None
            item.ciphertext, item.encryption_nonce, item.salt = (
                rotated.ciphertext,
                rotated.nonce,
                rotated.salt,
            )
            count += 1
        session.commit()
        return count
    except Exception:
        session.rollback()
        raise


def _prepare_snapshot(source: Path, destination: Path, transform):
    """Make and transform an isolated copy without replacing the source."""
    source = source.resolve(strict=True)
    destination = destination.absolute()
    if not source.is_file() or destination.exists() or destination.is_symlink():
        raise ValueError("source must be a file and destination must not exist")
    with tempfile.TemporaryDirectory(
        prefix=".memoryseal-rotation-", dir=destination.parent
    ) as temp:
        snapshot = Path(temp) / "snapshot.db"
        descriptor = os.open(snapshot, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        with (
            closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original,
            closing(sqlite3.connect(snapshot)) as copy,
        ):
            original.backup(copy)
            if copy.execute("PRAGMA journal_mode=DELETE").fetchone()[0] != "delete":
                raise ValueError("snapshot journal mode could not be isolated")
        engine = create_engine(f"sqlite:///{snapshot}")
        try:
            with engine.connect() as conn:
                if conn.exec_driver_sql("PRAGMA user_version").scalar_one() != SCHEMA_VERSION:
                    raise ValueError("snapshot schema version is not current")
                if conn.exec_driver_sql("PRAGMA quick_check").scalar_one() != "ok":
                    raise ValueError("snapshot integrity check failed")
            with Session(engine) as session:
                if (
                    session.scalar(
                        select(ProvenanceOutbox.id)
                        .where(ProvenanceOutbox.state == "publishing")
                        .limit(1)
                    )
                    is not None
                ):
                    raise ValueError("snapshot contains an in-flight provenance publication")
                session.rollback()
                result = transform(session)
            with engine.connect() as conn:
                if conn.exec_driver_sql("PRAGMA quick_check").scalar_one() != "ok":
                    raise ValueError("rotated snapshot integrity check failed")
        finally:
            engine.dispose()
        # Atomic exclusive publication: never overwrite an existing destination.
        os.link(snapshot, destination)
        return result


def prepare_rotated_snapshot(
    source: Path, destination: Path, old_master: bytes, new_master: bytes
) -> int:
    """Create a rotated copy; callers must stop writers and coordinate cutover."""
    return _prepare_snapshot(
        source, destination, lambda session: reencrypt_snapshot(session, old_master, new_master)
    )


def protect_legacy_salts(session: Session, master: bytes) -> tuple[int, int]:
    """Protect salts in an isolated snapshot after checking every memory and retry digest."""
    return _protect_legacy_fields(session, master, field="salt")


def protect_legacy_sources(session: Session, master: bytes) -> tuple[int, int]:
    """Protect plaintext source references in an isolated snapshot."""
    return _protect_legacy_fields(session, master, field="source")


def _protect_legacy_fields(session: Session, master: bytes, *, field: str) -> tuple[int, int]:
    if len(master) != 32 or session.in_transaction():
        raise ValueError("a 32-byte master key and clean session are required")
    try:
        session.execute(text("BEGIN IMMEDIATE"))
        checked = protected = 0
        rows = session.scalars(select(Memory).order_by(Memory.id).execution_options(yield_per=200))
        for item in rows:
            key = namespace_key(master, item.owner_address, item.namespace)
            binding = context(item.id, item.owner_address, item.namespace)
            sealed = SealedMemory(
                item.ciphertext, item.encryption_nonce, item.salt, item.commitment
            )
            plaintext = open_memory(key, sealed, context=binding).decode("utf-8")
            source_reference = reveal_source_reference(
                key, item.source_reference, item.source_reference_encrypted, context=binding
            )
            if bool(item.request_id) != bool(item.request_digest):
                raise ValueError("incomplete write retry metadata")
            if item.request_id:
                digest = write_digest(
                    key,
                    item.namespace,
                    plaintext,
                    item.source_type,
                    source_reference,
                    item.parent_id,
                )
                if not hmac.compare_digest(digest, item.request_digest):
                    raise ValueError("write retry digest mismatch")
            if field == "salt" and len(item.salt) == 32:
                item.salt = protect_salt(key, item.salt, context=binding)
                protected += 1
            elif field == "source" and item.source_reference is not None:
                item.source_reference_encrypted = protect_source_reference(
                    key, source_reference, context=binding
                )
                item.source_reference = None
                protected += 1
            checked += 1
        session.commit()
        return checked, protected
    except Exception:
        session.rollback()
        raise


def prepare_salt_snapshot(source: Path, destination: Path, master: bytes) -> tuple[int, int]:
    """Protect legacy salts in a new snapshot without switching the live database."""
    return _prepare_snapshot(
        source, destination, lambda session: protect_legacy_salts(session, master)
    )


def prepare_source_snapshot(source: Path, destination: Path, master: bytes) -> tuple[int, int]:
    """Protect plaintext source references in a new snapshot without cutover."""
    return _prepare_snapshot(
        source, destination, lambda session: protect_legacy_sources(session, master)
    )


def verify_rotated_snapshot(
    source: Path, snapshot: Path, old_master: bytes, new_master: bytes
) -> int:
    """Compare two point-in-time database views and verify every memory under both keys.

    The caller must keep writers stopped through verification and cutover. This
    function does not monitor later changes or perform the switch.
    """
    return _verify_snapshot(source, snapshot, old_master, new_master, mode="rotation")


def verify_salt_snapshot(source: Path, snapshot: Path, master: bytes) -> int:
    """Compare a salt-only snapshot with its source without performing cutover."""
    return _verify_snapshot(source, snapshot, master, master, mode="salt")


def verify_source_snapshot(source: Path, snapshot: Path, master: bytes) -> int:
    """Compare a source-reference-only snapshot without performing cutover."""
    return _verify_snapshot(source, snapshot, master, master, mode="source")


def _verify_snapshot(
    source: Path, snapshot: Path, old_master: bytes, new_master: bytes, *, mode: str
) -> int:
    from itertools import zip_longest

    source, snapshot = source.resolve(strict=True), snapshot.resolve(strict=True)
    if not source.is_file() or not snapshot.is_file() or os.path.samefile(source, snapshot):
        raise ValueError("two distinct database files are required")
    if (
        len(old_master) != 32
        or len(new_master) != 32
        or (mode == "rotation" and hmac.compare_digest(old_master, new_master))
    ):
        raise ValueError("two distinct 32-byte master keys are required")
    with (
        closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original,
        closing(sqlite3.connect(snapshot.as_uri() + "?mode=ro", uri=True)) as rotated,
    ):
        original.row_factory = rotated.row_factory = sqlite3.Row
        for db in (original, rotated):
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            if db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                raise ValueError("database schema version is not current")
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("database integrity check failed")
            if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ValueError("database foreign key check failed")
            if db.execute(
                "SELECT 1 FROM provenance_outbox WHERE state = 'publishing' LIMIT 1"
            ).fetchone():
                raise ValueError("database contains an in-flight provenance publication")
        schema_query = "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        if [tuple(row) for row in original.execute(schema_query)] != [
            tuple(row) for row in rotated.execute(schema_query)
        ]:
            raise ValueError("database schemas differ")
        tables = [
            row[0]
            for row in original.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        rotated_tables = [
            row[0]
            for row in rotated.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        if tables != rotated_tables or "memories" not in tables:
            raise ValueError("database tables differ")
        count = 0
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            query = f"SELECT * FROM {quoted} ORDER BY rowid"
            for left, right in zip_longest(original.execute(query), rotated.execute(query)):
                if left is None or right is None or left.keys() != right.keys():
                    raise ValueError("database records differ")
                if table != "memories":
                    if tuple(left) != tuple(right):
                        raise ValueError("database records differ")
                    continue
                excluded = {
                    "ciphertext",
                    "encryption_nonce",
                    "request_digest",
                    "salt",
                    "source_reference",
                    "source_reference_encrypted",
                }
                if mode == "salt":
                    excluded = {"salt"}
                    if not isinstance(right["salt"], bytes) or len(right["salt"]) != 60:
                        raise ValueError("snapshot contains an unprotected salt")
                elif mode == "source":
                    excluded = {"source_reference", "source_reference_encrypted"}
                    if right["source_reference"] is not None:
                        raise ValueError("snapshot contains a plaintext source reference")
                if any(left[name] != right[name] for name in left.keys() if name not in excluded):  # noqa: SIM118 - sqlite Row iteration yields values
                    raise ValueError("memory metadata differs")
                binding = context(left["id"], left["owner_address"], left["namespace"])
                plaintexts = []
                salts = []
                sources = []
                for row, master in ((left, old_master), (right, new_master)):
                    key = namespace_key(master, row["owner_address"], row["namespace"])
                    plaintext = open_memory(
                        key,
                        SealedMemory(
                            row["ciphertext"],
                            row["encryption_nonce"],
                            row["salt"],
                            row["commitment"],
                        ),
                        context=binding,
                    ).decode("utf-8")
                    source_reference = reveal_source_reference(
                        key,
                        row["source_reference"],
                        row["source_reference_encrypted"],
                        context=binding,
                    )
                    if bool(row["request_id"]) != bool(row["request_digest"]):
                        raise ValueError("incomplete write retry metadata")
                    if row["request_id"]:
                        digest = write_digest(
                            key,
                            row["namespace"],
                            plaintext,
                            row["source_type"],
                            source_reference,
                            row["parent_id"],
                        )
                        if not hmac.compare_digest(digest, row["request_digest"]):
                            raise ValueError("write retry digest mismatch")
                    plaintexts.append(plaintext)
                    sources.append(source_reference)
                    salts.append(reveal_salt(key, row["salt"], context=binding))
                if (
                    plaintexts[0] != plaintexts[1]
                    or sources[0] != sources[1]
                    or not hmac.compare_digest(salts[0], salts[1])
                ):
                    raise ValueError("memory content differs")
                count += 1
        return count
