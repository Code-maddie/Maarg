"""Regression tests for defects found in the final system audit.

Each test reproduces the original failure first-hand; see srihitha.md
"FINAL SYSTEM AUDIT" for root causes.
"""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.engines.e4_temperature.pressure import EMERGENCY_THRESHOLD
from app.engines.e7_graph_memory.cache import InProcessCache
from app.engines.e7_graph_memory.memory import GraphMemory
from app.engines.e7_graph_memory.planner import plan_recovery
from app.models import (
    Auction,
    Leg,
    RecoveryOutcome,
    RecoveryPlan,
    Shipment,
    ShipmentLeg,
)
from app.models.enums import LegStatus, PlanStatus, ShipmentStatus
from app.services.orchestrator import RecoveryOrchestrator
from app.workers.simulator import DisruptionType, Simulator
from app.workers.world import WorldSpec

SPEC = WorldSpec(seed=42, hub_count=12, vehicle_count=40, shipment_count=120, leg_count=260)


class StubE1:
    def score(self, features):  # noqa: ANN001
        return 0.6


@pytest.fixture()
def sim(db):
    simulator = Simulator(spec=SPEC)
    simulator.reset(db, SPEC)
    for _ in range(8):
        simulator.tick(db)
    return simulator


def recover(db, sim, shipment=None):
    if shipment is None:
        d = sim.inject_disruption(db, DisruptionType.MISPLACE_SHIPMENT)
        shipment = db.get(Shipment, d.target_id)
    shipment.deadline_at = sim.clock.now + timedelta(hours=70)
    db.commit()
    return shipment, RecoveryOrchestrator(db, e1_service=StubE1()).recover(shipment, now=sim.clock.now)


def piggyback_recovery(db, sim, attempts=15):
    for _ in range(attempts):
        shipment, result = recover(db, sim)
        plan = db.get(RecoveryPlan, result.committed_plan_id)
        if plan and any(p.leg_id for p in plan.paths):
            return shipment, result, plan
    pytest.skip("no piggyback recovery in this world")


# --- P1: committing a plan books capacity ---------------------------------

def test_committed_piggyback_plan_books_its_legs(db, sim) -> None:
    shipment, _, plan = piggyback_recovery(db, sim)
    for step in plan.paths:
        if step.leg_id:
            link = db.scalar(select(ShipmentLeg).where(
                ShipmentLeg.shipment_id == shipment.id, ShipmentLeg.leg_id == step.leg_id))
            assert link is not None and link.is_recovery


def test_committing_consumes_residual_capacity(db, sim) -> None:
    d = sim.inject_disruption(db, DisruptionType.MISPLACE_SHIPMENT)
    shipment = db.get(Shipment, d.target_id)
    shipment.deadline_at = sim.clock.now + timedelta(hours=70)
    db.commit()
    result = RecoveryOrchestrator(db, e1_service=StubE1()).recover(shipment, now=sim.clock.now)
    plan = db.get(RecoveryPlan, result.committed_plan_id)
    legs = [s.leg_id for s in plan.paths if s.leg_id]
    if not legs:
        pytest.skip("dedicated plan")
    booked = db.scalar(select(func.count()).select_from(ShipmentLeg).where(ShipmentLeg.leg_id == legs[0]))
    leg = db.get(Leg, legs[0])
    assert leg.residual_kg <= leg.capacity_kg - shipment.weight_kg + 1e-6 or booked > 0


def test_replanning_releases_the_previous_booking(db, sim) -> None:
    shipment, _, plan = piggyback_recovery(db, sim)
    first_leg = next(s.leg_id for s in plan.paths if s.leg_id)
    leg = db.get(Leg, first_leg)
    residual_after_first = leg.residual_kg

    recover(db, sim, shipment)  # re-plan the same shipment
    db.refresh(leg)
    links = db.scalars(select(ShipmentLeg).where(
        ShipmentLeg.shipment_id == shipment.id, ShipmentLeg.boarded_at.is_(None))).all()
    committed = db.scalars(select(RecoveryPlan).where(
        RecoveryPlan.shipment_id == shipment.id,
        RecoveryPlan.status == PlanStatus.COMMITTED.value)).all()
    assert len(committed) == 1
    committed_legs = {s.leg_id for s in committed[0].paths if s.leg_id}
    # Only the new plan's legs are booked — no orphaned double booking.
    assert {l.leg_id for l in links} == committed_legs
    if first_leg not in committed_legs:
        assert leg.residual_kg == pytest.approx(residual_after_first + shipment.weight_kg, abs=1e-3)


