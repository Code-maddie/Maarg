"""Schemas for the simulation-control endpoints (SH.docx §9)."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.workers.simulator import DisruptionType


class WorldResetRequest(BaseModel):
    """Parameters for rebuilding the simulated world."""

    seed: int = Field(default=42, description="Fixed seed; same seed, same world.")
    hub_count: int = Field(default=30, ge=2, le=30)
    vehicle_count: int = Field(default=200, ge=1, le=2000)
    shipment_count: int = Field(default=5000, ge=1, le=50000)
    leg_count: int = Field(default=600, ge=1, le=10000)


class WorldResetResponse(BaseModel):
    hubs: int
    vehicles: int
    shipments: int
    legs: int
    seed: int
    start: str


class TickRequest(BaseModel):
    ticks: int = Field(default=1, ge=1, le=100, description="Ticks to advance.")


class TickResponse(BaseModel):
    tick: int
    now: str
    departed_legs: int
    arrived_legs: int
    shipments_moved: int
    shipments_delivered: int
    shipments_overdue: int
    events: List[str] = Field(default_factory=list)


class DisruptionRequest(BaseModel):
    """`POST /simulate/inject-disruption` — the live-demo trigger."""

    type: DisruptionType = Field(
        default=DisruptionType.MISPLACE_SHIPMENT,
        description="MISPLACE_SHIPMENT | DELAY_VEHICLE | CLOSE_HUB",
    )
    target_id: Optional[int] = Field(
        default=None, description="Target row id; omitted picks an eligible one."
    )
    delay_hours: float = Field(
        default=4.0, ge=0.1, le=72.0, description="DELAY_VEHICLE only."
    )


class DisruptionResponse(BaseModel):
    type: str
    target_id: int
    affected_shipments: List[int]
    affected_legs: List[int]
    detail: str


class SimulationStateResponse(BaseModel):
    tick: int
    now: str
    tick_minutes: int
    elapsed_hours: float
    seed: int
    hubs: int
    vehicles: int
    shipments: int
    legs: int
    shipment_status: Dict[str, int] = Field(default_factory=dict)
    leg_status: Dict[str, int] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class RoutePreviewResponse(BaseModel):
    """E4 + Pressure + E6 output for one shipment, computed but not committed."""

    shipment_id: int
    shipment_code: str
    temperature: Dict[str, Any]
    pressure: Dict[str, Any]
    compute_ms: float
    labels_explored: int
    edges_considered: int
    plans: List[Dict[str, Any]] = Field(default_factory=list)
    rejected: List[Dict[str, Any]] = Field(default_factory=list)
