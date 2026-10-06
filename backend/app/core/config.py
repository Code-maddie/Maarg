"""Application configuration.

Settings are read from environment variables and from ``backend/.env``.
Anything that varies between machines or environments belongs here, so no
other module needs to touch ``os.environ`` directly.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, List

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# backend/app/core/config.py -> backend/
BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Typed view of the backend environment."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_name: str = "SH-205 Intelligent Shipment Piggybacking"
    app_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = True

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8000

    # --- Logging ---
    log_level: str = "INFO"
    log_json: bool = False

    # --- CORS ---
    # Exact origins allowed to call the API. In production this is the
    # Vercel production domain (plus any custom domain).
    #
    # NoDecode is load-bearing: without it pydantic-settings tries to
    # JSON-decode any list-typed field read from the environment, and a
    # comma-separated CORS_ORIGINS raises SettingsError before the validator
    # below ever runs — the service would refuse to start.
    cors_origins: Annotated[List[str], NoDecode] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:8080",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
    ]

    # Vercel gives every preview deployment a unique generated hostname, so
    # they cannot be enumerated ahead of time. This regex admits them as a
    # group. Set it empty to allow only the exact origins above.
    cors_origin_regex: str = r"https://.*\.vercel\.app"

    # --- API ---
    api_v1_prefix: str = "/api/v1"

    # --- E1 model ---
    # Directory holding model.pkl + feature_pipeline.joblib. Relative paths
    # resolve against backend/, so the deploy root is self-contained.
    # These artifacts are READ-ONLY.
    #
    # v2 is the serving artifact: same feature contract as the v1 training
    # output, but depth-capped to 0.4 MB instead of 214 MB. See
    # e1-model/softHack/scripts/export_serving_model.py.
    e1_artifact_dir: str = "artifacts/misplacement_classifier/v2"
    e1_model_version: str = "v2"

    # v2 unpickles in well under a second, but loading still happens off the
    # request path so a cold start never blocks on it.
    e1_eager_load: bool = True
    e1_load_timeout_seconds: float = 120.0

    # --- Firebase ---
    # Two ways to supply the service account, checked in this order:
    #
    #   1. FIREBASE_CREDENTIALS_JSON — the whole service-account JSON as one
    #      environment variable. This is the production path: hosts like
    #      Render have no persistent place to put a secret file, and a
    #      credential in the environment never risks being committed.
    #   2. FIREBASE_CREDENTIALS_PATH — a file on disk, for local development.
    #
    # Neither value is ever logged or returned by an endpoint.
    firebase_credentials_json: str = ""
    firebase_credentials_path: str = "credentials/firebase-credentials.json"

    # "firebase": every protected route requires a verified Firebase ID token.
    # "disabled": local development bypass — every request is treated as a
    #             dev admin. Refused outright when ENVIRONMENT=production.
    auth_mode: str = "firebase"

    # Firestore push notifications (SH.docx §8.2). Off by default so tests
    # and local runs never write to the live Firebase project.
    firestore_enabled: bool = False

    # The Firebase *web* config the browser needs to sign in. These four
    # fields are public by design in Firebase — they identify the project to
    # the client SDK and are not credentials. The static frontend has no
    # build step that could inline them, so the backend serves them from
    # GET /auth/web-config.
    #
    # In production these come from the environment. Locally, if they are
    # unset, they are read from `frontend_env_path` so an existing checkout
    # keeps working with no extra setup.
    firebase_api_key: str = ""
    firebase_auth_domain: str = ""
    firebase_project_id: str = ""
    firebase_app_id: str = ""
    frontend_env_path: str = "frontend/.env"

    # --- Database ---
    # SQLite by default so a local checkout runs with no database server.
    # In production set DATABASE_URL to PostgreSQL; nothing in the
    # application depends on the dialect.
    database_url: str = "sqlite:///./sh205.db"
    db_echo: bool = False

    # Connection pool. Managed Postgres plans cap total connections quite
    # low, so these stay modest by default.
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_recycle_seconds: int = 1800

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept ``CORS_ORIGINS`` as a comma-separated string.

        pydantic-settings would otherwise try to JSON-decode a list field,
        which makes the .env file awkward to write by hand.
        """
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalise_log_level(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("auth_mode", mode="before")
    @classmethod
    def _normalise_auth_mode(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip().lower()
            if value not in {"firebase", "disabled"}:
                raise ValueError("AUTH_MODE must be 'firebase' or 'disabled'")
        return value

    @model_validator(mode="after")
    def _no_auth_bypass_in_production(self) -> "Settings":
        """The dev bypass must never be reachable in production."""
        if self.is_production and self.auth_mode == "disabled":
            raise ValueError("AUTH_MODE=disabled is not allowed in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    @property
    def auth_enabled(self) -> bool:
        return self.auth_mode == "firebase"

    @property
    def firebase_credentials_file(self) -> Path:
        path = Path(self.firebase_credentials_path)
        return path if path.is_absolute() else BACKEND_DIR / path

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def resolved_database_url(self) -> str:
        """The URL actually handed to SQLAlchemy.

        Two normalisations happen here so nothing downstream has to care:

        * Relative SQLite paths are anchored to ``backend/``. Otherwise the
          database file lands wherever the process happened to start.
        * Render (and Heroku) hand out ``postgres://`` URLs, a scheme
          SQLAlchemy 2 removed. They are rewritten to the psycopg 3 driver
          so the platform's value can be used verbatim.
        """
        url = self.database_url
        for legacy in ("postgres://", "postgresql://"):
            if url.startswith(legacy):
                return "postgresql+psycopg://" + url[len(legacy) :]

        prefix = "sqlite:///"
        if not url.startswith(prefix):
            return url

        raw = url[len(prefix) :]
        if raw.startswith(":memory:") or raw == "":
            return self.database_url

        path = Path(raw)
        if not path.is_absolute():
            path = BACKEND_DIR / raw.lstrip("./\\")
        return f"{prefix}{path.as_posix()}"

    @property
    def e1_artifact_path(self) -> Path:
        """Absolute path to the E1 artifact directory."""
        path = Path(self.e1_artifact_dir)
        return path if path.is_absolute() else BACKEND_DIR / path

    @property
    def backend_dir(self) -> Path:
        return BACKEND_DIR

    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT


@lru_cache
def get_settings() -> Settings:
    """Returns the process-wide settings instance."""
    return Settings()


settings = get_settings()
