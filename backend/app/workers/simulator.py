"""Simulation engine: the tick loop and disruption injection.

One ``tick`` advances simulated time and moves the world forward:
departures, arrivals, shipment transfers and capacity consumption.
Disruptions are injected on demand to drive the live demo (SH.docx §15).
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import Hub, Leg, Shipment, ShipmentLeg, Vehicle
from app.services.events import EventType, publish
from app.models.enums import LegStatus, ShipmentStatus, VehicleStatus
from app.workers.clock import SimulationClock
from app.workers.world import WorldSpec, build_world

logger = get_logger(__name__)


class DisruptionType(StrEnum):
    """Disruptions the demo can inject (SH.docx §9 /simulate/inject-disruption)."""

    MISPLACE_SHIPMENT = "MISPLACE_SHIPMENT"
    DELAY_VEHICLE = "DELAY_VEHICLE"
    CLOSE_HUB = "CLOSE_HUB"


@dataclass
class TickResult:
    """What one tick changed. Returned by the API and pushed over WebSocket."""

    tick: int
    now: str
    departed_legs: int = 0
    arrived_legs: int = 0
    shipments_moved: int = 0
    shipments_delivered: int = 0
    shipments_overdue: int = 0
    events: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DisruptionResult:
    type: str
    target_id: int
    affected_shipments: List[int] = field(default_factory=list)
    affected_legs: List[int] = field(default_factory=list)
    detail: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


class Simulator:
    """Owns the clock and mutates world state one tick at a time.

    Deliberately holds no engine logic: E1–E9 read the state this produces.
    Keeping them separate means the simulator can be driven by tests without
    any engine being available.
    """

    def __init__(
        self,
        spec: Optional[WorldSpec] = None,
        clock: Optional[SimulationClock] = None,
    ) -> None:
        self.spec = spec or WorldSpec()
        self.clock = clock or SimulationClock(self.spec.start, tick_minutes=15)
        self._rng = random.Random(self.spec.seed)

    # --- world -----------------------------------------------------------

    def reset(self, db: Session, spec: Optional[WorldSpec] = None) -> Dict[str, Any]:
        """Rebuilds the world and rewinds the clock."""
        if spec is not None:
            self.spec = spec

        self._rng = random.Random(self.spec.seed)
        summary = build_world(db, self.spec)
        self.clock = SimulationClock(self.spec.start, tick_minutes=15)

        return {
            "hubs": summary.hubs,
            "vehicles": summary.vehicles,
            "shipments": summary.shipments,
            "legs": summary.legs,
            "seed": summary.seed,
            "start": summary.start.isoformat(),
        }

    # --- tick ------------------------------------------------------------

    def tick(self, db: Session) -> TickResult:
        """Advances simulated time by one tick and applies its consequences."""
        now = self.clock.advance()
        result = TickResult(tick=self.clock.tick, now=now.isoformat())

        departed = self._depart_legs(db, now, result)
        self._arrive_legs(db, now, result)
        self._score_departed(db, departed, now)
        self._mark_overdue(db, now, result)

        db.commit()
        logger.info(
            "Tick %d @ %s: %d departed, %d arrived, %d moved",
            result.tick, now.isoformat(timespec="minutes"),
            result.departed_legs, result.arrived_legs, result.shipments_moved,
        )

        publish(EventType.TICK, result.as_dict(), at=now)
        return result

    def _depart_legs(self, db: Session, now, result: TickResult) -> List[int]:
        """Legs whose departure time has arrived leave the origin hub.

        Returns the ids of shipments that boarded, so E1 can score them.
        """
        boarded: List[int] = []
        due = db.scalars(
            select(Leg).where(
                # A delayed leg still departs, at its new departure time.
                Leg.status.in_([LegStatus.SCHEDULED.value, LegStatus.DELAYED.value]),
                Leg.departure_at <= now,
            )
        ).all()

        for leg in due:
            leg.status = LegStatus.DEPARTED.value

            vehicle = db.get(Vehicle, leg.vehicle_id)
            if vehicle is not None:
                vehicle.status = VehicleStatus.EN_ROUTE.value

            for link in leg.shipment_links:
                link.is_aboard = True
                link.boarded_at = now

                shipment = db.get(Shipment, link.shipment_id)
                if shipment is not None and shipment.status in {
                    ShipmentStatus.PENDING.value,
                    ShipmentStatus.RECOVERING.value,
                }:
                    shipment.status = ShipmentStatus.IN_TRANSIT.value
                    # In transit: not resident at any hub.
                    shipment.current_hub_id = None
                    boarded.append(shipment.id)

            result.departed_legs += 1

        return boarded

    def _score_departed(self, db: Session, shipment_ids: List[int], now) -> int:
        """E1 scores shipments as they go in flight (SH.docx §7.2, §10.3).

        Without this no shipment ever receives P(misplace), leaving E3 hub
        candidates and the risk fallbacks empty. Batched, skipped when E1 is
        not loaded, and never raises - the tick must not depend on the model
        being ready.
        """
        if not shipment_ids:
            return 0
        try:
            from app.engines.e1_misplacement.registry import get_registry
            from app.engines.e1_misplacement.service import features_for_shipment

            registry = get_registry()
            if not registry.is_loaded:
                return 0

            hubs = {hub.id: hub for hub in db.scalars(select(Hub)).all()}
            shipments = [db.get(Shipment, sid) for sid in shipment_ids]
            shipments = [s for s in shipments
                         if s is not None and s.origin_hub_id in hubs and s.dest_hub_id in hubs]
            rows = [
                features_for_shipment(
                    s, origin=hubs[s.origin_hub_id], dest=hubs[s.dest_hub_id], at=now,
                ).as_row()
                for s in shipments
            ]
            for shipment, probability in zip(shipments, registry.predict_batch(rows)):
                shipment.p_misplace = probability
            db.commit()
            return len(shipments)
        except Exception:  # noqa: BLE001 - scoring must never break a tick
            db.rollback()
            logger.exception("E1 scoring of departed shipments failed")
            return 0

    def _arrive_legs(self, db: Session, now, result: TickResult) -> None:
        """Legs whose arrival time has passed drop their load at the hub."""
        due = db.scalars(
            select(Leg).where(
                Leg.status == LegStatus.DEPARTED.value,
                Leg.arrival_at <= now,
            )
        ).all()

        for leg in due:
            leg.status = LegStatus.ARRIVED.value

            vehicle = db.get(Vehicle, leg.vehicle_id)
            destination = db.get(Hub, leg.to_hub_id)
            if vehicle is not None:
                vehicle.status = VehicleStatus.IDLE.value
                vehicle.current_hub_id = leg.to_hub_id
                if destination is not None:
                    vehicle.current_lat = destination.lat
                    vehicle.current_lng = destination.lng

            for link in leg.shipment_links:
                if not link.is_aboard:
                    continue

                link.is_aboard = False
                link.alighted_at = now

                shipment = db.get(Shipment, link.shipment_id)
                if shipment is None:
                    continue

                shipment.current_hub_id = leg.to_hub_id
                result.shipments_moved += 1

                # Capacity is returned to the leg once the load is off.
                leg.residual_kg = min(
                    leg.capacity_kg, leg.residual_kg + shipment.weight_kg
                )
                leg.residual_m3 = min(
                    leg.capacity_m3, leg.residual_m3 + shipment.volume_m3
                )

                if shipment.dest_hub_id == leg.to_hub_id:
                    shipment.status = ShipmentStatus.DELIVERED.value
                    shipment.delivered_at = now
                    result.shipments_delivered += 1
                    result.events.append(f"{shipment.code} delivered")
                    if link.is_recovery:
                        # Closes Plan -> Prove: plan COMPLETED + E9 outcome.
                        from app.services.booking import complete_recovery

                        complete_recovery(db, shipment, now)

            result.arrived_legs += 1

    def _mark_overdue(self, db: Session, now, result: TickResult) -> None:
        """Counts shipments past their deadline but not yet delivered."""
        result.shipments_overdue = (
            db.scalar(
                select(func.count())
                .select_from(Shipment)
                .where(
                    Shipment.deadline_at < now,
                    Shipment.status.notin_(
                        [
                            ShipmentStatus.DELIVERED.value,
                            ShipmentStatus.FAILED.value,
                        ]
                    ),
                )
            )
            or 0
        )

    # --- assignment ------------------------------------------------------

    def assign_shipment_to_leg(
        self,
        db: Session,
        shipment: Shipment,
        leg: Leg,
        *,
        seq: int = 0,
        is_recovery: bool = False,
    ) -> ShipmentLeg:
        """Books a shipment onto a leg, consuming its residual capacity.

        Raises ``ValueError`` when the leg cannot take the load — capacity is
        a hard constraint for E6, so it is enforced at the point of booking
        rather than discovered later.
        """
        if not leg.can_fit(shipment.weight_kg, shipment.volume_m3):
            raise ValueError(
                f"Leg {leg.id} cannot fit shipment {shipment.code}: "
                f"needs {shipment.weight_kg}kg/{shipment.volume_m3}m3, "
                f"residual {leg.residual_kg}kg/{leg.residual_m3}m3"
            )

        leg.residual_kg = round(leg.residual_kg - shipment.weight_kg, 3)
        leg.residual_m3 = round(leg.residual_m3 - shipment.volume_m3, 3)

        link = ShipmentLeg(
            shipment_id=shipment.id,
            leg_id=leg.id,
            seq=seq,
            is_recovery=is_recovery,
        )
        db.add(link)
        db.commit()
        return link

    # --- disruption ------------------------------------------------------

    def inject_disruption(
        self,
        db: Session,
        disruption_type: DisruptionType,
        target_id: Optional[int] = None,
        *,
        delay_hours: float = 4.0,
    ) -> DisruptionResult:
        """Injects a disruption — the trigger for the whole recovery demo."""
        if disruption_type is DisruptionType.MISPLACE_SHIPMENT:
            return self._misplace_shipment(db, target_id)
        if disruption_type is DisruptionType.DELAY_VEHICLE:
            return self._delay_vehicle(db, target_id, delay_hours)
        if disruption_type is DisruptionType.CLOSE_HUB:
            return self._close_hub(db, target_id)

        raise ValueError(f"Unknown disruption type: {disruption_type}")

    def _misplace_shipment(
        self, db: Session, shipment_id: Optional[int]
    ) -> DisruptionResult:
        if shipment_id is None:
            shipment = db.scalars(
                select(Shipment)
                .where(
                    Shipment.status.in_(
                        [
                            ShipmentStatus.PENDING.value,
                            ShipmentStatus.IN_TRANSIT.value,
                        ]
                    )
                )
                .limit(1)
            ).first()
        else:
            shipment = db.get(Shipment, shipment_id)

        if shipment is None:
            raise ValueError("No eligible shipment to misplace")

        shipment.status = ShipmentStatus.MISPLACED.value
        shipment.misplaced_at = self.clock.now

        # Its future (not yet boarded) bookings are void: release them, or
        # the shipment would still "depart" on its old itinerary.
        from app.services.booking import release_pending_bookings

        release_pending_bookings(db, shipment)

        # Taken off whatever was carrying it, and its capacity released.
        for link in shipment.legs:
            if link.is_aboard:
                link.is_aboard = False
                leg = db.get(Leg, link.leg_id)
                if leg is not None:
                    leg.residual_kg = min(
                        leg.capacity_kg, leg.residual_kg + shipment.weight_kg
                    )
                    leg.residual_m3 = min(
                        leg.capacity_m3, leg.residual_m3 + shipment.volume_m3
                    )

        db.commit()
        logger.info("Disruption: shipment %s misplaced", shipment.code)

        publish(
            EventType.DISRUPTION,
            {
                "type": DisruptionType.MISPLACE_SHIPMENT.value,
                "shipment_id": shipment.id,
                "shipment_code": shipment.code,
            },
            at=self.clock.now,
        )

        return DisruptionResult(
            type=DisruptionType.MISPLACE_SHIPMENT.value,
            target_id=shipment.id,
            affected_shipments=[shipment.id],
            detail=f"Shipment {shipment.code} marked MISPLACED",
        )

    def _delay_vehicle(
        self, db: Session, vehicle_id: Optional[int], delay_hours: float
    ) -> DisruptionResult:
        if vehicle_id is None:
            vehicle = db.scalars(select(Vehicle).limit(1)).first()
        else:
            vehicle = db.get(Vehicle, vehicle_id)

        if vehicle is None:
            raise ValueError("No eligible vehicle to delay")

        now = self.clock.now
        pending = db.scalars(
            select(Leg).where(
                Leg.vehicle_id == vehicle.id,
                Leg.status.in_(
                    [LegStatus.SCHEDULED.value, LegStatus.DEPARTED.value]
                ),
                Leg.arrival_at >= now,
            )
        ).all()

        affected_shipments: List[int] = []
        for leg in pending:
            leg.arrival_at = leg.arrival_at + timedelta(hours=delay_hours)
            if leg.status == LegStatus.SCHEDULED.value:
                leg.departure_at = leg.departure_at + timedelta(hours=delay_hours)
                # Only a not-yet-departed leg becomes DELAYED. A leg already
                # on the road keeps DEPARTED (with its later arrival), or it
                # would never be picked up by _arrive_legs again.
                leg.status = LegStatus.DELAYED.value
            affected_shipments.extend(
                link.shipment_id for link in leg.shipment_links
            )

        db.commit()
        logger.info(
            "Disruption: vehicle %s delayed %.1fh across %d legs",
            vehicle.code, delay_hours, len(pending),
        )

        publish(
            EventType.DISRUPTION,
            {
                "type": DisruptionType.DELAY_VEHICLE.value,
                "vehicle_id": vehicle.id,
                "vehicle_code": vehicle.code,
                "delay_hours": delay_hours,
                "legs_affected": len(pending),
            },
            at=now,
        )

        return DisruptionResult(
            type=DisruptionType.DELAY_VEHICLE.value,
            target_id=vehicle.id,
            affected_shipments=affected_shipments,
            affected_legs=[leg.id for leg in pending],
            detail=f"Vehicle {vehicle.code} delayed {delay_hours}h",
        )

    def _close_hub(self, db: Session, hub_id: Optional[int]) -> DisruptionResult:
        if hub_id is None:
            hub = db.scalars(select(Hub).where(Hub.is_active.is_(True)).limit(1)).first()
        else:
            hub = db.get(Hub, hub_id)

        if hub is None:
            raise ValueError("No eligible hub to close")

        hub.is_active = False
        now = self.clock.now

        cancelled = db.scalars(
            select(Leg).where(
                Leg.status == LegStatus.SCHEDULED.value,
                Leg.departure_at >= now,
                (Leg.from_hub_id == hub.id) | (Leg.to_hub_id == hub.id),
            )
        ).all()

        affected_shipments: List[int] = []
        for leg in cancelled:
            leg.status = LegStatus.CANCELLED.value
            for link in leg.shipment_links:
                affected_shipments.append(link.shipment_id)
                shipment = db.get(Shipment, link.shipment_id)
                if shipment is not None and shipment.status != ShipmentStatus.DELIVERED.value:
                    shipment.status = ShipmentStatus.MISPLACED.value
                    shipment.misplaced_at = now

        db.commit()
        logger.info(
            "Disruption: hub %s closed, %d legs cancelled", hub.code, len(cancelled)
        )

        publish(
            EventType.DISRUPTION,
            {
                "type": DisruptionType.CLOSE_HUB.value,
                "hub_id": hub.id,
                "hub_code": hub.code,
                "legs_cancelled": len(cancelled),
            },
            at=now,
        )

        return DisruptionResult(
            type=DisruptionType.CLOSE_HUB.value,
            target_id=hub.id,
            affected_shipments=affected_shipments,
            affected_legs=[leg.id for leg in cancelled],
            detail=f"Hub {hub.code} closed, {len(cancelled)} legs cancelled",
        )

    # --- introspection ---------------------------------------------------

    def state(self, db: Session) -> Dict[str, Any]:
        """Counts by status — what the dashboard header shows."""
        snapshot = self.clock.snapshot()

        status_counts = dict(
            db.execute(
                select(Shipment.status, func.count()).group_by(Shipment.status)
            ).all()
        )
        leg_counts = dict(
            db.execute(select(Leg.status, func.count()).group_by(Leg.status)).all()
        )

        return {
            "tick": snapshot.tick,
            "now": snapshot.now.isoformat(),
            "tick_minutes": snapshot.tick_minutes,
            "elapsed_hours": snapshot.elapsed_hours,
            "seed": self.spec.seed,
            "hubs": db.scalar(select(func.count()).select_from(Hub)) or 0,
            "vehicles": db.scalar(select(func.count()).select_from(Vehicle)) or 0,
            "shipments": db.scalar(select(func.count()).select_from(Shipment)) or 0,
            "legs": db.scalar(select(func.count()).select_from(Leg)) or 0,
            "shipment_status": status_counts,
            "leg_status": leg_counts,
        }


_simulator: Optional[Simulator] = None


def get_simulator() -> Simulator:
    """Returns the process-wide simulator."""
    global _simulator
    if _simulator is None:
        _simulator = Simulator()
    return _simulator


def reset_simulator() -> None:
    """Drops the cached simulator. Test-support only."""
    global _simulator
    _simulator = None
