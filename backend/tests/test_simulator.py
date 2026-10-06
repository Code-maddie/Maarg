"""Phase 4 validation: clock, world generation, tick loop, disruptions."""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.models import Hub, Leg, Shipment, Vehicle
from app.models.enums import LegStatus, ShipmentStatus
from app.workers.clock import SimulationClock
from app.workers.simulator import DisruptionType, Simulator
from app.workers.world import (
    WorldSpec,
    build_world,
    clear_world,
    road_distance_km,
    travel_hours,
)

# Small world so the suite stays fast; generation logic is identical at scale.
SMALL = WorldSpec(
    seed=42, hub_count=8, vehicle_count=12, shipment_count=40, leg_count=30
)


# --- clock ---------------------------------------------------------------

def test_clock_starts_at_zero() -> None:
    clock = SimulationClock(datetime(2026, 5, 1, 6, 0))
    assert clock.tick == 0
    assert clock.now == datetime(2026, 5, 1, 6, 0)


def test_clock_advances_by_tick_minutes() -> None:
    clock = SimulationClock(datetime(2026, 5, 1, 6, 0), tick_minutes=15)
    assert clock.advance() == datetime(2026, 5, 1, 6, 15)
    assert clock.advance(3) == datetime(2026, 5, 1, 7, 0)
    assert clock.tick == 4


def test_clock_snapshot_reports_elapsed_hours() -> None:
    clock = SimulationClock(datetime(2026, 5, 1, 6, 0), tick_minutes=30)
    clock.advance(4)
    snapshot = clock.snapshot()
    assert snapshot.tick == 4
    assert snapshot.elapsed_hours == pytest.approx(2.0)


def test_clock_reset_rewinds() -> None:
    clock = SimulationClock(datetime(2026, 5, 1, 6, 0))
    clock.advance(5)
    clock.reset()
    assert clock.tick == 0
    assert clock.now == datetime(2026, 5, 1, 6, 0)


def test_clock_rejects_bad_parameters() -> None:
    with pytest.raises(ValueError):
        SimulationClock(datetime(2026, 5, 1), tick_minutes=0)
    with pytest.raises(ValueError):
        SimulationClock(datetime(2026, 5, 1)).advance(0)


# --- distance helpers ----------------------------------------------------

def test_road_distance_exceeds_great_circle(db) -> None:
    delhi = Hub(code="D", name="D", lat=28.6139, lng=77.2090)
    mumbai = Hub(code="M", name="M", lat=19.0760, lng=72.8777)
    # ~1153 km great-circle, x1.35 road factor.
    assert road_distance_km(delhi, mumbai) == pytest.approx(1557, rel=0.02)


def test_travel_hours_has_a_floor() -> None:
    assert travel_hours(0.0) == 0.5
    assert travel_hours(450.0) == pytest.approx(10.0)


# --- world generation ----------------------------------------------------

def test_world_is_created_with_the_requested_counts(db) -> None:
    summary = build_world(db, SMALL)

    assert summary.hubs == 8
    assert summary.vehicles == 12
    assert summary.shipments == 40
    assert summary.legs == 30

    assert db.scalar(select(func.count()).select_from(Hub)) == 8
    assert db.scalar(select(func.count()).select_from(Vehicle)) == 12
    assert db.scalar(select(func.count()).select_from(Shipment)) == 40
    assert db.scalar(select(func.count()).select_from(Leg)) == 30


def test_same_seed_produces_an_identical_world(db) -> None:
    """The determinism guarantee the demo depends on."""
    build_world(db, SMALL)
    first = [
        (s.code, s.origin_hub_id, s.dest_hub_id, s.weight_kg, s.deadline_at)
        for s in db.scalars(select(Shipment).order_by(Shipment.code)).all()
    ]

    build_world(db, SMALL)
    second = [
        (s.code, s.origin_hub_id, s.dest_hub_id, s.weight_kg, s.deadline_at)
        for s in db.scalars(select(Shipment).order_by(Shipment.code)).all()
    ]

    assert first == second


def test_different_seed_produces_a_different_world(db) -> None:
    build_world(db, SMALL)
    first = [s.weight_kg for s in db.scalars(select(Shipment).order_by(Shipment.code)).all()]

    build_world(db, replace(SMALL, seed=99))
    second = [s.weight_kg for s in db.scalars(select(Shipment).order_by(Shipment.code)).all()]

    assert first != second


def test_rebuilding_replaces_rather_than_appends(db) -> None:
    build_world(db, SMALL)
    build_world(db, SMALL)
    assert db.scalar(select(func.count()).select_from(Shipment)) == 40


def test_generated_entities_are_internally_consistent(db) -> None:
    build_world(db, SMALL)

    for shipment in db.scalars(select(Shipment)).all():
        assert shipment.origin_hub_id != shipment.dest_hub_id
        assert shipment.weight_kg > 0
        assert shipment.status == ShipmentStatus.PENDING.value

    for leg in db.scalars(select(Leg)).all():
        assert leg.from_hub_id != leg.to_hub_id
        assert leg.arrival_at > leg.departure_at
        assert 0 <= leg.residual_kg <= leg.capacity_kg
        assert leg.distance_km > 0


