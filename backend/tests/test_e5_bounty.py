"""Phase 9 validation: E5 Bounty Market (Vickrey reverse auction)."""

import random
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.engines.e5_bounty.market import (
    DEDICATED_OVERHEAD_FRACTION,
    close_auction,
    compute_max_bounty,
    compute_payment,
    find_eligible_vehicles,
    open_auction,
    place_bid,
    run_auction,
    simulate_bids,
)
from app.models import Auction, Bid, Hub, Shipment
from app.models.enums import AuctionStatus

T0 = datetime(2026, 5, 1, 6, 0)


# --- MaxBounty (SH.docx §16) ---------------------------------------------

def test_max_bounty_takes_the_value_of_time_when_it_is_lower() -> None:
    # lambda*hours = 100*2 = 200; ceiling = 10000*0.85 = 8500
    assert compute_max_bounty(lam=100.0, hours_saved=2.0, dedicated_cost=10000.0) == 200.0


def test_max_bounty_is_capped_by_the_dedicated_cost() -> None:
    """A bounty must never cost more than simply dispatching a truck."""
    result = compute_max_bounty(lam=10000.0, hours_saved=50.0, dedicated_cost=1000.0)
    assert result == pytest.approx(1000.0 * (1 - DEDICATED_OVERHEAD_FRACTION))


def test_max_bounty_is_never_negative() -> None:
    assert compute_max_bounty(lam=-5.0, hours_saved=-5.0, dedicated_cost=-5.0) == 0.0


def test_max_bounty_is_zero_when_no_time_is_saved() -> None:
    assert compute_max_bounty(lam=500.0, hours_saved=0.0, dedicated_cost=9999.0) == 0.0


def test_max_bounty_rises_with_lambda() -> None:
    low = compute_max_bounty(lam=100.0, hours_saved=3.0, dedicated_cost=99999.0)
    high = compute_max_bounty(lam=400.0, hours_saved=3.0, dedicated_cost=99999.0)
    assert high > low


# --- Vickrey payment ------------------------------------------------------

def test_payment_is_the_second_lowest_bid() -> None:
    """The defining Vickrey property."""
    assert compute_payment([300.0, 500.0, 700.0], max_bounty=1000.0) == 500.0


def test_payment_is_capped_at_max_bounty() -> None:
    assert compute_payment([300.0, 900.0], max_bounty=600.0) == 600.0


def test_a_sole_bidder_is_paid_the_reserve() -> None:
    assert compute_payment([250.0], max_bounty=800.0) == 800.0


def test_no_bids_means_no_payment() -> None:
    assert compute_payment([], max_bounty=800.0) is None


def test_payment_ignores_bid_ordering() -> None:
    assert compute_payment([700.0, 300.0, 500.0], max_bounty=1000.0) == 500.0


def test_winner_payment_does_not_depend_on_their_own_bid() -> None:
    """Why truthful bidding is optimal — the incentive-compatibility claim."""
    honest = compute_payment([300.0, 500.0], max_bounty=1000.0)
    undercut = compute_payment([10.0, 500.0], max_bounty=1000.0)
    assert honest == undercut == 500.0


# --- eligibility ---------------------------------------------------------

@pytest.fixture()
def world(db):
    from app.workers.world import WorldSpec, build_world

    build_world(
        db,
        WorldSpec(seed=42, hub_count=10, vehicle_count=40,
                  shipment_count=30, leg_count=60),
    )
    return db


def test_eligible_vehicles_are_found_near_the_pickup(world) -> None:
    hub = world.scalars(select(Hub).limit(1)).first()
    eligible = find_eligible_vehicles(
        world, pickup_hub=hub, now=T0, weight_kg=10.0, volume_m3=0.5
    )
    assert eligible
    assert all(vehicle.detour_km <= 400.0 for vehicle in eligible)


def test_eligible_vehicles_are_ordered_by_true_cost(world) -> None:
    hub = world.scalars(select(Hub).limit(1)).first()
    eligible = find_eligible_vehicles(
        world, pickup_hub=hub, now=T0, weight_kg=10.0, volume_m3=0.5
    )
    costs = [vehicle.true_cost for vehicle in eligible]
    assert costs == sorted(costs)


def test_a_radius_of_zero_finds_almost_nothing(world) -> None:
    hub = world.scalars(select(Hub).limit(1)).first()
    eligible = find_eligible_vehicles(
        world, pickup_hub=hub, now=T0, weight_kg=10.0, volume_m3=0.5,
        radius_km=0.001,
    )
    # Only vehicles sitting exactly at the hub qualify.
    assert all(vehicle.detour_km < 0.01 for vehicle in eligible)


def test_an_oversized_shipment_finds_no_carrier(world) -> None:
    hub = world.scalars(select(Hub).limit(1)).first()
    assert find_eligible_vehicles(
        world, pickup_hub=hub, now=T0, weight_kg=999_999.0, volume_m3=0.5
    ) == []


# --- auction lifecycle ---------------------------------------------------

