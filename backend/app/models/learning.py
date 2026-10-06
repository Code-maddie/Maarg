"""E9 — Recovery outcome records.

Each completed (or failed) recovery writes one row
capturing what was predicted against what actually happened, so a future
retraining run has ground truth to learn from.

E9 is an extension: it observes E1–E8 and never alters their behaviour.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class RecoveryOutcome(Base, TimestampMixin):
    """Predicted versus actual for one recovery attempt."""

    __tablename__ = "recovery_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), index=True
    )
    plan_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("recovery_plans.id", ondelete="SET NULL"), nullable=True
    )

    strategy: Mapped[str] = mapped_column(String(16))
    succeeded: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # --- what the engines predicted -------------------------------------
    predicted_cost: Mapped[float] = mapped_column(Float, default=0.0)
    predicted_arrival: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    predicted_p_misplace: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    predicted_temperature: Mapped[float] = mapped_column(Float, default=0.0)
    predicted_lambda: Mapped[float] = mapped_column(Float, default=0.0)

    # --- what actually happened ------------------------------------------
    actual_cost: Mapped[float] = mapped_column(Float, default=0.0)
    actual_arrival: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    actually_misplaced: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- derived errors ---------------------------------------------------
    # actual - predicted; positive means the engine under-estimated.
    cost_error: Mapped[float] = mapped_column(Float, default=0.0)
    eta_error_hours: Mapped[float] = mapped_column(Float, default=0.0)

    # Brier contribution for this observation: (p - outcome)^2.
    # Averaging this column over many rows gives E1's live Brier score.
    risk_brier: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    met_deadline: Mapped[bool] = mapped_column(Boolean, default=False)
    recovery_seconds: Mapped[float] = mapped_column(Float, default=0.0)

    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        status = "ok" if self.succeeded else "failed"
        return f"<RecoveryOutcome s={self.shipment_id} {self.strategy} {status}>"
