"""Memory-aware routing: E6 with E7 warm-start in front of it.

On a cache hit the stored plans are returned without running the search at
all, which is where the visible latency drop in the demo comes from
(SH.docx §15, "warm-start re-plan, latency timer visible").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

import time

from app.core.logging import get_logger
from app.engines.e6_piggy_router.graph import transfer_ready_at
from app.engines.e6_piggy_router.router import (
    CandidatePlan,
    PlanLeg,
    RoutingResult,
    dedicated_plan,
    route_shipment,
)
from app.engines.e7_graph_memory.memory import (
    GraphMemory,
    QueryKey,
    StoredPlan,
    build_query_key,
    get_memory,
)
from app.models import Hub, Leg, Shipment
from app.models.enums import LegStatus, PlanStrategy

logger = get_logger(__name__)


@dataclass
class PlanningOutcome:
    """A routing result plus how it was obtained."""

    result: RoutingResult
    warm_started: bool
    query_key: QueryKey
    backtracked: int = 0
    # End-to-end planning time (graph build or revalidation included), so
    # warm and cold are compared like for like. result.compute_ms is the
    # search alone.
    wall_ms: float = 0.0

    @property
    def best(self) -> Optional[CandidatePlan]:
        return self.result.best

    @property
    def compute_ms(self) -> float:
        return self.result.compute_ms


def query_key_for(shipment: Shipment, now: datetime) -> QueryKey:
    """Equivalence key for this shipment's routing problem."""
    return build_query_key(
        origin_hub_id=shipment.current_hub_id or shipment.origin_hub_id,
        dest_hub_id=shipment.dest_hub_id,
        weight_kg=shipment.weight_kg,
        volume_m3=shipment.volume_m3,
        hours_to_deadline=max(0.0, shipment.hours_to_deadline(now)),
        lam=shipment.lam or shipment.sla_penalty_per_hour,
    )


_BOOKABLE = (LegStatus.SCHEDULED.value, LegStatus.DELAYED.value)


def _revalidate(db: Session, stored: StoredPlan, shipment: Shipment, now: datetime):
    """Checks a remembered plan against the current world.

    Returns (candidate, None, None) when still usable, rebuilt with the legs'
    CURRENT timings (a delay moves them), else (None, bad_leg_id, reason).
    """
    legs = []
    previous_arrival = None
    for hop in stored.legs:
        if hop.leg_id is None:
            return None, None, "Stored plan contains a dedicated hop; recomputed instead"
        leg = db.get(Leg, hop.leg_id)
        if leg is None:
            return None, hop.leg_id, f"Leg {hop.leg_id} no longer exists"
        if leg.status not in _BOOKABLE:
            return None, leg.id, f"Leg {leg.id} is now {leg.status}"
        if leg.departure_at < now:
            return None, leg.id, f"Leg {leg.id} departed at {leg.departure_at.isoformat(timespec='minutes')}"
        if not leg.can_fit(shipment.weight_kg, shipment.volume_m3):
            return None, leg.id, (f"Leg {leg.id} now has {leg.residual_kg:.1f} kg / "
                                  f"{leg.residual_m3:.2f} m3 free; shipment needs "
                                  f"{shipment.weight_kg:.1f} kg / {shipment.volume_m3:.2f} m3")
        if previous_arrival is not None and leg.departure_at < transfer_ready_at(previous_arrival):
            return None, leg.id, f"Connection onto leg {leg.id} is now too tight"
        previous_arrival = leg.arrival_at
        legs.append(
            PlanLeg(
                leg_id=leg.id, from_hub_id=leg.from_hub_id, to_hub_id=leg.to_hub_id,
                departure_at=leg.departure_at, arrival_at=leg.arrival_at,
                edge_cost=hop.edge_cost,
            )
        )

    if not legs:
        return None, None, "Stored plan had no legs"
    arrival = legs[-1].arrival_at
    if arrival > shipment.deadline_at:
        return None, legs[-1].leg_id, (
            f"Arrival {arrival.isoformat(timespec='minutes')} is now after the deadline "
            f"{shipment.deadline_at.isoformat(timespec='minutes')}")

    return CandidatePlan(
        strategy=stored.strategy, legs=tuple(legs), total_cost=stored.total_cost,
        arrival_at=arrival, transfers=stored.transfers, feasible=True, score=stored.score,
    ), None, None


