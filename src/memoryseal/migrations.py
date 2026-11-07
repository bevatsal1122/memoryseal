"""Small, explicit SQLite schema migration for the development gateway."""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from memoryseal.db import Base

# Version 13 adds guided setup receipts, agent labels, and durable publication scheduling.
SCHEMA_VERSION = 14


def migrate(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        raise RuntimeError("only SQLite is supported by the development gateway")
    with engine.connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            version = connection.exec_driver_sql("PRAGMA user_version").scalar_one()
            if version > SCHEMA_VERSION:
                raise RuntimeError("database schema is newer than this gateway")
            Base.metadata.create_all(connection)
            agent_columns = {c["name"] for c in inspect(connection).get_columns("agents")}
            if "policy_chain_id" not in agent_columns:
                connection.exec_driver_sql("ALTER TABLE agents ADD COLUMN policy_chain_id INTEGER")
            if "label" not in agent_columns:
                connection.exec_driver_sql("ALTER TABLE agents ADD COLUMN label VARCHAR")
            for table in ("provenance_outbox", "vault_outbox"):
                present = {c["name"] for c in inspect(connection).get_columns(table)}
                for name, definition in {
                    "publishing_started_at": "INTEGER",
                    "next_check_at": "INTEGER NOT NULL DEFAULT 0",
                    "check_attempts": "INTEGER NOT NULL DEFAULT 0",
                }.items():
                    if name not in present:
                        connection.exec_driver_sql(
                            f"ALTER TABLE {table} ADD COLUMN {name} {definition}"
                        )
            columns = {column["name"] for column in inspect(connection).get_columns("memories")}
            if "encryption_nonce" not in columns:
                count = connection.execute(text("SELECT count(*) FROM memories")).scalar_one()
                if count:
                    raise RuntimeError(
                        "legacy memory records lack encryption nonces; manual recovery required"
                    )
                connection.exec_driver_sql(
                    "ALTER TABLE memories ADD COLUMN encryption_nonce BLOB NOT NULL DEFAULT X''"
                )
            additions = {
                "trust_class": "VARCHAR NOT NULL DEFAULT 'untrusted'",
                "inference_status": "VARCHAR NOT NULL DEFAULT 'not_configured'",
                "inference_reference": "VARCHAR",
                "analysis_json": "VARCHAR",
                "request_id": "VARCHAR",
                "request_digest": "VARCHAR",
                "source_reference_encrypted": "BLOB",
                "owner_review_commitment": "VARCHAR",
                "auto_accepted": "BOOLEAN NOT NULL DEFAULT 0",
            }
            for name, definition in additions.items():
                if name not in columns:
                    connection.exec_driver_sql(
                        f"ALTER TABLE memories ADD COLUMN {name} {definition}"
                    )
            outbox_columns = {
                column["name"] for column in inspect(connection).get_columns("provenance_outbox")
            }
            if "creator_address" not in outbox_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE provenance_outbox ADD COLUMN creator_address VARCHAR"
                )
            if "attempt_id" not in outbox_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE provenance_outbox ADD COLUMN attempt_id VARCHAR"
                )
            if "event_type" not in outbox_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE provenance_outbox ADD COLUMN event_type VARCHAR NOT NULL DEFAULT 'memory_created'"
                )
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_agent_request_id ON memories (agent_id, request_id)"
            )
            capability_columns = {
                column["name"] for column in inspect(connection).get_columns("capabilities")
            }
            if "max_amount_text" not in capability_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE capabilities ADD COLUMN max_amount_text VARCHAR(78)"
                )
                connection.exec_driver_sql(
                    "UPDATE capabilities SET max_amount_text = CAST(max_amount AS TEXT) WHERE max_amount IS NOT NULL"
                )
            connection.exec_driver_sql(f"PRAGMA user_version = {SCHEMA_VERSION}")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