@pytest.fixture()
def shipment_in(world) -> Shipment:
    return world.scalars(select(Shipment).limit(1)).first()


def test_auction_opens_in_the_open_state(world, shipment_in) -> None:
    """Phase 9 criterion: the auction opens."""
    auction = open_auction(world, shipment_in, now=T0, max_bounty=900.0)

    assert auction.status == AuctionStatus.OPEN.value
    assert auction.max_bounty == 900.0
    assert auction.closes_at > auction.opened_at


def test_bids_are_recorded(world, shipment_in) -> None:
    """Phase 9 criterion: bids arrive."""
    auction = open_auction(world, shipment_in, now=T0, max_bounty=900.0)
    place_bid(world, auction, vehicle_id=1, amount=400.0)
    place_bid(world, auction, vehicle_id=2, amount=550.0)

    bids = world.scalars(select(Bid).where(Bid.auction_id == auction.id)).all()
    assert len(bids) == 2


def test_a_vehicle_cannot_bid_twice(world, shipment_in) -> None:
    auction = open_auction(world, shipment_in, now=T0, max_bounty=900.0)
    place_bid(world, auction, vehicle_id=1, amount=400.0)

    with pytest.raises(ValueError, match="already bid"):
        place_bid(world, auction, vehicle_id=1, amount=300.0)


def test_a_negative_bid_is_refused(world, shipment_in) -> None:
    auction = open_auction(world, shipment_in, now=T0, max_bounty=900.0)
    with pytest.raises(ValueError, match="negative"):
        place_bid(world, auction, vehicle_id=1, amount=-50.0)


def test_bidding_after_the_window_is_refused(world, shipment_in) -> None:
    auction = open_auction(world, shipment_in, now=T0, max_bounty=900.0)
    with pytest.raises(ValueError, match="closed"):
        place_bid(
            world, auction, vehicle_id=1, amount=400.0,
            now=T0 + timedelta(hours=5),
        )


def test_bidding_on_a_closed_auction_is_refused(world, shipment_in) -> None:
    auction = open_auction(world, shipment_in, now=T0, max_bounty=900.0)
    close_auction(world, auction)

    with pytest.raises(ValueError, match="not OPEN"):
        place_bid(world, auction, vehicle_id=1, amount=400.0)


# --- settlement ----------------------------------------------------------

def test_lowest_bidder_wins_and_is_paid_second_price(world, shipment_in) -> None:
    """Phase 9 criteria: winner selected, bounty calculation correct."""
    auction = open_auction(world, shipment_in, now=T0, max_bounty=1000.0)
    place_bid(world, auction, vehicle_id=1, amount=300.0)
    place_bid(world, auction, vehicle_id=2, amount=500.0)
    place_bid(world, auction, vehicle_id=3, amount=700.0)

    outcome = close_auction(world, auction)

    assert outcome.status == AuctionStatus.AWARDED.value
    assert outcome.winning_vehicle_id == 1
    assert outcome.lowest_bid == 300.0
    assert outcome.second_lowest_bid == 500.0
    assert outcome.payment == 500.0


def test_the_winning_bid_row_is_flagged(world, shipment_in) -> None:
    auction = open_auction(world, shipment_in, now=T0, max_bounty=1000.0)
    place_bid(world, auction, vehicle_id=1, amount=300.0)
    place_bid(world, auction, vehicle_id=2, amount=500.0)

    close_auction(world, auction)

    winners = world.scalars(
        select(Bid).where(Bid.auction_id == auction.id, Bid.is_winner.is_(True))
    ).all()
    assert len(winners) == 1
    assert winners[0].vehicle_id == 1


def test_payment_is_capped_by_max_bounty_on_settlement(world, shipment_in) -> None:
    auction = open_auction(world, shipment_in, now=T0, max_bounty=400.0)
    place_bid(world, auction, vehicle_id=1, amount=300.0)
    place_bid(world, auction, vehicle_id=2, amount=900.0)

    assert close_auction(world, auction).payment == 400.0


def test_an_auction_with_no_bids_closes_cleanly(world, shipment_in) -> None:
    auction = open_auction(world, shipment_in, now=T0, max_bounty=900.0)
    outcome = close_auction(world, auction)

    assert outcome.status == AuctionStatus.NO_BIDS.value
    assert outcome.payment is None
    assert outcome.winning_vehicle_id is None
    assert "No eligible vehicle" in outcome.reason


def test_a_sole_bidder_wins_at_the_reserve(world, shipment_in) -> None:
    auction = open_auction(world, shipment_in, now=T0, max_bounty=750.0)
    place_bid(world, auction, vehicle_id=1, amount=200.0)

    outcome = close_auction(world, auction)
    assert outcome.winning_vehicle_id == 1
    assert outcome.payment == 750.0


# --- simulated bidding ---------------------------------------------------

