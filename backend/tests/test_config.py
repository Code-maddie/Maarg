"""Phase 1 validation: configuration and logging behave as specified."""

import logging

from app.core.config import Settings, get_settings
from app.core.logging import JsonFormatter, configure_logging


def test_settings_are_cached() -> None:
    assert get_settings() is get_settings()


def test_cors_origins_parsed_from_comma_separated_string() -> None:
    settings = Settings(cors_origins="http://a.test, http://b.test ,")
    assert settings.cors_origins == ["http://a.test", "http://b.test"]


def test_cors_origins_accepts_a_list() -> None:
    settings = Settings(cors_origins=["http://a.test"])
    assert settings.cors_origins == ["http://a.test"]


def test_cors_origins_parsed_from_an_environment_variable(monkeypatch) -> None:
    """Regression: the deployed service reads CORS_ORIGINS from the environment.

    Passing the value to ``Settings(...)`` directly does not exercise the env
    source. Without ``NoDecode`` on the field, pydantic-settings tries to
    JSON-decode it there and raises before the validator runs, so the service
    fails to start with a comma-separated value — the documented format.
    """
    monkeypatch.setenv("CORS_ORIGINS", "https://a.test, https://b.test")
    assert Settings(_env_file=None).cors_origins == ["https://a.test", "https://b.test"]


def test_a_single_cors_origin_from_the_environment_is_not_json(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://only.test")
    assert Settings(_env_file=None).cors_origins == ["https://only.test"]


def test_log_level_is_normalised() -> None:
    assert Settings(log_level="debug").log_level == "DEBUG"


def test_is_production_flag() -> None:
    # Production refuses the auth bypass (Phase 19), and the test environment
    # sets AUTH_MODE=disabled, so production is built with auth enforced.
    assert Settings(environment="production", auth_mode="firebase").is_production is True
    assert Settings(environment="development").is_production is False


def test_paths_resolve_to_real_directories() -> None:
    settings = get_settings()
    assert settings.backend_dir.is_dir()
    assert (settings.backend_dir / "app").is_dir()
    assert settings.project_root.is_dir()


def test_e1_artifact_path_resolves_inside_backend() -> None:
    """The artifact must live under the deploy root, not the repo root.

    Render's root directory is backend/, so anything the service needs at
    runtime has to resolve there.
    """
    settings = get_settings()
    assert settings.e1_artifact_path.is_dir()
    assert settings.e1_artifact_path.is_relative_to(settings.backend_dir)
    assert (settings.e1_artifact_path / "model.pkl").exists()


# --- database URL normalisation -----------------------------------------

def test_relative_sqlite_path_is_anchored_to_backend() -> None:
    settings = Settings(database_url="sqlite:///./sh205.db")
    assert settings.resolved_database_url.endswith("/backend/sh205.db")


def test_in_memory_sqlite_is_left_alone() -> None:
    assert Settings(database_url="sqlite:///:memory:").resolved_database_url == (
        "sqlite:///:memory:"
    )


def test_legacy_postgres_scheme_is_rewritten_to_psycopg() -> None:
    """Render hands out `postgres://`, which SQLAlchemy 2 no longer accepts."""
    settings = Settings(database_url="postgres://u:p@host:5432/sh205")
    assert settings.resolved_database_url == "postgresql+psycopg://u:p@host:5432/sh205"


def test_postgresql_scheme_gets_an_explicit_driver() -> None:
    settings = Settings(database_url="postgresql://u:p@host:5432/sh205")
    assert settings.resolved_database_url == "postgresql+psycopg://u:p@host:5432/sh205"


def test_postgres_url_is_not_treated_as_sqlite() -> None:
    settings = Settings(database_url="postgres://u:p@host:5432/sh205")
    assert settings.is_sqlite is False


def test_driver_qualified_url_is_passed_through_unchanged() -> None:
    url = "postgresql+psycopg://u:p@host:5432/sh205"
    assert Settings(database_url=url).resolved_database_url == url


# --- production guardrails ----------------------------------------------

def test_production_refuses_the_auth_bypass() -> None:
    import pytest

    with pytest.raises(ValueError, match="not allowed in production"):
        Settings(environment="production", auth_mode="disabled")


def test_auth_mode_rejects_unknown_values() -> None:
    import pytest

    with pytest.raises(ValueError, match="AUTH_MODE"):
        Settings(auth_mode="off")


def test_json_formatter_emits_parseable_json() -> None:
    import json

    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hello %s", args=("world",), exc_info=None,
    )
    record.shipment_id = "SHP-1"

    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["shipment_id"] == "SHP-1"


def test_configure_logging_installs_single_handler() -> None:
    configure_logging()
    root = logging.getLogger()
    assert len(root.handlers) == 1
    # uvicorn loggers must propagate so output is not duplicated.
    assert logging.getLogger("uvicorn.access").propagate is True
