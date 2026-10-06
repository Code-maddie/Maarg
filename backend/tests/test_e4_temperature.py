"""Phase 5 validation: E4 Adaptive Recovery Temperature and lambda.

Formulas are asserted against SH.docx §16 directly.
"""

from datetime import timedelta

import pytest

from app.engines.e4_temperature.engine import (
    CASCADE_SATURATION_DEPTH,
    DELAY_SATURATION_HOURS,
    TIME_HORIZON_HOURS,
    TemperatureEngine,
    compute_lambda,
    compute_temperature,
    zone_for,
)
from app.engines.e4_temperature.policy import (
    DEFAULT_MODE,
    POLICY_WEIGHTS,
    PolicyWeights,
    get_active_weights,
    get_policy,
    set_policy,
    weights_for,
)
from app.models.base import utcnow
from app.models.enums import PolicyModeName, TemperatureZone

BASE = PolicyWeights()


def temp(**overrides) -> float:
    """Computes a temperature from sensible defaults."""
    kwargs = {
        "base_priority": 1.0,
        "hours_to_deadline": 48.0,
        "hours_overdue": 0.0,
        "cascade_depth": 0,
        "sla_penalty_per_hour": 100.0,
        "weights": BASE,
    }
    kwargs.update(overrides)
    return compute_temperature(**kwargs).temperature


# --- lambda (SH.docx §16) ------------------------------------------------

def test_lambda_equals_base_penalty_at_zero_temperature() -> None:
    assert compute_lambda(0.0, 100.0) == pytest.approx(100.0)


def test_lambda_doubles_at_temperature_50() -> None:
    assert compute_lambda(50.0, 100.0) == pytest.approx(200.0)


def test_lambda_triples_at_temperature_100() -> None:
    assert compute_lambda(100.0, 100.0) == pytest.approx(300.0)


def test_lambda_scales_with_the_sla_penalty() -> None:
    assert compute_lambda(50.0, 250.0) == pytest.approx(500.0)


def test_lambda_rises_monotonically_with_temperature() -> None:
    values = [compute_lambda(t, 100.0) for t in range(0, 101, 10)]
    assert values == sorted(values)
    assert len(set(values)) == len(values)


# --- clamping ------------------------------------------------------------

def test_temperature_is_clamped_to_the_0_100_range() -> None:
    hot = compute_temperature(
        base_priority=99.0,
        hours_to_deadline=-100.0,
        hours_overdue=100.0,
        cascade_depth=99,
        sla_penalty_per_hour=100.0,
        weights=PolicyWeights(w_base=500, w_time=500, w_delay=500, w_cascade=500),
    )
    assert hot.temperature == 100.0

    cold = compute_temperature(
        base_priority=0.0,
        hours_to_deadline=1000.0,
        hours_overdue=0.0,
        cascade_depth=0,
        sla_penalty_per_hour=100.0,
        weights=BASE,
    )
    assert cold.temperature == 0.0


# --- time term -----------------------------------------------------------

def test_temperature_rises_as_the_deadline_approaches() -> None:
    """The core E4 behaviour."""
    far = temp(hours_to_deadline=20.0)
    near = temp(hours_to_deadline=4.0)
    imminent = temp(hours_to_deadline=0.5)

    assert far < near < imminent


def test_time_term_is_zero_beyond_the_horizon() -> None:
    assert temp(hours_to_deadline=TIME_HORIZON_HOURS) == temp(
        hours_to_deadline=1000.0
    )


def test_overdue_saturates_the_time_term() -> None:
    breakdown = compute_temperature(
        base_priority=1.0, hours_to_deadline=-1.0, hours_overdue=1.0,
        cascade_depth=0, sla_penalty_per_hour=100.0, weights=BASE,
    )
    assert breakdown.t_time == pytest.approx(BASE.w_time)


def test_time_pressure_is_non_linear() -> None:
    """Urgency must climb faster near the deadline than far from it."""
    early_gain = temp(hours_to_deadline=18.0) - temp(hours_to_deadline=24.0)
    late_gain = temp(hours_to_deadline=0.0) - temp(hours_to_deadline=6.0)
    assert late_gain > early_gain


