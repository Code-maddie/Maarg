"""Map layer payloads.

Every payload here is shaped like the arrays the existing frontend already
renders from `data.js` (`HUBS`, `LEGS`, `CANDIDATES`, `heatPoints`). The map
code (gmaps.js / map.js) therefore draws live backend data without being
rewritten - only the data source changes.

HEATMAP — REAL E1 OUTPUT
------------------------
SH.docx §7 defines the heatmap as P(misplace) aggregated by
(from_hub, to_hub, hour_of_day). `hour_of_day` is a genuine E1 input, so each
active leg is scored by the trained model *at the requested hour*, and the
time-of-day slider shows the model's actual response to the hour. The
per-leg features are documented in `leg_features`. When E1 is unavailable
the heatmap falls back to stored shipment risk and says so in `source`.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.geo import haversine_km
from app.core.logging import get_logger
from app.engines.e1_misplacement.features import E1Features
from app.engines.e1_misplacement.registry import get_registry
from app.engines.e1_misplacement.service import build_features
from app.engines.e4_temperature.engine import zone_for
from app.models import (
    Auction,
    Bid,
    Hub,
    HubCandidate,
    Leg,
    Shipment,
    ShipmentLeg,
    Vehicle,
)
from app.models.enums import (
    AuctionStatus,
    CandidateStatus,
    LegStatus,
    VehicleType,
)
from app.services.geometry import (
    backfill_leg_polylines,
    decode_polyline,
    encode_polyline,
    leg_curve,
    point_along,
)

logger = get_logger(__name__)

ACTIVE_LEG_STATUSES = (
    LegStatus.SCHEDULED.value,
    LegStatus.DEPARTED.value,
    LegStatus.DELAYED.value,
)

# Heat point radii, matching data.js heatPoints().
HUB_HEAT_KM = 210
LEG_HEAT_KM = 140
LEG_HEAT_SCALE = 0.55

_risk_cache: Dict[Tuple, Dict[int, float]] = {}
_risk_lock = threading.Lock()


# --- hubs ----------------------------------------------------------------

def _label_anchor(hub: Hub, centre_lng: float) -> Tuple[str, int, int]:
    """Label placement in the shape data.js uses (a, dx, dy)."""
    if hub.lng < centre_lng - 2.5:
        return "end", -9, 4          # western hubs label to the left
    if hub.lng > centre_lng + 2.5:
        return "start", 9, -4        # eastern hubs label to the right
    return "middle", 0, -11          # central hubs label above


def hubs_payload(db: Session, hub_risk: Dict[int, float]) -> List[Dict[str, Any]]:
    # All hubs, closed ones flagged: a shipment can still reference a closed
    # hub, and the page resolves every code through hub(code).
    hubs = db.scalars(select(Hub)).all()
    if not hubs:
        return []
    centre = sum(h.lng for h in hubs) / len(hubs)

    payload = []
    for hub in sorted(hubs, key=lambda h: h.code):
        anchor, dx, dy = _label_anchor(hub, centre)
        payload.append(
            {
                "id": hub.code,
                "hub_id": hub.id,
                "name": hub.name.removesuffix(" Hub"),
                "lat": round(hub.lat, 5),
                "lon": round(hub.lng, 5),
                "base": round(hub_risk.get(hub.id, 0.0), 4),
                "a": anchor,
                "dx": dx,
                "dy": dy,
                "emergent": hub.is_emergent,
                "active": hub.is_active,
            }
        )
    return payload


# --- legs ----------------------------------------------------------------

def _hhmm(moment: datetime) -> str:
    return moment.strftime("%H:%M")


def active_legs(db: Session, limit: int) -> List[Leg]:
    """Legs worth drawing: moving first, then soonest departures."""
    rows = db.scalars(
        select(Leg).where(Leg.status.in_(ACTIVE_LEG_STATUSES))
    ).all()
    order = {LegStatus.DEPARTED.value: 0, LegStatus.DELAYED.value: 1,
             LegStatus.SCHEDULED.value: 2}
    rows = sorted(rows, key=lambda leg: (order.get(leg.status, 3), leg.departure_at))
    return rows[:limit]


def leg_path(leg: Leg, hubs: Dict[int, Hub]) -> List[Tuple[float, float]]:
    """Decoded stored polyline, or the curve computed on the fly."""
    if leg.polyline:
        return decode_polyline(leg.polyline)
    a, b = hubs[leg.from_hub_id], hubs[leg.to_hub_id]
    return leg_curve((a.lat, a.lng), (b.lat, b.lng))


def legs_payload(db: Session, now: datetime, limit: int) -> List[Dict[str, Any]]:
    backfill_leg_polylines(db)

    hubs = {hub.id: hub for hub in db.scalars(select(Hub)).all()}
    vehicles = {v.id: v for v in db.scalars(select(Vehicle)).all()}
    legs = active_legs(db, limit)
    leg_ids = [leg.id for leg in legs]

    aboard: Dict[int, List[List[Any]]] = {leg_id: [] for leg_id in leg_ids}
    shipment_to_leg: Dict[int, int] = {}
    if leg_ids:
        rows = db.execute(
            select(ShipmentLeg.leg_id, Shipment)
            .join(Shipment, Shipment.id == ShipmentLeg.shipment_id)
            .where(ShipmentLeg.leg_id.in_(leg_ids))
        ).all()
        for leg_id, shipment in rows:
            # [code, T, sla_penalty_per_hour] — the exact data.js shape.
            # legPanelHTML derives lambda as sla * (1 + T/50) itself, so
            # sending lambda here would double-count it.
            aboard[leg_id].append(
                [shipment.code, round(shipment.temperature),
                 round(shipment.sla_penalty_per_hour)]
            )
            shipment_to_leg[shipment.id] = leg_id

    # Live auctions for shipments aboard these legs (SH.docx §6.2).
    auctions: Dict[int, Dict[str, Any]] = {}
    if shipment_to_leg:
        open_auctions = db.scalars(
            select(Auction).where(
                Auction.status == AuctionStatus.OPEN.value,
                Auction.shipment_id.in_(list(shipment_to_leg)),
            )
        ).all()
        for auction in open_auctions:
            best = db.scalar(
                select(func.min(Bid.amount)).where(Bid.auction_id == auction.id)
            )
            auctions[shipment_to_leg[auction.shipment_id]] = {
                "auction_id": auction.id,
                "closes": max(0, int((auction.closes_at - now).total_seconds())),
                "best": round(best) if best is not None else None,
            }

    payload = []
    for leg in legs:
        if leg.from_hub_id not in hubs or leg.to_hub_id not in hubs:
            continue
        vehicle = vehicles.get(leg.vehicle_id)
        path = leg_path(leg, hubs)
        payload.append(
            {
                "id": f"L{leg.id}",
                "leg_id": leg.id,
                "vehicle_id": leg.vehicle_id,
                "veh": vehicle.code if vehicle else f"Vehicle {leg.vehicle_id}",
                "type": (
                    "Third-party"
                    if vehicle and vehicle.vehicle_type == VehicleType.THIRD_PARTY.value
                    else "Owned"
                ),
                "from": hubs[leg.from_hub_id].code,
                "to": hubs[leg.to_hub_id].code,
                "dep": _hhmm(leg.departure_at),
                "arr": _hhmm(leg.arrival_at),
                "departure_at": leg.departure_at.isoformat(),
                "arrival_at": leg.arrival_at.isoformat(),
                "tot": round(leg.capacity_kg),
                "res": round(leg.residual_kg),
                "rel": round(vehicle.reliability, 2) if vehicle else 0.0,
                "status": leg.status,
                "aboard": aboard.get(leg.id, []),
                "auction": auctions.get(leg.id),
                "path": [[round(lat, 5), round(lng, 5)] for lat, lng in path],
                "polyline": leg.polyline,
            }
        )
    return payload


# --- candidates ----------------------------------------------------------

def candidates_payload(db: Session) -> List[Dict[str, Any]]:
    hubs = db.scalars(select(Hub)).all()
    rows = db.scalars(
        select(HubCandidate)
        .where(HubCandidate.status != CandidateStatus.REJECTED.value)
        .order_by(HubCandidate.hub_score.desc())
    ).all()

    payload = []
    for row in rows:
        nearest = min(
            hubs, key=lambda h: haversine_km(row.lat, row.lng, h.lat, h.lng),
            default=None,
        )
        name = (
            f"Corridor near {nearest.name.removesuffix(' Hub')}" if nearest
            else f"Candidate {row.id}"
        )
        payload.append(
            {
                "id": f"C{row.id}",
                "candidate_id": row.id,
                "name": name,
                "lat": round(row.lat, 5),
                "lon": round(row.lng, 5),
                "usage": row.usage_count,
                "risk": round(row.mean_risk, 3),
                # data.js expresses money in rupee lakhs.
                "cost": round(row.est_setup_cost / 100_000, 1),
                "save": round(row.est_annual_savings / 100_000, 1),
                "status": row.status,
                "score": round(row.usage_count * row.mean_risk),
            }
        )
    return payload


# --- heat (real E1 risk by hour) ----------------------------------------

def leg_features(leg: Leg, hubs: Dict[int, Hub], vehicle: Optional[Vehicle],
                 hour: int, handoffs: int) -> E1Features:
    """E1 features for one leg at one hour.

    congestion_index is the leg's load factor (share of capacity in use):
    a fuller vehicle means more handling, which is the operational meaning
    of the trained feature. num_handoffs is the number of shipments aboard.
    """
    load = 0.0
    if leg.capacity_kg > 0:
        load = 1.0 - (leg.residual_kg / leg.capacity_kg)
    moment = leg.departure_at.replace(hour=hour, minute=0)
    return build_features(
        origin_code=hubs[leg.from_hub_id].code,
        dest_code=hubs[leg.to_hub_id].code,
        vehicle_type=vehicle.vehicle_type if vehicle else None,
        congestion_index=max(0.0, min(1.0, load)),
        num_handoffs=handoffs,
        at=moment,
    )


def _state_fingerprint(db: Session, legs: List[Leg], hubs: Dict[int, Hub]) -> Tuple:
    """Cache key covering every input the E1 heat features read.

    Row ids alone are NOT enough: SQLite reuses ids after a world rebuild, so
    a rebuild with a different seed but the same counts would otherwise be
    served the previous world's risk. Hashing the actual feature inputs
    (route endpoints, load, vehicle, aboard count) makes staleness impossible.
    """
    handoffs = dict(
        db.execute(
            select(ShipmentLeg.leg_id, func.count())
            .where(ShipmentLeg.leg_id.in_([leg.id for leg in legs]))
            .group_by(ShipmentLeg.leg_id)
        ).all()
    ) if legs else {}
    state = tuple(
        (
            leg.id,
            hubs[leg.from_hub_id].code if leg.from_hub_id in hubs else None,
            hubs[leg.to_hub_id].code if leg.to_hub_id in hubs else None,
            round(leg.residual_kg, 1),
            leg.vehicle_id,
            handoffs.get(leg.id, 0),
            leg.departure_at.isoformat(),
        )
        for leg in legs
    )
    return (hash(state),)


def leg_risk_by_hour(db: Session, legs: List[Leg], hour: int,
                     cache_key: Tuple) -> Tuple[Dict[int, float], str]:
    """P(misplace) per leg at ``hour``, from E1 when it is loaded."""
    key = (hour, *cache_key)
    with _risk_lock:
        if key in _risk_cache:
            return _risk_cache[key], "E1 model, scored per leg at this hour (cached)"

    registry = get_registry()
    if not registry.is_loaded or not legs:
        return {}, ""

    hubs = {hub.id: hub for hub in db.scalars(select(Hub)).all()}
    vehicles = {v.id: v for v in db.scalars(select(Vehicle)).all()}
    handoffs = dict(
        db.execute(
            select(ShipmentLeg.leg_id, func.count())
            .where(ShipmentLeg.leg_id.in_([leg.id for leg in legs]))
            .group_by(ShipmentLeg.leg_id)
        ).all()
    )

    usable = [l for l in legs if l.from_hub_id in hubs and l.to_hub_id in hubs]
    rows = [
        leg_features(l, hubs, vehicles.get(l.vehicle_id), hour, handoffs.get(l.id, 0))
        .as_row()
        for l in usable
    ]
    try:
        scores = registry.predict_batch(rows)
    except Exception:  # noqa: BLE001 - heatmap degrades, never errors
        logger.exception("E1 heat scoring failed")
        return {}, ""

    risk = {leg.id: score for leg, score in zip(usable, scores)}
    with _risk_lock:
        if len(_risk_cache) > 96:
            _risk_cache.clear()
        _risk_cache[key] = risk
    return risk, "E1 model, scored per leg at this hour"


def heat_payload(db: Session, *, hour: int, now: datetime, tick: int,
                 limit: int = 200) -> Dict[str, Any]:
    """Heat points in the data.js `heatPoints(hour)` shape: {lat,lng,w,km}."""
    hubs = {hub.id: hub for hub in db.scalars(select(Hub)).all()}
    legs = active_legs(db, limit)
    cache_key = _state_fingerprint(db, legs, hubs)

    risk, source = leg_risk_by_hour(db, legs, hour, cache_key)

    if not risk:
        # Fallback: stored shipment risk, attributed to the legs carrying it.
        rows = db.execute(
            select(ShipmentLeg.leg_id, func.avg(Shipment.p_misplace))
            .join(Shipment, Shipment.id == ShipmentLeg.shipment_id)
            .where(Shipment.p_misplace.is_not(None))
            .group_by(ShipmentLeg.leg_id)
        ).all()
        leg_ids = {leg.id for leg in legs}
        risk = {leg_id: float(value) for leg_id, value in rows if leg_id in leg_ids}
        source = (
            "stored shipment risk (E1 not loaded)" if risk
            else "no risk data yet (E1 not loaded, no shipments scored)"
        )

    # Hub risk = mean risk of the active legs touching it.
    touching: Dict[int, List[float]] = {}
    for leg in legs:
        if leg.id in risk:
            touching.setdefault(leg.from_hub_id, []).append(risk[leg.id])
            touching.setdefault(leg.to_hub_id, []).append(risk[leg.id])
    hub_risk = {hub_id: sum(v) / len(v) for hub_id, v in touching.items()}

    points: List[Dict[str, Any]] = []
    for hub_id, value in hub_risk.items():
        hub = hubs.get(hub_id)
        if hub is not None:
            points.append({"lat": round(hub.lat, 4), "lng": round(hub.lng, 4),
                           "w": round(value, 4), "km": HUB_HEAT_KM})

    # SH.docx §7.1: interpolate along the route and split the weight.
    for leg in legs:
        a, b = hubs.get(leg.from_hub_id), hubs.get(leg.to_hub_id)
        if a is None or b is None or leg.id not in risk:
            continue
        path = leg_path(leg, hubs)
        ra, rb = hub_risk.get(a.id, risk[leg.id]), hub_risk.get(b.id, risk[leg.id])
        for t in (0.33, 0.66):
            lat, lng = point_along(path, t)
            points.append({"lat": round(lat, 4), "lng": round(lng, 4),
                           "w": round((ra * (1 - t) + rb * t) * LEG_HEAT_SCALE, 4),
                           "km": LEG_HEAT_KM})

    return {
        "hour": hour,
        "source": source,
        "points": points,
        "hub_risk": {hubs[h].code: round(v, 4) for h, v in hub_risk.items() if h in hubs},
        "legs_scored": len(risk),
    }


# --- whole network -------------------------------------------------------

def network_payload(db: Session, *, hour: int, now: datetime, tick: int,
                    leg_limit: int = 60) -> Dict[str, Any]:
    """Everything one map needs, in one call."""
    heat = heat_payload(db, hour=hour, now=now, tick=tick)
    hub_ids = {hub.code: hub.id for hub in db.scalars(select(Hub)).all()}
    hub_risk = {hub_ids[code]: value for code, value in heat["hub_risk"].items()
                if code in hub_ids}

    return {
        "hour": hour,
        "now": now.isoformat(),
        "tick": tick,
        "hubs": hubs_payload(db, hub_risk),
        "legs": legs_payload(db, now, leg_limit),
        "candidates": candidates_payload(db),
        "heat": heat,
    }


# --- driver directions (SH.docx §6.3) -----------------------------------

def pickup_route(db: Session, auction: Auction) -> Dict[str, Any]:
    """Waypoints [driver, pickup, destination] for the Directions API call.

    The Directions request itself stays client-side (the existing
    livemap.js already calls DirectionsService, with OSRM as fallback),
    so the backend supplies the waypoints and a straight-line fallback path.
    """
    if auction.winning_vehicle_id is None:
        raise ValueError(f"Auction {auction.id} has no winning vehicle yet")

    vehicle = db.get(Vehicle, auction.winning_vehicle_id)
    shipment = db.get(Shipment, auction.shipment_id)
    pickup = db.get(Hub, shipment.current_hub_id or shipment.origin_hub_id)
    destination = db.get(Hub, shipment.dest_hub_id)

    start_lat = vehicle.current_lat if vehicle.current_lat is not None else pickup.lat
    start_lng = vehicle.current_lng if vehicle.current_lng is not None else pickup.lng

    waypoints = [
        {"role": "driver", "label": vehicle.code, "lat": start_lat, "lng": start_lng},
        {"role": "pickup", "label": pickup.name, "hub": pickup.code,
         "lat": pickup.lat, "lng": pickup.lng},
        {"role": "destination", "label": destination.name, "hub": destination.code,
         "lat": destination.lat, "lng": destination.lng},
    ]
    straight = [(w["lat"], w["lng"]) for w in waypoints]
    detour = haversine_km(start_lat, start_lng, pickup.lat, pickup.lng)

    return {
        "auction_id": auction.id,
        "shipment_code": shipment.code,
        "vehicle_code": vehicle.code,
        "waypoints": waypoints,
        "detour_km": round(detour, 2),
        "fallback_path": [[round(a, 5), round(b, 5)] for a, b in straight],
        "fallback_polyline": encode_polyline(straight),
    }
