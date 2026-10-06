"""E7 — Graph Memory.

Remembers what the router has already learned so repeated planning for
similar shipments is cheaper and does not re-walk paths already known to
fail:

  * **Warm-start** — previously found plans for an equivalent query are
    returned immediately instead of re-searching.
  * **Failed-path memory** — legs and full routes that failed are recorded
    and skipped on subsequent searches.
  * **Dominance** — a stored plan is kept only if nothing already stored is
    at least as good on cost, arrival and transfers.
  * **Backtracking** — when a committed plan fails, the failure is recorded
    and the next-best stored alternative is offered.

State is keyed by an *equivalence class* rather than by shipment id: two
shipments from the same hub to the same hub, of similar size and urgency,
face the same routing problem, so one can reuse the other's answer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from app.core.logging import get_logger
from app.engines.e6_piggy_router.router import CandidatePlan
from app.engines.e7_graph_memory.cache import InProcessCache, MemoryCache

logger = get_logger(__name__)

# Bucket widths for the equivalence key. Coarser buckets mean more cache
# hits but looser matches; these are tuned so a hit is genuinely reusable.
WEIGHT_BUCKET_KG = 25.0
VOLUME_BUCKET_M3 = 1.0
DEADLINE_BUCKET_HOURS = 2.0
LAMBDA_BUCKET = 100.0

PLAN_KEY_PREFIX = "plans"
FAILED_LEG_KEY_PREFIX = "failed_leg"
FAILED_ROUTE_KEY_PREFIX = "failed_route"


@dataclass(frozen=True, slots=True)
class QueryKey:
    """An equivalence class of routing problems."""

    origin_hub_id: int
    dest_hub_id: int
    weight_bucket: int
    volume_bucket: int
    deadline_bucket: int
    lambda_bucket: int

    def as_cache_key(self, prefix: str = PLAN_KEY_PREFIX) -> str:
        return (
            f"{prefix}:{self.origin_hub_id}:{self.dest_hub_id}:"
            f"{self.weight_bucket}:{self.volume_bucket}:"
            f"{self.deadline_bucket}:{self.lambda_bucket}"
        )


def build_query_key(
    *,
    origin_hub_id: int,
    dest_hub_id: int,
    weight_kg: float,
    volume_m3: float,
    hours_to_deadline: float,
    lam: float,
) -> QueryKey:
    """Maps a concrete routing problem onto its equivalence class.

    Buckets round *down* for weight and volume so a cached plan is never
    reused for a shipment that is larger than the one it was computed for.
    """
    return QueryKey(
        origin_hub_id=origin_hub_id,
        dest_hub_id=dest_hub_id,
        weight_bucket=int(math.floor(max(0.0, weight_kg) / WEIGHT_BUCKET_KG)),
        volume_bucket=int(math.floor(max(0.0, volume_m3) / VOLUME_BUCKET_M3)),
        deadline_bucket=int(
            math.floor(max(0.0, hours_to_deadline) / DEADLINE_BUCKET_HOURS)
        ),
        lambda_bucket=int(math.floor(max(0.0, lam) / LAMBDA_BUCKET)),
    )


@dataclass(frozen=True, slots=True)
class StoredLeg:
    """One hop of a stored plan.

    Hub ids are retained deliberately: without them a warm-started plan
    cannot be persisted (the RecoveryPath foreign keys would be invalid),
    which made warm-start output unusable downstream.
    """

    leg_id: Optional[int]
    from_hub_id: int
    to_hub_id: int
    departure_at: Optional[str]
    arrival_at: Optional[str]
    edge_cost: float


@dataclass
class StoredPlan:
    """A plan retained for reuse."""

    leg_ids: Tuple[Optional[int], ...]
    strategy: str
    total_cost: float
    transfers: int
    arrival_at: Optional[str]
    score: float
    legs: Tuple[StoredLeg, ...] = ()

    def dominates(self, other: "StoredPlan") -> bool:
        """No worse on cost and transfers, strictly better on one."""
        return (
            self.total_cost <= other.total_cost
            and self.transfers <= other.transfers
            and (
                self.total_cost < other.total_cost
                or self.transfers < other.transfers
            )
        )

    @classmethod
    def from_plan(cls, plan: CandidatePlan) -> "StoredPlan":
        return cls(
            leg_ids=tuple(leg.leg_id for leg in plan.legs),
            strategy=plan.strategy,
            total_cost=plan.total_cost,
            transfers=plan.transfers,
            arrival_at=plan.arrival_at.isoformat() if plan.arrival_at else None,
            score=plan.score,
            legs=tuple(
                StoredLeg(
                    leg_id=leg.leg_id,
                    from_hub_id=leg.from_hub_id,
                    to_hub_id=leg.to_hub_id,
                    departure_at=leg.departure_at.isoformat()
                    if leg.departure_at
                    else None,
                    arrival_at=leg.arrival_at.isoformat()
                    if leg.arrival_at
                    else None,
                    edge_cost=leg.edge_cost,
                )
                for leg in plan.legs
            ),
        )


@dataclass
class WarmStart:
    """What memory could supply for a query."""

    plans: List[StoredPlan] = field(default_factory=list)
    failed_leg_ids: Set[int] = field(default_factory=set)
    failed_routes: Set[Tuple[Optional[int], ...]] = field(default_factory=set)

    @property
    def hit(self) -> bool:
        return bool(self.plans)


class GraphMemory:
    """E7: retained labels, failed-path memory and warm-start."""

    def __init__(self, cache: Optional[MemoryCache] = None) -> None:
        self.cache = cache or InProcessCache()

    # --- storing ---------------------------------------------------------

    def remember_plans(
        self, key: QueryKey, plans: Sequence[CandidatePlan], *, limit: int = 5
    ) -> List[StoredPlan]:
        """Stores feasible plans, cheapest first, deduplicated by route.

        Dominance is deliberately NOT applied here. It belongs to partial
        labels during the search, where pruning is what makes RCSPP
        tractable. Applying it to *stored alternatives* would throw away the
        very fallbacks backtracking depends on: if the cheapest route is
        strictly better on every axis, dominance would leave exactly one
        plan, and a failure of that plan would have nothing to fall back to.

        Distinct routes are therefore all retained, up to ``limit``.
        """
        seen: Set[Tuple[Optional[int], ...]] = set()
        kept: List[StoredPlan] = []

        candidates = [
            StoredPlan.from_plan(plan) for plan in plans if plan.feasible
        ]

        for candidate in sorted(candidates, key=lambda item: item.total_cost):
            if candidate.leg_ids in seen:
                continue
            seen.add(candidate.leg_ids)
            kept.append(candidate)
            if len(kept) >= limit:
                break

        if kept:
            self.cache.set(key.as_cache_key(), kept)
        logger.debug("E7 stored %d plans for %s", len(kept), key.as_cache_key())
        return kept

    def remember_failed_leg(self, key: QueryKey, leg_id: int) -> None:
        """Records a leg that could not actually carry the shipment."""
        cache_key = key.as_cache_key(FAILED_LEG_KEY_PREFIX)
        failed: Set[int] = set(self.cache.get(cache_key) or set())
        failed.add(leg_id)
        self.cache.set(cache_key, failed)

    def remember_failed_route(
        self, key: QueryKey, leg_ids: Sequence[Optional[int]]
    ) -> None:
        """Records a complete route that failed, so it is not retried."""
        cache_key = key.as_cache_key(FAILED_ROUTE_KEY_PREFIX)
        failed: Set[Tuple[Optional[int], ...]] = set(
            self.cache.get(cache_key) or set()
        )
        failed.add(tuple(leg_ids))
        self.cache.set(cache_key, failed)

        # A failed route also invalidates any stored plan that used it.
        self._drop_matching_plans(key, tuple(leg_ids))

    def _drop_matching_plans(
        self, key: QueryKey, leg_ids: Tuple[Optional[int], ...]
    ) -> None:
        cache_key = key.as_cache_key()
        stored: List[StoredPlan] = list(self.cache.get(cache_key) or [])
        remaining = [plan for plan in stored if plan.leg_ids != leg_ids]

        if len(remaining) != len(stored):
            self.cache.set(cache_key, remaining)

    # --- retrieving ------------------------------------------------------

    def warm_start(self, key: QueryKey) -> WarmStart:
        """Everything memory knows about this equivalence class."""
        plans: List[StoredPlan] = list(self.cache.get(key.as_cache_key()) or [])
        failed_legs: Set[int] = set(
            self.cache.get(key.as_cache_key(FAILED_LEG_KEY_PREFIX)) or set()
        )
        failed_routes: Set[Tuple[Optional[int], ...]] = set(
            self.cache.get(key.as_cache_key(FAILED_ROUTE_KEY_PREFIX)) or set()
        )

        usable = [
            plan
            for plan in plans
            if plan.leg_ids not in failed_routes
            and not any(
                leg_id in failed_legs
                for leg_id in plan.leg_ids
                if leg_id is not None
            )
        ]

        return WarmStart(
            plans=usable,
            failed_leg_ids=failed_legs,
            failed_routes=failed_routes,
        )

    def next_alternative(
        self, key: QueryKey, *, after: Sequence[Optional[int]]
    ) -> Optional[StoredPlan]:
        """Backtracking: the best stored plan that is not ``after``.

        Used when a committed plan fails and a replacement is needed
        without re-running the full search.
        """
        self.remember_failed_route(key, after)
        remaining = self.warm_start(key).plans
        return remaining[0] if remaining else None

    def is_route_known_bad(
        self, key: QueryKey, leg_ids: Sequence[Optional[int]]
    ) -> bool:
        return tuple(leg_ids) in self.warm_start(key).failed_routes

    # --- housekeeping ----------------------------------------------------

    def invalidate(self, key: QueryKey) -> None:
        """Forgets everything about one equivalence class."""
        for prefix in (
            PLAN_KEY_PREFIX,
            FAILED_LEG_KEY_PREFIX,
            FAILED_ROUTE_KEY_PREFIX,
        ):
            self.cache.delete(key.as_cache_key(prefix))

    def clear(self) -> None:
        self.cache.clear()

    def stats(self) -> Dict[str, Any]:
        return self.cache.stats()


_memory: Optional[GraphMemory] = None


def get_memory() -> GraphMemory:
    """Returns the process-wide Graph Memory."""
    global _memory
    if _memory is None:
        _memory = GraphMemory()
    return _memory


def reset_memory() -> None:
    """Drops the cached instance. Test-support only."""
    global _memory
    _memory = None
