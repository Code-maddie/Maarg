"""E6 — Piggy Router.

Resource-Constrained Shortest Path (RCSPP) over the time-expanded graph,
solved by label setting with dominance pruning, returning the k best
recovery plans.

Resources tracked per label: accumulated cost, arrival time, number of
transfers. A label is dominated when another label at the same hub is no
worse on every resource and strictly better on at least one — dropping
dominated labels is what keeps the search tractable.

Strategies (SH.docx §5.2):
  PIGGYBACK  - rides only existing scheduled capacity (cheapest)
  DEDICATED  - a vehicle dispatched specifically for this shipment
  HYBRID     - existing capacity for part of the journey, dedicated for the rest
"""

from __future__ import annotations

import heapq
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.core.geo import haversine_km
from app.core.logging import get_logger
from app.models import Hub, Shipment
from app.models.enums import PlanStrategy
from app.engines.e6_piggy_router.graph import (
    Edge,
    TransportGraph,
    build_graph,
    transfer_ready_at,
)

logger = get_logger(__name__)

# A plan may not transfer more than this many times; each transfer is a
# physical handling risk, and unbounded transfers explode the search.
MAX_TRANSFERS = 4

# Labels kept per hub. Bounds worst-case memory on dense graphs.
MAX_LABELS_PER_HUB = 40

# Cost model for a dedicated vehicle dispatched just for this shipment.
DEDICATED_COST_PER_KM = 55.0
DEDICATED_FIXED_COST = 2500.0
DEDICATED_SPEED_KMH = 50.0
DEDICATED_ROAD_FACTOR = 1.35


class RejectionReason:
    """Concrete rejection reasons. E8 shows these verbatim, never a placeholder."""

    # Covers both "no legs connect these hubs" and "every connecting leg
    # arrives too late" — late edges are pruned during expansion, so the two
    # are indistinguishable by the time we report. The wording is accurate
    # for both rather than guessing between them.
    NO_PATH = (
        "No route using existing capacity reaches the destination "
        "before the deadline"
    )
    DEADLINE_MISSED = "Arrival {arrival} is after the deadline {deadline}"
    CAPACITY = "No leg on this route has capacity for {weight}kg / {volume}m3"
    TOO_MANY_TRANSFERS = "Requires {transfers} transfers, limit is {limit}"
    DOMINATED = "Dominated by a cheaper plan arriving no later"
    HUB_CLOSED = "Route passes through a closed hub"


@dataclass(frozen=True, slots=True)
class PlanLeg:
    """One hop of a candidate plan."""

    leg_id: Optional[int]
    from_hub_id: int
    to_hub_id: int
    departure_at: datetime
    arrival_at: datetime
    edge_cost: float
    is_dedicated: bool = False


@dataclass(frozen=True, slots=True)
class CandidatePlan:
    """A complete recovery plan produced by E6."""

    strategy: str
    legs: Tuple[PlanLeg, ...]
    total_cost: float
    arrival_at: Optional[datetime]
    transfers: int
    feasible: bool
    rejection_reason: Optional[str] = None
    score: float = 0.0

    @property
    def transit_hours(self) -> float:
        if not self.legs or self.arrival_at is None:
            return 0.0
        return max(
            0.0,
            (self.arrival_at - self.legs[0].departure_at).total_seconds() / 3600.0,
        )


@dataclass(order=True)
class _Label:
    """A partial path. Ordered by cost so the heap pops cheapest first."""

    cost: float
    arrival: datetime
    transfers: int
    hub_id: int = field(compare=False)
    path: Tuple[PlanLeg, ...] = field(compare=False, default=())

    def dominates(self, other: "_Label") -> bool:
        """True when this label is at least as good on every resource.

        Dominance is what makes label setting tractable: a label that is
        worse on all three resources can never lead to a better plan.
        """
        return (
            self.cost <= other.cost
            and self.arrival <= other.arrival
            and self.transfers <= other.transfers
            and (
                self.cost < other.cost
                or self.arrival < other.arrival
                or self.transfers < other.transfers
            )
        )


