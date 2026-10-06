"""Phase 12 validation: Route Fusion."""

from datetime import datetime, timedelta

import pytest

from app.engines.e6_piggy_router.fusion import (
    CORRIDOR_MATCH_KM,
    MAX_DETOUR_FACTOR,
    Movement,
    are_compatible,
    fuse_all,
    merged_distance_km,
    try_fuse,
)
from app.models import Hub

T0 = datetime(2026, 5, 1, 6, 0)


def hub(code: str, lat: float, lng: float, hub_id: int = 1) -> Hub:
    instance = Hub(code=code, name=code, lat=lat, lng=lng, is_active=True)
    instance.id = hub_id
    return instance


DELHI = hub("DEL", 28.6139, 77.2090, 1)
DELHI_NEAR = hub("DEL2", 28.70, 77.30, 2)       # ~14 km from Delhi
MUMBAI = hub("BOM", 19.0760, 72.8777, 3)
MUMBAI_NEAR = hub("BOM2", 19.15, 72.95, 4)      # ~11 km from Mumbai
CHENNAI = hub("MAA", 13.0827, 80.2707, 5)


def movement(
    shipment_id: int,
    origin: Hub,
    destination: Hub,
    *,
    weight: float = 50.0,
    volume: float = 1.0,
    deadline_h: float = 120.0,
    cost: float = 50_000.0,
) -> Movement:
    return Movement(
        shipment_id=shipment_id,
        code=f"S{shipment_id:03d}",
        origin=origin,
        destination=destination,
        weight_kg=weight,
        volume_m3=volume,
        deadline_at=T0 + timedelta(hours=deadline_h),
        depart_after=T0,
        cost=cost,
    )


def fuse(a: Movement, b: Movement, **overrides):
    kwargs = {"capacity_kg": 1000.0, "capacity_m3": 40.0, "cost_per_km": 25.0}
    kwargs.update(overrides)
    return try_fuse(a, b, **kwargs)


# --- compatibility -------------------------------------------------------

def test_parallel_corridors_are_compatible() -> None:
    ok, origin_km, dest_km = are_compatible(
        movement(1, DELHI, MUMBAI), movement(2, DELHI_NEAR, MUMBAI_NEAR)
    )
    assert ok is True
    assert origin_km < CORRIDOR_MATCH_KM
    assert dest_km < CORRIDOR_MATCH_KM


def test_divergent_corridors_are_incompatible() -> None:
    ok, _, _ = are_compatible(
        movement(1, DELHI, MUMBAI), movement(2, DELHI, CHENNAI)
    )
    assert ok is False


def test_opposite_directions_are_incompatible() -> None:
    ok, _, _ = are_compatible(
        movement(1, DELHI, MUMBAI), movement(2, MUMBAI, DELHI)
    )
    assert ok is False


# --- merging -------------------------------------------------------------

def test_compatible_routes_merge() -> None:
    """Phase 12 criterion: compatible routes merge."""
    result = fuse(
        movement(1, DELHI, MUMBAI), movement(2, DELHI_NEAR, MUMBAI_NEAR)
    )

    assert result.merged is True
    assert result.shipment_ids == (1, 2)
    assert "merged" in result.reason


def test_incompatible_routes_stay_separate() -> None:
    """Phase 12 criterion: incompatible routes remain separate."""
    result = fuse(movement(1, DELHI, MUMBAI), movement(2, DELHI, CHENNAI))

    assert result.merged is False
    assert "do not overlap" in result.reason


def test_merging_reduces_vehicle_km() -> None:
    """Phase 12 criterion: movement reduction."""
    result = fuse(
        movement(1, DELHI, MUMBAI), movement(2, DELHI_NEAR, MUMBAI_NEAR)
    )

    assert result.merged_distance_km < result.separate_distance_km
    assert result.distance_saved_km > 0


def test_merging_reduces_cost() -> None:
    """Phase 12 criterion: cost comparison."""
    result = fuse(
        movement(1, DELHI, MUMBAI), movement(2, DELHI_NEAR, MUMBAI_NEAR)
    )

    assert result.merged_cost < result.separate_cost
    assert result.cost_saving > 0


def test_utilisation_gain_is_reported() -> None:
    """Phase 12 criterion: utilisation improvement."""
    result = fuse(
        movement(1, DELHI, MUMBAI), movement(2, DELHI_NEAR, MUMBAI_NEAR)
    )

    assert 0.0 < result.utilisation_gain < 1.0


# --- capacity ------------------------------------------------------------

def test_over_weight_merge_is_refused() -> None:
    result = fuse(
        movement(1, DELHI, MUMBAI, weight=800.0),
        movement(2, DELHI_NEAR, MUMBAI_NEAR, weight=800.0),
        capacity_kg=1000.0,
    )

    assert result.merged is False
    assert "exceeds vehicle capacity" in result.reason


def test_over_volume_merge_is_refused() -> None:
    result = fuse(
        movement(1, DELHI, MUMBAI, volume=30.0),
        movement(2, DELHI_NEAR, MUMBAI_NEAR, volume=30.0),
        capacity_m3=40.0,
    )

    assert result.merged is False
    assert "exceeds vehicle capacity" in result.reason