def test_misplacement_releases_the_unboarded_itinerary(db, sim) -> None:
    link = db.scalars(select(ShipmentLeg).where(ShipmentLeg.boarded_at.is_(None))).first()
    if link is None:
        pytest.skip("no unboarded booking")
    leg = db.get(Leg, link.leg_id)
    shipment = db.get(Shipment, link.shipment_id)
    before = leg.residual_kg
    sim.inject_disruption(db, DisruptionType.MISPLACE_SHIPMENT, target_id=shipment.id)
    db.refresh(leg)
    assert leg.residual_kg == pytest.approx(min(leg.capacity_kg, before + shipment.weight_kg), abs=1e-3)
    assert db.scalar(select(ShipmentLeg).where(ShipmentLeg.id == link.id)) is None


# --- P2: a recovered shipment moves, delivers, and E9 records it ----------

def test_recovered_shipment_is_delivered_and_outcome_recorded(db, sim) -> None:
    shipment, result, plan = piggyback_recovery(db, sim)
    for _ in range(600):
        sim.tick(db)
        db.refresh(shipment)
        if shipment.status == ShipmentStatus.DELIVERED.value:
            break
    assert shipment.status == ShipmentStatus.DELIVERED.value
    db.refresh(plan)
    assert plan.status == PlanStatus.COMPLETED.value
    outcome = db.scalar(select(RecoveryOutcome).where(RecoveryOutcome.plan_id == plan.id))
    assert outcome is not None and outcome.succeeded
    assert outcome.recovery_seconds > 0


# --- P3: auction linked to the committed plan -----------------------------

def test_auction_is_linked_to_the_committed_plan(db, sim) -> None:
    shipment, result = recover(db, sim)
    auction = db.scalar(select(Auction).where(Auction.shipment_id == shipment.id))
    plan = db.get(RecoveryPlan, result.committed_plan_id)
    assert auction.plan_id == plan.id
    assert plan.bounty_cost == pytest.approx(auction.payment or 0.0)


# --- P4: warm-start never reuses a dead leg --------------------------------

@pytest.mark.parametrize("breakage", ["cancel", "fill", "depart"])
def test_warm_start_revalidates_and_backtracks(db, sim, breakage) -> None:
    memory = GraphMemory(cache=InProcessCache())
    shipment = db.scalars(select(Shipment).where(Shipment.status == ShipmentStatus.PENDING.value)).first()
    shipment.deadline_at = sim.clock.now + timedelta(hours=80)
    shipment.lam = 150.0
    db.commit()

    cold = plan_recovery(db, shipment, now=sim.clock.now, memory=memory)
    stored_leg = next((l.leg_id for p in cold.result.plans for l in p.legs if l.leg_id), None)
    if stored_leg is None:
        pytest.skip("no piggyback plan to remember")

    leg = db.get(Leg, stored_leg)
    if breakage == "cancel":
        leg.status = LegStatus.CANCELLED.value
    elif breakage == "fill":
        leg.residual_kg = 0.0
    else:
        leg.departure_at = sim.clock.now - timedelta(minutes=5)
    db.commit()

    again = plan_recovery(db, shipment, now=sim.clock.now, memory=memory)
    offered = {l.leg_id for p in again.result.plans for l in p.legs}
    assert stored_leg not in offered
    assert stored_leg in memory.warm_start(again.query_key).failed_leg_ids


def test_warm_start_uses_current_leg_timings(db, sim) -> None:
    memory = GraphMemory(cache=InProcessCache())
    shipment = db.scalars(select(Shipment).where(Shipment.status == ShipmentStatus.PENDING.value)).first()
    shipment.deadline_at = sim.clock.now + timedelta(hours=90)
    shipment.lam = 150.0
    db.commit()
    cold = plan_recovery(db, shipment, now=sim.clock.now, memory=memory)
    first = next((p for p in cold.result.plans if p.legs and p.legs[0].leg_id), None)
    if first is None:
        pytest.skip("no piggyback plan")
    leg = db.get(Leg, first.legs[-1].leg_id)
    leg.arrival_at = leg.arrival_at + timedelta(hours=1)   # a delay
    db.commit()
    warm = plan_recovery(db, shipment, now=sim.clock.now, memory=memory)
    same = [p for p in warm.result.plans if p.legs and p.legs[-1].leg_id == leg.id]
    if same:
        assert same[0].arrival_at == leg.arrival_at


# --- P5: Emergency Recovery Mode is acted on --------------------------------

