"""Turns persisted rows into the API's response shapes.

Kept out of the route modules so the mapping is testable on its own and so
routes stay thin.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines.e4_temperature.engine import zone_for
from app.engines.e4_temperature.pressure import EMERGENCY_THRESHOLD
from app.models import (
    Auction,
    Bid,
    Hub,
    Leg,
    RecoveryPlan,
    Shipment,
    ShipmentLeg,
    Vehicle,
)
from app.models.enums import AuctionStatus
from app.schemas.api import (
    AboardShipment,
    AuctionOut,
    BidOut,
    BountyStatus,
    LegDetail,
    PathStep,
    RecoveryPlanOut,
    ShipmentDetail,
    ShipmentSummary,
    VehicleOut,
)


def hub_code_map(db: Session) -> Dict[int, str]:
    return {hub.id: hub.code for hub in db.scalars(select(Hub)).all()}


def hub_name_map(db: Session) -> Dict[int, str]:
    return {hub.id: hub.name for hub in db.scalars(select(Hub)).all()}


def shipment_summary(
    shipment: Shipment, codes: Dict[int, str]
) -> ShipmentSummary:
    return ShipmentSummary(
        id=shipment.id,
        code=shipment.code,
        status=shipment.status,
        origin_hub=codes.get(shipment.origin_hub_id),
        dest_hub=codes.get(shipment.dest_hub_id),
        current_hub=codes.get(shipment.current_hub_id),
        weight_kg=shipment.weight_kg,
        volume_m3=shipment.volume_m3,
        deadline_at=shipment.deadline_at,
        temperature=shipment.temperature,
        zone=str(zone_for(shipment.temperature)),
        lam=shipment.lam,
        pressure=shipment.pressure,
        emergency=shipment.pressure >= EMERGENCY_THRESHOLD,
        p_misplace=shipment.p_misplace,
        cascade_depth=shipment.cascade_depth,
    )


def shipment_detail(
    shipment: Shipment, codes: Dict[int, str], now
) -> ShipmentDetail:
    base = shipment_summary(shipment, codes)
    return ShipmentDetail(
        **base.model_dump(),
        misplaced_at=shipment.misplaced_at,
        delivered_at=shipment.delivered_at,
        sla_penalty_per_hour=shipment.sla_penalty_per_hour,
        base_priority=shipment.base_priority,
        customer_premium=shipment.customer_premium,
        hours_to_deadline=round(shipment.hours_to_deadline(now), 3),
    )


def plan_out(plan: RecoveryPlan, codes: Dict[int, str]) -> RecoveryPlanOut:
    return RecoveryPlanOut(
        id=plan.id,
        shipment_id=plan.shipment_id,
        strategy=plan.strategy,
        status=plan.status,
        rank=plan.rank,
        score=plan.score,
        total_cost=plan.total_cost,
        bounty_cost=plan.bounty_cost,
        eta=plan.eta,
        transit_hours=plan.transit_hours,
        compute_ms=plan.compute_ms,
        warm_started=plan.warm_started,
        rejection_reason=plan.rejection_reason,
        path=[
            PathStep(
                seq=step.seq,
                leg_id=step.leg_id,
                from_hub=codes.get(step.from_hub_id, str(step.from_hub_id)),
                to_hub=codes.get(step.to_hub_id, str(step.to_hub_id)),
                departure_at=step.departure_at,
                arrival_at=step.arrival_at,
                edge_cost=step.edge_cost,
            )
            for step in plan.paths
        ],
    )


def vehicle_out(vehicle: Vehicle, codes: Dict[int, str]) -> VehicleOut:
    return VehicleOut(
        id=vehicle.id,
        code=vehicle.code,
        vehicle_type=vehicle.vehicle_type,
        status=vehicle.status,
        capacity_kg=vehicle.capacity_kg,
        capacity_m3=vehicle.capacity_m3,
        reliability=vehicle.reliability,
        cost_per_km=vehicle.cost_per_km,
        current_hub=codes.get(vehicle.current_hub_id),
        current_lat=vehicle.current_lat,
        current_lng=vehicle.current_lng,
    )


def bounty_status_for_leg(
    db: Session, leg: Leg, now=None
) -> Optional[BountyStatus]:
    """Live auction state for a leg, if one is running.

    A leg is linked to an auction through the shipments aboard it.
    """
    shipment_ids = [
        link.shipment_id
        for link in db.scalars(
            select(ShipmentLeg).where(ShipmentLeg.leg_id == leg.id)
        ).all()
    ]
    if not shipment_ids:
        return None

    auction = db.scalars(
        select(Auction)
        .where(Auction.shipment_id.in_(shipment_ids))
        .order_by(Auction.id.desc())
        .limit(1)
    ).first()

    if auction is None:
        return None

    bids = db.scalars(select(Bid).where(Bid.auction_id == auction.id)).all()
    best = min((bid.amount for bid in bids), default=None)

    remaining = None
    if now is not None and auction.status == AuctionStatus.OPEN.value:
        remaining = max(0.0, (auction.closes_at - now).total_seconds())

    return BountyStatus(
        auction_id=auction.id,
        status=auction.status,
        max_bounty=auction.max_bounty,
        best_bid=best,
        bid_count=len(bids),
        closes_at=auction.closes_at,
        seconds_remaining=remaining,
    )


def _leg_geometry(leg: Leg, source, destination):
    """(path, encoded polyline) — stored polyline if present, else computed."""
    from app.services.geometry import decode_polyline, encode_polyline, leg_curve

    if leg.polyline:
        points = decode_polyline(leg.polyline)
        encoded = leg.polyline
    elif source is not None and destination is not None:
        points = leg_curve((source.lat, source.lng), (destination.lat, destination.lng))
        encoded = encode_polyline(points)
    else:
        return [], None
    return [[round(a, 5), round(b, 5)] for a, b in points], encoded


def leg_detail(db: Session, leg: Leg, now=None) -> LegDetail:
    """The click-a-route info panel payload (SH.docx §6.2)."""
    vehicle = db.get(Vehicle, leg.vehicle_id)
    source = db.get(Hub, leg.from_hub_id)
    destination = db.get(Hub, leg.to_hub_id)

    aboard: List[AboardShipment] = []
    for link in db.scalars(
        select(ShipmentLeg).where(ShipmentLeg.leg_id == leg.id)
    ).all():
        shipment = db.get(Shipment, link.shipment_id)
        if shipment is None:
            continue
        aboard.append(
            AboardShipment(
                code=shipment.code,
                weight_kg=shipment.weight_kg,
                temperature=shipment.temperature,
                zone=str(zone_for(shipment.temperature)),
                lam=shipment.lam,
            )
        )

    path, encoded = _leg_geometry(leg, source, destination)

    return LegDetail(
        id=leg.id,
        vehicle_code=vehicle.code if vehicle else "unknown",
        vehicle_type=vehicle.vehicle_type if vehicle else "unknown",
        reliability=vehicle.reliability if vehicle else 0.0,
        from_hub=source.code if source else str(leg.from_hub_id),
        to_hub=destination.code if destination else str(leg.to_hub_id),
        from_lat=source.lat if source else 0.0,
        from_lng=source.lng if source else 0.0,
        to_lat=destination.lat if destination else 0.0,
        to_lng=destination.lng if destination else 0.0,
        departure_at=leg.departure_at,
        arrival_at=leg.arrival_at,
        capacity_kg=leg.capacity_kg,
        residual_kg=leg.residual_kg,
        capacity_m3=leg.capacity_m3,
        residual_m3=leg.residual_m3,
        distance_km=leg.distance_km,
        status=leg.status,
        aboard=aboard,
        bounty=bounty_status_for_leg(db, leg, now),
        path=path,
        polyline=encoded,
    )


def auction_out(db: Session, auction: Auction) -> AuctionOut:
    codes = {v.id: v.code for v in db.scalars(select(Vehicle)).all()}
    return AuctionOut(
        id=auction.id,
        shipment_id=auction.shipment_id,
        plan_id=auction.plan_id,
        status=auction.status,
        max_bounty=auction.max_bounty,
        opened_at=auction.opened_at,
        closes_at=auction.closes_at,
        winning_vehicle_id=auction.winning_vehicle_id,
        payment=auction.payment,
        bids=[
            BidOut(
                id=bid.id,
                vehicle_id=bid.vehicle_id,
                vehicle_code=codes.get(bid.vehicle_id),
                amount=bid.amount,
                detour_km=bid.detour_km,
                is_winner=bid.is_winner,
            )
            for bid in sorted(auction.bids, key=lambda b: b.amount)
        ],
    )
