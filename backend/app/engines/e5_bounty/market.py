"""E5 — Bounty Market.

A reverse auction: vehicles already heading the right way bid to carry a
misplaced shipment, and the cheapest wins. Pricing follows SH.docx §16:

    MaxBounty = min(lambda(s) * delta_t_saved,  C_dedicated - C_overhead)
    Payment   = min(second_lowest_bid, MaxBounty)          [Vickrey]

Vickrey (second-price) pricing means a bidder's best strategy is to bid their
true cost, because what they are paid does not depend on their own bid. That
is the defensible answer to "why won't carriers game this?".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.geo import haversine_km
from app.core.logging import get_logger
from app.models import Auction, Bid, Hub, Leg, Shipment, Vehicle
from app.models.enums import AuctionStatus, LegStatus, VehicleType

logger = get_logger(__name__)

# How long an auction stays open in simulated time.
DEFAULT_WINDOW_MINUTES = 15

# Overhead the operator keeps when using a dedicated vehicle; MaxBounty can
# never exceed what dedicated recovery would have cost minus this.
DEDICATED_OVERHEAD_FRACTION = 0.15

# A vehicle further than this from the pickup is not eligible.
ELIGIBILITY_RADIUS_KM = 400.0

# Road distance exceeds great-circle; same factor the rest of the engine uses.
ROAD_FACTOR = 1.35

# Loading, securing, scanning and unloading. This is what a carrier charges
# even when the detour is zero, and it is why no bid is ever free.
HANDLING_FEE = 250.0

# No carrier works for nothing. Without a floor, a vehicle sitting exactly at
# the pickup hub bids 0 and wins a zero-rupee bounty — which is both
# economically wrong and a broken demo beat.
MIN_BID = 100.0


@dataclass
class EligibleVehicle:
    """A vehicle that could plausibly take the job, with its detour cost."""

    vehicle_id: int
    code: str
    vehicle_type: str
    reliability: float
    detour_km: float
    haul_km: float
    true_cost: float

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AuctionOutcome:
    """The result of closing an auction."""

    auction_id: int
    status: str
    max_bounty: float
    winning_vehicle_id: Optional[int] = None
    payment: Optional[float] = None
    bid_count: int = 0
    lowest_bid: Optional[float] = None
    second_lowest_bid: Optional[float] = None
    reason: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compute_max_bounty(
    *, lam: float, hours_saved: float, dedicated_cost: float
) -> float:
    """MaxBounty = min(lambda * delta_t_saved, C_dedicated - C_overhead).

    The first term is what the time saving is worth; the second is the cap
    that keeps a bounty from ever costing more than simply dispatching a
    dedicated vehicle. Never negative.
    """
    value_of_time = max(0.0, lam) * max(0.0, hours_saved)
    dedicated_ceiling = max(0.0, dedicated_cost) * (1.0 - DEDICATED_OVERHEAD_FRACTION)
    return round(max(0.0, min(value_of_time, dedicated_ceiling)), 2)


def compute_payment(bids: Sequence[float], max_bounty: float) -> Optional[float]:
    """Payment = min(second_lowest_bid, MaxBounty).

    With a single bidder there is no second price, so the bidder is paid
    MaxBounty — the most the operator was willing to pay anyway, which keeps
    the mechanism truthful rather than letting a monopolist name any number.
    """
    if not bids:
        return None

    ordered = sorted(bids)
    if len(ordered) == 1:
        # Standard reverse-Vickrey with a reserve: the sole bidder is paid
        # the reserve price, not their own ask. Paying their ask would make
        # under-bidding costly and destroy truthfulness.
        return round(max(0.0, max_bounty), 2)

    return round(min(ordered[1], max_bounty), 2)


def find_eligible_vehicles(
    db: Session,
    *,
    pickup_hub: Hub,
    now: datetime,
    weight_kg: float,
    volume_m3: float,
    dropoff_hub: Optional[Hub] = None,
    radius_km: float = ELIGIBILITY_RADIUS_KM,
    limit: int = 20,
) -> List[EligibleVehicle]:
    """Vehicles near the pickup with capacity to spare.

    "Already heading that way" is the whole point: eligibility is geographic
    proximity plus residual capacity, not a general fleet query.

    A bidder's true cost is their **marginal** cost: the detour to reach the
    pickup, plus a handling fee. The haul itself is deliberately excluded —
    the whole premise of piggybacking is that the vehicle is already making
    that journey, so charging for it would double-count work the carrier is
    doing anyway, and would push every bid above MaxBounty on long routes
    (making the market award nothing at all).

    ``haul_km`` is still reported, for transparency in the Explainer, but it
    does not enter the price.
    """
    eligible: List[EligibleVehicle] = []

    vehicles = db.scalars(select(Vehicle)).all()
    hubs = {hub.id: hub for hub in db.scalars(select(Hub)).all()}

    haul_km = 0.0
    if dropoff_hub is not None:
        haul_km = haversine_km(
            pickup_hub.lat, pickup_hub.lng, dropoff_hub.lat, dropoff_hub.lng
        ) * ROAD_FACTOR

    for vehicle in vehicles:
        position = None
        if vehicle.current_lat is not None and vehicle.current_lng is not None:
            position = (vehicle.current_lat, vehicle.current_lng)
        elif vehicle.current_hub_id in hubs:
            hub = hubs[vehicle.current_hub_id]
            position = (hub.lat, hub.lng)

        if position is None:
            continue

        detour = haversine_km(position[0], position[1], pickup_hub.lat, pickup_hub.lng)
        if detour > radius_km:
            continue

        if vehicle.capacity_kg < weight_kg or vehicle.capacity_m3 < volume_m3:
            continue

        # Marginal cost: the detour plus handling. Floored so no carrier
        # ever bids zero.
        true_cost = max(
            MIN_BID, round(detour * vehicle.cost_per_km + HANDLING_FEE, 2)
        )

        eligible.append(
            EligibleVehicle(
                vehicle_id=vehicle.id,
                code=vehicle.code,
                vehicle_type=vehicle.vehicle_type,
                reliability=vehicle.reliability,
                detour_km=round(detour, 2),
                haul_km=round(haul_km, 2),
                true_cost=true_cost,
            )
        )

    eligible.sort(key=lambda item: item.true_cost)
    return eligible[:limit]


def open_auction(
    db: Session,
    shipment: Shipment,
    *,
    now: datetime,
    max_bounty: float,
    plan_id: Optional[int] = None,
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
) -> Auction:
    """Opens a reverse auction for one shipment."""
    auction = Auction(
        shipment_id=shipment.id,
        plan_id=plan_id,
        status=AuctionStatus.OPEN.value,
        max_bounty=max_bounty,
        opened_at=now,
        closes_at=now + timedelta(minutes=window_minutes),
    )
    db.add(auction)
    db.commit()

    logger.info(
        "E5 auction %d opened for %s, MaxBounty=%.2f, closes %s",
        auction.id, shipment.code, max_bounty,
        auction.closes_at.isoformat(timespec="minutes"),
    )
    return auction


def place_bid(
    db: Session,
    auction: Auction,
    *,
    vehicle_id: int,
    amount: float,
    detour_km: float = 0.0,
    now: Optional[datetime] = None,
) -> Bid:
    """Records a bid. Raises when the auction is not open to it."""
    if auction.status != AuctionStatus.OPEN.value:
        raise ValueError(f"Auction {auction.id} is {auction.status}, not OPEN")

    if now is not None and now > auction.closes_at:
        raise ValueError(f"Auction {auction.id} closed at {auction.closes_at}")

    if amount < 0:
        raise ValueError("Bid amount must not be negative")

    existing = db.scalar(
        select(Bid).where(
            Bid.auction_id == auction.id, Bid.vehicle_id == vehicle_id
        )
    )
    if existing is not None:
        raise ValueError(f"Vehicle {vehicle_id} has already bid on auction {auction.id}")

    bid = Bid(
        auction_id=auction.id,
        vehicle_id=vehicle_id,
        amount=round(amount, 2),
        detour_km=round(detour_km, 2),
    )
    db.add(bid)
    db.commit()
    return bid


def simulate_bids(
    db: Session,
    auction: Auction,
    eligible: Sequence[EligibleVehicle],
    *,
    rng,
    participation_rate: float = 0.6,
) -> List[Bid]:
    """Generates bids from eligible vehicles (prototype stand-in for drivers).

    Bidders ask their true cost plus a small margin. Third-party carriers ask
    for more, which is what makes owned capacity preferable at equal distance.
    """
    placed: List[Bid] = []

    for vehicle in eligible:
        if rng.random() > participation_rate:
            continue

        margin = (
            rng.uniform(1.10, 1.45)
            if vehicle.vehicle_type == VehicleType.THIRD_PARTY.value
            else rng.uniform(1.02, 1.20)
        )
        amount = vehicle.true_cost * margin

        # Nobody bids above the posted maximum; it would never be accepted.
        if amount > auction.max_bounty:
            continue

        placed.append(
            place_bid(
                db,
                auction,
                vehicle_id=vehicle.vehicle_id,
                amount=amount,
                detour_km=vehicle.detour_km,
            )
        )

    return placed


def close_auction(
    db: Session, auction: Auction, *, now: Optional[datetime] = None
) -> AuctionOutcome:
    """Closes an auction and settles it under Vickrey rules."""
    bids = db.scalars(select(Bid).where(Bid.auction_id == auction.id)).all()

    if not bids:
        auction.status = AuctionStatus.NO_BIDS.value
        db.commit()
        logger.info("E5 auction %d closed with no bids", auction.id)
        return AuctionOutcome(
            auction_id=auction.id,
            status=auction.status,
            max_bounty=auction.max_bounty,
            reason="No eligible vehicle bid within the window",
        )

    ordered = sorted(bids, key=lambda bid: bid.amount)
    winner = ordered[0]
    amounts = [bid.amount for bid in ordered]

    payment = compute_payment(amounts, auction.max_bounty)

    for bid in bids:
        bid.is_winner = bid.id == winner.id

    auction.status = AuctionStatus.AWARDED.value
    auction.winning_vehicle_id = winner.vehicle_id
    auction.payment = payment
    db.commit()

    logger.info(
        "E5 auction %d awarded to vehicle %d: bid %.2f, paid %.2f (%d bids)",
        auction.id, winner.vehicle_id, winner.amount, payment, len(bids),
    )

    return AuctionOutcome(
        auction_id=auction.id,
        status=auction.status,
        max_bounty=auction.max_bounty,
        winning_vehicle_id=winner.vehicle_id,
        payment=payment,
        bid_count=len(bids),
        lowest_bid=amounts[0],
        second_lowest_bid=amounts[1] if len(amounts) > 1 else None,
        reason="Lowest bidder wins, paid the second-lowest bid capped at MaxBounty",
    )


def run_auction(
    db: Session,
    shipment: Shipment,
    *,
    now: datetime,
    lam: float,
    hours_saved: float,
    dedicated_cost: float,
    rng,
    pickup_hub: Optional[Hub] = None,
    plan_id: Optional[int] = None,
) -> AuctionOutcome:
    """Opens, bids and settles an auction in one call (demo convenience)."""
    hub = pickup_hub or db.get(
        Hub, shipment.current_hub_id or shipment.origin_hub_id
    )
    if hub is None:
        raise ValueError(f"Shipment {shipment.code} has no pickup hub")

    max_bounty = compute_max_bounty(
        lam=lam, hours_saved=hours_saved, dedicated_cost=dedicated_cost
    )
    auction = open_auction(
        db, shipment, now=now, max_bounty=max_bounty, plan_id=plan_id
    )

    eligible = find_eligible_vehicles(
        db,
        pickup_hub=hub,
        dropoff_hub=db.get(Hub, shipment.dest_hub_id),
        now=now,
        weight_kg=shipment.weight_kg,
        volume_m3=shipment.volume_m3,
    )
    simulate_bids(db, auction, eligible, rng=rng)

    return close_auction(db, auction, now=now)
