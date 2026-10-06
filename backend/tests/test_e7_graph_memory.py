"""Phase 8 validation: E7 Graph Memory — cache, failed paths, warm-start."""

from datetime import datetime, timedelta

import pytest

from app.engines.e6_piggy_router.router import CandidatePlan, PlanLeg
from app.engines.e7_graph_memory.cache import InProcessCache
from app.engines.e7_graph_memory.memory import (
    GraphMemory,
    StoredPlan,
    build_query_key,
    get_memory,
    reset_memory,
)
from app.engines.e7_graph_memory.planner import (
    plan_recovery,
    query_key_for,
    record_failure,
)
from app.models.enums import PlanStrategy

T0 = datetime(2026, 5, 1, 6, 0)


def make_plan(
    *leg_ids: int, cost: float = 1000.0, transfers: int = 0, hours: int = 8
) -> CandidatePlan:
    legs = tuple(
        PlanLeg(
            leg_id=leg_id,
            from_hub_id=1,
            to_hub_id=2,
            departure_at=T0,
            arrival_at=T0 + timedelta(hours=hours),
            edge_cost=cost,
        )
        for leg_id in leg_ids
    )
    return CandidatePlan(
        strategy=PlanStrategy.PIGGYBACK.value,
        legs=legs,
        total_cost=cost,
        arrival_at=T0 + timedelta(hours=hours),
        transfers=transfers,
        feasible=True,
        score=0.5,
    )


def key(**overrides):
    kwargs = {
        "origin_hub_id": 1,
        "dest_hub_id": 2,
        "weight_kg": 10.0,
        "volume_m3": 0.5,
        "hours_to_deadline": 20.0,
        "lam": 150.0,
    }
    kwargs.update(overrides)
    return build_query_key(**kwargs)


@pytest.fixture()
def memory() -> GraphMemory:
    return GraphMemory(cache=InProcessCache(max_entries=100))


# --- cache ---------------------------------------------------------------

def test_cache_round_trips() -> None:
    cache = InProcessCache()
    cache.set("a", [1, 2])
    assert cache.get("a") == [1, 2]


def test_cache_miss_returns_none() -> None:
    assert InProcessCache().get("absent") is None


def test_cache_delete_and_clear() -> None:
    cache = InProcessCache()
    cache.set("a", 1)
    cache.delete("a")
    assert cache.get("a") is None

    cache.set("b", 2)
    cache.clear()
    assert len(cache) == 0


def test_cache_evicts_least_recently_used() -> None:
    cache = InProcessCache(max_entries=2)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.get("a")          # 'a' is now most recent
    cache.set("c", 3)       # evicts 'b'

    assert cache.get("a") == 1
    assert cache.get("b") is None
    assert cache.get("c") == 3


def test_cache_reports_hits_and_misses() -> None:
    cache = InProcessCache()
    cache.set("a", 1)
    cache.get("a")
    cache.get("zzz")

    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["entries"] == 1


def test_cache_rejects_a_zero_bound() -> None:
    with pytest.raises(ValueError):
        InProcessCache(max_entries=0)


# --- equivalence keys ----------------------------------------------------

def test_similar_shipments_share_a_key() -> None:
    """Two near-identical problems must reuse each other's answer."""
    assert key(weight_kg=10.0) == key(weight_kg=20.0)  # same 25kg bucket


def test_different_weight_classes_do_not_share_a_key() -> None:
    assert key(weight_kg=10.0) != key(weight_kg=200.0)


def test_different_routes_do_not_share_a_key() -> None:
    assert key(dest_hub_id=2) != key(dest_hub_id=9)


def test_different_urgency_does_not_share_a_key() -> None:
    assert key(hours_to_deadline=1.0) != key(hours_to_deadline=40.0)


def test_weight_buckets_round_down() -> None:
    """A cached plan must never be reused for a heavier shipment."""
    assert key(weight_kg=24.9).weight_bucket == 0
    assert key(weight_kg=25.0).weight_bucket == 1


def test_negative_inputs_do_not_produce_negative_buckets() -> None:
    assert key(hours_to_deadline=-50.0).deadline_bucket == 0


# --- storing and dominance ----------------------------------------------

def test_plans_are_stored_and_returned(memory: GraphMemory) -> None:
    k = key()
    memory.remember_plans(k, [make_plan(1, cost=500.0)])

    warm = memory.warm_start(k)
    assert warm.hit is True
    assert warm.plans[0].leg_ids == (1,)


