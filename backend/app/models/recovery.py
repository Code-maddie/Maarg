"""Recovery plans and their ordered paths, plus the bounty auction tables."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import AuctionStatus, PlanStatus, PlanStrategy


class RecoveryPlan(Base, TimestampMixin):
    """One candidate recovery for a misplaced shipment.

    E6 produces k of these per shipment; the best-ranked one is proposed and
    the rest are retained so E8 can explain why they lost.
    """

    __tablename__ = "recovery_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), index=True
    )

    strategy: Mapped[str] = mapped_column(
        String(16), default=PlanStrategy.PIGGYBACK.value
    )
    status: Mapped[str] = mapped_column(
        String(16), default=PlanStatus.PROPOSED.value, index=True
    )

    # Rank 1 is the engine's top pick; the dispatcher may override to another.
    rank: Mapped[int] = mapped_column(Integer, default=1)
    score: Mapped[float] = mapped_column(Float, default=0.0)

    total_cost: Mapped[float] = mapped_column(Float, default=0.0)
    bounty_cost: Mapped[float] = mapped_column(Float, default=0.0)
    eta: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    transit_hours: Mapped[float] = mapped_column(Float, default=0.0)

    # Set when E6 discards a candidate; consumed verbatim by E8 so the
    # explainer never shows a placeholder reason.
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Milliseconds E6 spent producing this plan — surfaced as the UI's
    # "re-plan latency" figure (SH.docx §15).
    compute_ms: Mapped[float] = mapped_column(Float, default=0.0)
    warm_started: Mapped[bool] = mapped_column(Boolean, default=False)

    shipment: Mapped["Shipment"] = relationship(back_populates="recovery_plans")
    paths: Mapped[List["RecoveryPath"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="RecoveryPath.seq",
    )

    def __repr__(self) -> str:
        return f"<RecoveryPlan {self.id} {self.strategy} rank={self.rank}>"


class RecoveryPath(Base, TimestampMixin):
    """One ordered hop of a recovery plan."""

    __tablename__ = "recovery_paths"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("recovery_plans.id", ondelete="CASCADE"), index=True
    )

    # Position within the plan, starting at 0.
    seq: Mapped[int] = mapped_column(Integer)

    leg_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("legs.id", ondelete="SET NULL"), nullable=True
    )
    from_hub_id: Mapped[int] = mapped_column(ForeignKey("hubs.id", ondelete="RESTRICT"))
    to_hub_id: Mapped[int] = mapped_column(ForeignKey("hubs.id", ondelete="RESTRICT"))

    departure_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    arrival_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    edge_cost: Mapped[float] = mapped_column(Float, default=0.0)

    plan: Mapped["RecoveryPlan"] = relationship(back_populates="paths")

    __table_args__ = (UniqueConstraint("plan_id", "seq", name="uq_path_plan_seq"),)

    def __repr__(self) -> str:
        return f"<RecoveryPath plan={self.plan_id} seq={self.seq}>"


class Auction(Base, TimestampMixin):
    """An E5 reverse auction for one recovery leg.

    Vickrey: the lowest bidder wins and is paid the second-lowest bid, capped
    at MaxBounty (SH.docx §16).
    """

    __tablename__ = "auctions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), index=True
    )
    plan_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("recovery_plans.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[str] = mapped_column(
        String(16), default=AuctionStatus.OPEN.value, index=True
    )
    max_bounty: Mapped[float] = mapped_column(Float, default=0.0)

    opened_at: Mapped[datetime] = mapped_column(DateTime)
    closes_at: Mapped[datetime] = mapped_column(DateTime)

    winning_vehicle_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True
    )
    payment: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    bids: Mapped[List["Bid"]] = relationship(
        back_populates="auction", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Auction {self.id} {self.status} max={self.max_bounty:.0f}>"


class Bid(Base, TimestampMixin):
    """One vehicle's ask for carrying a recovery leg."""

    __tablename__ = "bids"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    auction_id: Mapped[int] = mapped_column(
        ForeignKey("auctions.id", ondelete="CASCADE"), index=True
    )
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), index=True
    )

    amount: Mapped[float] = mapped_column(Float)
    detour_km: Mapped[float] = mapped_column(Float, default=0.0)
    is_winner: Mapped[bool] = mapped_column(Boolean, default=False)

    auction: Mapped["Auction"] = relationship(back_populates="bids")

    __table_args__ = (
        # A vehicle bids at most once per auction.
        UniqueConstraint("auction_id", "vehicle_id", name="uq_bid_auction_vehicle"),
    )

    def __repr__(self) -> str:
        return f"<Bid {self.amount:.0f} v={self.vehicle_id}>"
