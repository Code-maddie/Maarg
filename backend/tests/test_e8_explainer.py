"""Phase 14 validation: E8 Explainer.

Determinism and reason-quality are the acceptance criteria, so both are
tested hard.
"""

from datetime import datetime, timedelta

import pytest

from app.engines.e4_temperature.engine import TemperatureBreakdown
from app.engines.e4_temperature.pressure import compute_pressure
from app.engines.e5_bounty.market import AuctionOutcome
from app.engines.e6_piggy_router.router import CandidatePlan, PlanLeg
from app.engines.e8_explainer.explainer import (
    MISSING_REASON,
    build_route_evidence,
    explain,
    explain_alternatives,
)
from app.models.enums import PlanStrategy

T0 = datetime(2026, 5, 1, 6, 0)
DEADLINE = T0 + timedelta(hours=24)
HUB_NAMES = {1: "Delhi Hub", 2: "Indore Hub", 3: "Mumbai Hub"}


def plan(
    *,
    strategy: str = PlanStrategy.PIGGYBACK.value,
    cost: float = 50_000.0,
    transfers: int = 0,
    hours: int = 10,
    feasible: bool = True,
    reason: str = None,
    score: float = 0.8,
    legs: int = 1,
) -> CandidatePlan:
    hops = []
    for index in range(legs):
        hops.append(
            PlanLeg(
                leg_id=index + 1,
                from_hub_id=1 + index,
                to_hub_id=2 + index,
                departure_at=T0 + timedelta(hours=index * 2),
                arrival_at=T0 + timedelta(hours=hours),
                edge_cost=cost / max(1, legs),
                is_dedicated=(strategy == PlanStrategy.DEDICATED.value),
            )
        )

    return CandidatePlan(
        strategy=strategy,
        legs=tuple(hops),
        total_cost=cost,
        arrival_at=T0 + timedelta(hours=hours) if feasible else None,
        transfers=transfers,
        feasible=feasible,
        rejection_reason=reason,
        score=score,
    )


def temperature() -> TemperatureBreakdown:
    return TemperatureBreakdown(
        shipment_id=1, temperature=78.2, lam=641.0, zone="HOT",
        t_base=10.0, t_time=40.0, t_delay=18.2, t_cascade=10.0,
        hours_to_deadline=4.0, policy_mode="BUSINESS",
    )


# --- determinism (acceptance criterion) ----------------------------------

def test_explanation_is_deterministic() -> None:
    """Phase 14 criterion: the selected-plan explanation is deterministic."""
    chosen = plan()
    rejected = [plan(feasible=False, reason="Capacity exceeded", cost=0.0)]

    first = explain(
        shipment_code="S001", chosen=chosen, rejected=rejected,
        hub_names=HUB_NAMES, deadline=DEADLINE, temperature=temperature(),
    ).as_dict()
    second = explain(
        shipment_code="S001", chosen=chosen, rejected=rejected,
        hub_names=HUB_NAMES, deadline=DEADLINE, temperature=temperature(),
    ).as_dict()

    assert first == second


def test_repeated_calls_produce_identical_prose() -> None:
    chosen = plan()
    runs = [
        explain(
            shipment_code="S001", chosen=chosen,
            also_ran=[plan(strategy=PlanStrategy.DEDICATED.value, cost=90_000.0)],
            hub_names=HUB_NAMES, deadline=DEADLINE,
        ).why_chosen
        for _ in range(5)
    ]
    assert all(run == runs[0] for run in runs)


def test_explanation_does_not_read_the_clock() -> None:
    """Nothing in the output may depend on wall-clock time."""
    import time

    chosen = plan()
    first = explain(shipment_code="S1", chosen=chosen, deadline=DEADLINE).as_dict()
    time.sleep(0.05)
    second = explain(shipment_code="S1", chosen=chosen, deadline=DEADLINE).as_dict()

    assert first == second


# --- rejected alternatives (acceptance criterion) ------------------------