@dataclass
class RoutingResult:
    """Everything one routing call produced, feasible and rejected alike."""

    plans: List[CandidatePlan]
    rejected: List[CandidatePlan]
    compute_ms: float
    labels_explored: int
    edges_considered: int

    @property
    def best(self) -> Optional[CandidatePlan]:
        return self.plans[0] if self.plans else None


def dedicated_plan(
    origin: Hub,
    destination: Hub,
    depart_at: datetime,
    deadline: Optional[datetime] = None,
) -> CandidatePlan:
    """Builds the always-available fallback: send a vehicle just for this.

    Expensive by design — it is the benchmark every piggyback plan is scored
    against, and the cap on MaxBounty in E5.
    """
    distance = haversine_km(
        origin.lat, origin.lng, destination.lat, destination.lng
    ) * DEDICATED_ROAD_FACTOR
    hours = max(0.5, distance / DEDICATED_SPEED_KMH)
    arrival = depart_at + timedelta(hours=hours)
    cost = DEDICATED_FIXED_COST + distance * DEDICATED_COST_PER_KM

    leg = PlanLeg(
        leg_id=None,
        from_hub_id=origin.id,
        to_hub_id=destination.id,
        departure_at=depart_at,
        arrival_at=arrival,
        edge_cost=round(cost, 2),
        is_dedicated=True,
    )

    feasible = deadline is None or arrival <= deadline
    return CandidatePlan(
        strategy=PlanStrategy.DEDICATED.value,
        legs=(leg,),
        total_cost=round(cost, 2),
        arrival_at=arrival,
        transfers=0,
        feasible=feasible,
        rejection_reason=(
            None
            if feasible
            else RejectionReason.DEADLINE_MISSED.format(
                arrival=arrival.isoformat(timespec="minutes"),
                deadline=deadline.isoformat(timespec="minutes"),
            )
        ),
    )