def test_clear_world_preserves_configuration(db) -> None:
    from app.models import ModelArtifact

    build_world(db, SMALL)
    db.add(ModelArtifact(name="m", version="v1", storage_path="p"))
    db.commit()

    clear_world(db)

    assert db.scalar(select(func.count()).select_from(Hub)) == 0
    assert db.scalar(select(func.count()).select_from(Shipment)) == 0
    # Configuration must survive a world rebuild.
    assert db.scalar(select(func.count()).select_from(ModelArtifact)) == 1


# --- tick ----------------------------------------------------------------

@pytest.fixture()
def sim(db) -> Simulator:
    simulator = Simulator(spec=SMALL)
    simulator.reset(db, SMALL)
    return simulator


def test_tick_advances_the_clock(db, sim) -> None:
    before = sim.clock.now
    result = sim.tick(db)

    assert sim.clock.tick == 1
    assert sim.clock.now > before
    assert result.tick == 1


def test_tick_departs_due_legs(db, sim) -> None:
    """Advancing far enough must move legs out of SCHEDULED."""
    scheduled_before = db.scalar(
        select(func.count()).select_from(Leg).where(
            Leg.status == LegStatus.SCHEDULED.value
        )
    )
    assert scheduled_before > 0

    for _ in range(100):  # 100 x 15min = 25 simulated hours
        sim.tick(db)

    scheduled_after = db.scalar(
        select(func.count()).select_from(Leg).where(
            Leg.status == LegStatus.SCHEDULED.value
        )
    )
    assert scheduled_after < scheduled_before


def test_tick_changes_state(db, sim) -> None:
    """The Phase 4 acceptance criterion: a tick changes the world."""
    def fingerprint() -> tuple:
        legs = db.scalars(select(Leg).order_by(Leg.id)).all()
        return tuple((leg.id, leg.status) for leg in legs)

    before = fingerprint()
    for _ in range(60):
        sim.tick(db)

    assert fingerprint() != before


def test_shipment_rides_a_leg_from_departure_to_arrival(db, sim) -> None:
    shipment = db.scalars(select(Shipment).limit(1)).first()
    leg = db.scalars(
        select(Leg).where(Leg.status == LegStatus.SCHEDULED.value)
        .order_by(Leg.departure_at)
        .limit(1)
    ).first()

    # Route the shipment to this leg's destination so it counts as delivered.
    shipment.dest_hub_id = leg.to_hub_id
    shipment.current_hub_id = leg.from_hub_id
    db.commit()

    sim.assign_shipment_to_leg(db, shipment, leg)

    # Run past the leg's arrival time.
    while sim.clock.now <= leg.arrival_at + timedelta(minutes=30):
        sim.tick(db)

    db.refresh(shipment)
    db.refresh(leg)

    assert leg.status == LegStatus.ARRIVED.value
    assert shipment.current_hub_id == leg.to_hub_id
    assert shipment.status == ShipmentStatus.DELIVERED.value
    assert shipment.delivered_at is not None


def test_vehicle_position_follows_its_leg(db, sim) -> None:
    leg = db.scalars(
        select(Leg).where(Leg.status == LegStatus.SCHEDULED.value)
        .order_by(Leg.departure_at).limit(1)
    ).first()
    destination = db.get(Hub, leg.to_hub_id)

    while sim.clock.now <= leg.arrival_at + timedelta(minutes=30):
        sim.tick(db)

    vehicle = db.get(Vehicle, leg.vehicle_id)
    db.refresh(vehicle)
    assert vehicle.current_hub_id == destination.id
    assert vehicle.current_lat == pytest.approx(destination.lat)


def test_overdue_shipments_are_counted(db, sim) -> None:
    shipment = db.scalars(select(Shipment).limit(1)).first()
    shipment.deadline_at = sim.clock.now - timedelta(hours=1)
    db.commit()

    assert sim.tick(db).shipments_overdue >= 1


# --- capacity ------------------------------------------------------------

def test_assigning_a_shipment_consumes_capacity(db, sim) -> None:
    shipment = db.scalars(select(Shipment).limit(1)).first()
    leg = db.scalars(select(Leg).limit(1)).first()

    leg.residual_kg = 500.0
    leg.residual_m3 = 20.0
    shipment.weight_kg = 100.0
    shipment.volume_m3 = 2.0
    db.commit()

    sim.assign_shipment_to_leg(db, shipment, leg)
    db.refresh(leg)

    assert leg.residual_kg == pytest.approx(400.0)
    assert leg.residual_m3 == pytest.approx(18.0)


def test_overloading_a_leg_is_refused(db, sim) -> None:
    shipment = db.scalars(select(Shipment).limit(1)).first()
    leg = db.scalars(select(Leg).limit(1)).first()

    leg.residual_kg = 5.0
    shipment.weight_kg = 100.0
    db.commit()

    with pytest.raises(ValueError, match="cannot fit"):
        sim.assign_shipment_to_leg(db, shipment, leg)


