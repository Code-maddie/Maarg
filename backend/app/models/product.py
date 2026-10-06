"""Product-layer tables from SH.docx §8.1: auth, policy, audit, registry."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

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
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, utcnow
from app.models.enums import CandidateStatus, PolicyModeName, UserRole


class User(Base, TimestampMixin):
    """An application user, authenticated by Firebase.

    The role here mirrors the Firebase custom claim. The claim is the source
    of truth and is re-verified server-side on every request (SH.docx §12);
    this row exists so the UI can list and manage users.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    firebase_uid: Mapped[Optional[str]] = mapped_column(
        String(128), unique=True, index=True, nullable=True
    )
    role: Mapped[str] = mapped_column(String(16), default=UserRole.CUSTOMER.value)

    # Set only for DRIVER users.
    vehicle_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:
        return f"<User {self.email} {self.role}>"


class AuditLog(Base):
    """Immutable record of every destructive or overriding action.

    Has no TimestampMixin on purpose: audit rows are never updated, so an
    ``updated_at`` column would be misleading.
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(32), index=True)

    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    reason_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, index=True
    )

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} {self.target_type}:{self.target_id}>"


class PolicyMode(Base, TimestampMixin):
    """Singleton row holding the active policy dial and its E4 weights."""

    __tablename__ = "policy_modes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(
        String(16), default=PolicyModeName.BUSINESS.value
    )

    # Coefficients consumed by E4 when computing T_base. JSON text rather than
    # a JSON column so the schema is identical on SQLite and PostgreSQL.
    weights_json: Mapped[str] = mapped_column(Text, default="{}")

    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:
        return f"<PolicyMode {self.mode}>"


class HubCandidate(Base, TimestampMixin):
    """An E3 Hub Emergence proposal, persisted for admin review.

    HubScore(L) = usage_count(L, 30d) x mean_risk(cell(L))  — SH.docx §16.
    """

    __tablename__ = "hub_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)

    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    mean_risk: Mapped[float] = mapped_column(Float, default=0.0)
    hub_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)

    est_setup_cost: Mapped[float] = mapped_column(Float, default=0.0)
    est_annual_savings: Mapped[float] = mapped_column(Float, default=0.0)

    status: Mapped[str] = mapped_column(
        String(16), default=CandidateStatus.PENDING.value, index=True
    )

    # Set once an admin approves and the hub is created.
    approved_hub_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("hubs.id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:
        return f"<HubCandidate {self.id} score={self.hub_score:.2f} {self.status}>"


class ModelArtifact(Base, TimestampMixin):
    """A trained model version the ModelRegistry can load (SH.docx §10.3).

    Exactly one row per ``name`` may have ``is_active`` set; the registry's
    reload endpoint swaps which one that is.
    """

    __tablename__ = "model_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(32))

    # Local directory holding model.pkl + feature_pipeline.joblib.
    storage_path: Mapped[str] = mapped_column(String(512))

    trained_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_artifact_name_version"),
    )

    def __repr__(self) -> str:
        active = " ACTIVE" if self.is_active else ""
        return f"<ModelArtifact {self.name} {self.version}{active}>"
