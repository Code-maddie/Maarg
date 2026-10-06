"""Phase 2 validation: CRUD, relationships and constraints for every table."""

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import (
    Auction,
    AuditLog,
    Bid,
    Hub,
    HubCandidate,
    Leg,
    ModelArtifact,
    PolicyMode,
    RecoveryPath,
    RecoveryPlan,
    Shipment,
    User,
    Vehicle,
    utcnow,
)
from app.models.enums import (
    AuctionStatus,
    AuditAction,
    CandidateStatus,
    PlanStrategy,
    ShipmentStatus,
    TemperatureZone,
    UserRole,
)


# --- Hub -----------------------------------------------------------------

def test_hub_crud(db, hubs) -> None:
    fetched = db.scalar(select(Hub).where(Hub.code == "DEL"))
    assert fetched.name == "Delhi Hub"

    fetched.name = "Delhi Central"
    db.commit()
    assert db.scalar(select(Hub).where(Hub.code == "DEL")).name == "Delhi Central"

    db.delete(fetched)
    db.commit()
    assert db.scalar(select(Hub).where(Hub.code == "DEL")) is None


def test_hub_code_is_unique(db, hubs) -> None:
    db.add(Hub(code="DEL", name="Duplicate", lat=0.0, lng=0.0))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_hub_timestamps_are_populated(db, hubs) -> None:
    assert hubs[0].created_at is not None
    assert hubs[0].updated_at is not None


# --- Vehicle -------------------------------------------------------------

def test_vehicle_crud_and_defaults(db, vehicle) -> None:
    assert vehicle.vehicle_type == "OWNED"
    assert vehicle.reliability == pytest.approx(0.9)
    assert vehicle.capacity_kg == 500.0


# --- Leg -----------------------------------------------------------------

@pytest.fixture()
def leg(db, hubs, vehicle) -> Leg:
    now = utcnow()
    created = Leg(
        vehicle_id=vehicle.id,
        from_hub_id=hubs[0].id,
        to_hub_id=hubs[1].id,
        departure_at=now,
        arrival_at=now + timedelta(hours=3),
        capacity_kg=500.0,
        residual_kg=85.0,
        capacity_m3=20.0,
        residual_m3=4.0,
    )
    db.add(created)
    db.commit()
    return created


def test_leg_transit_hours(db, leg) -> None:
    assert leg.transit_hours == pytest.approx(3.0)


def test_leg_capacity_check(db, leg) -> None:
    assert leg.can_fit(50.0, 1.0) is True
    assert leg.can_fit(500.0, 1.0) is False   # over weight
    assert leg.can_fit(50.0, 10.0) is False   # over volume


def test_leg_relationships(db, leg, hubs, vehicle) -> None:
    assert leg.vehicle.code == vehicle.code
    assert leg.from_hub.code == "DEL"
    assert leg.to_hub.code == "BOM"