class PiggyRouter:
    """Label-setting RCSPP solver producing k-best recovery plans."""

    def __init__(
        self,
        graph: TransportGraph,
        *,
        max_transfers: int = MAX_TRANSFERS,
        max_labels_per_hub: int = MAX_LABELS_PER_HUB,
    ) -> None:
        self.graph = graph
        self.max_transfers = max_transfers
        self.max_labels_per_hub = max_labels_per_hub

    def route(
        self,
        *,
        origin_hub_id: int,
        dest_hub_id: int,
        depart_after: datetime,
        deadline: datetime,
        weight_kg: float,
        volume_m3: float,
        lam: float,
        k: int = 5,
        allow_dedicated: bool = True,
        excluded_leg_ids: Optional[frozenset[int]] = None,
    ) -> RoutingResult:
        """Finds up to ``k`` feasible plans, cheapest first.

        ``excluded_leg_ids`` comes from E7 Graph Memory: legs already known
        to have failed for an equivalent shipment are not re-explored.
        """
        started = time.perf_counter()
        excluded = excluded_leg_ids or frozenset()

        plans: List[CandidatePlan] = []
        rejected: List[CandidatePlan] = []
        labels_explored = 0

        origin = self.graph.hub(origin_hub_id)
        destination = self.graph.hub(dest_hub_id)

        if origin is None or destination is None:
            return RoutingResult(
                plans=[],
                rejected=[
                    CandidatePlan(
                        strategy=PlanStrategy.PIGGYBACK.value,
                        legs=(), total_cost=0.0, arrival_at=None, transfers=0,
                        feasible=False, rejection_reason=RejectionReason.NO_PATH,
                    )
                ],
                compute_ms=(time.perf_counter() - started) * 1000,
                labels_explored=0,
                edges_considered=self.graph.edge_count,
            )

        # --- label setting ---------------------------------------------
        start = _Label(cost=0.0, arrival=depart_after, transfers=0, hub_id=origin_hub_id)
        heap: List[_Label] = [start]
        settled: Dict[int, List[_Label]] = {origin_hub_id: [start]}
        arrivals: List[_Label] = []

        while heap:
            label = heapq.heappop(heap)
            labels_explored += 1

            if label.hub_id == dest_hub_id and label.path:
                arrivals.append(label)
                # k-best: keep expanding, a later label may still be better
                # on another resource, but stop once we have plenty.
                if len(arrivals) >= k * 3:
                    break
                continue

            if label.transfers > self.max_transfers:
                continue

            earliest = (
                label.arrival
                if not label.path
                else transfer_ready_at(label.arrival)
            )

            for edge in self.graph.outgoing(
                label.hub_id,
                earliest_departure=earliest,
                weight_kg=weight_kg,
                volume_m3=volume_m3,
            ):
                # Prune anything that cannot possibly meet the deadline.
                if edge.arrival_at > deadline:
                    continue

                # E7: a leg already known to have failed is not re-explored.
                if edge.leg_id in excluded:
                    continue

                transfers = label.transfers + (1 if label.path else 0)
                if transfers > self.max_transfers:
                    continue

                candidate = _Label(
                    cost=label.cost + edge.weight(lam),
                    arrival=edge.arrival_at,
                    transfers=transfers,
                    hub_id=edge.to_hub_id,
                    path=label.path
                    + (
                        PlanLeg(
                            leg_id=edge.leg_id,
                            from_hub_id=edge.from_hub_id,
                            to_hub_id=edge.to_hub_id,
                            departure_at=edge.departure_at,
                            arrival_at=edge.arrival_at,
                            edge_cost=round(edge.weight(lam), 2),
                        ),
                    ),
                )

                if self._insert_if_not_dominated(
                    settled, candidate, dest_hub_id=dest_hub_id
                ):
                    heapq.heappush(heap, candidate)

        # --- assemble plans ---------------------------------------------
        for label in sorted(arrivals, key=lambda item: (item.cost, item.arrival)):
            if label.arrival > deadline:
                rejected.append(
                    self._reject(
                        label,
                        RejectionReason.DEADLINE_MISSED.format(
                            arrival=label.arrival.isoformat(timespec="minutes"),
                            deadline=deadline.isoformat(timespec="minutes"),
                        ),
                    )
                )
                continue

            plans.append(
                CandidatePlan(
                    strategy=PlanStrategy.PIGGYBACK.value,
                    legs=label.path,
                    total_cost=round(label.cost, 2),
                    arrival_at=label.arrival,
                    transfers=label.transfers,
                    feasible=True,
                )
            )
            if len(plans) >= k:
                break

        # If no piggyback plan survived, say so explicitly — even when the
        # dedicated fallback succeeds. Otherwise E8 would show the dispatcher
        # "DEDICATED chosen" with nothing explaining why riding existing
        # capacity was impossible, which is the question they actually ask.
        if not plans:
            rejected.append(
                CandidatePlan(
                    strategy=PlanStrategy.PIGGYBACK.value,
                    legs=(), total_cost=0.0, arrival_at=None, transfers=0,
                    feasible=False,
                    rejection_reason=(
                        RejectionReason.NO_PATH
                        if not arrivals
                        else RejectionReason.DEADLINE_MISSED.format(
                            arrival=min(
                                label.arrival for label in arrivals
                            ).isoformat(timespec="minutes"),
                            deadline=deadline.isoformat(timespec="minutes"),
                        )
                    ),
                )
            )

        # --- dedicated fallback -----------------------------------------
        if allow_dedicated:
            fallback = dedicated_plan(origin, destination, depart_after, deadline)
            (plans if fallback.feasible else rejected).append(fallback)

        scored = self._score(plans, deadline)

        return RoutingResult(
            plans=scored[:k],
            rejected=rejected,
            compute_ms=round((time.perf_counter() - started) * 1000, 3),
            labels_explored=labels_explored,
            edges_considered=self.graph.edge_count,
        )

    def _insert_if_not_dominated(
        self,
        settled: Dict[int, List[_Label]],
        candidate: _Label,
        *,
        dest_hub_id: Optional[int] = None,
    ) -> bool:
        """Keeps ``candidate`` only if no existing label dominates it.

        Dominance is applied to *intermediate* hubs only. At the destination
        every arriving label is retained (up to the cap), because k-best needs
        the alternatives that the optimal plan would otherwise dominate away —
        and E8 needs them to explain what was rejected and why.
        """
        bucket = settled.setdefault(candidate.hub_id, [])

        if candidate.hub_id == dest_hub_id:
            if len(bucket) >= self.max_labels_per_hub:
                return False
            bucket.append(candidate)
            return True

        for existing in bucket:
            if existing.dominates(candidate):
                return False

        # Drop anything the newcomer dominates.
        bucket[:] = [item for item in bucket if not candidate.dominates(item)]

        if len(bucket) >= self.max_labels_per_hub:
            return False

        bucket.append(candidate)
        return True

    def _reject(self, label: _Label, reason: str) -> CandidatePlan:
        return CandidatePlan(
            strategy=PlanStrategy.PIGGYBACK.value,
            legs=label.path,
            total_cost=round(label.cost, 2),
            arrival_at=label.arrival,
            transfers=label.transfers,
            feasible=False,
            rejection_reason=reason,
        )

    def _score(
        self, plans: Sequence[CandidatePlan], deadline: datetime
    ) -> List[CandidatePlan]:
        """Ranks plans: cheaper, earlier and fewer transfers score higher.

        Score is normalised to [0,1] against the worst candidate in the set,
        so it is comparable within one routing call.
        """
        if not plans:
            return []

        max_cost = max(plan.total_cost for plan in plans) or 1.0
        max_transfers = max(plan.transfers for plan in plans) or 1

        scored: List[CandidatePlan] = []
        for plan in plans:
            cost_score = 1.0 - (plan.total_cost / max_cost)
            transfer_score = 1.0 - (plan.transfers / max_transfers)

            if plan.arrival_at is not None:
                slack_hours = (deadline - plan.arrival_at).total_seconds() / 3600.0
                slack_score = max(0.0, min(1.0, slack_hours / 24.0))
            else:
                slack_score = 0.0

            score = 0.55 * cost_score + 0.25 * slack_score + 0.20 * transfer_score

            scored.append(
                CandidatePlan(
                    strategy=plan.strategy,
                    legs=plan.legs,
                    total_cost=plan.total_cost,
                    arrival_at=plan.arrival_at,
                    transfers=plan.transfers,
                    feasible=plan.feasible,
                    rejection_reason=plan.rejection_reason,
                    score=round(score, 4),
                )
            )

        scored.sort(key=lambda item: (-item.score, item.total_cost))
        return scored


