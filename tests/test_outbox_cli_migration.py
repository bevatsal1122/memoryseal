import os
import subprocess
import sys

from sqlalchemy import create_engine, inspect

from memoryseal.db import Base
from memoryseal.migrations import SCHEMA_VERSION


def run_worker(tmp_path, database):
    env = {key: value for key, value in os.environ.items() if not key.startswith("MEMORYSEAL_")}
    env["MEMORYSEAL_DATABASE_URL"] = f"sqlite:///{database}"
    return subprocess.run(
        [sys.executable, "-m", "memoryseal.outbox_worker"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def test_worker_upgrades_old_schema_before_access(tmp_path):
    path = tmp_path / "old.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE provenance_outbox DROP COLUMN attempt_id")
        connection.exec_driver_sql("PRAGMA user_version = 4")
    result = run_worker(tmp_path, path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "not_configured"
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA user_version").scalar_one() == SCHEMA_VERSION
        assert "attempt_id" in {
            column["name"] for column in inspect(connection).get_columns("provenance_outbox")
        }
    engine.dispose()


def test_worker_refuses_unknown_future_schema(tmp_path):
    path = tmp_path / "future.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        connection.exec_driver_sql(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    result = run_worker(tmp_path, path)
    assert result.returncode != 0
    assert "newer than this gateway" in result.stderr
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA user_version").scalar_one() == SCHEMA_VERSION + 1
    engine.dispose()
