import pytest
from sqlalchemy import create_engine, inspect

from memoryseal import migrations
from memoryseal.db import Base
from memoryseal.migrations import SCHEMA_VERSION, migrate


def test_legacy_memory_schema_is_upgraded_without_losing_rows(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP INDEX uq_memory_agent_request_id")
        connection.exec_driver_sql("ALTER TABLE memories DROP COLUMN request_id")
        connection.exec_driver_sql("ALTER TABLE memories DROP COLUMN request_digest")
        connection.exec_driver_sql("ALTER TABLE memories DROP COLUMN source_reference_encrypted")
        for column in ("inference_status", "inference_reference", "analysis_json"):
            connection.exec_driver_sql(f"ALTER TABLE memories DROP COLUMN {column}")
        connection.exec_driver_sql("ALTER TABLE provenance_outbox DROP COLUMN creator_address")
        connection.exec_driver_sql("ALTER TABLE provenance_outbox DROP COLUMN attempt_id")
        connection.exec_driver_sql("ALTER TABLE provenance_outbox DROP COLUMN event_type")
        connection.exec_driver_sql(
            "INSERT INTO agents (id, owner_address, signing_address, revoked, created_at) VALUES ('a', 'o', 's', 0, CURRENT_TIMESTAMP)"
        )
        connection.exec_driver_sql(
            "INSERT INTO memories (id, owner_address, agent_id, namespace, source_type, category, trust_class, status, ciphertext, encryption_nonce, commitment, salt, policy_version, created_at) VALUES ('m', 'o', 'a', 'n', 'agent', 'other', 'untrusted', 'accepted', X'01', X'02', 'c', X'03', 1, CURRENT_TIMESTAMP)"
        )
        connection.exec_driver_sql(
            "INSERT INTO provenance_outbox (id, memory_id, payload, state, created_at) VALUES ('e', 'm', '{}', 'uncertain', CURRENT_TIMESTAMP)"
        )
        connection.exec_driver_sql("PRAGMA user_version = 1")
    migrate(engine)
    migrate(engine)
    assert {c["name"] for c in inspect(engine).get_columns("memories")} >= {
        "analysis_json",
        "inference_status",
        "source_reference_encrypted",
    }
    with engine.connect() as connection:
        assert (
            connection.exec_driver_sql(
                "SELECT inference_status FROM memories WHERE id='m'"
            ).scalar_one()
            == "not_configured"
        )
        assert connection.exec_driver_sql("PRAGMA user_version").scalar_one() == SCHEMA_VERSION
        assert {"creator_address", "attempt_id", "event_type"} <= {
            c["name"] for c in inspect(connection).get_columns("provenance_outbox")
        }
        assert connection.exec_driver_sql(
            "SELECT state, creator_address, event_type FROM provenance_outbox WHERE id='e'"
        ).one() == ("uncertain", None, "memory_created")
    engine.dispose()


def test_refuses_unknown_future_schema(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'future.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with pytest.raises(RuntimeError, match="newer"):
        migrate(engine)
    engine.dispose()


def test_version_five_database_upgrades_without_rewriting_salts_and_old_reader_refuses(
    tmp_path, monkeypatch
):
    engine = create_engine(f"sqlite:///{tmp_path / 'version-five.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA user_version = 5")
        connection.exec_driver_sql(
            "INSERT INTO agents (id, owner_address, signing_address, revoked, created_at) VALUES ('a', 'o', 's', 0, CURRENT_TIMESTAMP)"
        )
        connection.exec_driver_sql(
            "INSERT INTO memories (id, owner_address, agent_id, namespace, source_type, category, trust_class, status, inference_status, ciphertext, encryption_nonce, commitment, salt, policy_version, created_at) VALUES ('m', 'o', 'a', 'n', 'agent', 'other', 'untrusted', 'quarantined', 'not_configured', X'01', X'02', 'c', zeroblob(32), 1, CURRENT_TIMESTAMP)"
        )
    migrate(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA user_version").scalar_one() == SCHEMA_VERSION
        assert (
            connection.exec_driver_sql("SELECT salt FROM memories WHERE id='m'").scalar_one()
            == b"\x00" * 32
        )
    monkeypatch.setattr(migrations, "SCHEMA_VERSION", 5)
    with pytest.raises(RuntimeError, match="newer"):
        migrate(engine)
    engine.dispose()


def test_legacy_capability_amount_is_preserved_as_exact_decimal_text(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'amount.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE capabilities DROP COLUMN max_amount_text")
        connection.exec_driver_sql("ALTER TABLE capabilities ADD COLUMN max_amount INTEGER")
        connection.exec_driver_sql(
            "INSERT INTO agents (id, owner_address, signing_address, revoked, created_at) VALUES ('a', 'o', 's', 0, CURRENT_TIMESTAMP)"
        )
        connection.exec_driver_sql(
            "INSERT INTO capabilities (id, agent_id, operation, resource, max_amount, revoked, policy_version) VALUES ('c', 'a', 'transfer', 'T', 9223372036854775807, 0, 1)"
        )
        connection.exec_driver_sql("PRAGMA user_version = 3")
    migrate(engine)
    migrate(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT max_amount_text, typeof(max_amount_text) FROM capabilities WHERE id='c'"
        ).one() == ("9223372036854775807", "text")
    engine.dispose()