def test_leg_foreign_key_is_enforced(db, hubs) -> None:
    """SQLite ignores FKs unless the pragma is on — this proves it is."""
    now = utcnow()
    db.add(
        Leg(
            vehicle_id=999999,
            from_hub_id=hubs[0].id,
            to_hub_id=hubs[1].id,
            departure_at=now,
            arrival_at=now + timedelta(hours=1),
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_deleting_vehicle_cascades_to_legs(db, leg, vehicle) -> None:
    db.delete(vehicle)
    db.commit()
    assert db.scalars(select(Leg)).all() == []


# --- Shipment ------------------------------------------------------------

def test_shipment_crud_and_defaults(db, shipment) -> None:
    assert shipment.status == ShipmentStatus.IN_TRANSIT.value
    assert shipment.temperature == 0.0
    assert shipment.p_misplace is None


@pytest.mark.parametrize(
    ("temperature", "expected"),
    [
        (0.0, TemperatureZone.COLD),
        (33.9, TemperatureZone.COLD),
        (34.0, TemperatureZone.WARMING),
        (66.9, TemperatureZone.WARMING),
        (67.0, TemperatureZone.HOT),
        (100.0, TemperatureZone.HOT),
    ],
)
def test_temperature_zone_banding(db, shipment, temperature, expected) -> None:
    shipment.temperature = temperature
    assert shipment.temperature_zone == expected


def test_hours_to_deadline_goes_negative_when_overdue(db, shipment) -> None:
    now = utcnow()
    assert shipment.hours_to_deadline(now) == pytest.approx(12.0, abs=0.01)
    assert shipment.hours_to_deadline(now + timedelta(hours=20)) < 0


# --- RecoveryPlan / RecoveryPath ----------------------------------------

@pytest.fixture()
def plan(db, shipment, hubs) -> RecoveryPlan:
    created = RecoveryPlan(
        shipment_id=shipment.id,
        strategy=PlanStrategy.PIGGYBACK.value,
        rank=1,
        total_cost=1200.0,
    )
    created.paths = [
        RecoveryPath(seq=0, from_hub_id=hubs[0].id, to_hub_id=hubs[2].id),
        RecoveryPath(seq=1, from_hub_id=hubs[2].id, to_hub_id=hubs[1].id),
    ]
    db.add(created)
    db.commit()
    return created


def test_plan_paths_come_back_in_sequence(db, plan) -> None:
    assert [p.seq for p in plan.paths] == [0, 1]


def test_plan_path_seq_is_unique_per_plan(db, plan, hubs) -> None:
    db.add(
        RecoveryPath(
            plan_id=plan.id, seq=0, from_hub_id=hubs[0].id, to_hub_id=hubs[1].id
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_deleting_plan_cascades_to_paths(db, plan) -> None:
    db.delete(plan)
    db.commit()
    assert db.scalars(select(RecoveryPath)).all() == []


def test_deleting_shipment_cascades_to_plans(db, shipment, plan) -> None:
    db.delete(shipment)
    db.commit()
    assert db.scalars(select(RecoveryPlan)).all() == []
    assert db.scalars(select(RecoveryPath)).all() == []


# --- Auction / Bid -------------------------------------------------------

@pytest.fixture()
def auction(db, shipment) -> Auction:
    now = utcnow()
    created = Auction(
        shipment_id=shipment.id,
        max_bounty=800.0,
        opened_at=now,
        closes_at=now + timedelta(minutes=5),
    )
    db.add(created)
    db.commit()
    return created


def test_auction_defaults_to_open(db, auction) -> None:
    assert auction.status == AuctionStatus.OPEN.value


def test_bids_attach_to_auction(db, auction, vehicle) -> None:
    db.add(Bid(auction_id=auction.id, vehicle_id=vehicle.id, amount=480.0))
    db.commit()
    db.refresh(auction)
    assert len(auction.bids) == 1
    assert auction.bids[0].amount == 480.0


def test_vehicle_can_bid_only_once_per_auction(db, auction, vehicle) -> None:
    db.add(Bid(auction_id=auction.id, vehicle_id=vehicle.id, amount=480.0))
    db.commit()
    db.add(Bid(auction_id=auction.id, vehicle_id=vehicle.id, amount=400.0))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_deleting_auction_cascades_to_bids(db, auction, vehicle) -> None:
    db.add(Bid(auction_id=auction.id, vehicle_id=vehicle.id, amount=480.0))
    db.commit()
    db.delete(auction)
    db.commit()
    assert db.scalars(select(Bid)).all() == []


# --- Product-layer tables ------------------------------------------------

def test_user_crud_and_unique_email(db) -> None:
    db.add(User(email="ops@example.com", role=UserRole.DISPATCHER.value))
    db.commit()
    assert db.scalar(select(User).where(User.email == "ops@example.com")).role == "DISPATCHER"

    db.add(User(email="ops@example.com"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_audit_log_records_an_action(db) -> None:
    db.add(
        AuditLog(
            action=AuditAction.OVERRIDE_PLAN.value,
            target_type="RecoveryPlan",
            target_id=1,
            reason_text="Dispatcher preferred the hybrid route.",
        )
    )
    db.commit()
    entry = db.scalar(select(AuditLog))
    assert entry.action == "OVERRIDE_PLAN"
    assert entry.timestamp is not None


def test_policy_mode_stores_weights(db) -> None:
    db.add(PolicyMode(mode="SLA_STRICT", weights_json='{"w_time": 2.0}'))
    db.commit()
    assert db.scalar(select(PolicyMode)).mode == "SLA_STRICT"


def test_hub_candidate_defaults_to_pending(db) -> None:
    db.add(HubCandidate(lat=22.5, lng=75.9, usage_count=40, mean_risk=0.7, hub_score=28.0))
    db.commit()
    assert db.scalar(select(HubCandidate)).status == CandidateStatus.PENDING.value


def test_model_artifact_version_is_unique_per_name(db) -> None:
    db.add(
        ModelArtifact(
            name="misplacement_classifier", version="v1", storage_path="a", is_active=True
        )
    )
    db.commit()
    db.add(
        ModelArtifact(
            name="misplacement_classifier", version="v1", storage_path="b"
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