def test_capacity_returns_when_the_shipment_alights(db, sim) -> None:
    shipment = db.scalars(select(Shipment).limit(1)).first()

    # Must be a leg carrying nothing else: other shipments alighting would
    # also return their capacity and muddy the assertion.
    leg = next(
        candidate
        for candidate in db.scalars(
            select(Leg)
            .where(Leg.status == LegStatus.SCHEDULED.value)
            .order_by(Leg.departure_at)
        ).all()
        if not candidate.shipment_links
    )

    leg.residual_kg = 500.0
    shipment.weight_kg = 100.0
    db.commit()

    sim.assign_shipment_to_leg(db, shipment, leg)
    db.refresh(leg)
    assert leg.residual_kg == pytest.approx(400.0)

    while sim.clock.now <= leg.arrival_at + timedelta(minutes=30):
        sim.tick(db)

    db.refresh(leg)
    assert leg.residual_kg == pytest.approx(500.0)


# --- disruptions ---------------------------------------------------------

def test_misplace_disruption_changes_shipment_state(db, sim) -> None:
    """The Phase 4 acceptance criterion for disruption injection."""
    result = sim.inject_disruption(db, DisruptionType.MISPLACE_SHIPMENT)

    shipment = db.get(Shipment, result.target_id)
    assert shipment.status == ShipmentStatus.MISPLACED.value
    assert shipment.misplaced_at is not None
    assert result.affected_shipments == [shipment.id]


def test_misplace_can_target_a_specific_shipment(db, sim) -> None:
    target = db.scalars(select(Shipment).order_by(Shipment.code).limit(1)).first()
    result = sim.inject_disruption(
        db, DisruptionType.MISPLACE_SHIPMENT, target_id=target.id
    )

    db.refresh(target)
    assert result.target_id == target.id
    assert target.status == ShipmentStatus.MISPLACED.value


def test_misplacing_releases_capacity(db, sim) -> None:
    shipment = db.scalars(select(Shipment).limit(1)).first()
    leg = db.scalars(
        select(Leg).where(Leg.status == LegStatus.SCHEDULED.value)
        .order_by(Leg.departure_at).limit(1)
    ).first()

    leg.residual_kg = 500.0
    shipment.weight_kg = 80.0
    db.commit()

    sim.assign_shipment_to_leg(db, shipment, leg)
    while sim.clock.now <= leg.departure_at:
        sim.tick(db)

    db.refresh(leg)
    consumed = leg.residual_kg

    sim.inject_disruption(
        db, DisruptionType.MISPLACE_SHIPMENT, target_id=shipment.id
    )
    db.refresh(leg)

    assert leg.residual_kg > consumed


def test_delay_disruption_pushes_arrival_times_out(db, sim) -> None:
    vehicle = db.scalars(select(Vehicle).limit(1)).first()
    leg = db.scalars(select(Leg).where(Leg.vehicle_id == vehicle.id).limit(1)).first()

    if leg is None:
        pytest.skip("seeded vehicle has no legs")

    before = leg.arrival_at
    sim.inject_disruption(
        db, DisruptionType.DELAY_VEHICLE, target_id=vehicle.id, delay_hours=6.0
    )
    db.refresh(leg)

    assert leg.arrival_at == before + timedelta(hours=6)
    assert leg.status == LegStatus.DELAYED.value


def test_close_hub_cancels_its_legs(db, sim) -> None:
    hub = db.scalars(select(Hub).limit(1)).first()
    result = sim.inject_disruption(
        db, DisruptionType.CLOSE_HUB, target_id=hub.id
    )

    db.refresh(hub)
    assert hub.is_active is False

    for leg_id in result.affected_legs:
        assert db.get(Leg, leg_id).status == LegStatus.CANCELLED.value


def test_unaffected_shipments_are_untouched(db, sim) -> None:
    """Disruption must be surgical, not global."""
    before = {
        s.id: s.status
        for s in db.scalars(select(Shipment)).all()
    }

    result = sim.inject_disruption(db, DisruptionType.MISPLACE_SHIPMENT)

    for shipment in db.scalars(select(Shipment)).all():
        if shipment.id in result.affected_shipments:
            continue
        assert shipment.status == before[shipment.id]


def test_disruption_without_a_target_fails_clearly(db) -> None:
    simulator = Simulator(spec=SMALL)
    clear_world(db)
    with pytest.raises(ValueError, match="No eligible shipment"):
        simulator.inject_disruption(db, DisruptionType.MISPLACE_SHIPMENT)


# --- state ---------------------------------------------------------------

def test_state_reports_counts(db, sim) -> None:
    state = sim.state(db)

    assert state["hubs"] == 8
    assert state["shipments"] == 40
    assert state["tick"] == 0
    assert state["seed"] == 42
    assert state["shipment_status"][ShipmentStatus.PENDING.value] == 40


def test_state_tracks_status_changes(db, sim) -> None:
    sim.inject_disruption(db, DisruptionType.MISPLACE_SHIPMENT)
    state = sim.state(db)
    assert state["shipment_status"].get(ShipmentStatus.MISPLACED.value) == 1
