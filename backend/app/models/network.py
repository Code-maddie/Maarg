"""Physical network entities: hubs, vehicles and legs."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import LegStatus, VehicleStatus, VehicleType


class Hub(Base, TimestampMixin):
    """A sorting/transfer facility in the network."""

    __tablename__ = "hubs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))

    # Stored as plain columns rather than a PostGIS geometry so the schema
    # runs on SQLite; app.core.geo provides the ST_DWithin equivalent.
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)

    capacity_kg: Mapped[float] = mapped_column(Float, default=10000.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # True for hubs created by approving an E3 Hub Emergence candidate.
    is_emergent: Mapped[bool] = mapped_column(Boolean, default=False)

    outbound_legs: Mapped[List["Leg"]] = relationship(
        back_populates="from_hub", foreign_keys="Leg.from_hub_id"
    )
    inbound_legs: Mapped[List["Leg"]] = relationship(
        back_populates="to_hub", foreign_keys="Leg.to_hub_id"
    )

    __table_args__ = (Index("ix_hubs_location", "lat", "lng"),)

    def __repr__(self) -> str:
        return f"<Hub {self.code} ({self.lat:.4f}, {self.lng:.4f})>"


class Vehicle(Base, TimestampMixin):
    """A truck, owned or third-party, that can carry shipments."""

    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    vehicle_type: Mapped[str] = mapped_column(
        String(16), default=VehicleType.OWNED.value
    )
    status: Mapped[str] = mapped_column(String(16), default=VehicleStatus.IDLE.value)

    capacity_kg: Mapped[float] = mapped_column(Float, default=500.0)
    capacity_m3: Mapped[float] = mapped_column(Float, default=20.0)

    # E5 uses this to weight bids; E6 uses it in plan scoring.
    reliability: Mapped[float] = mapped_column(Float, default=0.9)
    cost_per_km: Mapped[float] = mapped_column(Float, default=25.0)

    current_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    current_lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    current_hub_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("hubs.id", ondelete="SET NULL"), nullable=True
    )

    legs: Mapped[List["Leg"]] = relationship(
        back_populates="vehicle", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Vehicle {self.code} {self.vehicle_type}>"


class Leg(Base, TimestampMixin):
    """One scheduled vehicle movement between two hubs.

    Legs are the edges of the time-expanded graph that E6 searches, and the
    unit the frontend renders as a clickable polyline (SH.docx §6).
    """

    __tablename__ = "legs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), index=True
    )
    from_hub_id: Mapped[int] = mapped_column(
        ForeignKey("hubs.id", ondelete="RESTRICT"), index=True
    )
    to_hub_id: Mapped[int] = mapped_column(
        ForeignKey("hubs.id", ondelete="RESTRICT"), index=True
    )

    departure_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    arrival_at: Mapped[datetime] = mapped_column(DateTime, index=True)

    capacity_kg: Mapped[float] = mapped_column(Float, default=500.0)
    residual_kg: Mapped[float] = mapped_column(Float, default=500.0)
    capacity_m3: Mapped[float] = mapped_column(Float, default=20.0)
    residual_m3: Mapped[float] = mapped_column(Float, default=20.0)

    # Edge weight inputs for w(e) = C_transit + lambda*hours + handling (SH.docx §16).
    transit_cost: Mapped[float] = mapped_column(Float, default=0.0)
    handling_penalty: Mapped[float] = mapped_column(Float, default=0.0)
    distance_km: Mapped[float] = mapped_column(Float, default=0.0)

    status: Mapped[str] = mapped_column(String(16), default=LegStatus.SCHEDULED.value)

    # Encoded polyline for map rendering.
    polyline: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    vehicle: Mapped["Vehicle"] = relationship(back_populates="legs")
    shipment_links: Mapped[List["ShipmentLeg"]] = relationship(
        back_populates="leg", cascade="all, delete-orphan"
    )
    from_hub: Mapped["Hub"] = relationship(
        back_populates="outbound_legs", foreign_keys=[from_hub_id]
    )
    to_hub: Mapped["Hub"] = relationship(
        back_populates="inbound_legs", foreign_keys=[to_hub_id]
    )

    @property
    def transit_hours(self) -> float:
        return max(0.0, (self.arrival_at - self.departure_at).total_seconds() / 3600.0)

    def can_fit(self, weight_kg: float, volume_m3: float) -> bool:
        """Capacity feasibility check used by E6."""
        return self.residual_kg >= weight_kg and self.residual_m3 >= volume_m3

    def __repr__(self) -> str:
        return f"<Leg {self.id} hub{self.from_hub_id}->hub{self.to_hub_id}>"
