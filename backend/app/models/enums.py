"""Enumerations shared across the schema.

All of these are stored as plain strings rather than native database enums,
so the schema stays portable between SQLite and PostgreSQL and values can be
added without a type migration.
"""

from enum import StrEnum


class ShipmentStatus(StrEnum):
    PENDING = "PENDING"
    IN_TRANSIT = "IN_TRANSIT"
    MISPLACED = "MISPLACED"
    RECOVERING = "RECOVERING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class TemperatureZone(StrEnum):
    """Display banding for Temperature, per SH.docx §5.2."""

    COLD = "COLD"
    WARMING = "WARMING"
    HOT = "HOT"


class VehicleType(StrEnum):
    OWNED = "OWNED"
    THIRD_PARTY = "THIRD_PARTY"


class VehicleStatus(StrEnum):
    IDLE = "IDLE"
    EN_ROUTE = "EN_ROUTE"
    LOADING = "LOADING"
    OFFLINE = "OFFLINE"


class LegStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    DEPARTED = "DEPARTED"
    ARRIVED = "ARRIVED"
    CANCELLED = "CANCELLED"
    DELAYED = "DELAYED"


class PlanStrategy(StrEnum):
    """Recovery strategy badges, per SH.docx §5.2."""

    PIGGYBACK = "PIGGYBACK"
    HYBRID = "HYBRID"
    DEDICATED = "DEDICATED"
    PRE_RESERVED = "PRE_RESERVED"


class PlanStatus(StrEnum):
    PROPOSED = "PROPOSED"
    COMMITTED = "COMMITTED"
    REJECTED = "REJECTED"
    OVERRIDDEN = "OVERRIDDEN"
    COMPLETED = "COMPLETED"


class AuctionStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    AWARDED = "AWARDED"
    NO_BIDS = "NO_BIDS"


class PolicyModeName(StrEnum):
    """Admin policy dial, per SH.docx §5.1."""

    BUSINESS = "BUSINESS"
    SLA_STRICT = "SLA_STRICT"
    FAIRNESS = "FAIRNESS"
    EFFICIENCY = "EFFICIENCY"


class CandidateStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class UserRole(StrEnum):
    ADMIN = "ADMIN"
    DISPATCHER = "DISPATCHER"
    DRIVER = "DRIVER"
    CUSTOMER = "CUSTOMER"


class AuditAction(StrEnum):
    OVERRIDE_PLAN = "OVERRIDE_PLAN"
    APPROVE_HUB = "APPROVE_HUB"
    REJECT_HUB = "REJECT_HUB"
    CHANGE_POLICY_MODE = "CHANGE_POLICY_MODE"
    RELOAD_MODEL = "RELOAD_MODEL"
    INJECT_DISRUPTION = "INJECT_DISRUPTION"
    SET_USER_ROLE = "SET_USER_ROLE"