def test_rejected_candidates_show_their_actual_reasons() -> None:
    """Phase 14 criterion: rejected candidates show actual reasons."""
    rejected = [
        plan(feasible=False, reason="No route reaches the destination in time", cost=0.0),
        plan(feasible=False, reason="Capacity 5kg is below the required 100kg", cost=0.0),
    ]

    result = explain(
        shipment_code="S1", chosen=plan(), rejected=rejected, deadline=DEADLINE
    )

    reasons = [alt.reason for alt in result.alternatives]
    assert "No route reaches the destination in time" in reasons
    assert "Capacity 5kg is below the required 100kg" in reasons


def test_no_alternative_ever_carries_a_placeholder() -> None:
    result = explain(
        shipment_code="S1",
        chosen=plan(),
        rejected=[plan(feasible=False, reason="Deadline missed", cost=0.0)],
        also_ran=[plan(strategy=PlanStrategy.DEDICATED.value, cost=90_000.0)],
        deadline=DEADLINE,
    )

    for alt in result.alternatives:
        assert alt.reason
        assert "TODO" not in alt.reason
        assert alt.reason.strip() != ""


def test_a_missing_reason_is_reported_as_a_defect() -> None:
    """The explainer must not invent a plausible excuse."""
    result = explain(
        shipment_code="S1",
        chosen=plan(),
        rejected=[plan(feasible=False, reason=None, cost=0.0)],
        deadline=DEADLINE,
    )

    assert result.alternatives[0].reason == MISSING_REASON
    assert "defect" in result.alternatives[0].reason


def test_feasible_also_rans_get_a_comparative_reason() -> None:
    """A plan that merely scored lower still needs an explanation."""
    result = explain(
        shipment_code="S1",
        chosen=plan(cost=50_000.0),
        also_ran=[plan(strategy=PlanStrategy.DEDICATED.value, cost=90_000.0)],
        deadline=DEADLINE,
    )

    reason = result.alternatives[0].reason
    assert "more expensive" in reason
    assert "90000.00" in reason or "90,000" in reason


def test_a_cheaper_but_slower_alternative_is_explained_correctly() -> None:
    result = explain(
        shipment_code="S1",
        chosen=plan(cost=50_000.0, transfers=0, hours=10),
        also_ran=[plan(cost=30_000.0, transfers=3, hours=20)],
        deadline=DEADLINE,
    )

    reason = result.alternatives[0].reason
    assert "transfers" in reason
    assert "handling risk" in reason


def test_cost_delta_is_reported() -> None:
    result = explain(
        shipment_code="S1",
        chosen=plan(cost=50_000.0),
        also_ran=[plan(strategy=PlanStrategy.DEDICATED.value, cost=90_000.0)],
        deadline=DEADLINE,
    )
    assert result.alternatives[0].cost_delta == 40_000.0


def test_the_chosen_plan_is_not_listed_as_an_alternative() -> None:
    chosen = plan()
    result = explain(
        shipment_code="S1", chosen=chosen, also_ran=[chosen], deadline=DEADLINE
    )
    assert result.alternatives == []


# --- route / cost / ETA / capacity evidence ------------------------------

def test_route_evidence_names_real_hubs() -> None:
    evidence = build_route_evidence(plan(legs=2), HUB_NAMES)

    assert evidence[0].from_hub == "Delhi Hub"
    assert evidence[0].to_hub == "Indore Hub"
    assert evidence[1].to_hub == "Mumbai Hub"


def test_route_evidence_falls_back_for_unknown_hubs() -> None:
    evidence = build_route_evidence(plan(), {})
    assert evidence[0].from_hub == "Hub 1"


def test_route_evidence_carries_times_and_cost() -> None:
    evidence = build_route_evidence(plan(), HUB_NAMES)

    assert evidence[0].departure_at is not None
    assert evidence[0].arrival_at is not None
    assert evidence[0].cost > 0


def test_dedicated_legs_are_marked() -> None:
    evidence = build_route_evidence(
        plan(strategy=PlanStrategy.DEDICATED.value), HUB_NAMES
    )
    assert evidence[0].is_dedicated is True


# --- the positive case ---------------------------------------------------

def test_piggyback_explains_that_no_vehicle_was_dispatched() -> None:
    result = explain(shipment_code="S1", chosen=plan(), deadline=DEADLINE)
    assert any("already scheduled" in line for line in result.why_chosen)


def test_dedicated_explains_why_it_was_necessary() -> None:
    result = explain(
        shipment_code="S1",
        chosen=plan(strategy=PlanStrategy.DEDICATED.value),
        deadline=DEADLINE,
    )
    assert any("No existing capacity" in line for line in result.why_chosen)