def test_infeasible_plans_are_not_stored(memory: GraphMemory) -> None:
    infeasible = CandidatePlan(
        strategy=PlanStrategy.PIGGYBACK.value, legs=(), total_cost=0.0,
        arrival_at=None, transfers=0, feasible=False,
        rejection_reason="nope",
    )
    assert memory.remember_plans(key(), [infeasible]) == []


def test_alternatives_are_retained_for_backtracking(memory: GraphMemory) -> None:
    """A strictly worse route is still kept — it is the fallback.

    Dominance is NOT applied to stored plans; if it were, a route that loses
    on every axis would be discarded and a failure of the best plan would
    leave nothing to fall back to.
    """
    kept = memory.remember_plans(
        key(),
        [
            make_plan(1, cost=500.0, transfers=0),
            make_plan(2, cost=900.0, transfers=1),   # worse on both, still kept
        ],
    )
    assert len(kept) == 2
    assert kept[0].total_cost == 500.0   # cheapest first


def test_identical_routes_are_deduplicated(memory: GraphMemory) -> None:
    kept = memory.remember_plans(
        key(), [make_plan(1, cost=500.0), make_plan(1, cost=700.0)]
    )
    assert len(kept) == 1


def test_stored_plan_dominance_logic() -> None:
    better = StoredPlan((1,), "PIGGYBACK", 100.0, 0, None, 0.9)
    worse = StoredPlan((2,), "PIGGYBACK", 200.0, 1, None, 0.3)

    assert better.dominates(worse) is True
    assert worse.dominates(better) is False
    assert better.dominates(better) is False


def test_storage_respects_the_limit(memory: GraphMemory) -> None:
    plans = [make_plan(i, cost=100.0 * i, transfers=i) for i in range(1, 12)]
    assert len(memory.remember_plans(key(), plans, limit=3)) == 3


# --- failed-path memory --------------------------------------------------

def test_a_failed_route_is_remembered(memory: GraphMemory) -> None:
    """Phase 8 criterion: a failed route is remembered."""
    k = key()
    memory.remember_failed_route(k, [1, 2])

    assert memory.is_route_known_bad(k, [1, 2]) is True
    assert memory.is_route_known_bad(k, [3, 4]) is False


def test_a_failed_route_is_removed_from_stored_plans(memory: GraphMemory) -> None:
    """Phase 8 criterion: the repeated bad path is avoided."""
    k = key()
    memory.remember_plans(k, [make_plan(1, cost=500.0), make_plan(2, cost=800.0)])
    assert len(memory.warm_start(k).plans) == 2

    memory.remember_failed_route(k, [1])

    remaining = memory.warm_start(k).plans
    assert len(remaining) == 1
    assert remaining[0].leg_ids == (2,)


def test_a_failed_leg_invalidates_every_plan_using_it(memory: GraphMemory) -> None:
    k = key()
    memory.remember_plans(k, [make_plan(1, 2, cost=500.0), make_plan(3, cost=800.0)])

    memory.remember_failed_leg(k, 2)

    remaining = memory.warm_start(k).plans
    assert [plan.leg_ids for plan in remaining] == [(3,)]


def test_failed_legs_are_reported_for_router_exclusion(memory: GraphMemory) -> None:
    k = key()
    memory.remember_failed_leg(k, 7)
    memory.remember_failed_leg(k, 9)

    assert memory.warm_start(k).failed_leg_ids == {7, 9}


# --- backtracking --------------------------------------------------------

def test_next_alternative_is_offered(memory: GraphMemory) -> None:
    """Phase 8 criterion: an alternative path is found."""
    k = key()
    memory.remember_plans(
        k, [make_plan(1, cost=500.0), make_plan(2, cost=700.0, transfers=1)]
    )

    alternative = memory.next_alternative(k, after=[1])

    assert alternative is not None
    assert alternative.leg_ids == (2,)


def test_backtracking_runs_out_cleanly(memory: GraphMemory) -> None:
    k = key()
    memory.remember_plans(k, [make_plan(1, cost=500.0)])

    assert memory.next_alternative(k, after=[1]) is None


