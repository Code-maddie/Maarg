"""Map layer routes — SH.docx §6 and §7.

Payloads mirror the arrays the existing frontend renders (`data.js`), so the
existing Google Maps / Leaflet code can draw them unchanged.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Auction
from app.services.mapdata import heat_payload, network_payload, pickup_route
from app.workers.simulator import get_simulator

router = APIRouter(prefix="/map", tags=["map"])


def _hour(hour: int) -> int:
    return get_simulator().clock.now.hour if hour < 0 else hour


@router.get("/network", summary="Every map layer in one call")
def network(
    hour: int = Query(default=-1, ge=-1, le=23, description="-1 uses sim time."),
    leg_limit: int = Query(default=60, ge=1, le=600),
    db: Session = Depends(get_db),
) -> dict:
    """Hubs (markers), legs (polylines), candidates (gold pins) and heat."""
    simulator = get_simulator()
    return network_payload(
        db, hour=_hour(hour), now=simulator.clock.now,
        tick=simulator.clock.tick, leg_limit=leg_limit,
    )


@router.get("/heat", summary="Heat points for one hour")
def heat(
    hour: int = Query(default=-1, ge=-1, le=23, description="-1 uses sim time."),
    db: Session = Depends(get_db),
) -> dict:
    """For the admin time-of-day slider (SH.docx §7.1): re-fetch per hour."""
    simulator = get_simulator()
    return heat_payload(
        db, hour=_hour(hour), now=simulator.clock.now, tick=simulator.clock.tick
    )


@router.get("/pickup-route/{auction_id}", summary="Driver waypoints (§6.3)")
def driver_route(auction_id: int, db: Session = Depends(get_db)) -> dict:
    """[driver position, pickup, destination] for the Directions API."""
    auction = db.get(Auction, auction_id)
    if auction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Auction {auction_id} not found",
        )
    try:
        return pickup_route(db, auction)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
