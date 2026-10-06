"""Phase 7 validation: E6 Piggy Router.

Uses hand-built graphs so every constraint is exercised deterministically,
plus one test against the real generated world.
"""

from datetime import datetime, timedelta

import pytest

from app.engines.e6_piggy_router.graph import (
    MIN_TRANSFER_MINUTES,
    Edge,
    TransportGraph,
    build_graph,
    transfer_ready_at,
)
from app.engines.e6_piggy_router.router import (
    MAX_TRANSFERS,
    PiggyRouter,
    RejectionReason,
    _Label,
    dedicated_plan,
    route_shipment,
)
from app.models import Hub
from app.models.enums import LegStatus, PlanStrategy

T0 = datetime(2026, 5, 1, 6, 0)


def hub(hub_id: int, code: str, lat: float, lng: float) -> Hub:
    instance = Hub(code=code, name=code, lat=lat, lng=lng, is_active=True)
    instance.id = hub_id
    return instance


# A → B → C corridor, plus a slow direct A → C.
HUB_A = hub(1, "A", 28.61, 77.20)
HUB_B = hub(2, "B", 23.02, 72.57)
HUB_C = hub(3, "C", 19.07, 72.87)
HUBS = {1: HUB_A, 2: HUB_B, 3: HUB_C}


def edge(
    leg_id: int,
    frm: int,
    to: int,
    dep_h: float,
    arr_h: float,
    *,
    cost: float = 1000.0,
    residual_kg: float = 500.0,
    residual_m3: float = 20.0,
    handling: float = 0.0,
) -> Edge:
    return Edge(
        leg_id=leg_id,
        from_hub_id=frm,
        to_hub_id=to,
        departure_at=T0 + timedelta(hours=dep_h),
        arrival_at=T0 + timedelta(hours=arr_h),
        residual_kg=residual_kg,
        residual_m3=residual_m3,
        transit_cost=cost,
        handling_penalty=handling,
        distance_km=500.0,
        vehicle_id=leg_id,
    )


def router_for(*edges: Edge) -> PiggyRouter:
    return PiggyRouter(TransportGraph(list(edges), HUBS))


def route(
    router: PiggyRouter,
    *,
    deadline_h: float = 48.0,
    weight: float = 10.0,
    volume: float = 0.5,
    lam: float = 100.0,
    k: int = 5,
    allow_dedicated: bool = False,
):
    return router.route(
        origin_hub_id=1,
        dest_hub_id=3,
        depart_after=T0,
        deadline=T0 + timedelta(hours=deadline_h),
        weight_kg=weight,
        volume_m3=volume,
        lam=lam,
        k=k,
        allow_dedicated=allow_dedicated,
    )


# --- edge weight (SH.docx §16) -------------------------------------------

def test_edge_weight_matches_the_formula() -> None:
    e = edge(1, 1, 2, 0, 4, cost=1000.0, handling=150.0)
    # 1000 + 100*4 + 150
    assert e.weight(100.0) == pytest.approx(1550.0)


def test_edge_weight_rises_with_lambda() -> None:
    e = edge(1, 1, 2, 0, 4, cost=1000.0)
    assert e.weight(200.0) > e.weight(50.0)


def test_transit_hours_is_never_negative() -> None:
    assert edge(1, 1, 2, 5, 2).transit_hours == 0.0


# --- feasible routing ----------------------------------------------------

def test_direct_route_is_found() -> None:
    """Phase 7 criterion: a feasible route is generated."""
    result = route(router_for(edge(1, 1, 3, 1, 9)))

    assert result.best is not None
    assert result.best.feasible is True
    assert [leg.leg_id for leg in result.best.legs] == [1]


def test_multi_hop_route_is_found() -> None:
    result = route(router_for(edge(1, 1, 2, 1, 5), edge(2, 2, 3, 7, 11)))

    assert result.best is not None
    assert [leg.leg_id for leg in result.best.legs] == [1, 2]
    assert result.best.transfers == 1


def test_cheapest_plan_ranks_first() -> None:
    result = route(
        router_for(
            edge(1, 1, 3, 1, 9, cost=9000.0),
            edge(2, 1, 3, 1, 9, cost=1000.0),
        )
    )
    assert result.best.legs[0].leg_id == 2


def test_k_best_returns_multiple_ordered_plans() -> None:
    result = route(
        router_for(
            edge(1, 1, 3, 1, 9, cost=1000.0),
            edge(2, 1, 3, 2, 10, cost=2000.0),
            edge(3, 1, 3, 3, 11, cost=3000.0),
        ),
        k=3,
    )

    assert len(result.plans) >= 2
    scores = [plan.score for plan in result.plans]
    assert scores == sorted(scores, reverse=True)