def test_backtracking_does_not_reoffer_a_failed_route(memory: GraphMemory) -> None:
    k = key()
    memory.remember_plans(
        k,
        [
            make_plan(1, cost=500.0),
            make_plan(2, cost=700.0, transfers=1),
            make_plan(3, cost=900.0, transfers=2),
        ],
    )

    first = memory.next_alternative(k, after=[1])
    second = memory.next_alternative(k, after=first.leg_ids)

    assert first.leg_ids == (2,)
    assert second.leg_ids == (3,)


# --- housekeeping --------------------------------------------------------

def test_invalidate_forgets_one_class_only(memory: GraphMemory) -> None:
    a, b = key(dest_hub_id=2), key(dest_hub_id=3)
    memory.remember_plans(a, [make_plan(1)])
    memory.remember_plans(b, [make_plan(2)])

    memory.invalidate(a)

    assert memory.warm_start(a).hit is False
    assert memory.warm_start(b).hit is True


def test_get_memory_is_a_singleton() -> None:
    reset_memory()
    assert get_memory() is get_memory()
    reset_memory()


# --- warm-start against the real router ----------------------------------

@pytest.fixture()
def world(db):
    from sqlalchemy import select

    from app.models import Shipment
    from app.workers.world import WorldSpec, build_world

    build_world(
        db,
        WorldSpec(seed=42, hub_count=10, vehicle_count=30,
                  shipment_count=50, leg_count=150),
    )
    shipment = db.scalars(select(Shipment).limit(1)).first()
    shipment.lam = 200.0
    shipment.deadline_at = datetime(2026, 5, 4, 6, 0)
    db.commit()
    return shipment


def test_first_plan_is_a_cold_search(db, world, memory) -> None:
    outcome = plan_recovery(db, world, now=T0, memory=memory)

    assert outcome.warm_started is False
    assert outcome.result.labels_explored > 0


def test_second_plan_is_warm_started(db, world, memory) -> None:
    """Phase 8 criterion: warm-start reuses prior work."""
    first = plan_recovery(db, world, now=T0, memory=memory)
    assert first.best is not None

    second = plan_recovery(db, world, now=T0, memory=memory)

    assert second.warm_started is True
    assert second.result.labels_explored == 0
    assert second.best is not None


def test_warm_start_is_faster_than_a_cold_search(db, world, memory) -> None:
    """End-to-end wall time, like for like.

    Audit fix: this used to compare a hard-coded warm compute_ms of 0.0
    against the cold search-only time, so it proved nothing. Warm-start now
    does real work (revalidating remembered legs against the database) and
    must still beat a cold search that builds the graph from the database.
    """
    cold = plan_recovery(db, world, now=T0, memory=memory)
    warm = plan_recovery(db, world, now=T0, memory=memory)

    assert warm.warm_started is True
    assert warm.wall_ms < cold.wall_ms


def test_warm_start_can_be_disabled(db, world, memory) -> None:
    plan_recovery(db, world, now=T0, memory=memory)
    again = plan_recovery(db, world, now=T0, memory=memory, use_warm_start=False)

    assert again.warm_started is False


def test_a_recorded_failure_changes_the_next_plan(db, world, memory) -> None:
    first = plan_recovery(db, world, now=T0, memory=memory)
    chosen = [leg.leg_id for leg in first.best.legs]

    record_failure(world, T0, leg_ids=chosen, memory=memory)

    after = plan_recovery(db, world, now=T0, memory=memory)
    if after.warm_started:
        assert [leg.leg_id for leg in after.best.legs] != chosen


def test_a_failed_leg_is_excluded_from_the_next_search(db, world, memory) -> None:
    first = plan_recovery(db, world, now=T0, memory=memory)
    failed_leg = first.best.legs[0].leg_id

    k = query_key_for(world, T0)
    memory.remember_failed_leg(k, failed_leg)

    after = plan_recovery(db, world, now=T0, memory=memory, use_warm_start=False)

    for plan in after.result.plans:
        assert failed_leg not in [leg.leg_id for leg in plan.legs]


def test_dedicated_plans_are_not_memorised(db, world, memory) -> None:
    """Dedicated cost depends on departure time, so caching it would lie."""
    plan_recovery(db, world, now=T0, memory=memory)

    stored = memory.warm_start(query_key_for(world, T0)).plans
    assert all(plan.strategy != PlanStrategy.DEDICATED.value for plan in stored)
