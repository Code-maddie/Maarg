"""Recovery Cascade.

One disruption is rarely isolated: a delayed truck strands the shipments it
was carrying, those shipments miss their onward connections, and the hubs
waiting for them fall behind. The cascade engine walks that dependency graph
and updates priority, temperature and pressure for everything genuinely
affected — and nothing else.

TERMINATION
-----------
A cascade must never loop. Three independent guards make that structural,
not a matter of luck:

  1. Every entity is visited **at most once** (a ``visited`` set).
  2. Propagation stops at ``max_depth`` hops.
  3. Influence decays by ``DECAY_PER_HOP`` each hop and stops below
     ``MIN_INFLUENCE``.

Guard 1 alone bounds the work by the number of entities, so the traversal
terminates even if the other two were removed.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.engines.e4_temperature.engine import (
    CASCADE_SATURATION_DEPTH,
    TemperatureEngine,
)
from app.engines.e4_temperature.pressure import apply_pressure
from app.models import Hub, Leg, Shipment, ShipmentLeg, Vehicle
from app.models.enums import LegStatus, ShipmentStatus

logger = get_logger(__name__)

# How far a disruption may propagate.
DEFAULT_MAX_DEPTH = 4

# Influence retained per hop; a 3-hop-away shipment is affected far less
# than a directly stranded one.
DECAY_PER_HOP = 0.55

# Below this, propagation stops — the effect is no longer meaningful.
MIN_INFLUENCE = 0.05


@dataclass
class CascadeNode:
    """One affected entity and how strongly."""

    entity_type: str
    entity_id: int
    depth: int
    influence: float
    reason: str

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CascadeResult:
    """Everything one cascade touched."""

    origin_type: str
    origin_id: int
    max_depth_reached: int = 0
    iterations: int = 0
    terminated_by: str = ""
    shipments: List[CascadeNode] = field(default_factory=list)
    vehicles: List[CascadeNode] = field(default_factory=list)
    hubs: List[CascadeNode] = field(default_factory=list)

    @property
    def affected_shipment_ids(self) -> List[int]:
        return [node.entity_id for node in self.shipments]

    @property
    def total_affected(self) -> int:
        return len(self.shipments) + len(self.vehicles) + len(self.hubs)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "origin_type": self.origin_type,
            "origin_id": self.origin_id,
            "max_depth_reached": self.max_depth_reached,
            "iterations": self.iterations,
            "terminated_by": self.terminated_by,
            "total_affected": self.total_affected,
            "shipments": [node.as_dict() for node in self.shipments],
            "vehicles": [node.as_dict() for node in self.vehicles],
            "hubs": [node.as_dict() for node in self.hubs],
        }


class CascadeEngine:
    """Propagates a disruption through the dependency graph."""

    def __init__(
        self,
        db: Session,
        *,
        max_depth: int = DEFAULT_MAX_DEPTH,
        decay: float = DECAY_PER_HOP,
        min_influence: float = MIN_INFLUENCE,
    ) -> None:
        self.db = db
        self.max_depth = max_depth
        self.decay = decay
        self.min_influence = min_influence

    # --- graph traversal -------------------------------------------------

    def _shipments_on_leg(self, leg_id: int) -> List[int]:
        return [
            link.shipment_id
            for link in self.db.scalars(
                select(ShipmentLeg).where(ShipmentLeg.leg_id == leg_id)
            ).all()
        ]

    def _legs_of_vehicle(self, vehicle_id: int, now: datetime) -> List[Leg]:
        return list(
            self.db.scalars(
                select(Leg).where(
                    Leg.vehicle_id == vehicle_id, Leg.arrival_at >= now
                )
            ).all()
        )

    def _onward_legs_for_shipment(
        self, shipment_id: int, now: datetime
    ) -> List[Leg]:
        """Legs this shipment is still booked to ride."""
        links = self.db.scalars(
            select(ShipmentLeg).where(ShipmentLeg.shipment_id == shipment_id)
        ).all()

        legs: List[Leg] = []
        for link in links:
            leg = self.db.get(Leg, link.leg_id)
            if leg is not None and leg.arrival_at >= now:
                legs.append(leg)
        return legs

    def propagate(
        self,
        *,
        origin_type: str,
        origin_id: int,
        now: datetime,
        initial_influence: float = 1.0,
    ) -> CascadeResult:
        """Walks the dependency graph outward from one disruption."""
        result = CascadeResult(origin_type=origin_type, origin_id=origin_id)

        # (type, id) pairs already handled. This is the primary termination
        # guarantee: nothing is ever enqueued twice.
        visited: Set[Tuple[str, int]] = set()
        queue: deque[Tuple[str, int, int, float, str]] = deque()
        queue.append((origin_type, origin_id, 0, initial_influence, "origin of disruption"))

        terminated_by = "queue exhausted"

        while queue:
            entity_type, entity_id, depth, influence, reason = queue.popleft()
            result.iterations += 1

            if (entity_type, entity_id) in visited:
                continue
            visited.add((entity_type, entity_id))

            result.max_depth_reached = max(result.max_depth_reached, depth)

            node = CascadeNode(
                entity_type=entity_type,
                entity_id=entity_id,
                depth=depth,
                influence=round(influence, 4),
                reason=reason,
            )
            if entity_type == "shipment":
                result.shipments.append(node)
            elif entity_type == "vehicle":
                result.vehicles.append(node)
            elif entity_type == "hub":
                result.hubs.append(node)

            if depth >= self.max_depth:
                terminated_by = "max depth reached"
                continue

            next_influence = influence * self.decay
            if next_influence < self.min_influence:
                terminated_by = "influence decayed below threshold"
                continue

            for child in self._neighbours(entity_type, entity_id, now):
                if child[:2] not in visited:
                    queue.append(
                        (child[0], child[1], depth + 1, next_influence, child[2])
                    )

        result.terminated_by = terminated_by
        return result

    def _neighbours(
        self, entity_type: str, entity_id: int, now: datetime
    ) -> List[Tuple[str, int, str]]:
        """Entities directly downstream of this one."""
        if entity_type == "vehicle":
            neighbours: List[Tuple[str, int, str]] = []
            for leg in self._legs_of_vehicle(entity_id, now):
                for shipment_id in self._shipments_on_leg(leg.id):
                    neighbours.append(
                        ("shipment", shipment_id, f"aboard delayed leg {leg.id}")
                    )
                neighbours.append(
                    ("hub", leg.to_hub_id, f"awaiting delayed leg {leg.id}")
                )
            return neighbours

        if entity_type == "shipment":
            neighbours = []
            for leg in self._onward_legs_for_shipment(entity_id, now):
                neighbours.append(
                    ("vehicle", leg.vehicle_id, f"carrying affected shipment {entity_id}")
                )
                neighbours.append(
                    ("hub", leg.to_hub_id, f"destination of affected shipment {entity_id}")
                )
            return neighbours

        if entity_type == "hub":
            neighbours = []
            legs = self.db.scalars(
                select(Leg).where(
                    Leg.from_hub_id == entity_id,
                    Leg.departure_at >= now,
                    Leg.status.in_(
                        [LegStatus.SCHEDULED.value, LegStatus.DELAYED.value]
                    ),
                )
            ).all()
            for leg in legs:
                for shipment_id in self._shipments_on_leg(leg.id):
                    neighbours.append(
                        ("shipment", shipment_id, f"departing congested hub {entity_id}")
                    )
            return neighbours

        return []

    # --- applying --------------------------------------------------------

    def apply(self, result: CascadeResult, *, now: datetime) -> List[int]:
        """Writes cascade depth, temperature and pressure onto affected shipments.

        Returns the ids actually modified. Shipments already delivered or
        failed are skipped — a cascade cannot make history worse.
        """
        engine = TemperatureEngine.from_db(self.db)
        touched: List[int] = []

        for node in result.shipments:
            shipment = self.db.get(Shipment, node.entity_id)
            if shipment is None:
                continue
            if shipment.status in {
                ShipmentStatus.DELIVERED.value,
                ShipmentStatus.FAILED.value,
            }:
                continue

            # Use *influence*, not raw hop count, to set the cascade depth
            # E4 will read. Hop count alone is badly misleading here: a
            # shipment four hops away with influence 0.09 would otherwise
            # get cascade_depth=4 and nearly saturate E4's cascade term,
            # making a barely-connected shipment look almost as urgent as a
            # directly stranded one. Influence already decays per hop, so
            # scaling by it keeps the heat proportional to real exposure.
            effective_depth = math.ceil(node.influence * CASCADE_SATURATION_DEPTH)
            shipment.cascade_depth = max(shipment.cascade_depth, effective_depth)

            engine.apply(shipment, now)
            apply_pressure(shipment, now)
            touched.append(shipment.id)

        self.db.commit()
        logger.info(
            "Cascade from %s %d: %d shipments updated (depth %d, %d iterations, %s)",
            result.origin_type, result.origin_id, len(touched),
            result.max_depth_reached, result.iterations, result.terminated_by,
        )
        return touched


def cascade_from_vehicle(
    db: Session, vehicle_id: int, *, now: datetime, max_depth: int = DEFAULT_MAX_DEPTH
) -> Tuple[CascadeResult, List[int]]:
    """Convenience: propagate a vehicle delay and apply its consequences."""
    engine = CascadeEngine(db, max_depth=max_depth)
    result = engine.propagate(origin_type="vehicle", origin_id=vehicle_id, now=now)
    return result, engine.apply(result, now=now)


def cascade_from_shipment(
    db: Session, shipment_id: int, *, now: datetime, max_depth: int = DEFAULT_MAX_DEPTH
) -> Tuple[CascadeResult, List[int]]:
    """Convenience: propagate a shipment misplacement."""
    engine = CascadeEngine(db, max_depth=max_depth)
    result = engine.propagate(origin_type="shipment", origin_id=shipment_id, now=now)
    return result, engine.apply(result, now=now)


def cascade_from_hub(
    db: Session, hub_id: int, *, now: datetime, max_depth: int = DEFAULT_MAX_DEPTH
) -> Tuple[CascadeResult, List[int]]:
    """Convenience: propagate a hub closure."""
    engine = CascadeEngine(db, max_depth=max_depth)
    result = engine.propagate(origin_type="hub", origin_id=hub_id, now=now)
    return result, engine.apply(result, now=now)