def test_k_limits_the_number_of_plans() -> None:
    result = route(
        router_for(*[edge(i, 1, 3, i, i + 8, cost=1000.0 * i) for i in range(1, 8)]),
        k=2,
    )
    assert len(result.plans) <= 2


# --- infeasibility -------------------------------------------------------

def test_no_path_is_rejected_with_a_reason() -> None:
    """Phase 7 criterion: an infeasible route is rejected."""
    result = route(router_for(edge(1, 1, 2, 1, 5)))  # nothing reaches hub 3

    assert result.plans == []
    assert result.best is None
    assert any(
        plan.rejection_reason == RejectionReason.NO_PATH for plan in result.rejected
    )


def test_empty_graph_is_rejected() -> None:
    result = route(router_for())
    assert result.plans == []
    assert result.rejected


def test_unknown_hub_is_rejected() -> None:
    result = PiggyRouter(TransportGraph([], HUBS)).route(
        origin_hub_id=999, dest_hub_id=3, depart_after=T0,
        deadline=T0 + timedelta(hours=10), weight_kg=1.0, volume_m3=0.1,
        lam=100.0,
    )
    assert result.plans == []
    assert result.rejected[0].rejection_reason == RejectionReason.NO_PATH


# --- capacity constraint -------------------------------------------------

def test_capacity_is_respected_by_weight() -> None:
    """Phase 7 criterion: capacity respected."""
    result = route(router_for(edge(1, 1, 3, 1, 9, residual_kg=5.0)), weight=100.0)
    assert result.plans == []


def test_capacity_is_respected_by_volume() -> None:
    result = route(router_for(edge(1, 1, 3, 1, 9, residual_m3=0.1)), volume=5.0)
    assert result.plans == []


def test_a_leg_with_exactly_enough_capacity_is_usable() -> None:
    result = route(
        router_for(edge(1, 1, 3, 1, 9, residual_kg=100.0, residual_m3=2.0)),
        weight=100.0, volume=2.0,
    )
    assert result.best is not None


def test_router_picks_the_leg_that_fits() -> None:
    result = route(
        router_for(
            edge(1, 1, 3, 1, 9, cost=100.0, residual_kg=5.0),    # cheap, too small
            edge(2, 1, 3, 1, 9, cost=5000.0, residual_kg=500.0),  # dear, fits
        ),
        weight=100.0,
    )
    assert result.best.legs[0].leg_id == 2


# --- deadline constraint -------------------------------------------------

def test_deadline_is_respected() -> None:
    """Phase 7 criterion: deadline respected."""
    result = route(router_for(edge(1, 1, 3, 1, 40)), deadline_h=10.0)
    assert result.plans == []


def test_a_plan_arriving_exactly_on_the_deadline_is_accepted() -> None:
    result = route(router_for(edge(1, 1, 3, 1, 10)), deadline_h=10.0)
    assert result.best is not None


def test_router_prefers_an_on_time_plan_over_a_cheaper_late_one() -> None:
    result = route(
        router_for(
            edge(1, 1, 3, 1, 40, cost=10.0),     # cheap but late
            edge(2, 1, 3, 1, 9, cost=5000.0),    # dear but on time
        ),
        deadline_h=12.0,
    )
    assert result.best.legs[0].leg_id == 2


# --- transfer constraint -------------------------------------------------

def test_transfer_requires_the_minimum_connection_time() -> None:
    assert transfer_ready_at(T0) == T0 + timedelta(minutes=MIN_TRANSFER_MINUTES)


def test_a_too_tight_connection_is_not_used() -> None:
    """Second leg departs 10 minutes after the first arrives."""
    result = route(
        router_for(
            edge(1, 1, 2, 1, 5),
            edge(2, 2, 3, 5 + (10 / 60), 9),
        )
    )
    assert result.plans == []


def test_a_sufficient_connection_is_used() -> None:
    result = route(
        router_for(
            edge(1, 1, 2, 1, 5),
            edge(2, 2, 3, 5 + (45 / 60), 9),
        )
    )
    assert result.best is not None
    assert result.best.transfers == 1


