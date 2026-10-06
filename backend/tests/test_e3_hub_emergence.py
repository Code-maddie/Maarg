"""Phase 11 validation: E3 Hub Emergence."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.engines.e3_hub_emergence.engine import (
    CELL_SIZE_DEGREES,
    MIN_DISTANCE_FROM_HUB_KM,
    CellStats,
    aggregate_usage,
    approve_candidate,
    cell_centre,
    cell_for,
    estimate_savings,
    generate_candidates,
    reject_candidate,
    score_cells,
    too_close_to_existing_hub,
)
from app.models import AuditLog, Hub, HubCandidate, Leg, Shipment, ShipmentLeg
from app.models.enums import AuditAction, CandidateStatus, ShipmentStatus

T0 = datetime(2026, 5, 1, 6, 0)


def stats(usage: int, risk: float, cell=(0, 0)) -> CellStats:
    instance = CellStats(cell=cell, lat=1.0, lng=1.0, usage_count=usage)
    instance.risk_total = risk * max(1, usage)
    instance.risk_samples = max(1, usage)
    return instance


# --- HubScore (SH.docx §16) ----------------------------------------------

def test_hub_score_is_usage_times_mean_risk() -> None:
    assert stats(20, 0.6).hub_score == pytest.approx(12.0)


def test_high_use_and_high_risk_beats_either_alone() -> None:
    """The whole point of the formula."""
    busy_and_risky = stats(50, 0.8).hub_score
    busy_only = stats(50, 0.05).hub_score
    risky_only = stats(3, 0.95).hub_score

    assert busy_and_risky > busy_only
    assert busy_and_risky > risky_only


def test_zero_risk_scores_zero() -> None:
    assert stats(100, 0.0).hub_score == 0.0


def test_mean_risk_without_samples_is_zero() -> None:
    empty = CellStats(cell=(0, 0), lat=0.0, lng=0.0, usage_count=10)
    assert empty.mean_risk == 0.0
    assert empty.hub_score == 0.0


# --- grid ----------------------------------------------------------------

def test_nearby_points_share_a_cell() -> None:
    assert cell_for(28.61, 77.20) == cell_for(28.70, 77.30)


def test_distant_points_do_not_share_a_cell() -> None:
    assert cell_for(28.61, 77.20) != cell_for(19.07, 72.87)


def test_cell_centre_is_inside_its_cell() -> None:
    cell = cell_for(28.61, 77.20)
    lat, lng = cell_centre(cell)
    assert cell_for(lat, lng) == cell


def test_negative_coordinates_bucket_correctly() -> None:
    assert cell_for(-10.2, -40.7) == cell_for(-10.1, -40.6)


# --- ranking -------------------------------------------------------------

def test_cells_rank_by_hub_score() -> None:
    ranked = score_cells(
        [stats(10, 0.2, (1, 1)), stats(40, 0.9, (2, 2)), stats(20, 0.5, (3, 3))],
        min_usage=5,
    )
    assert [cell.cell for cell in ranked] == [(2, 2), (3, 3), (1, 1)]


def test_under_used_cells_are_dropped() -> None:
    """Phase 11 criterion: a low-risk/quiet area must not dominate."""
    ranked = score_cells([stats(2, 0.99, (9, 9)), stats(30, 0.4, (1, 1))], min_usage=5)
    assert [cell.cell for cell in ranked] == [(1, 1)]


def test_savings_scale_with_traffic_and_risk() -> None:
    _, small = estimate_savings(stats(10, 0.2))
    _, large = estimate_savings(stats(100, 0.8))
    assert large > small


def test_setup_cost_is_reported() -> None:
    setup, _ = estimate_savings(stats(10, 0.5))
    assert setup > 0


# --- proximity guard -----------------------------------------------------

def test_a_location_near_an_existing_hub_is_excluded(db, hubs) -> None:
    delhi = hubs[0]
    assert too_close_to_existing_hub(delhi.lat + 0.01, delhi.lng, hubs) is True


def test_a_distant_location_is_allowed(db, hubs) -> None:
    assert too_close_to_existing_hub(0.0, 0.0, hubs) is False


def test_an_inactive_hub_does_not_block_a_candidate(db, hubs) -> None:
    delhi = hubs[0]
    delhi.is_active = False
    db.commit()
    assert too_close_to_existing_hub(delhi.lat, delhi.lng, [delhi]) is False


# --- aggregation over real data -----------------------------------------

@pytest.fixture()
def traffic(db):
    """A world with concentrated, risky traffic into one hub."""
    from app.workers.world import WorldSpec, build_world

    build_world(
        db,
        WorldSpec(seed=42, hub_count=10, vehicle_count=20,
                  shipment_count=60, leg_count=80),
    )

    # Give every shipment a risk score so mean_risk is meaningful.
    for index, shipment in enumerate(db.scalars(select(Shipment)).all()):
        shipment.p_misplace = 0.8 if index % 2 == 0 else 0.2
    db.commit()
    return db


def test_aggregation_produces_cells(traffic) -> None:
    cells = aggregate_usage(traffic, now=T0 + timedelta(days=1))
    assert cells
    assert all(cell.usage_count > 0 for cell in cells.values())


def test_aggregation_ignores_traffic_outside_the_window(traffic) -> None:
    recent = aggregate_usage(traffic, now=T0 + timedelta(days=1))
    ancient = aggregate_usage(traffic, now=T0 + timedelta(days=400))

    recent_total = sum(cell.usage_count for cell in recent.values())
    ancient_total = sum(cell.usage_count for cell in ancient.values())
    assert ancient_total < recent_total


def test_mean_risk_reflects_the_shipments(traffic) -> None:
    cells = aggregate_usage(traffic, now=T0 + timedelta(days=1))
    for cell in cells.values():
        if cell.risk_samples:
            assert 0.0 <= cell.mean_risk <= 1.0


# --- candidate generation ------------------------------------------------

def test_candidates_are_generated_and_persisted(traffic) -> None:
    """Phase 11 criterion: a high-risk/high-use area generates a candidate."""
    candidates = generate_candidates(
        traffic, now=T0 + timedelta(days=1), min_usage=1
    )

    assert candidates
    stored = traffic.scalars(select(HubCandidate)).all()
    assert len(stored) == len(candidates)
    assert all(c.status == CandidateStatus.PENDING.value for c in stored)


def test_candidates_are_ranked_by_score(traffic) -> None:
    candidates = generate_candidates(
        traffic, now=T0 + timedelta(days=1), min_usage=1, limit=5
    )
    scores = [c.hub_score for c in candidates]
    assert scores == sorted(scores, reverse=True)


def test_candidate_generation_respects_the_limit(traffic) -> None:
    assert len(
        generate_candidates(traffic, now=T0 + timedelta(days=1), min_usage=1, limit=2)
    ) <= 2


def test_regenerating_does_not_duplicate_candidates(traffic) -> None:
    generate_candidates(traffic, now=T0 + timedelta(days=1), min_usage=1)
    first = len(traffic.scalars(select(HubCandidate)).all())

    generate_candidates(traffic, now=T0 + timedelta(days=1), min_usage=1)
    assert len(traffic.scalars(select(HubCandidate)).all()) == first


def test_no_traffic_means_no_candidates(db) -> None:
    assert generate_candidates(db, now=T0) == []


def test_candidates_carry_a_savings_estimate(traffic) -> None:
    candidates = generate_candidates(
        traffic, now=T0 + timedelta(days=1), min_usage=1
    )
    for candidate in candidates:
        assert candidate.est_setup_cost > 0
        assert candidate.est_annual_savings >= 0


# --- approval ------------------------------------------------------------

@pytest.fixture()
def candidate(db) -> HubCandidate:
    instance = HubCandidate(
        lat=22.25, lng=75.75, usage_count=40, mean_risk=0.7, hub_score=28.0,
        est_setup_cost=2_500_000.0, est_annual_savings=900_000.0,
    )
    db.add(instance)
    db.commit()
    return instance


def test_approval_creates_a_hub(db, candidate) -> None:
    """Phase 11 criterion: approval updates the database."""
    hub = approve_candidate(db, candidate, actor_user_id=None)

    assert hub.id is not None
    assert hub.is_emergent is True
    assert hub.lat == candidate.lat
    assert candidate.status == CandidateStatus.APPROVED.value
    assert candidate.approved_hub_id == hub.id


def test_approval_writes_an_audit_entry(db, candidate) -> None:
    """SH.docx §12: approving actions must be audited."""
    approve_candidate(db, candidate, reason="Strong corridor")

    entry = db.scalar(
        select(AuditLog).where(AuditLog.action == AuditAction.APPROVE_HUB.value)
    )
    assert entry is not None
    assert entry.target_id == candidate.id
    assert "Strong corridor" in entry.reason_text


def test_the_new_hub_is_usable_by_the_router(db, candidate) -> None:
    hub = approve_candidate(db, candidate)
    assert db.scalar(select(Hub).where(Hub.id == hub.id)).is_active is True


def test_double_approval_is_refused(db, candidate) -> None:
    approve_candidate(db, candidate)
    with pytest.raises(ValueError, match="already approved"):
        approve_candidate(db, candidate)


def test_rejection_is_recorded_and_audited(db, candidate) -> None:
    reject_candidate(db, candidate, reason="Lease too expensive")

    assert candidate.status == CandidateStatus.REJECTED.value
    entry = db.scalar(
        select(AuditLog).where(AuditLog.action == AuditAction.REJECT_HUB.value)
    )
    assert entry is not None
    assert "Lease too expensive" in entry.reason_text


def test_rejection_creates_no_hub(db, candidate) -> None:
    before = len(db.scalars(select(Hub)).all())
    reject_candidate(db, candidate)
    assert len(db.scalars(select(Hub)).all()) == before