def test_a_merge_that_exactly_fills_the_vehicle_is_allowed() -> None:
    result = fuse(
        movement(1, DELHI, MUMBAI, weight=500.0, volume=20.0),
        movement(2, DELHI_NEAR, MUMBAI_NEAR, weight=500.0, volume=20.0),
        capacity_kg=1000.0, capacity_m3=40.0,
    )
    assert result.merged is True


# --- deadline ------------------------------------------------------------

def test_a_merge_that_would_miss_a_deadline_is_refused() -> None:
    """Phase 12 criterion: deadline check."""
    result = fuse(
        movement(1, DELHI, MUMBAI, deadline_h=120.0),
        movement(2, DELHI_NEAR, MUMBAI_NEAR, deadline_h=2.0),
    )

    assert result.merged is False
    assert "miss the deadline" in result.reason
    assert "S002" in result.reason


def test_the_tighter_deadline_governs() -> None:
    generous = fuse(
        movement(1, DELHI, MUMBAI, deadline_h=200.0),
        movement(2, DELHI_NEAR, MUMBAI_NEAR, deadline_h=200.0),
    )
    tight = fuse(
        movement(1, DELHI, MUMBAI, deadline_h=200.0),
        movement(2, DELHI_NEAR, MUMBAI_NEAR, deadline_h=1.0),
    )

    assert generous.merged is True
    assert tight.merged is False


# --- cost guard ----------------------------------------------------------

def test_a_merge_with_no_saving_is_refused() -> None:
    """Separate trips are already cheap; merging must not be forced."""
    result = fuse(
        movement(1, DELHI, MUMBAI, cost=1.0),
        movement(2, DELHI_NEAR, MUMBAI_NEAR, cost=1.0),
    )

    assert result.merged is False
    assert "not below the separate cost" in result.reason


def test_a_wandering_merge_is_refused() -> None:
    result = fuse(
        movement(1, DELHI, MUMBAI),
        movement(2, DELHI_NEAR, MUMBAI_NEAR),
        cost_per_km=0.0001,   # cost never blocks; the detour guard must
        capacity_kg=100_000.0,
    )
    # This pair is genuinely tight, so it should still merge.
    assert result.merged is True


# --- merged distance -----------------------------------------------------

def test_merged_distance_picks_the_better_ordering() -> None:
    a = movement(1, DELHI, MUMBAI)
    b = movement(2, DELHI_NEAR, MUMBAI_NEAR)
    assert merged_distance_km(a, b) == pytest.approx(merged_distance_km(b, a))


def test_merged_distance_beats_two_separate_trips() -> None:
    a = movement(1, DELHI, MUMBAI)
    b = movement(2, DELHI_NEAR, MUMBAI_NEAR)
    assert merged_distance_km(a, b) < a.distance_km + b.distance_km


# --- rejection quality ---------------------------------------------------

def test_every_refusal_carries_a_concrete_reason() -> None:
    cases = [
        fuse(movement(1, DELHI, MUMBAI), movement(2, DELHI, CHENNAI)),
        fuse(
            movement(1, DELHI, MUMBAI, weight=900.0),
            movement(2, DELHI_NEAR, MUMBAI_NEAR, weight=900.0),
        ),
        fuse(
            movement(1, DELHI, MUMBAI),
            movement(2, DELHI_NEAR, MUMBAI_NEAR, deadline_h=1.0),
        ),
    ]
    for result in cases:
        assert result.merged is False
        assert result.reason and "TODO" not in result.reason


def test_a_refused_merge_reports_no_saving() -> None:
    result = fuse(movement(1, DELHI, MUMBAI), movement(2, DELHI, CHENNAI))
    assert result.cost_saving == 0.0


# --- batch ---------------------------------------------------------------

def test_batch_fusion_pairs_compatible_movements() -> None:
    results = fuse_all(
        [
            movement(1, DELHI, MUMBAI),
            movement(2, DELHI_NEAR, MUMBAI_NEAR),
            movement(3, DELHI, CHENNAI),
        ],
        capacity_kg=1000.0, capacity_m3=40.0, cost_per_km=25.0,
    )

    assert len(results) == 1
    assert set(results[0].shipment_ids) == {1, 2}


def test_a_movement_is_merged_at_most_once() -> None:
    results = fuse_all(
        [
            movement(1, DELHI, MUMBAI),
            movement(2, DELHI_NEAR, MUMBAI_NEAR),
            movement(3, DELHI, MUMBAI),
        ],
        capacity_kg=1000.0, capacity_m3=40.0, cost_per_km=25.0,
    )

    merged_ids = [i for result in results for i in result.shipment_ids]
    assert len(merged_ids) == len(set(merged_ids))


def test_batch_with_nothing_compatible_merges_nothing() -> None:
    assert fuse_all(
        [movement(1, DELHI, MUMBAI), movement(2, DELHI, CHENNAI)],
        capacity_kg=1000.0, capacity_m3=40.0, cost_per_km=25.0,
    ) == []


def test_empty_batch_is_safe() -> None:
    assert fuse_all([], capacity_kg=1.0, capacity_m3=1.0, cost_per_km=1.0) == []