def test_transfer_limit_is_enforced() -> None:
    """A chain longer than MAX_TRANSFERS must not be returned."""
    edges = []
    hubs = dict(HUBS)
    for i in range(MAX_TRANSFERS + 3):
        source, target = 10 + i, 11 + i
        for node in (source, target):
            if node not in hubs:
                hubs[node] = hub(node, f"H{node}", 20.0 + node * 0.1, 75.0)
        edges.append(edge(100 + i, source, target, i * 2, i * 2 + 1))

    router = PiggyRouter(TransportGraph(edges, hubs))
    result = router.route(
        origin_hub_id=10, dest_hub_id=11 + MAX_TRANSFERS + 2,
        depart_after=T0, deadline=T0 + timedelta(hours=100),
        weight_kg=1.0, volume_m3=0.1, lam=100.0, allow_dedicated=False,
    )

    for plan in result.plans:
        assert plan.transfers <= MAX_TRANSFERS


# --- dominance -----------------------------------------------------------

def test_label_dominance_detects_a_worse_label() -> None:
    better = _Label(cost=100.0, arrival=T0, transfers=0, hub_id=1)
    worse = _Label(cost=200.0, arrival=T0 + timedelta(hours=1), transfers=1, hub_id=1)

    assert better.dominates(worse) is True
    assert worse.dominates(better) is False


def test_identical_labels_do_not_dominate_each_other() -> None:
    a = _Label(cost=100.0, arrival=T0, transfers=0, hub_id=1)
    b = _Label(cost=100.0, arrival=T0, transfers=0, hub_id=1)
    assert a.dominates(b) is False


def test_a_label_better_on_only_one_resource_still_dominates() -> None:
    better = _Label(cost=100.0, arrival=T0, transfers=0, hub_id=1)
    worse = _Label(cost=100.0, arrival=T0, transfers=1, hub_id=1)
    assert better.dominates(worse) is True


def test_a_label_cheaper_but_later_does_not_dominate() -> None:
    cheap_late = _Label(cost=50.0, arrival=T0 + timedelta(hours=5), transfers=0, hub_id=1)
    dear_early = _Label(cost=500.0, arrival=T0, transfers=0, hub_id=1)

    assert cheap_late.dominates(dear_early) is False
    assert dear_early.dominates(cheap_late) is False


def test_dominance_keeps_the_search_bounded() -> None:
    """Many parallel equivalent edges must not explode label count."""
    edges = [edge(i, 1, 2, 1, 5, cost=1000.0) for i in range(1, 30)]
    edges.append(edge(999, 2, 3, 6, 10))

    result = PiggyRouter(TransportGraph(edges, HUBS)).route(
        origin_hub_id=1, dest_hub_id=3, depart_after=T0,
        deadline=T0 + timedelta(hours=48), weight_kg=1.0, volume_m3=0.1,
        lam=100.0, allow_dedicated=False,
    )
    assert result.labels_explored < 200


# --- strategies ----------------------------------------------------------

def test_dedicated_plan_is_always_available() -> None:
    plan = dedicated_plan(HUB_A, HUB_C, T0, T0 + timedelta(hours=100))

    assert plan.strategy == PlanStrategy.DEDICATED.value
    assert plan.feasible is True
    assert plan.total_cost > 0
    assert plan.legs[0].is_dedicated is True


def test_dedicated_plan_can_miss_a_tight_deadline() -> None:
    plan = dedicated_plan(HUB_A, HUB_C, T0, T0 + timedelta(minutes=5))
    assert plan.feasible is False
    assert "after the deadline" in plan.rejection_reason


def test_dedicated_is_offered_when_requested() -> None:
    result = route(router_for(edge(1, 1, 3, 1, 9)), allow_dedicated=True)
    assert any(
        plan.strategy == PlanStrategy.DEDICATED.value for plan in result.plans
    )


def test_piggyback_beats_dedicated_on_cost() -> None:
    """The core pitch: reuse existing capacity instead of dispatching."""
    result = route(router_for(edge(1, 1, 3, 1, 9, cost=500.0)), allow_dedicated=True)

    piggy = next(p for p in result.plans if p.strategy == PlanStrategy.PIGGYBACK.value)
    dedicated = next(p for p in result.plans if p.strategy == PlanStrategy.DEDICATED.value)

    assert piggy.total_cost < dedicated.total_cost
    assert result.best.strategy == PlanStrategy.PIGGYBACK.value


def test_dedicated_wins_when_no_piggyback_exists() -> None:
    result = route(router_for(), allow_dedicated=True)
    assert result.best is not None
    assert result.best.strategy == PlanStrategy.DEDICATED.value


# --- rejection reasons are concrete --------------------------------------