def _rejected_from(stored: StoredPlan, reason: str) -> CandidatePlan:
    return CandidatePlan(
        strategy=stored.strategy, legs=(), total_cost=stored.total_cost,
        arrival_at=None, transfers=stored.transfers, feasible=False,
        rejection_reason=f"Remembered route no longer valid: {reason}",
    )


def plan_recovery(
    db: Session,
    shipment: Shipment,
    *,
    now: datetime,
    k: int = 5,
    memory: Optional[GraphMemory] = None,
    use_warm_start: bool = True,
    allow_dedicated: bool = True,
) -> PlanningOutcome:
    """Routes a shipment, reusing memory where possible."""
    wall_started = time.perf_counter()
    store = memory or get_memory()
    key = query_key_for(shipment, now)
    warm = store.warm_start(key)

    if use_warm_start and warm.hit:
        started = time.perf_counter()
        plans: List[CandidatePlan] = []
        rejected: List[CandidatePlan] = []

        # Memory is only a hint: every stored plan is revalidated against the
        # CURRENT world before reuse (audit fix — warm-start previously
        # re-offered legs that had since been cancelled, departed or filled).
        for stored in warm.plans:
            candidate, bad_leg, reason = _revalidate(db, stored, shipment, now)
            if candidate is None:
                # Backtrack: remember the leg that broke this plan so neither
                # memory nor the cold search offers it again.
                if bad_leg is not None:
                    store.remember_failed_leg(key, bad_leg)
                rejected.append(_rejected_from(stored, reason))
                continue
            plans.append(candidate)
            if len(plans) >= k:
                break

        if plans:
            if allow_dedicated:
                origin = db.get(Hub, shipment.current_hub_id or shipment.origin_hub_id)
                destination = db.get(Hub, shipment.dest_hub_id)
                if origin is not None and destination is not None:
                    fallback = dedicated_plan(origin, destination, now, shipment.deadline_at)
                    if fallback.feasible:
                        plans.append(fallback)
            logger.info(
                "E7 warm-start for %s: %d plan(s) reused, %d backtracked",
                shipment.code, len(plans), len(rejected),
            )
            return PlanningOutcome(
                result=RoutingResult(
                    plans=plans,
                    rejected=rejected,
                    compute_ms=round((time.perf_counter() - started) * 1000, 3),
                    labels_explored=0,
                    edges_considered=0,
                ),
                warm_started=True,
                query_key=key,
                backtracked=len(rejected),
                wall_ms=round((time.perf_counter() - wall_started) * 1000, 3),
            )

        # Every remembered plan is now invalid: fall through to a cold search
        # that excludes the legs just recorded as failed.
        warm = store.warm_start(key)
        logger.info("E7 warm-start for %s: all %d stored plans invalid, cold search",
                    shipment.code, len(rejected))

    result = route_shipment(
        db,
        shipment,
        now=now,
        k=k,
        allow_dedicated=allow_dedicated,
        excluded_leg_ids=frozenset(warm.failed_leg_ids),
    )

    # Only piggyback plans are worth remembering; the dedicated fallback is
    # recomputed trivially and its cost depends on the departure time.
    store.remember_plans(
        key,
        [
            plan
            for plan in result.plans
            if plan.strategy != PlanStrategy.DEDICATED.value
        ],
    )

    return PlanningOutcome(
        result=result, warm_started=False, query_key=key,
        wall_ms=round((time.perf_counter() - wall_started) * 1000, 3),
    )


def record_failure(
    shipment: Shipment,
    now: datetime,
    *,
    leg_ids: List[Optional[int]],
    failed_leg_id: Optional[int] = None,
    memory: Optional[GraphMemory] = None,
) -> Optional[StoredPlan]:
    """Records that a committed plan failed and returns the next alternative."""
    store = memory or get_memory()
    key = query_key_for(shipment, now)

    if failed_leg_id is not None:
        store.remember_failed_leg(key, failed_leg_id)

    alternative = store.next_alternative(key, after=leg_ids)
    logger.info(
        "E7 recorded failure for %s; alternative %s",
        shipment.code,
        "found" if alternative else "not available",
    )
    return alternative
