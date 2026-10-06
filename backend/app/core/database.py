"""Database engine, session lifecycle and health probe.

Local development runs on SQLite, which needs no server. Production runs on
PostgreSQL. Everything goes through SQLAlchemy, so the only difference
between the two is the value of ``DATABASE_URL`` — no application or engine
code branches on the dialect.
"""

from collections.abc import Generator
from typing import Any, Dict

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _engine_kwargs() -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {"echo": settings.db_echo, "future": True}

    if settings.is_sqlite:
        # FastAPI serves sync endpoints from a threadpool, so a connection
        # can legitimately be used from a thread other than the one that
        # created it. SQLite rejects that unless we opt out of the check.
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # Managed Postgres closes idle connections and sits behind proxies
        # that drop them silently, so check liveness before handing one out
        # and retire connections before the server would.
        kwargs["pool_pre_ping"] = True
        kwargs["pool_size"] = settings.db_pool_size
        kwargs["max_overflow"] = settings.db_max_overflow
        kwargs["pool_recycle"] = settings.db_pool_recycle_seconds

    return kwargs


engine: Engine = create_engine(settings.resolved_database_url, **_engine_kwargs())


@event.listens_for(engine, "connect")
def _configure_sqlite(dbapi_connection, connection_record) -> None:
    """Turn on the SQLite pragmas the schema actually relies on.

    SQLite ignores FOREIGN KEY constraints unless they are enabled per
    connection, which would let orphan rows through silently. WAL mode lets
    the simulation tick loop read while a write is in flight.
    """
    if not settings.is_sqlite:
        return

    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
    finally:
        cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a session that always gets closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Creates any missing tables.

    Alembic owns schema migrations; this exists so tests and a first local
    run work without a migration step.
    """
    from app.models import Base  # imported here so every model is registered

    Base.metadata.create_all(bind=engine)
    logger.info(
        "Database ready (%s, %d tables)",
        engine.dialect.name,
        len(Base.metadata.tables),
    )


def check_database() -> bool:
    """Returns True when the database answers a trivial query."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - readiness must never raise
        logger.exception("Database health check failed")
        return False
