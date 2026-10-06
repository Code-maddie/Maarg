"""Shared test fixtures.

Every test gets a throwaway file-backed SQLite database. A file rather than
``:memory:`` so the connection pool and the FOREIGN KEY pragma behave exactly
as they do at runtime.
"""

import os

# Must run before anything imports app.core.config (settings are cached).
# Suites written before Phase 19 exercise behaviour, not auth, so they run in
# dev-bypass mode. tests/test_auth.py switches enforcement back on and
# substitutes the token verifier — no test ever calls the live Firebase
# project, and Firestore stays disabled.
os.environ["AUTH_MODE"] = "disabled"
os.environ["FIRESTORE_ENABLED"] = "false"

from datetime import timedelta  # noqa: E402
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, Hub, Shipment, Vehicle, utcnow
from app.models.enums import ShipmentStatus


@pytest.fixture()
def db(tmp_path: Path) -> Iterator[Session]:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_connection, connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def hubs(db: Session) -> list[Hub]:
    """Three real Indian hub locations, used for distance assertions."""
    created = [
        Hub(code="DEL", name="Delhi Hub", lat=28.6139, lng=77.2090),
        Hub(code="BOM", name="Mumbai Hub", lat=19.0760, lng=72.8777),
        Hub(code="BLR", name="Bengaluru Hub", lat=12.9716, lng=77.5946),
    ]
    db.add_all(created)
    db.commit()
    return created


@pytest.fixture()
def vehicle(db: Session, hubs: list[Hub]) -> Vehicle:
    created = Vehicle(
        code="TRK-12", capacity_kg=500.0, capacity_m3=20.0, current_hub_id=hubs[0].id
    )
    db.add(created)
    db.commit()
    return created


@pytest.fixture()
def shipment(db: Session, hubs: list[Hub]) -> Shipment:
    created = Shipment(
        code="S204",
        origin_hub_id=hubs[0].id,
        dest_hub_id=hubs[1].id,
        current_hub_id=hubs[0].id,
        weight_kg=25.0,
        volume_m3=0.5,
        status=ShipmentStatus.IN_TRANSIT.value,
        deadline_at=utcnow() + timedelta(hours=12),
        sla_penalty_per_hour=100.0,
    )
    db.add(created)
    db.commit()
    return created