# --- delay term ----------------------------------------------------------

def test_delay_term_increases_with_lateness() -> None:
    assert temp(hours_overdue=0.0) < temp(hours_overdue=3.0) < temp(hours_overdue=9.0)


def test_delay_term_saturates() -> None:
    at_saturation = temp(hours_overdue=DELAY_SATURATION_HOURS)
    beyond = temp(hours_overdue=DELAY_SATURATION_HOURS * 10)
    assert at_saturation == pytest.approx(beyond)


# --- cascade term --------------------------------------------------------

def test_cascade_term_increases_with_depth() -> None:
    assert temp(cascade_depth=0) < temp(cascade_depth=2) < temp(cascade_depth=4)


def test_cascade_term_saturates() -> None:
    assert temp(cascade_depth=CASCADE_SATURATION_DEPTH) == pytest.approx(
        temp(cascade_depth=CASCADE_SATURATION_DEPTH * 5)
    )


# --- base term -----------------------------------------------------------

def test_higher_priority_raises_temperature() -> None:
    assert temp(base_priority=0.5) < temp(base_priority=2.0)


# --- breakdown -----------------------------------------------------------

def test_breakdown_terms_sum_to_the_temperature() -> None:
    breakdown = compute_temperature(
        base_priority=1.5, hours_to_deadline=3.0, hours_overdue=0.0,
        cascade_depth=2, sla_penalty_per_hour=100.0, weights=BASE,
    )
    total = (
        breakdown.t_base + breakdown.t_time
        + breakdown.t_delay + breakdown.t_cascade
    )
    assert breakdown.temperature == pytest.approx(total, abs=0.01)


def test_customer_premium_raises_lambda_but_not_temperature() -> None:
    """SH.docx §4.4: expedite payment is an input, not an override."""
    plain = compute_temperature(
        base_priority=1.0, hours_to_deadline=5.0, hours_overdue=0.0,
        cascade_depth=0, sla_penalty_per_hour=100.0, weights=BASE,
    )
    premium = compute_temperature(
        base_priority=1.0, hours_to_deadline=5.0, hours_overdue=0.0,
        cascade_depth=0, sla_penalty_per_hour=100.0, weights=BASE,
        customer_premium=250.0,
    )

    assert premium.temperature == plain.temperature
    assert premium.lam == pytest.approx(plain.lam + 250.0)


# --- zones ---------------------------------------------------------------

@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.0, TemperatureZone.COLD),
        (33.9, TemperatureZone.COLD),
        (34.0, TemperatureZone.WARMING),
        (66.9, TemperatureZone.WARMING),
        (67.0, TemperatureZone.HOT),
        (100.0, TemperatureZone.HOT),
    ],
)
def test_zone_banding(value, expected) -> None:
    assert zone_for(value) == expected


# --- policy modes --------------------------------------------------------

def test_every_documented_mode_has_weights() -> None:
    for mode in PolicyModeName:
        assert mode.value in POLICY_WEIGHTS


def test_unknown_mode_falls_back_to_business() -> None:
    assert weights_for("NONSENSE") == POLICY_WEIGHTS[DEFAULT_MODE]


def test_policy_mode_changes_the_output() -> None:
    """The admin dial must visibly change recommendations."""
    scenario = {
        "base_priority": 1.0,
        "hours_to_deadline": 4.0,
        "hours_overdue": 0.0,
        "cascade_depth": 3,
        "sla_penalty_per_hour": 100.0,
    }
    results = {
        mode: compute_temperature(**scenario, weights=weights).temperature
        for mode, weights in POLICY_WEIGHTS.items()
    }
    assert len(set(results.values())) > 1


def test_sla_strict_reacts_harder_to_deadlines_than_fairness() -> None:
    scenario = {
        "base_priority": 1.0, "hours_to_deadline": 2.0, "hours_overdue": 0.0,
        "cascade_depth": 0, "sla_penalty_per_hour": 100.0,
    }
    strict = compute_temperature(
        **scenario, weights=POLICY_WEIGHTS[PolicyModeName.SLA_STRICT.value]
    ).t_time
    fair = compute_temperature(
        **scenario, weights=POLICY_WEIGHTS[PolicyModeName.FAIRNESS.value]
    ).t_time
    assert strict > fair


