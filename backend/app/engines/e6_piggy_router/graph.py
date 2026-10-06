"""Time-expanded transportation graph for E6.

Nodes are (hub, time) pairs; edges are scheduled legs. A shipment sitting at
a hub waiting for a later departure is modelled implicitly — an edge is
traversable from any arrival time at or before its departure time, minus the
minimum transfer allowance.

Edge weight, SH.docx §16:

    w(e) = C_transit(e) + lambda(s) * transit_hours(e) + handling_penalty(e)

Geo pruning uses the haversine helper from app.core.geo rather than PostGIS
ST_DWithin (constraint C3).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.geo import haversine_km
from app.models import Hub, Leg
from app.models.enums import LegStatus

# A shipment needs this long at a hub to be unloaded and reloaded.
MIN_TRANSFER_MINUTES = 30

# Legs whose origin is further than this from the shipment's current position
# are not worth considering. Generous, because detours are the whole point.
DEFAULT_GEO_RADIUS_KM = 1500.0

# Statuses a leg can have and still be usable for a future recovery.
USABLE_LEG_STATUSES = (LegStatus.SCHEDULED.value, LegStatus.DELAYED.value)


@dataclass(frozen=True, slots=True)
class Edge:
    """A traversable leg with its precomputed cost inputs."""

    leg_id: int
    from_hub_id: int
    to_hub_id: int
    departure_at: datetime
    arrival_at: datetime
    residual_kg: float
    residual_m3: float
    transit_cost: float
    handling_penalty: float
    distance_km: float
    vehicle_id: int

    @property
    def transit_hours(self) -> float:
        return max(0.0, (self.arrival_at - self.departure_at).total_seconds() / 3600.0)

    def weight(self, lam: float) -> float:
        """w(e) = C_transit + lambda * transit_hours + handling_penalty."""
        return (
            self.transit_cost
            + lam * self.transit_hours
            + self.handling_penalty
        )

    def can_carry(self, weight_kg: float, volume_m3: float) -> bool:
        return self.residual_kg >= weight_kg and self.residual_m3 >= volume_m3


class TransportGraph:
    """Adjacency over hubs, holding only legs that are still usable."""

    def __init__(self, edges: Sequence[Edge], hubs: Dict[int, Hub]) -> None:
        self.hubs = hubs
        self._out: Dict[int, List[Edge]] = {}

        for edge in edges:
            self._out.setdefault(edge.from_hub_id, []).append(edge)

        # Earliest departure first: label-setting expands in time order.
        for bucket in self._out.values():
            bucket.sort(key=lambda item: item.departure_at)

    @property
    def edge_count(self) -> int:
        return sum(len(bucket) for bucket in self._out.values())

    def outgoing(
        self,
        hub_id: int,
        *,
        earliest_departure: Optional[datetime] = None,
        weight_kg: float = 0.0,
        volume_m3: float = 0.0,
    ) -> List[Edge]:
        """Feasible edges leaving ``hub_id``.

        Filters on the three hard constraints at once — time, weight and
        volume — so the search never expands an infeasible label.
        """
        candidates = self._out.get(hub_id, [])
        results: List[Edge] = []

        for edge in candidates:
            if earliest_departure is not None and edge.departure_at < earliest_departure:
                continue
            if not edge.can_carry(weight_kg, volume_m3):
                continue
            results.append(edge)

        return results

    def hub(self, hub_id: int) -> Optional[Hub]:
        return self.hubs.get(hub_id)


def transfer_ready_at(arrival: datetime) -> datetime:
    """Earliest a shipment arriving at ``arrival`` can board another leg."""
    return arrival + timedelta(minutes=MIN_TRANSFER_MINUTES)


def build_graph(
    db: Session,
    *,
    now: datetime,
    horizon_hours: float = 72.0,
    origin: Optional[Hub] = None,
    radius_km: float = DEFAULT_GEO_RADIUS_KM,
    weight_kg: float = 0.0,
    volume_m3: float = 0.0,
    extra_edges: Iterable[Edge] = (),
) -> TransportGraph:
    """Loads usable legs into an in-memory graph.

    Prunes on time horizon, capacity and geography before building, so the
    label-setting search operates on the smallest viable edge set.
    """
    horizon = now + timedelta(hours=horizon_hours)

    hubs = {hub.id: hub for hub in db.scalars(select(Hub)).all()}

    rows = db.scalars(
        select(Leg).where(
            Leg.status.in_(USABLE_LEG_STATUSES),
            Leg.departure_at >= now,
            Leg.departure_at <= horizon,
            Leg.residual_kg >= weight_kg,
            Leg.residual_m3 >= volume_m3,
        )
    ).all()

    edges: List[Edge] = []
    for leg in rows:
        source = hubs.get(leg.from_hub_id)
        if source is None:
            continue

        # Geo pruning: the PostGIS ST_DWithin equivalent.
        if origin is not None:
            distance = haversine_km(origin.lat, origin.lng, source.lat, source.lng)
            if distance > radius_km:
                continue

        # A closed hub cannot be used as a transfer point.
        destination = hubs.get(leg.to_hub_id)
        if destination is None or not destination.is_active:
            continue

        edges.append(
            Edge(
                leg_id=leg.id,
                from_hub_id=leg.from_hub_id,
                to_hub_id=leg.to_hub_id,
                departure_at=leg.departure_at,
                arrival_at=leg.arrival_at,
                residual_kg=leg.residual_kg,
                residual_m3=leg.residual_m3,
                transit_cost=leg.transit_cost,
                handling_penalty=leg.handling_penalty,
                distance_km=leg.distance_km,
                vehicle_id=leg.vehicle_id,
            )
        )

    edges.extend(extra_edges)
    return TransportGraph(edges, hubs)
