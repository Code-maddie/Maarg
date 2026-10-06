"""Association between shipments and the legs that carry them.

SH.docx §6.1 requires the leg info panel to list the
"shipments currently aboard", and the simulator needs somewhere to record
which shipment is riding which vehicle movement.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class ShipmentLeg(Base, TimestampMixin):
    """One shipment travelling on one leg."""

    __tablename__ = "shipment_legs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), index=True
    )
    leg_id: Mapped[int] = mapped_column(
        ForeignKey("legs.id", ondelete="CASCADE"), index=True
    )

    # Position in the shipment's journey, starting at 0.
    seq: Mapped[int] = mapped_column(Integer, default=0)

    boarded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    alighted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # True once the shipment has physically left the origin hub on this leg.
    is_aboard: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # True when this assignment came from a recovery plan rather than the
    # shipment's original itinerary.
    is_recovery: Mapped[bool] = mapped_column(Boolean, default=False)

    shipment: Mapped["Shipment"] = relationship(back_populates="legs")
    leg: Mapped["Leg"] = relationship(back_populates="shipment_links")

    __table_args__ = (
        UniqueConstraint("shipment_id", "leg_id", name="uq_shipment_leg"),
    )

    def __repr__(self) -> str:
        return f"<ShipmentLeg s={self.shipment_id} leg={self.leg_id}>"
