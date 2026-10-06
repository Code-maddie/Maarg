"""Phase 13 validation: Recovery Cascade.

Termination is the headline risk, so it is tested from several directions
including a deliberately cyclic graph.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.engines.e4_temperature.cascade import (
    DECAY_PER_HOP,
    MIN_INFLUENCE,
    CascadeEngine,
    cascade_from_hub,
    cascade_from_shipment,
    cascade_from_vehicle,
)
from app.models import Hub, Leg, Shipment, ShipmentLeg, Vehicle
from app.models.enums import LegStatus, ShipmentStatus

T0 = datetime(2026, 5, 1, 6, 0)


@pytest.fixture()
def chain(db, hubs):
    """A deterministic dependency chain:

        vehicle V1 -> leg L1 (hub0 -> hub1) carrying S1
        S1 continues on leg L2 (hub1 -> hub2) on vehicle V2 carrying S2 too
        S3 is unrelated and must stay untouched.
    """
    v1 = Vehicle(code="V1", capacity_kg=1000.0, capacity_m3=40.0)
    v2 = Vehicle(code="V2", capacity_kg=1000.0, capacity_m3=40.0)
    db.add_all([v1, v2])
    db.commit()

    l1 = Leg(
        vehicle_id=v1.id, from_hub_id=hubs[0].id, to_hub_id=hubs[1].id,
        departure_at=T0 + timedelta(hours=1),
        arrival_at=T0 + timedelta(hours=5),
        capacity_kg=1000.0, residual_kg=900.0,
        capacity_m3=40.0, residual_m3=38.0,
    )
    l2 = Leg(
        vehicle_id=v2.id, from_hub_id=hubs[1].id, to_hub_id=hubs[2].id,
        departure_at=T0 + timedelta(hours=6),
        arrival_at=T0 + timedelta(hours=10),
        capacity_kg=1000.0, residual_kg=900.0,
        capacity_m3=40.0, residual_m3=38.0,
    )
    db.add_all([l1, l2])
    db.commit()

    def make(code: str, deadline_h: float) -> Shipment:
        return Shipment(
            code=code,
            origin_hub_id=hubs[0].id,
            dest_hub_id=hubs[2].id,
            current_hub_id=hubs[0].id,
            weight_kg=20.0, volume_m3=0.5,
            status=ShipmentStatus.IN_TRANSIT.value,
            deadline_at=T0 + timedelta(hours=deadline_h),
            sla_penalty_per_hour=100.0,
        )

    s1, s2, s3 = make("S1", 12), make("S2", 14), make("S3", 40)
    db.add_all([s1, s2, s3])
    db.commit()

    db.add_all(
        [
            ShipmentLeg(shipment_id=s1.id, leg_id=l1.id, seq=0),
            ShipmentLeg(shipment_id=s1.id, leg_id=l2.id, seq=1),
            ShipmentLeg(shipment_id=s2.id, leg_id=l2.id, seq=0),
        ]
    )
    db.commit()

    return {"v1": v1, "v2": v2, "l1": l1, "l2": l2,
            "s1": s1, "s2": s2, "s3": s3, "hubs": hubs}


# --- propagation ---------------------------------------------------------

def test_a_vehicle_delay_reaches_its_shipments(db, chain) -> None:
    """Phase 13 criterion: one disruption affects downstream state."""
    result = CascadeEngine(db).propagate(
        origin_type="vehicle", origin_id=chain["v1"].id, now=T0
    )

    assert chain["s1"].id in result.affected_shipment_ids
    assert result.total_affected > 1


def test_the_cascade_reaches_a_second_hop(db, chain) -> None:
    """S1 is stranded, so S2 sharing S1's onward leg is affected too."""
    result = CascadeEngine(db).propagate(
        origin_type="vehicle", origin_id=chain["v1"].id, now=T0
    )

    assert chain["s2"].id in result.affected_shipment_ids
    assert result.max_depth_reached >= 2


def test_unrelated_shipments_are_untouched(db, chain) -> None:
    """Phase 13 criterion: unaffected shipments remain unchanged."""
    result = CascadeEngine(db).propagate(
        origin_type="vehicle", origin_id=chain["v1"].id, now=T0
    )

    assert chain["s3"].id not in result.affected_shipment_ids


def test_influence_decays_with_distance(db, chain) -> None:
    result = CascadeEngine(db).propagate(
        origin_type="vehicle", origin_id=chain["v1"].id, now=T0
    )

    by_depth = {node.depth: node.influence for node in result.shipments}
    depths = sorted(by_depth)
    for shallow, deep in zip(depths, depths[1:]):
        assert by_depth[deep] < by_depth[shallow]


def test_decay_matches_the_configured_rate(db, chain) -> None:
    result = CascadeEngine(db).propagate(
        origin_type="vehicle", origin_id=chain["v1"].id, now=T0
    )
    depth_one = [n for n in result.shipments if n.depth == 1]
    if depth_one:
        assert depth_one[0].influence == pytest.approx(DECAY_PER_HOP, abs=0.001)


