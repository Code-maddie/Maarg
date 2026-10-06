"""Shipment entity — the thing that gets misplaced and recovered."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import ShipmentStatus, TemperatureZone


class Shipment(Base, TimestampMixin):
    """A parcel moving through the network.

    Carries the live engine outputs (``p_misplace`` from E1, ``temperature``
    and ``lam`` from E4, plus the recovery pressure score) so the dispatcher queue can
    be sorted without recomputing them on every request.
    """

    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)

    origin_hub_id: Mapped[int] = mapped_column(
        ForeignKey("hubs.id", ondelete="RESTRICT"), index=True
    )
    dest_hub_id: Mapped[int] = mapped_column(
        ForeignKey("hubs.id", ondelete="RESTRICT"), index=True
    )
    current_hub_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("hubs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    weight_kg: Mapped[float] = mapped_column(Float, default=10.0)
    volume_m3: Mapped[float] = mapped_column(Float, default=0.1)

    status: Mapped[str] = mapped_column(
        String(16), default=ShipmentStatus.PENDING.value, index=True
    )

    deadline_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    misplaced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # --- Engine outputs -------------------------------------------------
    # E1: calibrated P(misplace), null until scored.
    p_misplace: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # E4: T(s) in [0,100] and lambda in rupees/hour.
    temperature: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    lam: Mapped[float] = mapped_column(Float, default=0.0)

    # Recovery Pressure Score in [0,1].
    pressure: Mapped[float] = mapped_column(Float, default=0.0)

    # How many cascade hops from the originating disruption.
    cascade_depth: Mapped[int] = mapped_column(Integer, default=0)

    # SLA inputs feeding lambda (SH.docx §16).
    sla_penalty_per_hour: Mapped[float] = mapped_column(Float, default=100.0)
    base_priority: Mapped[float] = mapped_column(Float, default=1.0)

    # Customer "pay to expedite" input (SH.docx §4.4) — raises lambda, never
    # overrides the engine's decision.
    customer_premium: Mapped[float] = mapped_column(Float, default=0.0)

    recovery_plans: Mapped[List["RecoveryPlan"]] = relationship(
        back_populates="shipment", cascade="all, delete-orphan"
    )
    legs: Mapped[List["ShipmentLeg"]] = relationship(
        back_populates="shipment",
        cascade="all, delete-orphan",
        order_by="ShipmentLeg.seq",
    )

    @property
    def temperature_zone(self) -> TemperatureZone:
        """Display banding used by the dispatcher queue."""
        if self.temperature >= 67:
            return TemperatureZone.HOT
        if self.temperature >= 34:
            return TemperatureZone.WARMING
        return TemperatureZone.COLD

    def hours_to_deadline(self, now: datetime) -> float:
        """Signed hours remaining; negative once the deadline has passed."""
        return (self.deadline_at - now).total_seconds() / 3600.0

    def __repr__(self) -> str:
        return f"<Shipment {self.code} {self.status} T={self.temperature:.1f}>"
