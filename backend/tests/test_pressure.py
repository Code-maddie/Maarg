"""Phase 6 validation: Recovery Pressure Score and Emergency Recovery Mode."""

from datetime import timedelta

import pytest

from app.engines.e4_temperature.pressure import (
    ATTEMPT_SATURATION,
    CASCADE_SATURATION_DEPTH,
    EMERGENCY_THRESHOLD,
    TIME_HORIZON_HOURS,
    apply_pressure,
    cascade_factor,
    compute_pressure,
    evaluate_shipment,
    risk_factor,
    temperature_factor,
    time_factor,
)
from app.models.base import utcnow


def pressure(**overrides) -> float:
    kwargs = {"hours_to_deadline": 24.0, "temperature": 0.0}
    kwargs.update(overrides)
    return compute_pressure(**kwargs).pressure


# --- bounds --------------------------------------------------------------

def test_pressure_is_zero_when_nothing_is_wrong() -> None:
    assert pressure() == 0.0


def test_pressure_is_one_in_the_worst_case() -> None:
    assert compute_pressure(
        hours_to_deadline=-5.0,
        temperature=100.0,
        cascade_depth=10,
        p_misplace=1.0,
        failed_attempts=10,
    ).pressure == pytest.approx(1.0)


@pytest.mark.parametrize("hours", [-50.0, -1.0, 0.0, 1.0, 6.0, 12.0, 100.0])
@pytest.mark.parametrize("temperature", [0.0, 50.0, 100.0])
def test_pressure_always_stays_in_range(hours, temperature) -> None:
    result = compute_pressure(
        hours_to_deadline=hours,
        temperature=temperature,
        cascade_depth=3,
        p_misplace=0.5,
        failed_attempts=2,
    )
    assert 0.0 <= result.pressure <= 1.0


# --- individual factors --------------------------------------------------

def test_time_factor_saturates_at_the_deadline() -> None:
    assert time_factor(0.0) == 1.0
    assert time_factor(-10.0) == 1.0


def test_time_factor_is_zero_beyond_the_horizon() -> None:
    assert time_factor(TIME_HORIZON_HOURS) == 0.0
    assert time_factor(100.0) == 0.0


def test_time_factor_is_linear_in_between() -> None:
    assert time_factor(TIME_HORIZON_HOURS / 2) == pytest.approx(0.5)


def test_temperature_factor_normalises_to_unit_range() -> None:
    assert temperature_factor(0.0) == 0.0
    assert temperature_factor(50.0) == pytest.approx(0.5)
    assert temperature_factor(100.0) == 1.0
    assert temperature_factor(500.0) == 1.0


def test_cascade_factor_saturates() -> None:
    assert cascade_factor(0) == 0.0
    assert cascade_factor(CASCADE_SATURATION_DEPTH) == 1.0
    assert cascade_factor(CASCADE_SATURATION_DEPTH * 3) == 1.0


def test_risk_factor_weights_failures_above_predictions() -> None:
    """A failure that actually happened beats a prediction that it might."""
    predicted = risk_factor(1.0, failed_attempts=0)
    actual = risk_factor(0.0, failed_attempts=ATTEMPT_SATURATION)
    assert actual > predicted


def test_risk_factor_handles_an_unscored_shipment() -> None:
    assert risk_factor(None, 0) == 0.0


# --- the acceptance criteria --------------------------------------------

def test_pressure_changes_with_time() -> None:
    """Phase 6 criterion: pressure rises as the deadline approaches."""
    far = pressure(hours_to_deadline=24.0)
    mid = pressure(hours_to_deadline=6.0)
    near = pressure(hours_to_deadline=1.0)
    overdue = pressure(hours_to_deadline=-2.0)

    assert far < mid < near < overdue


def test_pressure_responds_to_priority_via_temperature() -> None:
    """Phase 6 criterion: pressure responds to priority."""
    assert pressure(temperature=10.0) < pressure(temperature=90.0)


def test_pressure_responds_to_cascade() -> None:
    """Phase 6 criterion: pressure responds to cascade."""
    assert pressure(cascade_depth=0) < pressure(cascade_depth=2) < pressure(
        cascade_depth=5
    )