def route_shipment(
    db: Session,
    shipment: Shipment,
    *,
    now: datetime,
    k: int = 5,
    horizon_hours: float = 72.0,
    allow_dedicated: bool = True,
    excluded_leg_ids: Optional[frozenset[int]] = None,
) -> RoutingResult:
    """Convenience entry point: builds the graph and routes one shipment."""
    origin_id = shipment.current_hub_id or shipment.origin_hub_id
    origin = db.get(Hub, origin_id)

    graph = build_graph(
        db,
        now=now,
        horizon_hours=horizon_hours,
        origin=origin,
        weight_kg=shipment.weight_kg,
        volume_m3=shipment.volume_m3,
    )

    router = PiggyRouter(graph)
    result = router.route(
        origin_hub_id=origin_id,
        dest_hub_id=shipment.dest_hub_id,
        depart_after=now,
        deadline=shipment.deadline_at,
        weight_kg=shipment.weight_kg,
        volume_m3=shipment.volume_m3,
        lam=shipment.lam or shipment.sla_penalty_per_hour,
        k=k,
        allow_dedicated=allow_dedicated,
        excluded_leg_ids=excluded_leg_ids,
    )

    logger.info(
        "E6 routed %s: %d plans, %d rejected, %d labels, %.1f ms",
        shipment.code, len(result.plans), len(result.rejected),
        result.labels_explored, result.compute_ms,
    )
    return result
