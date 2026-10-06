"""Response/request schemas for the documented REST surface (SH.docx §9).

Field names are chosen to map cleanly onto what the frontend's `data.js`
already consumes, so going live is a data-source swap rather than a UI
rewrite.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# --- shipments -----------------------------------------------------------

class ShipmentSummary(BaseModel):
    """Row in the dispatcher's misplaced-shipment queue."""

    id: int
    code: str
    status: str
    origin_hub: Optional[str] = None
    dest_hub: Optional[str] = None
    current_hub: Optional[str] = None
    weight_kg: float
    volume_m3: float
    deadline_at: Optional[datetime] = None
    temperature: float
    zone: str
    lam: float = Field(..., description="Rupees per hour.")
    pressure: float
    emergency: bool = False
    p_misplace: Optional[float] = None
    cascade_depth: int = 0

    model_config = ConfigDict(from_attributes=True)


class ShipmentDetail(ShipmentSummary):
    misplaced_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    sla_penalty_per_hour: float
    base_priority: float
    customer_premium: float
    hours_to_deadline: Optional[float] = None


class ShipmentList(BaseModel):
    total: int
    items: List[ShipmentSummary]


# --- recovery plans ------------------------------------------------------

class PathStep(BaseModel):
    seq: int
    leg_id: Optional[int] = None
    from_hub: str
    to_hub: str
    departure_at: Optional[datetime] = None
    arrival_at: Optional[datetime] = None
    edge_cost: float


class RecoveryPlanOut(BaseModel):
    id: int
    shipment_id: int
    strategy: str
    status: str
    rank: int
    score: float
    total_cost: float
    bounty_cost: float
    eta: Optional[datetime] = None
    transit_hours: float
    compute_ms: float
    warm_started: bool
    rejection_reason: Optional[str] = None
    path: List[PathStep] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class RecoveryPlanBundle(BaseModel):
    """The committed plan plus every alternative, for the detail panel."""

    shipment_id: int
    shipment_code: str
    committed: Optional[RecoveryPlanOut] = None
    alternatives: List[RecoveryPlanOut] = Field(default_factory=list)
    rejected: List[RecoveryPlanOut] = Field(default_factory=list)


class OverrideRequest(BaseModel):
    """`POST /shipments/{id}/override` — dispatcher picks another plan."""

    chosen_plan_id: int
    reason: str = Field(..., min_length=3, max_length=500)


class OverrideResponse(BaseModel):
    shipment_id: int
    previous_plan_id: Optional[int] = None
    chosen_plan_id: int
    audit_log_id: int


# --- vehicles and legs ---------------------------------------------------

class VehicleOut(BaseModel):
    id: int
    code: str
    vehicle_type: str
    status: str
    capacity_kg: float
    capacity_m3: float
    reliability: float
    cost_per_km: float
    current_hub: Optional[str] = None
    current_lat: Optional[float] = None
    current_lng: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class AboardShipment(BaseModel):
    """A shipment riding a leg, as the route info panel shows it."""

    code: str
    weight_kg: float
    temperature: float
    zone: str
    lam: float


class LegDetail(BaseModel):
    """`GET /legs/{id}` — the click-a-route info panel (SH.docx §6.2)."""

    id: int
    vehicle_code: str
    vehicle_type: str
    reliability: float
    from_hub: str
    to_hub: str
    from_lat: float
    from_lng: float
    to_lat: float
    to_lng: float
    departure_at: datetime
    arrival_at: datetime
    capacity_kg: float
    residual_kg: float
    capacity_m3: float
    residual_m3: float
    distance_km: float
    status: str
    aboard: List[AboardShipment] = Field(default_factory=list)
    bounty: Optional["BountyStatus"] = None
    # Curve geometry, as points and as a Google encoded polyline.
    path: List[List[float]] = Field(default_factory=list)
    polyline: Optional[str] = None


class BountyStatus(BaseModel):
    """`GET /legs/{id}/bounty-status`."""

    auction_id: Optional[int] = None
    status: str
    max_bounty: float = 0.0
    best_bid: Optional[float] = None
    bid_count: int = 0
    closes_at: Optional[datetime] = None
    seconds_remaining: Optional[float] = None


# --- hubs ----------------------------------------------------------------

class HubOut(BaseModel):
    id: int
    code: str
    name: str
    lat: float
    lng: float
    capacity_kg: float
    is_active: bool
    is_emergent: bool

    model_config = ConfigDict(from_attributes=True)


