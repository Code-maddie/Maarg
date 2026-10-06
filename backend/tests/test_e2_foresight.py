"""Phase 10 validation: E2 Foresight Reservation (critical fractile)."""

import pytest

from app.engines.e2_foresight.reservation import (
    MIN_RISK_TO_CONSIDER,
    critical_fractile_threshold,
    evaluate_reservation,
    evaluate_shipment,
    premium_burn_ratio,
)


def decide(**overrides):
    kwargs = {
        "p_misplace": 0.5,
        "dedicated_cost": 10_000.0,
        "expected_bounty": 4_000.0,
        "premium": 1_000.0,
    }
    kwargs.update(overrides)
    return evaluate_reservation(**kwargs)


# --- the threshold formula (SH.docx §16) ---------------------------------

def test_threshold_matches_the_formula() -> None:
    # 1000 / (1000 + 10000 - 4000) = 1000/7000
    assert critical_fractile_threshold(
        premium=1000.0, dedicated_cost=10_000.0, expected_bounty=4_000.0
    ) == pytest.approx(1000 / 7000)


def test_a_free_option_is_always_worth_taking() -> None:
    assert critical_fractile_threshold(
        premium=0.0, dedicated_cost=10_000.0, expected_bounty=1_000.0
    ) == 0.0


def test_threshold_is_one_when_the_option_saves_nothing() -> None:
    """Bounty costs as much as dedicated recovery — never buy."""
    assert critical_fractile_threshold(
        premium=500.0, dedicated_cost=5_000.0, expected_bounty=5_000.0
    ) == 1.0


def test_threshold_is_one_when_the_bounty_costs_more() -> None:
    assert critical_fractile_threshold(
        premium=500.0, dedicated_cost=5_000.0, expected_bounty=9_000.0
    ) == 1.0


def test_threshold_rises_with_the_premium() -> None:
    cheap = critical_fractile_threshold(
        premium=100.0, dedicated_cost=10_000.0, expected_bounty=2_000.0
    )
    dear = critical_fractile_threshold(
        premium=5_000.0, dedicated_cost=10_000.0, expected_bounty=2_000.0
    )
    assert dear > cheap


def test_threshold_falls_as_the_saving_grows() -> None:
    small = critical_fractile_threshold(
        premium=1_000.0, dedicated_cost=3_000.0, expected_bounty=2_000.0
    )
    large = critical_fractile_threshold(
        premium=1_000.0, dedicated_cost=50_000.0, expected_bounty=2_000.0
    )
    assert large < small


def test_threshold_always_stays_in_range() -> None:
    for premium in (0.0, 1.0, 1e6):
        for dedicated in (0.0, 100.0, 1e6):
            for bounty in (0.0, 100.0, 1e6):
                value = critical_fractile_threshold(
                    premium=premium, dedicated_cost=dedicated,
                    expected_bounty=bounty,
                )
                assert 0.0 <= value <= 1.0


# --- the buy rule --------------------------------------------------------

def test_reservation_occurs_above_the_threshold() -> None:
    """Phase 10 criterion: reservation occurs when the condition is met."""
    result = decide(p_misplace=0.9)

    assert result.should_reserve is True
    assert result.p_misplace >= result.threshold
    assert ">= threshold" in result.reason


def test_reservation_is_rejected_below_the_threshold() -> None:
    """Phase 10 criterion: reservation rejected otherwise."""
    # threshold is 1000/7000 = 0.143
    result = decide(p_misplace=0.10)

    assert result.should_reserve is False
    assert "< threshold" in result.reason


def test_the_boundary_case_buys() -> None:
    threshold = critical_fractile_threshold(
        premium=1_000.0, dedicated_cost=10_000.0, expected_bounty=4_000.0
    )
    assert decide(p_misplace=threshold).should_reserve is True


def test_an_unscored_shipment_never_reserves() -> None:
    result = decide(p_misplace=None)
    assert result.should_reserve is False
    assert "not been scored" in result.reason


def test_a_negligible_risk_never_reserves() -> None:
    result = decide(p_misplace=MIN_RISK_TO_CONSIDER / 2, premium=0.0)
    assert result.should_reserve is False
    assert "below the" in result.reason


def test_no_saving_means_no_reservation() -> None:
    result = decide(p_misplace=0.99, dedicated_cost=5_000.0, expected_bounty=5_000.0)
    assert result.should_reserve is False
    assert "saves nothing" in result.reason


def test_probability_is_clamped() -> None:
    assert decide(p_misplace=5.0).p_misplace == 1.0
    assert decide(p_misplace=-3.0).p_misplace == 0.0


def test_premium_defaults_to_a_rate_of_the_dedicated_cost() -> None:
    result = evaluate_reservation(
        p_misplace=0.5, dedicated_cost=10_000.0, expected_bounty=2_000.0,
        premium_rate=0.10,
    )
    assert result.premium == 1_000.0


def test_reason_is_always_concrete() -> None:
    """E8 renders these verbatim."""
    for probability in (None, 0.0, 0.01, 0.2, 0.5, 0.99):
        reason = decide(p_misplace=probability).reason
        assert reason and "TODO" not in reason


def test_higher_risk_makes_reservation_more_likely() -> None:
    low = decide(p_misplace=0.05)
    high = decide(p_misplace=0.95)
    assert low.should_reserve is False
    assert high.should_reserve is True


def test_a_more_expensive_premium_makes_reservation_less_likely() -> None:
    cheap = decide(p_misplace=0.30, premium=100.0)
    dear = decide(p_misplace=0.30, premium=9_000.0)

    assert cheap.should_reserve is True
    assert dear.should_reserve is False


# --- persisted shipments -------------------------------------------------

def test_evaluate_reads_the_shipment_risk(db, shipment) -> None:
    shipment.p_misplace = 0.8
    db.commit()

    result = evaluate_shipment(
        shipment, dedicated_cost=20_000.0, expected_bounty=5_000.0
    )
    assert result.shipment_id == shipment.id
    assert result.p_misplace == 0.8
    assert result.should_reserve is True


def test_an_unscored_persisted_shipment_is_safe(db, shipment) -> None:
    shipment.p_misplace = None
    db.commit()

    result = evaluate_shipment(
        shipment, dedicated_cost=20_000.0, expected_bounty=5_000.0
    )
    assert result.should_reserve is False


# --- premium burn ratio (SH.docx §5.1) -----------------------------------

def test_premium_burn_ratio_below_one_means_the_options_paid_off() -> None:
    assert premium_burn_ratio(2_000.0, 10_000.0) == 0.2


def test_premium_burn_ratio_with_no_avoided_cost() -> None:
    assert premium_burn_ratio(500.0, 0.0) == float("inf")
    assert premium_burn_ratio(0.0, 0.0) == 0.0
