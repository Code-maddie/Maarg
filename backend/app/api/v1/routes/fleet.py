"""Vehicle and leg routes — SH.docx §9 "Vehicles & Legs".

`GET /legs/{id}` is what the click-a-route info panel calls (§6.1).
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Leg, Vehicle
from app.schemas.api import BountyStatus, LegDetail, VehicleOut
from app.services.presentation import (
    bounty_status_for_leg,
    hub_code_map,
    leg_detail,
    vehicle_out,
)
from app.workers.simulator import get_simulator

router = APIRouter(tags=["fleet"])


@router.get("/vehicles", response_model=List[VehicleOut], summary="List vehicles")
def list_vehicles(
    db: Session = Depends(get_db),
    vehicle_type: Optional[str] = None,
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> List[VehicleOut]:
    query = select(Vehicle)
    if vehicle_type:
        query = query.where(Vehicle.vehicle_type == vehicle_type)

    rows = db.scalars(query.order_by(Vehicle.id).offset(offset).limit(limit)).all()
    codes = hub_code_map(db)
    return [vehicle_out(row, codes) for row in rows]


@router.get("/legs", response_model=List[LegDetail], summary="List legs")
def list_legs(
    db: Session = Depends(get_db),
    leg_status: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> List[LegDetail]:
    """Legs for the map's polyline layer."""
    query = select(Leg)
    if leg_status:
        query = query.where(Leg.status == leg_status)

    rows = db.scalars(
        query.order_by(Leg.departure_at).offset(offset).limit(limit)
    ).all()
    now = get_simulator().clock.now
    return [leg_detail(db, row, now) for row in rows]


def _get_leg(db: Session, leg_id: int) -> Leg:
    leg = db.get(Leg, leg_id)
    if leg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Leg {leg_id} not found",
        )
    return leg


@router.get(
    "/legs/{leg_id}", response_model=LegDetail, summary="Route-click info panel"
)
def get_leg(leg_id: int, db: Session = Depends(get_db)) -> LegDetail:
    """Everything the dispatcher needs about one movement (SH.docx §6.2)."""
    return leg_detail(db, _get_leg(db, leg_id), get_simulator().clock.now)


@router.get(
    "/legs/{leg_id}/bounty-status",
    response_model=BountyStatus,
    summary="Live auction state for a leg",
)
def get_leg_bounty(leg_id: int, db: Session = Depends(get_db)) -> BountyStatus:
    leg = _get_leg(db, leg_id)
    result = bounty_status_for_leg(db, leg, get_simulator().clock.now)

    if result is None:
        return BountyStatus(status="NONE")
    return result