def test_pressure_responds_to_failed_attempts() -> None:
    assert pressure(failed_attempts=0) < pressure(failed_attempts=3)


# --- emergency mode ------------------------------------------------------

def test_emergency_is_off_below_the_threshold() -> None:
    result = compute_pressure(hours_to_deadline=24.0, temperature=0.0)
    assert result.pressure < EMERGENCY_THRESHOLD
    assert result.emergency is False


def test_emergency_triggers_above_the_threshold() -> None:
    """Phase 6 criterion: the emergency threshold works."""
    result = compute_pressure(
        hours_to_deadline=0.0,
        temperature=100.0,
        cascade_depth=5,
        p_misplace=0.9,
        failed_attempts=3,
    )
    assert result.pressure >= EMERGENCY_THRESHOLD
    assert result.emergency is True


def test_emergency_flag_tracks_the_threshold_exactly() -> None:
    for hours in [12.0, 9.0, 6.0, 3.0, 0.0, -5.0]:
        result = compute_pressure(
            hours_to_deadline=hours, temperature=80.0, cascade_depth=3,
            p_misplace=0.6, failed_attempts=2,
        )
        assert result.emergency == (result.pressure >= EMERGENCY_THRESHOLD)


def test_a_calm_shipment_never_triggers_emergency() -> None:
    assert (
        compute_pressure(hours_to_deadline=48.0, temperature=5.0).emergency
        is False
    )


# --- breakdown -----------------------------------------------------------

def test_breakdown_reconstructs_the_score() -> None:
    from app.engines.e4_temperature.pressure import (
        W_CASCADE, W_RISK, W_TEMPERATURE, W_TIME,
    )

    result = compute_pressure(
        hours_to_deadline=4.0, temperature=60.0, cascade_depth=2,
        p_misplace=0.5, failed_attempts=1,
    )
    recomputed = (
        W_TIME * result.f_time
        + W_TEMPERATURE * result.f_temperature
        + W_CASCADE * result.f_cascade
        + W_RISK * result.f_risk
    )
    assert result.pressure == pytest.approx(recomputed, abs=0.001)


def test_weights_sum_to_one() -> None:
    """What guarantees the score is bounded in [0,1]."""
    from app.engines.e4_temperature.pressure import (
        W_CASCADE, W_RISK, W_TEMPERATURE, W_TIME,
    )

    assert W_TIME + W_TEMPERATURE + W_CASCADE + W_RISK == pytest.approx(1.0)


# --- persisted shipments -------------------------------------------------

def test_evaluate_uses_shipment_state(db, shipment) -> None:
    shipment.temperature = 80.0
    shipment.cascade_depth = 3
    shipment.p_misplace = 0.7
    shipment.deadline_at = utcnow() + timedelta(hours=1)
    db.commit()

    result = evaluate_shipment(shipment)

    assert result.shipment_id == shipment.id
    assert result.f_temperature == pytest.approx(0.8)
    assert result.pressure > 0.5


def test_apply_writes_pressure_onto_the_shipment(db, shipment) -> None:
    shipment.temperature = 70.0
    shipment.deadline_at = utcnow() + timedelta(hours=2)
    db.commit()

    result = apply_pressure(shipment)
    db.commit()

    assert shipment.pressure == result.pressure
    assert 0.0 <= shipment.pressure <= 1.0


def test_pressure_rises_as_simulated_time_passes(db, shipment) -> None:
    """The same shipment, evaluated later, must be under more pressure."""
    shipment.temperature = 50.0
    now = utcnow()
    shipment.deadline_at = now + timedelta(hours=10)
    db.commit()

    early = evaluate_shipment(shipment, now).pressure
    later = evaluate_shipment(shipment, now + timedelta(hours=8)).pressure

    assert later > early


def test_unscored_shipment_does_not_crash(db, shipment) -> None:
    shipment.p_misplace = None
    db.commit()
    assert 0.0 <= evaluate_shipment(shipment).pressure <= 1.0
