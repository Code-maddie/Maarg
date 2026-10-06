"""Phase 15 validation: E9 Recovery Outcome Learning."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.engines.e9_learning.outcomes import (
    ActualResult,
    PredictionSnapshot,
    brier_contribution,
    record_from_shipment,
    record_outcome,
    summarise_errors,
    training_records,
)
from app.models import RecoveryOutcome
from app.models.base import utcnow
from app.models.enums import PlanStrategy, ShipmentStatus

T0 = datetime(2026, 5, 1, 6, 0)


def prediction(**overrides) -> PredictionSnapshot:
    kwargs = {
        "cost": 50_000.0,
        "arrival": T0 + timedelta(hours=10),
        "p_misplace": 0.7,
        "temperature": 78.2,
        "lam": 641.0,
        "strategy": PlanStrategy.PIGGYBACK.value,
    }
    kwargs.update(overrides)
    return PredictionSnapshot(**kwargs)


def actual(**overrides) -> ActualResult:
    kwargs = {
        "cost": 52_000.0,
        "arrival": T0 + timedelta(hours=11),
        "succeeded": True,
        "misplaced": True,
    }
    kwargs.update(overrides)
    return ActualResult(**kwargs)


# --- Brier contribution --------------------------------------------------

def test_a_confident_correct_prediction_scores_near_zero() -> None:
    assert brier_contribution(0.95, True) == pytest.approx(0.0025)


def test_a_confident_wrong_prediction_scores_near_one() -> None:
    assert brier_contribution(0.95, False) == pytest.approx(0.9025)


def test_a_coin_flip_scores_a_quarter() -> None:
    """0.5 always scores 0.25 — exactly what an uninformative model gets."""
    assert brier_contribution(0.5, True) == 0.25
    assert brier_contribution(0.5, False) == 0.25


def test_an_unscored_prediction_has_no_brier() -> None:
    assert brier_contribution(None, True) is None


# --- recording (acceptance criterion) ------------------------------------

def test_a_recovery_produces_an_outcome_record(db, shipment) -> None:
    """Phase 15 criterion: a recovery produces an outcome record."""
    record_outcome(db, shipment, predicted=prediction(), actual=actual())

    rows = db.scalars(select(RecoveryOutcome)).all()
    assert len(rows) == 1
    assert rows[0].shipment_id == shipment.id
    assert rows[0].strategy == PlanStrategy.PIGGYBACK.value


def test_cost_error_is_recorded_correctly(db, shipment) -> None:
    """Phase 15 criterion: prediction error recorded correctly."""
    row = record_outcome(
        db, shipment,
        predicted=prediction(cost=50_000.0),
        actual=actual(cost=52_000.0),
    )
    # actual - predicted; positive means the engine under-estimated.
    assert row.cost_error == 2_000.0


def test_an_over_estimate_produces_a_negative_error(db, shipment) -> None:
    row = record_outcome(
        db, shipment,
        predicted=prediction(cost=60_000.0),
        actual=actual(cost=52_000.0),
    )
    assert row.cost_error == -8_000.0


def test_eta_error_is_recorded_in_hours(db, shipment) -> None:
    row = record_outcome(
        db, shipment,
        predicted=prediction(arrival=T0 + timedelta(hours=10)),
        actual=actual(arrival=T0 + timedelta(hours=13, minutes=30)),
    )
    assert row.eta_error_hours == pytest.approx(3.5)


def test_eta_error_is_zero_when_either_time_is_missing(db, shipment) -> None:
    row = record_outcome(
        db, shipment,
        predicted=prediction(arrival=None),
        actual=actual(arrival=None, succeeded=False),
    )
    assert row.eta_error_hours == 0.0


def test_the_prediction_snapshot_is_preserved(db, shipment) -> None:
    """The record must keep what was believed at commit time."""
    row = record_outcome(db, shipment, predicted=prediction(), actual=actual())

    assert row.predicted_cost == 50_000.0
    assert row.predicted_p_misplace == 0.7
    assert row.predicted_temperature == 78.2
    assert row.predicted_lambda == 641.0


def test_brier_is_stored_per_observation(db, shipment) -> None:
    row = record_outcome(
        db, shipment,
        predicted=prediction(p_misplace=0.9),
        actual=actual(misplaced=True),
    )
    assert row.risk_brier == pytest.approx(0.01)


def test_deadline_hit_is_recorded(db, shipment) -> None:
    hit = record_outcome(
        db, shipment,
        predicted=prediction(),
        actual=actual(arrival=T0 + timedelta(hours=1)),
        deadline=T0 + timedelta(hours=10),
    )
    assert hit.met_deadline is True


def test_a_late_arrival_misses_the_deadline(db, shipment) -> None:
    late = record_outcome(
        db, shipment,
        predicted=prediction(),
        actual=actual(arrival=T0 + timedelta(hours=40)),
        deadline=T0 + timedelta(hours=10),
    )
    assert late.met_deadline is False


def test_a_failed_recovery_cannot_meet_its_deadline(db, shipment) -> None:
    row = record_outcome(
        db, shipment,
        predicted=prediction(),
        actual=actual(succeeded=False, arrival=T0, failure_reason="No carrier"),
        deadline=T0 + timedelta(hours=10),
    )
    assert row.succeeded is False
    assert row.met_deadline is False
    assert row.failure_reason == "No carrier"


def test_recording_from_shipment_state(db, shipment) -> None:
    shipment.status = ShipmentStatus.DELIVERED.value
    shipment.misplaced_at = T0
    shipment.delivered_at = T0 + timedelta(hours=6)
    db.commit()

    row = record_from_shipment(
        db, shipment, predicted=prediction(), now=T0 + timedelta(hours=8)
    )

    assert row.succeeded is True
    assert row.recovery_seconds == pytest.approx(6 * 3600)
    assert row.actually_misplaced is True


def test_an_undelivered_shipment_records_a_failure(db, shipment) -> None:
    shipment.status = ShipmentStatus.MISPLACED.value
    shipment.misplaced_at = T0
    db.commit()

    row = record_from_shipment(
        db, shipment, predicted=prediction(), now=T0 + timedelta(hours=3)
    )

    assert row.succeeded is False
    assert "MISPLACED" in row.failure_reason


# --- aggregation ---------------------------------------------------------

def test_summary_of_no_data_is_safe(db) -> None:
    summary = summarise_errors(db)
    assert summary.count == 0
    assert summary.brier_score is None
    assert summary.cost_bias == "no data"


def test_summary_aggregates_recorded_outcomes(db, shipment) -> None:
    record_outcome(db, shipment, predicted=prediction(cost=100.0),
                   actual=actual(cost=150.0))
    record_outcome(db, shipment, predicted=prediction(cost=200.0),
                   actual=actual(cost=250.0))

    summary = summarise_errors(db)
    assert summary.count == 2
    assert summary.mean_cost_error == 50.0
    assert summary.success_rate == 1.0


def test_summary_detects_systematic_under_estimation(db, shipment) -> None:
    for _ in range(3):
        record_outcome(db, shipment, predicted=prediction(cost=100.0),
                       actual=actual(cost=500.0))

    assert summarise_errors(db).cost_bias == "under-estimating cost"


def test_summary_detects_systematic_over_estimation(db, shipment) -> None:
    for _ in range(3):
        record_outcome(db, shipment, predicted=prediction(cost=900.0),
                       actual=actual(cost=100.0))

    assert summarise_errors(db).cost_bias == "over-estimating cost"


def test_absolute_error_does_not_cancel_out(db, shipment) -> None:
    """A +100/-100 pair averages to zero but is not actually accurate."""
    record_outcome(db, shipment, predicted=prediction(cost=100.0),
                   actual=actual(cost=200.0))
    record_outcome(db, shipment, predicted=prediction(cost=200.0),
                   actual=actual(cost=100.0))

    summary = summarise_errors(db)
    assert summary.mean_cost_error == 0.0
    assert summary.mean_abs_cost_error == 100.0


def test_summary_computes_a_live_brier_score(db, shipment) -> None:
    record_outcome(db, shipment, predicted=prediction(p_misplace=0.5),
                   actual=actual(misplaced=True))
    record_outcome(db, shipment, predicted=prediction(p_misplace=0.5),
                   actual=actual(misplaced=False))

    assert summarise_errors(db).brier_score == pytest.approx(0.25)


def test_summary_can_filter_by_strategy(db, shipment) -> None:
    record_outcome(db, shipment,
                   predicted=prediction(strategy=PlanStrategy.PIGGYBACK.value),
                   actual=actual())
    record_outcome(db, shipment,
                   predicted=prediction(strategy=PlanStrategy.DEDICATED.value),
                   actual=actual())

    assert summarise_errors(db, strategy=PlanStrategy.DEDICATED.value).count == 1


def test_deadline_hit_rate_is_reported(db, shipment) -> None:
    record_outcome(db, shipment, predicted=prediction(),
                   actual=actual(arrival=T0 + timedelta(hours=1)),
                   deadline=T0 + timedelta(hours=10))
    record_outcome(db, shipment, predicted=prediction(),
                   actual=actual(arrival=T0 + timedelta(hours=40)),
                   deadline=T0 + timedelta(hours=10))

    assert summarise_errors(db).deadline_hit_rate == 0.5


# --- training export -----------------------------------------------------

def test_training_records_are_plain_dicts(db, shipment) -> None:
    """SH.docx §10.1 keeps Colab decoupled: the handoff is data, not objects."""
    record_outcome(db, shipment, predicted=prediction(), actual=actual())

    rows = training_records(db)
    assert len(rows) == 1
    assert isinstance(rows[0], dict)
    assert rows[0]["predicted_p_misplace"] == 0.7
    assert rows[0]["actually_misplaced"] == 1


def test_training_records_are_json_serialisable(db, shipment) -> None:
    import json

    record_outcome(db, shipment, predicted=prediction(), actual=actual())
    assert json.dumps(training_records(db))


def test_training_records_respect_the_limit(db, shipment) -> None:
    for _ in range(5):
        record_outcome(db, shipment, predicted=prediction(), actual=actual())

    assert len(training_records(db, limit=2)) == 2


def test_training_export_is_empty_without_data(db) -> None:
    assert training_records(db) == []


# --- E9 must not alter E1-E8 --------------------------------------------

def test_recording_does_not_mutate_the_shipment(db, shipment) -> None:
    """E9 is an observer; it must never change engine state."""
    before = (
        shipment.status, shipment.temperature, shipment.lam,
        shipment.pressure, shipment.p_misplace, shipment.cascade_depth,
    )

    record_outcome(db, shipment, predicted=prediction(), actual=actual())
    db.refresh(shipment)

    assert (
        shipment.status, shipment.temperature, shipment.lam,
        shipment.pressure, shipment.p_misplace, shipment.cascade_depth,
    ) == before