def test_the_saving_against_dedicated_is_quantified() -> None:
    """The headline number for the pitch."""
    result = explain(
        shipment_code="S1",
        chosen=plan(cost=60_000.0),
        also_ran=[plan(strategy=PlanStrategy.DEDICATED.value, cost=100_000.0)],
        deadline=DEADLINE,
    )

    saving_lines = [line for line in result.why_chosen if "saving" in line]
    assert saving_lines
    assert "40000.00" in saving_lines[0]
    assert "40.0%" in saving_lines[0]


def test_deadline_slack_is_stated() -> None:
    result = explain(
        shipment_code="S1", chosen=plan(hours=10), deadline=DEADLINE
    )
    assert result.slack_hours == pytest.approx(14.0)
    assert any("inside the" in line for line in result.why_chosen)


def test_a_late_arrival_is_admitted_not_hidden() -> None:
    result = explain(
        shipment_code="S1", chosen=plan(hours=40), deadline=DEADLINE
    )
    assert result.slack_hours < 0
    assert any("past the" in line for line in result.why_chosen)


def test_transfers_are_described() -> None:
    zero = explain(shipment_code="S1", chosen=plan(transfers=0), deadline=DEADLINE)
    two = explain(shipment_code="S1", chosen=plan(transfers=2), deadline=DEADLINE)

    assert any("no transfers" in line for line in zero.why_chosen)
    assert any("2 transfer" in line for line in two.why_chosen)


def test_lambda_pricing_is_explained() -> None:
    result = explain(
        shipment_code="S1", chosen=plan(), deadline=DEADLINE,
        temperature=temperature(),
    )
    line = [l for l in result.why_chosen if "lambda" in l][0]
    assert "641.00" in line
    assert "78.2" in line
    assert "HOT" in line
    assert "BUSINESS" in line


# --- engine evidence blocks ---------------------------------------------

def test_urgency_block_carries_the_full_breakdown() -> None:
    pressure = compute_pressure(hours_to_deadline=2.0, temperature=78.2)
    result = explain(
        shipment_code="S1", chosen=plan(), deadline=DEADLINE,
        temperature=temperature(), pressure=pressure,
    )

    assert result.urgency["temperature"] == 78.2
    assert result.urgency["lambda_per_hour"] == 641.0
    assert result.urgency["t_time"] == 40.0
    assert "pressure" in result.urgency
    assert "emergency" in result.urgency


def test_market_block_shows_the_vickrey_numbers() -> None:
    outcome = AuctionOutcome(
        auction_id=7, status="AWARDED", max_bounty=900.0,
        winning_vehicle_id=3, payment=500.0, bid_count=3,
        lowest_bid=300.0, second_lowest_bid=500.0,
        reason="Lowest bidder wins, paid the second-lowest bid",
    )
    result = explain(
        shipment_code="S1", chosen=plan(), deadline=DEADLINE, auction=outcome
    )

    assert result.market["payment"] == 500.0
    assert result.market["second_lowest_bid"] == 500.0
    assert result.market["bid_count"] == 3


def test_blocks_are_empty_when_no_engine_ran() -> None:
    result = explain(shipment_code="S1", chosen=plan(), deadline=DEADLINE)

    assert result.urgency == {}
    assert result.market == {}
    assert result.foresight == {}
    assert result.cascade == {}
    assert result.fusion == {}


def test_headline_summarises_the_decision() -> None:
    result = explain(shipment_code="S204", chosen=plan(cost=67_586.35), deadline=DEADLINE)

    assert "S204" in result.headline
    assert "PIGGYBACK" in result.headline
    assert "67586.35" in result.headline


def test_output_serialises_cleanly_for_the_api() -> None:
    import json

    result = explain(
        shipment_code="S1", chosen=plan(legs=2),
        rejected=[plan(feasible=False, reason="Deadline missed", cost=0.0)],
        hub_names=HUB_NAMES, deadline=DEADLINE, temperature=temperature(),
    )

    payload = json.dumps(result.as_dict())
    assert "S1" in payload
    assert json.loads(payload)["route"][0]["from_hub"] == "Delhi Hub"