class HubCreate(BaseModel):
    code: str = Field(..., min_length=2, max_length=32)
    name: str = Field(..., min_length=2, max_length=128)
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    capacity_kg: float = Field(default=10_000.0, gt=0)


class HubCandidateOut(BaseModel):
    id: int
    lat: float
    lng: float
    usage_count: int
    mean_risk: float
    hub_score: float
    est_setup_cost: float
    est_annual_savings: float
    status: str
    approved_hub_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class CandidateDecision(BaseModel):
    reason: str = Field(default="", max_length=500)
    code: Optional[str] = None
    name: Optional[str] = None


# --- heatmap -------------------------------------------------------------

class RiskCell(BaseModel):
    """One heatmap point, per SH.docx §7.1."""

    lat: float
    lng: float
    weight: float = Field(..., ge=0.0, le=1.0, description="mean_risk 0-1.")
    hub_code: Optional[str] = None
    sample_count: int = 0


class HeatmapResponse(BaseModel):
    hour: int
    cells: List[RiskCell] = Field(default_factory=list)
    source: str


# --- market --------------------------------------------------------------

class BidOut(BaseModel):
    id: int
    vehicle_id: int
    vehicle_code: Optional[str] = None
    amount: float
    detour_km: float
    is_winner: bool

    model_config = ConfigDict(from_attributes=True)


class AuctionOut(BaseModel):
    id: int
    shipment_id: int
    plan_id: Optional[int] = None
    status: str
    max_bounty: float
    opened_at: datetime
    closes_at: datetime
    winning_vehicle_id: Optional[int] = None
    payment: Optional[float] = None
    bids: List[BidOut] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class BidRequest(BaseModel):
    vehicle_id: int
    amount: float = Field(..., ge=0)
    detour_km: float = Field(default=0.0, ge=0)


class ReservationOut(BaseModel):
    """A Foresight option evaluation (SH.docx §9 `/reservations`)."""

    shipment_id: int
    shipment_code: str
    should_reserve: bool
    p_misplace: float
    threshold: float
    premium: float
    dedicated_cost: float
    expected_bounty: float
    expected_saving: float
    reason: str


# --- policy --------------------------------------------------------------

class PolicyModeOut(BaseModel):
    mode: str
    weights: Dict[str, float] = Field(default_factory=dict)
    updated_at: Optional[datetime] = None
    available_modes: List[str] = Field(default_factory=list)


class PolicyModeUpdate(BaseModel):
    mode: str
    weights: Optional[Dict[str, float]] = None
    reason: str = Field(default="", max_length=500)


# --- explainer -----------------------------------------------------------

class ExplainerResponse(BaseModel):
    """`GET /shipments/{id}/explainer` — the counterfactual card."""

    shipment_id: int
    shipment_code: str
    headline: str
    strategy: str
    total_cost: float
    arrival_at: Optional[str] = None
    deadline_at: Optional[str] = None
    transfers: int
    slack_hours: Optional[float] = None
    why_chosen: List[str] = Field(default_factory=list)
    route: List[Dict[str, Any]] = Field(default_factory=list)
    alternatives: List[Dict[str, Any]] = Field(default_factory=list)
    urgency: Dict[str, Any] = Field(default_factory=dict)
    market: Dict[str, Any] = Field(default_factory=dict)
    foresight: Dict[str, Any] = Field(default_factory=dict)
    cascade: Dict[str, Any] = Field(default_factory=dict)
    fusion: Dict[str, Any] = Field(default_factory=dict)


# --- metrics -------------------------------------------------------------

class MetricsResponse(BaseModel):
    """Admin metrics panel (SH.docx §5.1)."""

    shipments_total: int = 0
    delivered: int = 0
    misplaced: int = 0
    recovering: int = 0
    sla_percent: float = 0.0
    recovery_cost_total: float = 0.0
    mean_recovery_cost: float = 0.0
    recovered_via_existing_capacity_pct: float = 0.0
    vehicle_km_avoided: float = 0.0
    median_replan_latency_ms: float = 0.0
    mean_replan_latency_ms: float = 0.0
    premium_burn_ratio: Optional[float] = None
    mean_recovery_seconds: float = 0.0
    strategy_mix: Dict[str, int] = Field(default_factory=dict)
    bounty_paid_total: float = 0.0
    outcome_summary: Dict[str, Any] = Field(default_factory=dict)


LegDetail.model_rebuild()