def test_efficiency_reacts_harder_to_cascade_than_sla_strict() -> None:
    scenario = {
        "base_priority": 1.0, "hours_to_deadline": 20.0, "hours_overdue": 0.0,
        "cascade_depth": 4, "sla_penalty_per_hour": 100.0,
    }
    efficiency = compute_temperature(
        **scenario, weights=POLICY_WEIGHTS[PolicyModeName.EFFICIENCY.value]
    ).t_cascade
    strict = compute_temperature(
        **scenario, weights=POLICY_WEIGHTS[PolicyModeName.SLA_STRICT.value]
    ).t_cascade
    assert efficiency > strict


# --- persistence ---------------------------------------------------------

def test_policy_row_is_created_on_first_use(db) -> None:
    policy = get_policy(db)
    assert policy.mode == DEFAULT_MODE
    # Singleton: a second call must not create another row.
    assert get_policy(db).id == policy.id


def test_set_policy_persists_the_mode(db) -> None:
    set_policy(db, PolicyModeName.EFFICIENCY.value)
    assert get_policy(db).mode == PolicyModeName.EFFICIENCY.value
    assert get_active_weights(db) == POLICY_WEIGHTS[PolicyModeName.EFFICIENCY.value]


def test_set_policy_rejects_an_unknown_mode(db) -> None:
    with pytest.raises(ValueError, match="Unknown policy mode"):
        set_policy(db, "TURBO")


def test_custom_weights_override_mode_defaults(db) -> None:
    set_policy(db, PolicyModeName.BUSINESS.value, weights={"w_time": 99.0})
    assert get_active_weights(db).w_time == pytest.approx(99.0)


def test_corrupt_weights_json_falls_back_to_defaults(db) -> None:
    policy = get_policy(db)
    policy.weights_json = "{not json"
    db.commit()
    assert get_active_weights(db) == POLICY_WEIGHTS[DEFAULT_MODE]


# --- engine against persisted shipments ----------------------------------

def test_engine_applies_temperature_to_a_shipment(db, shipment) -> None:
    engine = TemperatureEngine.from_db(db)
    breakdown = engine.apply(shipment)

    assert shipment.temperature == breakdown.temperature
    assert shipment.lam == breakdown.lam
    assert 0.0 <= shipment.temperature <= 100.0
    assert shipment.lam > 0


def test_engine_reflects_an_approaching_deadline(db, shipment) -> None:
    engine = TemperatureEngine.from_db(db)
    now = utcnow()

    shipment.deadline_at = now + timedelta(hours=20)
    cool = engine.evaluate(shipment, now).temperature

    shipment.deadline_at = now + timedelta(hours=1)
    hot = engine.evaluate(shipment, now).temperature

    assert hot > cool


def test_engine_picks_up_a_policy_change(db, shipment) -> None:
    from datetime import timedelta as td

    shipment.deadline_at = utcnow() + td(hours=2)
    shipment.cascade_depth = 4
    db.commit()

    set_policy(db, PolicyModeName.SLA_STRICT.value)
    strict = TemperatureEngine.from_db(db).evaluate(shipment).temperature

    set_policy(db, PolicyModeName.EFFICIENCY.value)
    efficiency = TemperatureEngine.from_db(db).evaluate(shipment).temperature

    assert strict != efficiency


def test_apply_many_commits_every_shipment(db, hubs) -> None:
    from app.models import Shipment
    from app.models.enums import ShipmentStatus

    created = [
        Shipment(
            code=f"T{i:03d}",
            origin_hub_id=hubs[0].id,
            dest_hub_id=hubs[1].id,
            weight_kg=10.0,
            status=ShipmentStatus.MISPLACED.value,
            deadline_at=utcnow() + timedelta(hours=i + 1),
            sla_penalty_per_hour=100.0,
        )
        for i in range(5)
    ]
    db.add_all(created)
    db.commit()

    results = TemperatureEngine.from_db(db).apply_many(db, created)

    assert len(results) == 5
    assert all(s.lam > 0 for s in created)
    # Tighter deadline must be hotter.
    assert created[0].temperature > created[4].temperature
