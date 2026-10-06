"""Database models.

Importing this package registers every table on ``Base.metadata``, which is
what ``init_db()`` and Alembic autogenerate rely on.
"""

from app.models.base import Base, TimestampMixin, utcnow
from app.models.enums import (
    AuctionStatus,
    AuditAction,
    CandidateStatus,
    LegStatus,
    PlanStatus,
    PlanStrategy,
    PolicyModeName,
    ShipmentStatus,
    TemperatureZone,
    UserRole,
    VehicleStatus,
    VehicleType,
)
from app.models.learning import RecoveryOutcome
from app.models.network import Hub, Leg, Vehicle
from app.models.product import (
    AuditLog,
    HubCandidate,
    ModelArtifact,
    PolicyMode,
    User,
)
from app.models.recovery import Auction, Bid, RecoveryPath, RecoveryPlan
from app.models.shipment import Shipment
from app.models.simulation import ShipmentLeg

__all__ = [
    "Base",
    "TimestampMixin",
    "utcnow",
    # enums
    "AuctionStatus",
    "AuditAction",
    "CandidateStatus",
    "LegStatus",
    "PlanStatus",
    "PlanStrategy",
    "PolicyModeName",
    "ShipmentStatus",
    "TemperatureZone",
    "UserRole",
    "VehicleStatus",
    "VehicleType",
    # tables
    "Hub",
    "Vehicle",
    "Leg",
    "Shipment",
    "RecoveryPlan",
    "RecoveryPath",
    "ShipmentLeg",
    "RecoveryOutcome",
    "Auction",
    "Bid",
    "User",
    "AuditLog",
    "PolicyMode",
    "HubCandidate",
    "ModelArtifact",
]
