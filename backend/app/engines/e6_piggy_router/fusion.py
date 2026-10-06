"""Route Fusion.

Merges two recovery movements that are going the same way into one vehicle
trip. Where E6 asks "which existing capacity can carry this shipment?",
fusion asks "are we about to run two trucks where one would do?".

A merge is only allowed when every one of these holds:

  1. **Compatibility** — the routes overlap enough to be worth combining.
  2. **Capacity** — one vehicle can carry both loads.
  3. **Deadline** — neither shipment misses its deadline after merging.
  4. **Cost** — the merged trip costs no more than the two separate ones.

Failing any of them leaves the routes separate, and the reason is recorded
so E8 can explain why.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.geo import haversine_km
from app.core.logging import get_logger
from app.models import Hub

logger = get_logger(__name__)

# Detour a merged trip may add over the longer of the two originals.
MAX_DETOUR_FACTOR = 1.35

# Two corridors are compatible when their endpoints are within this distance.
CORRIDOR_MATCH_KM = 250.0

AVERAGE_SPEED_KMH = 45.0
ROAD_FACTOR = 1.35


class FusionRejection:
    """Concrete reasons a merge was refused. Rendered verbatim by E8."""

    INCOMPATIBLE = (
        "Corridors do not overlap: origins {origin_km:.0f}km apart, "
        "destinations {dest_km:.0f}km apart (limit {limit:.0f}km)"
    )
    CAPACITY = (
        "Combined load {weight:.1f}kg / {volume:.2f}m3 exceeds vehicle "
        "capacity {cap_kg:.1f}kg / {cap_m3:.2f}m3"
    )
    DEADLINE = (
        "Merged arrival {arrival} would miss the deadline {deadline} "
        "for shipment {code}"
    )
    NO_SAVING = (
        "Merged cost {merged:.2f} is not below the separate cost {separate:.2f}"
    )
    DETOUR = (
        "Merged distance {merged:.0f}km exceeds {limit:.0f}km "
        "({factor:.2f}x the longer leg)"
    )


@dataclass(frozen=True, slots=True)
class Movement:
    """One shipment that needs moving, as fusion sees it."""

    shipment_id: int
    code: str
    origin: Hub
    destination: Hub
    weight_kg: float
    volume_m3: float
    deadline_at: datetime
    depart_after: datetime
    cost: float

    @property
    def distance_km(self) -> float:
        return haversine_km(
            self.origin.lat, self.origin.lng,
            self.destination.lat, self.destination.lng,
        ) * ROAD_FACTOR


@dataclass
class FusionResult:
    """Whether two movements merged, and the numbers behind it."""

    merged: bool
    shipment_ids: Tuple[int, ...]
    separate_cost: float
    merged_cost: float
    separate_distance_km: float
    merged_distance_km: float
    reason: str = ""

    @property
    def cost_saving(self) -> float:
        return round(self.separate_cost - self.merged_cost, 2)

    @property
    def distance_saved_km(self) -> float:
        """Vehicle-km avoided — one of the headline metrics (SH.docx §5.1)."""
        return round(self.separate_distance_km - self.merged_distance_km, 2)

    @property
    def utilisation_gain(self) -> float:
        """Fractional reduction in vehicle-km."""
        if self.separate_distance_km <= 0:
            return 0.0
        return round(self.distance_saved_km / self.separate_distance_km, 4)

    def as_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.update(
            cost_saving=self.cost_saving,
            distance_saved_km=self.distance_saved_km,
            utilisation_gain=self.utilisation_gain,
        )
        return data


def travel_hours(distance_km: float) -> float:
    return max(0.25, distance_km / AVERAGE_SPEED_KMH)


def merged_distance_km(a: Movement, b: Movement) -> float:
    """Shortest sensible combined route serving both movements.

    Two orderings are possible — pick up A first or B first — and the
    cheaper is used.
    """
    def leg(p: Hub, q: Hub) -> float:
        return haversine_km(p.lat, p.lng, q.lat, q.lng) * ROAD_FACTOR

    # A.origin -> B.origin -> A.dest -> B.dest
    route_a = (
        leg(a.origin, b.origin) + leg(b.origin, a.destination)
        + leg(a.destination, b.destination)
    )
    # B.origin -> A.origin -> B.dest -> A.dest
    route_b = (
        leg(b.origin, a.origin) + leg(a.origin, b.destination)
        + leg(b.destination, a.destination)
    )

    return min(route_a, route_b)


def are_compatible(
    a: Movement, b: Movement, *, match_km: float = CORRIDOR_MATCH_KM
) -> Tuple[bool, float, float]:
    """True when the two corridors run closely enough to share a vehicle."""
    origin_km = haversine_km(
        a.origin.lat, a.origin.lng, b.origin.lat, b.origin.lng
    )
    dest_km = haversine_km(
        a.destination.lat, a.destination.lng,
        b.destination.lat, b.destination.lng,
    )
    return (origin_km <= match_km and dest_km <= match_km), origin_km, dest_km


def try_fuse(
    a: Movement,
    b: Movement,
    *,
    capacity_kg: float,
    capacity_m3: float,
    cost_per_km: float,
    match_km: float = CORRIDOR_MATCH_KM,
) -> FusionResult:
    """Attempts to merge two movements onto one vehicle."""
    separate_distance = a.distance_km + b.distance_km
    separate_cost = a.cost + b.cost

    def refuse(reason: str, merged_km: float = 0.0) -> FusionResult:
        return FusionResult(
            merged=False,
            shipment_ids=(a.shipment_id, b.shipment_id),
            separate_cost=round(separate_cost, 2),
            merged_cost=round(separate_cost, 2),
            separate_distance_km=round(separate_distance, 2),
            merged_distance_km=round(merged_km or separate_distance, 2),
            reason=reason,
        )

    # 1. Compatibility
    compatible, origin_km, dest_km = are_compatible(a, b, match_km=match_km)
    if not compatible:
        return refuse(
            FusionRejection.INCOMPATIBLE.format(
                origin_km=origin_km, dest_km=dest_km, limit=match_km
            )
        )

    # 2. Capacity
    total_kg = a.weight_kg + b.weight_kg
    total_m3 = a.volume_m3 + b.volume_m3
    if total_kg > capacity_kg or total_m3 > capacity_m3:
        return refuse(
            FusionRejection.CAPACITY.format(
                weight=total_kg, volume=total_m3,
                cap_kg=capacity_kg, cap_m3=capacity_m3,
            )
        )

    combined_km = merged_distance_km(a, b)

    # A merge that wanders is not a merge worth making.
    detour_limit = max(a.distance_km, b.distance_km) * MAX_DETOUR_FACTOR
    if combined_km > detour_limit:
        return refuse(
            FusionRejection.DETOUR.format(
                merged=combined_km, limit=detour_limit, factor=MAX_DETOUR_FACTOR
            ),
            combined_km,
        )

    # 3. Deadline
    depart = max(a.depart_after, b.depart_after)
    arrival = depart + timedelta(hours=travel_hours(combined_km))

    for movement in (a, b):
        if arrival > movement.deadline_at:
            return refuse(
                FusionRejection.DEADLINE.format(
                    arrival=arrival.isoformat(timespec="minutes"),
                    deadline=movement.deadline_at.isoformat(timespec="minutes"),
                    code=movement.code,
                ),
                combined_km,
            )

    # 4. Cost
    combined_cost = combined_km * cost_per_km
    if combined_cost >= separate_cost:
        return refuse(
            FusionRejection.NO_SAVING.format(
                merged=combined_cost, separate=separate_cost
            ),
            combined_km,
        )

    logger.info(
        "Route fusion: %s + %s merged, %.0f km saved, %.2f cost saved",
        a.code, b.code,
        separate_distance - combined_km, separate_cost - combined_cost,
    )

    return FusionResult(
        merged=True,
        shipment_ids=(a.shipment_id, b.shipment_id),
        separate_cost=round(separate_cost, 2),
        merged_cost=round(combined_cost, 2),
        separate_distance_km=round(separate_distance, 2),
        merged_distance_km=round(combined_km, 2),
        reason="Compatible corridors merged within capacity and deadline",
    )


def fuse_all(
    movements: Sequence[Movement],
    *,
    capacity_kg: float,
    capacity_m3: float,
    cost_per_km: float,
    match_km: float = CORRIDOR_MATCH_KM,
) -> List[FusionResult]:
    """Greedily merges compatible pairs across a batch of movements.

    Greedy rather than optimal: pairing is O(n^2) here and an exact matching
    would be overkill for the prototype's scale.
    """
    used: set[int] = set()
    results: List[FusionResult] = []

    for i, first in enumerate(movements):
        if first.shipment_id in used:
            continue

        for second in movements[i + 1 :]:
            if second.shipment_id in used:
                continue

            outcome = try_fuse(
                first, second,
                capacity_kg=capacity_kg,
                capacity_m3=capacity_m3,
                cost_per_km=cost_per_km,
                match_km=match_km,
            )
            if outcome.merged:
                used.update({first.shipment_id, second.shipment_id})
                results.append(outcome)
                break

    return results
