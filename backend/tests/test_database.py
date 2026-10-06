"""Phase 2 validation: engine configuration, session lifecycle, migrations."""

import subprocess
import sys
from pathlib import Path

from sqlalchemy import inspect, text

from app.core.config import BACKEND_DIR, Settings
from app.core.database import SessionLocal, check_database, engine
from app.models import Base

EXPECTED_TABLES = {
    "hubs",
    "vehicles",
    "legs",
    "shipments",
    "recovery_plans",
    "recovery_paths",
    "auctions",
    "bids",
    "users",
    "audit_logs",
    "policy_modes",
    "hub_candidates",
    "model_artifacts",
}


def test_default_database_is_sqlite() -> None:
    assert Settings().is_sqlite is True


def test_relative_sqlite_path_anchors_to_backend_dir() -> None:
    settings = Settings(database_url="sqlite:///./sh205.db")
    assert settings.resolved_database_url.endswith("/sh205.db")
    assert BACKEND_DIR.as_posix() in settings.resolved_database_url


def test_memory_database_url_is_left_alone() -> None:
    settings = Settings(database_url="sqlite:///:memory:")
    assert settings.resolved_database_url == "sqlite:///:memory:"


def test_non_sqlite_url_is_passed_through() -> None:
    url = "postgresql+psycopg://u:p@localhost:5432/db"
    assert Settings(database_url=url).resolved_database_url == url
    assert Settings(database_url=url).is_sqlite is False


def test_foreign_key_pragma_is_enabled() -> None:
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_metadata_declares_every_expected_table() -> None:
    assert EXPECTED_TABLES.issubset(set(Base.metadata.tables))


def test_session_opens_and_closes() -> None:
    session = SessionLocal()
    try:
        assert session.execute(text("SELECT 1")).scalar() == 1
    finally:
        session.close()


def test_check_database_reports_healthy() -> None:
    assert check_database() is True


def test_alembic_upgrade_creates_every_table(tmp_path: Path) -> None:
    """Runs the real migration against a throwaway database file."""
    db_file = tmp_path / "migrated.db"
    env = {
        **_clean_env(),
        "DATABASE_URL": f"sqlite:///{db_file.as_posix()}",
    }

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    from sqlalchemy import create_engine

    migrated = create_engine(f"sqlite:///{db_file.as_posix()}")
    tables = set(inspect(migrated).get_table_names())
    migrated.dispose()

    assert EXPECTED_TABLES.issubset(tables)
    assert "alembic_version" in tables


def test_alembic_downgrade_removes_every_table(tmp_path: Path) -> None:
    db_file = tmp_path / "rollback.db"
    env = {
        **_clean_env(),
        "DATABASE_URL": f"sqlite:///{db_file.as_posix()}",
    }

    up = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    assert up.returncode == 0, up.stderr

    down = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "base"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    assert down.returncode == 0, down.stderr

    from sqlalchemy import create_engine

    rolled_back = create_engine(f"sqlite:///{db_file.as_posix()}")
    tables = set(inspect(rolled_back).get_table_names())
    rolled_back.dispose()

    assert not EXPECTED_TABLES & tables


def _clean_env() -> dict[str, str]:
    """Inherited environment minus any DATABASE_URL already set."""
    import os

    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    return env