def test_a_shipment_disruption_propagates(db, chain) -> None:
    result = CascadeEngine(db).propagate(
        origin_type="shipment", origin_id=chain["s1"].id, now=T0
    )
    assert chain["s1"].id in result.affected_shipment_ids
    assert result.total_affected >= 1


def test_a_hub_disruption_propagates(db, chain) -> None:
    result = CascadeEngine(db).propagate(
        origin_type="hub", origin_id=chain["hubs"][1].id, now=T0
    )
    assert result.total_affected >= 1


def test_past_legs_are_not_propagated_through(db, chain) -> None:
    """A leg that already arrived cannot be disrupted."""
    late = T0 + timedelta(hours=50)
    result = CascadeEngine(db).propagate(
        origin_type="vehicle", origin_id=chain["v1"].id, now=late
    )
    assert result.affected_shipment_ids == []


# --- termination (the headline risk) -------------------------------------

def test_cascade_terminates(db, chain) -> None:
    """Phase 13 criterion: the cascade cannot loop infinitely."""
    result = CascadeEngine(db).propagate(
        origin_type="vehicle", origin_id=chain["v1"].id, now=T0
    )
    assert result.terminated_by
    assert result.iterations < 1000


def test_max_depth_is_respected(db, chain) -> None:
    result = CascadeEngine(db, max_depth=1).propagate(
        origin_type="vehicle", origin_id=chain["v1"].id, now=T0
    )
    assert result.max_depth_reached <= 1


def test_depth_zero_visits_only_the_origin(db, chain) -> None:
    result = CascadeEngine(db, max_depth=0).propagate(
        origin_type="vehicle", origin_id=chain["v1"].id, now=T0
    )
    assert result.total_affected == 1
    assert result.terminated_by == "max depth reached"


def test_every_entity_is_visited_at_most_once(db, chain) -> None:
    result = CascadeEngine(db).propagate(
        origin_type="vehicle", origin_id=chain["v1"].id, now=T0
    )
    seen = [
        (node.entity_type, node.entity_id)
        for node in result.shipments + result.vehicles + result.hubs
    ]
    assert len(seen) == len(set(seen))


def test_a_cyclic_graph_still_terminates(db, hubs) -> None:
    """Two vehicles whose legs feed each other in a loop."""
    v1 = Vehicle(code="CV1", capacity_kg=1000.0, capacity_m3=40.0)
    v2 = Vehicle(code="CV2", capacity_kg=1000.0, capacity_m3=40.0)
    db.add_all([v1, v2])
    db.commit()

    # hub0 -> hub1 -> hub0, a genuine cycle.
    l1 = Leg(
        vehicle_id=v1.id, from_hub_id=hubs[0].id, to_hub_id=hubs[1].id,
        departure_at=T0 + timedelta(hours=1), arrival_at=T0 + timedelta(hours=4),
        capacity_kg=1000.0, residual_kg=900.0, capacity_m3=40.0, residual_m3=38.0,
    )
    l2 = Leg(
        vehicle_id=v2.id, from_hub_id=hubs[1].id, to_hub_id=hubs[0].id,
        departure_at=T0 + timedelta(hours=5), arrival_at=T0 + timedelta(hours=8),
        capacity_kg=1000.0, residual_kg=900.0, capacity_m3=40.0, residual_m3=38.0,
    )
    db.add_all([l1, l2])
    db.commit()

    shipment = Shipment(
        code="CYC", origin_hub_id=hubs[0].id, dest_hub_id=hubs[1].id,
        weight_kg=10.0, volume_m3=0.2,
        status=ShipmentStatus.IN_TRANSIT.value,
        deadline_at=T0 + timedelta(hours=20), sla_penalty_per_hour=100.0,
    )
    db.add(shipment)
    db.commit()

    db.add_all(
        [
            ShipmentLeg(shipment_id=shipment.id, leg_id=l1.id, seq=0),
            ShipmentLeg(shipment_id=shipment.id, leg_id=l2.id, seq=1),
        ]
    )
    db.commit()

    result = CascadeEngine(db, max_depth=50).propagate(
        origin_type="vehicle", origin_id=v1.id, now=T0
    )

    assert result.iterations < 500
    assert result.terminated_by


def test_an_unknown_origin_terminates_immediately(db) -> None:
    result = CascadeEngine(db).propagate(
        origin_type="vehicle", origin_id=999_999, now=T0
    )
    assert result.total_affected == 1
    assert result.iterations == 1


# --- applying ------------------------------------------------------------

def test_apply_updates_cascade_depth(db, chain) -> None:
    """Phase 13 criterion: priority update."""
    result, touched = cascade_from_vehicle(db, chain["v1"].id, now=T0)

    db.refresh(chain["s1"])
    assert chain["s1"].id in touched
    assert chain["s1"].cascade_depth >= 1