def test_simulated_bids_stay_under_max_bounty(world, shipment_in) -> None:
    hub = world.get(Hub, shipment_in.origin_hub_id)
    auction = open_auction(world, shipment_in, now=T0, max_bounty=100_000.0)
    eligible = find_eligible_vehicles(
        world, pickup_hub=hub, now=T0,
        weight_kg=shipment_in.weight_kg, volume_m3=shipment_in.volume_m3,
    )

    bids = simulate_bids(world, auction, eligible, rng=random.Random(42))
    assert all(bid.amount <= auction.max_bounty for bid in bids)


def test_simulated_bidding_is_deterministic(world, shipment_in) -> None:
    hub = world.get(Hub, shipment_in.origin_hub_id)
    eligible = find_eligible_vehicles(
        world, pickup_hub=hub, now=T0, weight_kg=1.0, volume_m3=0.1
    )

    a = open_auction(world, shipment_in, now=T0, max_bounty=100_000.0)
    first = [b.amount for b in simulate_bids(world, a, eligible, rng=random.Random(7))]

    other = world.scalars(select(Shipment).offset(1).limit(1)).first()
    b = open_auction(world, other, now=T0, max_bounty=100_000.0)
    second = [x.amount for x in simulate_bids(world, b, eligible, rng=random.Random(7))]

    assert first == second


def test_full_auction_run(world, shipment_in) -> None:
    outcome = run_auction(
        world, shipment_in,
        now=T0, lam=500.0, hours_saved=6.0, dedicated_cost=50_000.0,
        rng=random.Random(42),
    )

    assert outcome.max_bounty == 3000.0   # 500 * 6, under the ceiling
    assert outcome.status in {
        AuctionStatus.AWARDED.value, AuctionStatus.NO_BIDS.value
    }
    if outcome.status == AuctionStatus.AWARDED.value:
        assert outcome.payment <= outcome.max_bounty


def test_auction_row_is_persisted(world, shipment_in) -> None:
    run_auction(
        world, shipment_in, now=T0, lam=300.0, hours_saved=4.0,
        dedicated_cost=40_000.0, rng=random.Random(1),
    )
    assert world.scalars(select(Auction)).all()


# --- regression: zero-rupee bounties -------------------------------------

def test_a_vehicle_at_the_pickup_hub_still_costs_something(world) -> None:
    """Regression for a defect found during Phase 16 manual testing.

    Vehicles parked at the pickup hub had detour_km=0, so true_cost=0 and
    they bid 0. The auction then awarded a zero-rupee bounty — economically
    nonsensical and a broken demo beat. Carrying the shipment is the work
    being paid for, so the haul distance must count.
    """
    hubs = world.scalars(select(Hub).limit(2)).all()
    pickup, dropoff = hubs[0], hubs[1]

    eligible = find_eligible_vehicles(
        world, pickup_hub=pickup, dropoff_hub=dropoff, now=T0,
        weight_kg=10.0, volume_m3=0.5,
    )

    at_hub = [v for v in eligible if v.detour_km < 0.01]
    assert at_hub, "expected at least one vehicle parked at the pickup hub"
    for vehicle in at_hub:
        assert vehicle.true_cost > 0
        assert vehicle.haul_km > 0


def test_no_true_cost_is_ever_zero(world) -> None:
    hubs = world.scalars(select(Hub).limit(2)).all()
    eligible = find_eligible_vehicles(
        world, pickup_hub=hubs[0], dropoff_hub=hubs[1], now=T0,
        weight_kg=10.0, volume_m3=0.5,
    )
    assert all(v.true_cost >= 100.0 for v in eligible)


def test_the_haul_does_not_enter_the_price(world) -> None:
    """Piggybacking means the vehicle is already making that journey.

    Charging for the haul would double-count work the carrier is doing
    anyway, and would push every bid above MaxBounty on long routes so the
    market awarded nothing at all.
    """
    hubs = world.scalars(select(Hub).limit(3)).all()

    near = find_eligible_vehicles(
        world, pickup_hub=hubs[0], dropoff_hub=hubs[0], now=T0,
        weight_kg=10.0, volume_m3=0.5,
    )
    far = find_eligible_vehicles(
        world, pickup_hub=hubs[0], dropoff_hub=hubs[2], now=T0,
        weight_kg=10.0, volume_m3=0.5,
    )

    assert [v.true_cost for v in near] == [v.true_cost for v in far]


def test_a_bigger_detour_costs_more(world) -> None:
    """Price tracks the marginal effort, which is the detour."""
    hub = world.scalars(select(Hub).limit(1)).first()
    eligible = find_eligible_vehicles(
        world, pickup_hub=hub, dropoff_hub=hub, now=T0,
        weight_kg=10.0, volume_m3=0.5,
    )
    far = max(eligible, key=lambda v: v.detour_km)
    near = min(eligible, key=lambda v: v.detour_km)
    assert far.true_cost > near.true_cost


def test_a_full_auction_pays_a_real_bounty(world, shipment_in) -> None:
    outcome = run_auction(
        world, shipment_in,
        now=T0, lam=800.0, hours_saved=12.0, dedicated_cost=200_000.0,
        rng=random.Random(42),
    )

    if outcome.status == AuctionStatus.AWARDED.value:
        assert outcome.payment > 0, "auction awarded a zero-rupee bounty"
