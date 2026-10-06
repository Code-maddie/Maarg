"""Deterministic world builder.

Creates the simulated network described in SH.docx §14 block 0: 30 hubs,
200 vehicles and 5 000 shipments from a fixed seed, so every demo run and
every test produces an identical world.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.geo import haversine_km
from app.core.logging import get_logger
from app.models import (
    Auction,
    Bid,
    Hub,
    HubCandidate,
    Leg,
    RecoveryPath,
    RecoveryPlan,
    Shipment,
    ShipmentLeg,
    Vehicle,
)
from app.models.enums import ShipmentStatus, VehicleStatus, VehicleType

logger = get_logger(__name__)

# Real Indian locations so the Google Maps / Leaflet view looks plausible
# and distances are meaningful. (code, name, lat, lng)
HUB_SEEDS: Sequence[tuple[str, str, float, float]] = (
    ("DEL", "Delhi", 28.6139, 77.2090),
    ("BOM", "Mumbai", 19.0760, 72.8777),
    ("BLR", "Bengaluru", 12.9716, 77.5946),
    ("MAA", "Chennai", 13.0827, 80.2707),
    ("CCU", "Kolkata", 22.5726, 88.3639),
    ("HYD", "Hyderabad", 17.3850, 78.4867),
    ("PNQ", "Pune", 18.5204, 73.8567),
    ("AMD", "Ahmedabad", 23.0225, 72.5714),
    ("JAI", "Jaipur", 26.9124, 75.7873),
    ("LKO", "Lucknow", 26.8467, 80.9462),
    ("NAG", "Nagpur", 21.1458, 79.0882),
    ("IDR", "Indore", 22.7196, 75.8577),
    ("BBI", "Bhubaneswar", 20.2961, 85.8245),
    ("PAT", "Patna", 25.5941, 85.1376),
    ("GAU", "Guwahati", 26.1445, 91.7362),
    ("COK", "Kochi", 9.9312, 76.2673),
    ("TRV", "Thiruvananthapuram", 8.5241, 76.9366),
    ("VTZ", "Visakhapatnam", 17.6868, 83.2185),
    ("CJB", "Coimbatore", 11.0168, 76.9558),
    ("IXC", "Chandigarh", 30.7333, 76.7794),
    ("ATQ", "Amritsar", 31.6340, 74.8723),
    ("SXR", "Srinagar", 34.0837, 74.7973),
    ("DED", "Dehradun", 30.3165, 78.0322),
    ("RPR", "Raipur", 21.2514, 81.6296),
    ("RAJ", "Rajkot", 22.3039, 70.8022),
    ("SRT", "Surat", 21.1702, 72.8311),
    ("VNS", "Varanasi", 25.3176, 82.9739),
    ("MYQ", "Mysuru", 12.2958, 76.6394),
    ("HBX", "Hubballi", 15.3647, 75.1240),
    ("JDH", "Jodhpur", 26.2389, 73.0243),
)

AVERAGE_ROAD_SPEED_KMH = 45.0

# Road distance exceeds great-circle distance; this is the usual planning
# factor for Indian highway networks.
ROAD_DISTANCE_FACTOR = 1.35


@dataclass(frozen=True, slots=True)
class WorldSpec:
    """Parameters controlling world generation."""

    seed: int = 42
    hub_count: int = 30
    vehicle_count: int = 200
    shipment_count: int = 5000
    leg_count: int = 600
    start: datetime = datetime(2026, 5, 1, 6, 0, 0)
    horizon_hours: int = 48


@dataclass(frozen=True, slots=True)
class WorldSummary:
    hubs: int
    vehicles: int
    shipments: int
    legs: int
    seed: int
    start: datetime


def road_distance_km(a: Hub, b: Hub) -> float:
    """Estimated road distance between two hubs."""
    return haversine_km(a.lat, a.lng, b.lat, b.lng) * ROAD_DISTANCE_FACTOR


def travel_hours(distance_km: float) -> float:
    """Driving time for a road distance, with a floor for handling."""
    return max(0.5, distance_km / AVERAGE_ROAD_SPEED_KMH)


def clear_world(db: Session) -> None:
    """Removes all simulated state.

    Deleted most-dependent-first. Users, policy modes and model artifacts are
    deliberately preserved: they are configuration, not simulation output.
    """
    for model in (
        Bid,
        Auction,
        RecoveryPath,
        RecoveryPlan,
        ShipmentLeg,
        Shipment,
        Leg,
        Vehicle,
        HubCandidate,
        Hub,
    ):
        db.execute(delete(model))
    db.commit()


def build_world(db: Session, spec: WorldSpec | None = None) -> WorldSummary:
    """Generates a complete simulated world. Destroys any existing one.

    Everything derives from ``spec.seed``, so two runs with the same seed
    produce byte-identical worlds.
    """
    spec = spec or WorldSpec()
    rng = random.Random(spec.seed)

    clear_world(db)

    hubs = _create_hubs(db, spec)
    vehicles = _create_vehicles(db, spec, rng, hubs)
    legs = _create_legs(db, spec, rng, hubs, vehicles)
    shipments = _create_shipments(db, spec, rng, hubs, legs)
    booked = _assign_initial_itineraries(db, legs)

    from app.services.geometry import backfill_leg_polylines

    backfill_leg_polylines(db)

    logger.info(
        "World built: %d hubs, %d vehicles, %d legs, %d shipments, "
        "%d initially booked (seed=%d)",
        len(hubs), len(vehicles), len(legs), len(shipments), booked, spec.seed,
    )

    return WorldSummary(
        hubs=len(hubs),
        vehicles=len(vehicles),
        shipments=len(shipments),
        legs=len(legs),
        seed=spec.seed,
        start=spec.start,
    )


def _create_hubs(db: Session, spec: WorldSpec) -> List[Hub]:
    count = min(spec.hub_count, len(HUB_SEEDS))
    hubs = [
        Hub(
            code=code,
            name=f"{name} Hub",
            lat=lat,
            lng=lng,
            capacity_kg=10_000.0,
            is_active=True,
        )
        for code, name, lat, lng in HUB_SEEDS[:count]
    ]
    db.add_all(hubs)
    db.commit()
    return hubs


def _create_vehicles(
    db: Session, spec: WorldSpec, rng: random.Random, hubs: List[Hub]
) -> List[Vehicle]:
    vehicles: List[Vehicle] = []
    for index in range(spec.vehicle_count):
        home = rng.choice(hubs)
        # A third of the fleet is third-party: they bid in E5 auctions but
        # are less reliable, which is what makes the bounty market interesting.
        is_third_party = rng.random() < 0.33
        vehicles.append(
            Vehicle(
                code=f"TRK-{index:04d}",
                vehicle_type=(
                    VehicleType.THIRD_PARTY.value
                    if is_third_party
                    else VehicleType.OWNED.value
                ),
                status=VehicleStatus.IDLE.value,
                capacity_kg=rng.choice([500.0, 1000.0, 2000.0, 5000.0]),
                capacity_m3=rng.choice([20.0, 40.0, 60.0]),
                reliability=round(
                    rng.uniform(0.70, 0.95) if is_third_party
                    else rng.uniform(0.85, 0.99),
                    3,
                ),
                cost_per_km=round(rng.uniform(18.0, 35.0), 2),
                current_hub_id=home.id,
                current_lat=home.lat,
                current_lng=home.lng,
            )
        )

    db.add_all(vehicles)
    db.commit()
    return vehicles


def _create_legs(
    db: Session,
    spec: WorldSpec,
    rng: random.Random,
    hubs: List[Hub],
    vehicles: List[Vehicle],
) -> List[Leg]:
    legs: List[Leg] = []

    for _ in range(spec.leg_count):
        vehicle = rng.choice(vehicles)
        origin, destination = rng.sample(hubs, 2)

        distance = road_distance_km(origin, destination)
        hours = travel_hours(distance)

        departure = spec.start + timedelta(
            hours=rng.uniform(0, spec.horizon_hours)
        )
        arrival = departure + timedelta(hours=hours)

        # Legs start partially loaded, so the router has to work with real
        # residual capacity rather than empty trucks.
        used_fraction = rng.uniform(0.3, 0.9)

        legs.append(
            Leg(
                vehicle_id=vehicle.id,
                from_hub_id=origin.id,
                to_hub_id=destination.id,
                departure_at=departure,
                arrival_at=arrival,
                capacity_kg=vehicle.capacity_kg,
                residual_kg=round(vehicle.capacity_kg * (1 - used_fraction), 2),
                capacity_m3=vehicle.capacity_m3,
                residual_m3=round(vehicle.capacity_m3 * (1 - used_fraction), 2),
                distance_km=round(distance, 2),
                transit_cost=round(distance * vehicle.cost_per_km, 2),
                handling_penalty=round(rng.uniform(50.0, 200.0), 2),
            )
        )

    db.add_all(legs)
    db.commit()
    return legs


def _create_shipments(
    db: Session,
    spec: WorldSpec,
    rng: random.Random,
    hubs: List[Hub],
    legs: List[Leg],
) -> List[Shipment]:
    shipments: List[Shipment] = []

    for index in range(spec.shipment_count):
        origin, destination = rng.sample(hubs, 2)
        distance = road_distance_km(origin, destination)

        # Deadline gives roughly 1.5x-3x the direct driving time.
        slack = rng.uniform(1.5, 3.0)
        deadline = spec.start + timedelta(hours=travel_hours(distance) * slack)

        shipments.append(
            Shipment(
                code=f"S{index:05d}",
                origin_hub_id=origin.id,
                dest_hub_id=destination.id,
                current_hub_id=origin.id,
                weight_kg=round(rng.uniform(1.0, 120.0), 2),
                volume_m3=round(rng.uniform(0.05, 3.0), 3),
                status=ShipmentStatus.PENDING.value,
                deadline_at=deadline,
                sla_penalty_per_hour=round(rng.choice([50.0, 100.0, 250.0, 500.0]), 2),
                base_priority=round(rng.uniform(0.5, 2.0), 2),
            )
        )

    # bulk_save_objects is markedly faster than add_all for 5 000 rows and
    # this path does not need the ORM identity map afterwards.
    db.bulk_save_objects(shipments)
    db.commit()

    return shipments


def _assign_initial_itineraries(db: Session, legs: List[Leg]) -> int:
    """Books shipments onto any direct leg that already serves their route.

    Without this the world is static: nothing is aboard anything, so ticks
    move no cargo. Shipments with no matching direct leg stay PENDING, which
    is realistic — those are the ones awaiting dispatch, and the ones E6 will
    have to route once they are disrupted.
    """
    legs_by_route: dict[tuple[int, int], List[Leg]] = {}
    for leg in legs:
        legs_by_route.setdefault((leg.from_hub_id, leg.to_hub_id), []).append(leg)

    # Earliest departure first, so a shipment takes the soonest service.
    for candidates in legs_by_route.values():
        candidates.sort(key=lambda item: item.departure_at)

    links: List[ShipmentLeg] = []

    for shipment in db.scalars(select(Shipment)).all():
        candidates = legs_by_route.get(
            (shipment.origin_hub_id, shipment.dest_hub_id)
        )
        if not candidates:
            continue

        for leg in candidates:
            if not leg.can_fit(shipment.weight_kg, shipment.volume_m3):
                continue
            if leg.arrival_at > shipment.deadline_at:
                continue

            leg.residual_kg = round(leg.residual_kg - shipment.weight_kg, 3)
            leg.residual_m3 = round(leg.residual_m3 - shipment.volume_m3, 3)
            links.append(
                ShipmentLeg(shipment_id=shipment.id, leg_id=leg.id, seq=0)
            )
            break

    if links:
        db.bulk_save_objects(links)
    db.commit()

    return len(links)