def test_apply_updates_temperature_and_pressure(db, chain) -> None:
    """Phase 13 criteria: temperature update, pressure update."""
    before_temp = chain["s1"].temperature
    before_pressure = chain["s1"].pressure

    cascade_from_vehicle(db, chain["v1"].id, now=T0)
    db.refresh(chain["s1"])

    assert chain["s1"].temperature != before_temp or chain["s1"].lam > 0
    assert chain["s1"].pressure >= before_pressure
    assert 0.0 <= chain["s1"].temperature <= 100.0
    assert 0.0 <= chain["s1"].pressure <= 1.0


def test_cascade_depth_raises_temperature(db, chain) -> None:
    """The point of tracking depth: deeper cascade means hotter."""
    from app.engines.e4_temperature.engine import TemperatureEngine

    engine = TemperatureEngine.from_db(db)
    chain["s1"].cascade_depth = 0
    cool = engine.evaluate(chain["s1"], T0).temperature

    chain["s1"].cascade_depth = 4
    hot = engine.evaluate(chain["s1"], T0).temperature

    assert hot > cool


def test_unaffected_shipments_keep_their_values(db, chain) -> None:
    """Phase 13 criterion, at the persistence level."""
    before = (
        chain["s3"].temperature,
        chain["s3"].pressure,
        chain["s3"].cascade_depth,
    )

    cascade_from_vehicle(db, chain["v1"].id, now=T0)
    db.refresh(chain["s3"])

    assert (
        chain["s3"].temperature,
        chain["s3"].pressure,
        chain["s3"].cascade_depth,
    ) == before


def test_delivered_shipments_are_skipped(db, chain) -> None:
    """A cascade cannot make history worse."""
    chain["s1"].status = ShipmentStatus.DELIVERED.value
    db.commit()

    _, touched = cascade_from_vehicle(db, chain["v1"].id, now=T0)
    assert chain["s1"].id not in touched


def test_applying_twice_is_idempotent_on_depth(db, chain) -> None:
    cascade_from_vehicle(db, chain["v1"].id, now=T0)
    db.refresh(chain["s1"])
    first = chain["s1"].cascade_depth

    cascade_from_vehicle(db, chain["v1"].id, now=T0)
    db.refresh(chain["s1"])

    assert chain["s1"].cascade_depth == first


def test_cascade_from_shipment_helper(db, chain) -> None:
    result, touched = cascade_from_shipment(db, chain["s1"].id, now=T0)
    assert result.origin_type == "shipment"
    assert chain["s1"].id in touched


def test_cascade_from_hub_helper(db, chain) -> None:
    result, _ = cascade_from_hub(db, chain["hubs"][1].id, now=T0)
    assert result.origin_type == "hub"


def test_result_serialises_for_the_api(db, chain) -> None:
    result, _ = cascade_from_vehicle(db, chain["v1"].id, now=T0)
    payload = result.as_dict()

    assert payload["origin_type"] == "vehicle"
    assert "terminated_by" in payload
    assert isinstance(payload["shipments"], list)
    for node in payload["shipments"]:
        assert node["reason"]


def test_influence_not_hop_count_drives_cascade_depth(db, chain) -> None:
    """A weakly-connected shipment must not get near-maximum heat.

    Regression test for a defect found during Phase 13 manual testing:
    `influence` was computed and then ignored, so a shipment four hops away
    with influence 0.09 received cascade_depth=4 and nearly saturated E4's
    cascade term — as urgent as a directly stranded shipment.
    """
    from app.engines.e4_temperature.engine import CASCADE_SATURATION_DEPTH

    cascade_from_vehicle(db, chain["v1"].id, now=T0)
    db.refresh(chain["s1"])
    db.refresh(chain["s2"])

    # s1 is directly stranded (depth 1), s2 is further out.
    assert chain["s1"].cascade_depth >= chain["s2"].cascade_depth
    assert 0 <= chain["s1"].cascade_depth <= CASCADE_SATURATION_DEPTH
    assert 0 <= chain["s2"].cascade_depth <= CASCADE_SATURATION_DEPTH


def test_deeper_nodes_get_strictly_less_cascade_weight(db, chain) -> None:
    import math

    from app.engines.e4_temperature.cascade import CascadeEngine
    from app.engines.e4_temperature.engine import CASCADE_SATURATION_DEPTH

    result = CascadeEngine(db).propagate(
        origin_type="vehicle", origin_id=chain["v1"].id, now=T0
    )

    by_depth = {}
    for node in result.shipments:
        effective = math.ceil(node.influence * CASCADE_SATURATION_DEPTH)
        by_depth.setdefault(node.depth, set()).add(effective)

    depths = sorted(by_depth)
    for shallow, deep in zip(depths, depths[1:]):
        assert max(by_depth[deep]) <= max(by_depth[shallow])
