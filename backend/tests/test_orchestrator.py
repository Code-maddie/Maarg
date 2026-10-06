"""Phase 16 validation: the Recovery Orchestrator.

The acceptance criterion is that one recovery request executes the complete
pipeline, so these tests check the chain end to end and that a failure in any
single engine degrades rather than aborts it.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.engines.e1_misplacement.registry import ModelNotReadyError
from app.models import RecoveryPath, RecoveryPlan, Shipment
from app.models.enums import PlanStatus, PlanStrategy, ShipmentStatus
from app.services.orchestrator import RecoveryOrchestrator, recover_shipment

T0 = datetime(2026, 5, 1, 6, 0)

EXPECTED_STAGES = [
    "E1 misplacement",
    "E4 temperature",
    "Recovery pressure",
    "Recovery cascade",
    "E6 router + E7 memory",
    "E2 foresight",
    "E5 bounty market",
    "Persist plans",
    "E8 explainer",
]


class StubE1:
    """Deterministic stand-in for the 205 MB model."""

    def __init__(self, probability: float = 0.62) -> None:
        self.probability = probability
        self.calls = 0

    def score(self, features) -> float:  # noqa: ANN001
        self.calls += 1
        return self.probability

    @property
    def is_ready(self) -> bool:
        return True


class BrokenE1:
    def score(self, features):  # noqa: ANN001
        raise ModelNotReadyError("E1 model has not been loaded")

    @property
    def is_ready(self) -> bool:
        return False


@pytest.fixture()
def world(db):
    from app.workers.world import WorldSpec, build_world

    build_world(
        db,
        WorldSpec(seed=42, hub_count=12, vehicle_count=40,
                  shipment_count=60, leg_count=180),
    )
    return db


@pytest.fixture()
def misplaced(world) -> Shipment:
    shipment = world.scalars(select(Shipment).limit(1)).first()
    shipment.status = ShipmentStatus.MISPLACED.value
    shipment.misplaced_at = T0
    shipment.deadline_at = T0 + timedelta(hours=60)
    world.commit()
    return shipment


def run(db, shipment, **overrides):
    orchestrator = RecoveryOrchestrator(db, e1_service=StubE1())
    return orchestrator.recover(shipment, now=T0, **overrides)


# --- the acceptance criterion --------------------------------------------

def test_one_request_executes_the_complete_pipeline(world, misplaced) -> None:
    """Phase 16 criterion: one recovery request executes the whole pipeline."""
    result = run(world, misplaced)

    names = [stage.name for stage in result.stages]
    for expected in EXPECTED_STAGES:
        assert expected in names, f"stage {expected} did not run"


def test_every_stage_succeeds_on_the_happy_path(world, misplaced) -> None:
    result = run(world, misplaced)

    failures = [s for s in result.stages if not s.ok]
    assert failures == [], f"stages failed: {[(s.name, s.detail) for s in failures]}"


def test_stages_run_in_the_documented_order(world, misplaced) -> None:
    """E1 -> Pressure -> E4 -> Cascade -> E2 -> E5 -> E6 -> ... -> E8."""
    names = [s.name for s in result_names(world, misplaced)]

    assert names.index("E1 misplacement") < names.index("E4 temperature")
    assert names.index("E4 temperature") < names.index("Recovery pressure")
    assert names.index("Recovery pressure") < names.index("Recovery cascade")
    assert names.index("Recovery cascade") < names.index("E6 router + E7 memory")
    assert names.index("E6 router + E7 memory") < names.index("E2 foresight")
    assert names.index("E2 foresight") < names.index("E5 bounty market")
    assert names.index("Persist plans") < names.index("E8 explainer")


def result_names(db, shipment):
    return run(db, shipment).stages


def test_a_plan_is_committed(world, misplaced) -> None:
    result = run(world, misplaced)

    assert result.succeeded is True
    assert result.committed_plan_id is not None
    assert result.total_cost > 0
    assert result.strategy in {s.value for s in PlanStrategy}


def test_every_engine_contributed_output(world, misplaced) -> None:
    result = run(world, misplaced)

    assert result.temperature is not None
    assert result.pressure is not None
    assert result.cascade is not None
    assert result.reservation is not None
    assert result.auction is not None
    assert result.explanation is not None
    assert result.prediction is not None


# --- persistence ---------------------------------------------------------

def test_the_committed_plan_is_persisted(world, misplaced) -> None:
    result = run(world, misplaced)

    plan = world.get(RecoveryPlan, result.committed_plan_id)
    assert plan is not None
    assert plan.status == PlanStatus.COMMITTED.value
    assert plan.rank == 1
    assert plan.shipment_id == misplaced.id


def test_alternatives_are_persisted_as_proposed(world, misplaced) -> None:
    run(world, misplaced)

    proposed = world.scalars(
        select(RecoveryPlan).where(
            RecoveryPlan.shipment_id == misplaced.id,
            RecoveryPlan.status == PlanStatus.PROPOSED.value,
        )
    ).all()
    assert proposed, "no alternatives retained for dispatcher override"


def test_plan_paths_are_persisted_in_order(world, misplaced) -> None:
    result = run(world, misplaced)

    paths = world.scalars(
        select(RecoveryPath)
        .where(RecoveryPath.plan_id == result.committed_plan_id)
        .order_by(RecoveryPath.seq)
    ).all()

    assert paths
    assert [p.seq for p in paths] == list(range(len(paths)))


def test_exactly_one_plan_is_committed(world, misplaced) -> None:
    run(world, misplaced)

    committed = world.scalars(
        select(RecoveryPlan).where(
            RecoveryPlan.shipment_id == misplaced.id,
            RecoveryPlan.status == PlanStatus.COMMITTED.value,
        )
    ).all()
    assert len(committed) == 1


def test_a_second_recovery_supersedes_the_first(world, misplaced) -> None:
    first = run(world, misplaced)
    second = run(world, misplaced)

    assert second.committed_plan_id != first.committed_plan_id

    stale = world.get(RecoveryPlan, first.committed_plan_id)
    # The first COMMITTED plan stays committed; its PROPOSED siblings do not.
    superseded = world.scalars(
        select(RecoveryPlan).where(
            RecoveryPlan.rejection_reason == "Superseded by a newer recovery attempt"
        )
    ).all()
    assert superseded


def test_the_shipment_moves_to_recovering(world, misplaced) -> None:
    run(world, misplaced)
    world.refresh(misplaced)
    assert misplaced.status == ShipmentStatus.RECOVERING.value


def test_rejected_plans_are_persisted_with_their_reasons(world, misplaced) -> None:
    """E8 must survive a page reload, not live only in the response."""
    run(world, misplaced)

    rejected = world.scalars(
        select(RecoveryPlan).where(
            RecoveryPlan.shipment_id == misplaced.id,
            RecoveryPlan.status == PlanStatus.REJECTED.value,
        )
    ).all()

    for plan in rejected:
        if plan.rank == 0:
            assert plan.rejection_reason


# --- engine wiring -------------------------------------------------------

def test_e1_risk_is_written_to_the_shipment(world, misplaced) -> None:
    run(world, misplaced)
    world.refresh(misplaced)
    assert misplaced.p_misplace == pytest.approx(0.62)


def test_temperature_and_lambda_are_written(world, misplaced) -> None:
    result = run(world, misplaced)
    world.refresh(misplaced)

    assert misplaced.temperature == result.temperature.temperature
    assert misplaced.lam > 0
    assert 0.0 <= misplaced.temperature <= 100.0


def test_pressure_is_written(world, misplaced) -> None:
    run(world, misplaced)
    world.refresh(misplaced)
    assert 0.0 <= misplaced.pressure <= 1.0


def test_the_explanation_covers_the_committed_plan(world, misplaced) -> None:
    result = run(world, misplaced)

    assert result.explanation.shipment_code == misplaced.code
    assert result.explanation.strategy == result.strategy
    assert result.explanation.why_chosen
    assert result.explanation.route


def test_the_explanation_carries_every_engine_block(world, misplaced) -> None:
    result = run(world, misplaced)

    assert result.explanation.urgency
    assert result.explanation.market
    assert result.explanation.foresight
    assert result.explanation.cascade


def test_the_prediction_snapshot_feeds_e9(world, misplaced) -> None:
    result = run(world, misplaced)

    assert result.prediction.plan_id == result.committed_plan_id
    assert result.prediction.p_misplace == pytest.approx(0.62)
    assert result.prediction.strategy == result.strategy


def test_e9_can_record_the_outcome_afterwards(world, misplaced) -> None:
    """The full loop: recover, deliver, record."""
    from app.engines.e9_learning.outcomes import record_from_shipment
    from app.models import RecoveryOutcome

    result = run(world, misplaced)

    misplaced.status = ShipmentStatus.DELIVERED.value
    misplaced.delivered_at = T0 + timedelta(hours=20)
    world.commit()

    record_from_shipment(
        world, misplaced, predicted=result.prediction, now=T0 + timedelta(hours=21)
    )

    outcome = world.scalar(select(RecoveryOutcome))
    assert outcome is not None
    assert outcome.plan_id == result.committed_plan_id
    assert outcome.succeeded is True


# --- graceful degradation ------------------------------------------------

def test_an_unavailable_e1_does_not_abort_the_pipeline(world, misplaced) -> None:
    """E1 is 205 MB and may still be loading; recovery must still work."""
    orchestrator = RecoveryOrchestrator(world, e1_service=BrokenE1())
    result = orchestrator.recover(misplaced, now=T0)

    e1_stage = next(s for s in result.stages if s.name == "E1 misplacement")
    assert e1_stage.ok is True          # handled, not crashed
    assert "unavailable" in e1_stage.detail
    assert result.succeeded is True     # a plan was still committed


def test_cascade_can_be_skipped(world, misplaced) -> None:
    result = run(world, misplaced, run_cascade=False)

    assert "Recovery cascade" not in [s.name for s in result.stages]
    assert result.succeeded is True


def test_the_auction_can_be_skipped(world, misplaced) -> None:
    result = run(world, misplaced, run_auction_stage=False)

    assert "E5 bounty market" not in [s.name for s in result.stages]
    assert result.succeeded is True


def test_a_shipment_with_no_route_still_gets_a_plan(world, db) -> None:
    """A recovery returning nothing is worse than an expensive one."""
    from app.models import Hub

    shipment = world.scalars(select(Shipment).limit(1)).first()
    # An impossible deadline kills every piggyback option.
    shipment.deadline_at = T0 + timedelta(minutes=1)
    shipment.status = ShipmentStatus.MISPLACED.value
    world.commit()

    result = run(world, shipment)

    # The orchestrator's contract: a plan is ALWAYS committed. With an
    # impossible deadline that is the dedicated fallback, and the Explainer
    # must admit it arrives late rather than hide it.
    # (Audit fix: the previous assertion ended in "or True" and could never fail.)
    assert result.succeeded is True
    assert result.strategy == PlanStrategy.DEDICATED.value
    assert any("past the" in line for line in result.explanation.why_chosen)


# --- timing and determinism ---------------------------------------------

def test_every_stage_is_timed(world, misplaced) -> None:
    result = run(world, misplaced)

    assert result.total_ms > 0
    for stage in result.stages:
        assert stage.ms >= 0


def test_the_pipeline_is_fast_enough_for_the_demo(world, misplaced) -> None:
    result = run(world, misplaced)
    assert result.total_ms < 5000


def test_the_result_serialises_for_the_api(world, misplaced) -> None:
    import json

    payload = json.dumps(run(world, misplaced).as_dict())
    data = json.loads(payload)

    assert data["succeeded"] is True
    assert data["explanation"]["why_chosen"]
    assert isinstance(data["stages"], list)


def test_the_convenience_entry_point_works(world, misplaced) -> None:
    """recover_shipment uses the real E1, which may be unloaded here."""
    result = recover_shipment(world, misplaced, now=T0)
    assert result.shipment_code == misplaced.code
    assert len(result.stages) >= 5


def test_reported_temperature_matches_persisted_state(world, misplaced) -> None:
    """Regression: the Explainer must not quote pre-cascade figures.

    The cascade stage raises cascade_depth, which feeds E4's T_cascade term.
    Before the fix, result.temperature held the pre-cascade value while the
    shipment row held the post-cascade one — two different numbers for the
    same shipment in the same response.
    """
    result = run(world, misplaced)
    world.refresh(misplaced)

    assert misplaced.temperature == result.temperature.temperature
    assert misplaced.lam == result.temperature.lam
    assert misplaced.pressure == result.pressure.pressure
    # And the Explainer quotes the same figure.
    assert result.explanation.urgency["temperature"] == misplaced.temperature


def test_reprice_stage_runs_only_with_cascade(world, misplaced) -> None:
    with_cascade = [s.name for s in run(world, misplaced).stages]
    without = [s.name for s in run(world, misplaced, run_cascade=False).stages]

    assert "Re-price after cascade" in with_cascade
    assert "Re-price after cascade" not in without


def test_re_planning_leaves_exactly_one_committed_plan(world, misplaced) -> None:
    """Regression for a defect found during Phase 16 manual testing.

    _persist superseded only PROPOSED plans, so recovering the same shipment
    twice left two COMMITTED plans and the dispatcher would see two active
    recoveries for one shipment.
    """
    first = run(world, misplaced)
    second = run(world, misplaced)
    third = run(world, misplaced)

    committed = world.scalars(
        select(RecoveryPlan).where(
            RecoveryPlan.shipment_id == misplaced.id,
            RecoveryPlan.status == PlanStatus.COMMITTED.value,
        )
    ).all()

    assert len(committed) == 1
    assert committed[0].id == third.committed_plan_id

    # The earlier commitments are explicitly superseded, not silently dropped.
    for plan_id in (first.committed_plan_id, second.committed_plan_id):
        stale = world.get(RecoveryPlan, plan_id)
        assert stale.status == PlanStatus.REJECTED.value
        assert stale.rejection_reason == "Superseded by a newer recovery attempt"
