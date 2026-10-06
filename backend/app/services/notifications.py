"""Firestore push notifications — SH.docx §8.2 and §11.

Firestore is the "nervous system, not the brain": it carries bounty offers
and per-user notifications to clients that may be backgrounded (drivers),
while the engine's source of truth stays in the database.

Collections written:

    /notifications/{user_id}/items/{auto_id}   plan-change and offer alerts
    /bounty_offers/{auction_id}                live auction state for drivers
    /live_positions/{vehicle_id}               vehicle positions for maps

Every write here goes to the **live Firebase project**, so it is gated by
``FIRESTORE_ENABLED`` (off by default) and every function is a no-op that
returns False when disabled or unavailable. Nothing here ever raises: a
notification failure must never fail the recovery it describes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Dict, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import init_firebase

logger = get_logger(__name__)

NOTIFICATIONS = "notifications"
BOUNTY_OFFERS = "bounty_offers"
LIVE_POSITIONS = "live_positions"

_client: Any = None
_writes = 0
_failures = 0


def _firestore() -> Any:
    """The Firestore client, or None when disabled or unavailable."""
    global _client

    if not settings.firestore_enabled:
        return None
    if _client is not None:
        return _client
    if not init_firebase():
        return None

    try:
        from firebase_admin import firestore

        _client = firestore.client()
        return _client
    except Exception:  # noqa: BLE001 - disabled rather than raising
        logger.exception("Firestore client unavailable")
        return None


def _write(path_parts: tuple, data: Dict[str, Any], *, merge: bool = False) -> bool:
    global _writes, _failures

    client = _firestore()
    if client is None:
        return False

    try:
        ref = client
        for index, part in enumerate(path_parts):
            ref = ref.collection(part) if index % 2 == 0 else ref.document(part)

        payload = {**data, "written_at": datetime.now(UTC).isoformat()}
        if len(path_parts) % 2 == 1:
            ref.add(payload)                   # collection -> auto id
        else:
            ref.set(payload, merge=merge)      # explicit document
        _writes += 1
        return True
    except Exception:  # noqa: BLE001 - a notification must never fail a recovery
        _failures += 1
        logger.exception("Firestore write to %s failed", "/".join(map(str, path_parts)))
        return False


def notify_user(user_id: str, kind: str, payload: Dict[str, Any]) -> bool:
    """Appends a notification to /notifications/{user_id}/items."""
    return _write(
        (NOTIFICATIONS, str(user_id), "items"),
        {"kind": kind, "payload": payload, "read": False},
    )


def publish_bounty_offer(
    auction_id: int,
    *,
    status: str,
    max_bounty: float,
    shipment_code: str,
    closes_at: Optional[datetime] = None,
    best_bid: Optional[float] = None,
    winning_vehicle_id: Optional[int] = None,
    payment: Optional[float] = None,
) -> bool:
    """Writes live auction state to /bounty_offers/{auction_id}.

    Drivers listen here for the offer card and its countdown (§5.3). Bids
    themselves still go through FastAPI, never directly into Firestore —
    §11 is explicit that Firestore is a read/notify channel only.
    """
    return _write(
        (BOUNTY_OFFERS, str(auction_id)),
        {
            "auction_id": auction_id,
            "status": status,
            "max_bounty": max_bounty,
            "shipment_code": shipment_code,
            "closes_at": closes_at.isoformat() if closes_at else None,
            "best_bid": best_bid,
            "winning_vehicle_id": winning_vehicle_id,
            "payment": payment,
        },
        merge=True,
    )


def update_live_position(
    vehicle_id: int, *, lat: float, lng: float, status: str
) -> bool:
    """Writes a vehicle position to /live_positions/{vehicle_id}."""
    return _write(
        (LIVE_POSITIONS, str(vehicle_id)),
        {"vehicle_id": vehicle_id, "lat": lat, "lng": lng, "status": status},
        merge=True,
    )


def stats() -> Dict[str, Any]:
    return {
        "enabled": settings.firestore_enabled,
        "connected": _client is not None,
        "writes": _writes,
        "failures": _failures,
    }


def reset() -> None:
    """Test support only."""
    global _client, _writes, _failures
    _client = None
    _writes = _failures = 0