def test_emergency_mode_chooses_the_fastest_plan(db, sim, monkeypatch) -> None:
    """Deterministic: genuinely high pressure, and two known plans —
    cheap-but-slow vs dear-but-fast. Emergency mode must pick the fast one."""
    from app.engines.e6_piggy_router.router import CandidatePlan, PlanLeg, RoutingResult
    from app.engines.e7_graph_memory.planner import PlanningOutcome, query_key_for
    import app.services.orchestrator as orch

    d = sim.inject_disruption(db, DisruptionType.MISPLACE_SHIPMENT)
    shipment = db.get(Shipment, d.target_id)
    now = sim.clock.now
    shipment.deadline_at = now + timedelta(hours=1)
    shipment.cascade_depth = 5
    shipment.base_priority = 2.0
    db.commit()

    def plan(strategy, cost, hours):
        leg = PlanLeg(leg_id=None, from_hub_id=shipment.origin_hub_id, to_hub_id=shipment.dest_hub_id,
                      departure_at=now, arrival_at=now + timedelta(hours=hours), edge_cost=cost,
                      is_dedicated=True)
        return CandidatePlan(strategy=strategy, legs=(leg,), total_cost=cost,
                             arrival_at=now + timedelta(hours=hours), transfers=0, feasible=True)

    cheap_slow, dear_fast = plan("PIGGYBACK", 1_000.0, 12), plan("DEDICATED", 9_000.0, 2)
    monkeypatch.setattr(orch, "plan_recovery", lambda db_, s, now, k=5: PlanningOutcome(
        result=RoutingResult(plans=[cheap_slow, dear_fast], rejected=[], compute_ms=0.1,
                             labels_explored=1, edges_considered=1),
        warm_started=False, query_key=query_key_for(s, now)))

    result = RecoveryOrchestrator(db, e1_service=StubE1()).recover(shipment, now=now, run_cascade=False)

    assert result.pressure.emergency, f"pressure {result.pressure.pressure:.3f} < {EMERGENCY_THRESHOLD}"
    assert "Emergency ordering" in [s.name for s in result.stages]
    assert result.strategy == "DEDICATED" and result.total_cost == 9_000.0
    assert any("Emergency Recovery Mode" in line for line in result.explanation.why_chosen)


def test_without_emergency_the_cheapest_plan_stays_first(db, sim, monkeypatch) -> None:
    from app.engines.e6_piggy_router.router import CandidatePlan, PlanLeg, RoutingResult
    from app.engines.e7_graph_memory.planner import PlanningOutcome, query_key_for
    import app.services.orchestrator as orch

    d = sim.inject_disruption(db, DisruptionType.MISPLACE_SHIPMENT)
    shipment = db.get(Shipment, d.target_id)
    now = sim.clock.now
    shipment.deadline_at = now + timedelta(hours=90)
    db.commit()

    def plan(strategy, cost, hours):
        leg = PlanLeg(leg_id=None, from_hub_id=shipment.origin_hub_id, to_hub_id=shipment.dest_hub_id,
                      departure_at=now, arrival_at=now + timedelta(hours=hours), edge_cost=cost,
                      is_dedicated=True)
        return CandidatePlan(strategy=strategy, legs=(leg,), total_cost=cost,
                             arrival_at=now + timedelta(hours=hours), transfers=0, feasible=True)

    monkeypatch.setattr(orch, "plan_recovery", lambda db_, s, now, k=5: PlanningOutcome(
        result=RoutingResult(plans=[plan("PIGGYBACK", 1_000.0, 12), plan("DEDICATED", 9_000.0, 2)],
                             rejected=[], compute_ms=0.1, labels_explored=1, edges_considered=1),
        warm_started=False, query_key=query_key_for(s, now)))

    result = RecoveryOrchestrator(db, e1_service=StubE1()).recover(shipment, now=now, run_cascade=False)
    assert not result.pressure.emergency
    assert result.strategy == "PIGGYBACK"


# --- P6: delayed legs still depart and arrive ------------------------------

def test_delayed_scheduled_leg_still_departs(db, sim) -> None:
    leg = db.scalars(select(Leg).where(Leg.status == LegStatus.SCHEDULED.value)
                     .order_by(Leg.departure_at)).first()
    sim.inject_disruption(db, DisruptionType.DELAY_VEHICLE, target_id=leg.vehicle_id, delay_hours=1)
    db.refresh(leg)
    assert leg.status == LegStatus.DELAYED.value
    while sim.clock.now <= leg.arrival_at + timedelta(minutes=30):
        sim.tick(db)
    db.refresh(leg)
    assert leg.status == LegStatus.ARRIVED.value


def test_delayed_leg_already_on_the_road_still_arrives(db, sim) -> None:
    leg = db.scalars(select(Leg).where(Leg.status == LegStatus.DEPARTED.value)).first()
    if leg is None:
        pytest.skip("nothing on the road")
    original_arrival = leg.arrival_at
    sim.inject_disruption(db, DisruptionType.DELAY_VEHICLE, target_id=leg.vehicle_id, delay_hours=2)
    db.refresh(leg)
    assert leg.status == LegStatus.DEPARTED.value          # not stranded as DELAYED
    assert leg.arrival_at == original_arrival + timedelta(hours=2)
    while sim.clock.now <= leg.arrival_at + timedelta(minutes=30):
        sim.tick(db)
    db.refresh(leg)
    assert leg.status == LegStatus.ARRIVED.value