def test_every_rejection_carries_a_real_reason() -> None:
    """E8 must never display a placeholder."""
    result = route(router_for(edge(1, 1, 2, 1, 5)), deadline_h=2.0)

    assert result.rejected
    for plan in result.rejected:
        assert plan.rejection_reason
        assert plan.rejection_reason.strip() != ""
        assert "TODO" not in plan.rejection_reason


def test_deadline_rejection_names_the_times() -> None:
    plan = dedicated_plan(HUB_A, HUB_C, T0, T0 + timedelta(minutes=1))
    assert "2026-05-01" in plan.rejection_reason


# --- metrics -------------------------------------------------------------

def test_result_reports_compute_time_and_effort() -> None:
    result = route(router_for(edge(1, 1, 3, 1, 9)))
    assert result.compute_ms >= 0
    assert result.labels_explored > 0
    assert result.edges_considered == 1


# --- against the generated world -----------------------------------------

def test_graph_builds_from_the_database(db) -> None:
    from app.workers.world import WorldSpec, build_world

    build_world(db, WorldSpec(seed=42, hub_count=8, vehicle_count=10,
                              shipment_count=20, leg_count=40))

    graph = build_graph(db, now=datetime(2026, 5, 1, 6, 0), horizon_hours=72)
    assert graph.edge_count > 0
    assert len(graph.hubs) == 8


def test_graph_excludes_closed_hubs(db) -> None:
    from sqlalchemy import select
    from app.workers.world import WorldSpec, build_world

    build_world(db, WorldSpec(seed=42, hub_count=8, vehicle_count=10,
                              shipment_count=20, leg_count=40))

    closed = db.scalars(select(Hub).limit(1)).first()
    closed.is_active = False
    db.commit()

    graph = build_graph(db, now=datetime(2026, 5, 1, 6, 0))
    assert all(e.to_hub_id != closed.id for bucket in graph._out.values() for e in bucket)


def test_graph_excludes_cancelled_legs(db) -> None:
    from sqlalchemy import select
    from app.models import Leg
    from app.workers.world import WorldSpec, build_world

    build_world(db, WorldSpec(seed=42, hub_count=8, vehicle_count=10,
                              shipment_count=20, leg_count=40))

    leg = db.scalars(select(Leg).limit(1)).first()
    leg.status = LegStatus.CANCELLED.value
    db.commit()

    graph = build_graph(db, now=datetime(2026, 5, 1, 6, 0))
    assert all(
        e.leg_id != leg.id for bucket in graph._out.values() for e in bucket
    )


def test_route_shipment_end_to_end(db) -> None:
    from sqlalchemy import select
    from app.models import Shipment
    from app.workers.world import WorldSpec, build_world

    build_world(db, WorldSpec(seed=42, hub_count=10, vehicle_count=30,
                              shipment_count=50, leg_count=150))

    shipment = db.scalars(select(Shipment).limit(1)).first()
    shipment.lam = 200.0
    shipment.deadline_at = datetime(2026, 5, 4, 6, 0)
    db.commit()

    result = route_shipment(db, shipment, now=datetime(2026, 5, 1, 6, 0))

    assert result.best is not None
    assert result.best.total_cost > 0
    assert result.compute_ms < 5000


def test_piggyback_failure_is_explained_even_when_dedicated_succeeds() -> None:
    """E8 must be able to say WHY existing capacity could not be used.

    Regression test for a gap found during Phase 7 manual testing: when the
    dedicated fallback succeeded, no rejection was recorded at all, so the
    dispatcher saw "DEDICATED chosen" with no reason.
    """
    result = route(router_for(), allow_dedicated=True)

    assert result.best.strategy == PlanStrategy.DEDICATED.value
    piggyback_rejections = [
        plan for plan in result.rejected
        if plan.strategy == PlanStrategy.PIGGYBACK.value
    ]
    assert piggyback_rejections, "no explanation for the piggyback failure"
    assert piggyback_rejections[0].rejection_reason == RejectionReason.NO_PATH


def test_a_late_only_route_is_rejected_by_reference_to_the_deadline() -> None:
    """A leg exists but arrives late; the reason must mention the deadline.

    Late edges are pruned during expansion, so no label reaches the
    destination and NO_PATH is returned — its wording covers this case
    explicitly rather than blaming the planning horizon.
    """
    result = route(
        router_for(edge(1, 1, 3, 1, 40)), deadline_h=10.0, allow_dedicated=False
    )

    reasons = [plan.rejection_reason for plan in result.rejected]
    assert any("before the deadline" in (reason or "") for reason in reasons)
