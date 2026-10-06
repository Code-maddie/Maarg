"""Realtime event bus and WebSocket connection manager.

SH.docx §11 splits realtime in two: a WebSocket carries high-frequency,
session-scoped updates to screens that stay open (admin, dispatcher), while
Firestore carries durable per-user notifications to drivers. This module is
the WebSocket half.

Publishing is deliberately fire-and-forget and never raises: an engine must
never fail because nobody is listening, or because one browser tab died.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Dict, List, Optional, Set

from fastapi import WebSocket

from app.core.logging import get_logger

logger = get_logger(__name__)

# Events retained for clients that connect mid-demo.
HISTORY_LIMIT = 50


class EventType(StrEnum):
    """Everything the UI subscribes to (SH.docx §11)."""

    TICK = "tick"
    SHIPMENT_UPDATE = "shipment_update"
    VEHICLE_UPDATE = "vehicle_update"
    TEMPERATURE_UPDATE = "temperature_update"
    PRESSURE_UPDATE = "pressure_update"
    PLAN_CHANGED = "plan_changed"
    AUCTION_CHANGED = "auction_changed"
    CASCADE_EVENT = "cascade_event"
    DISRUPTION = "disruption"
    POLICY_CHANGED = "policy_changed"
    MODEL_STATUS = "model_status"


@dataclass
class Event:
    """One realtime message."""

    type: str
    payload: Dict[str, Any] = field(default_factory=dict)
    at: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "at": self.at, "payload": self.payload}


class ConnectionManager:
    """Tracks open WebSocket clients and fans events out to them."""

    def __init__(self) -> None:
        self._connections: Set[WebSocket] = set()
        self._history: List[Event] = []
        self._lock = asyncio.Lock()
        self._sent = 0
        self._dropped = 0

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        logger.info("WebSocket connected (%d open)", len(self._connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)
        logger.info("WebSocket disconnected (%d open)", len(self._connections))

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    def history(self, limit: int = HISTORY_LIMIT) -> List[Dict[str, Any]]:
        """Recent events, so a client joining mid-demo is not blank."""
        return [event.as_dict() for event in self._history[-limit:]]

    async def broadcast(self, event: Event) -> int:
        """Sends an event to every open client. Returns how many received it.

        A client that errors is dropped rather than retried: a dead browser
        tab must not stall the tick loop.
        """
        self._history.append(event)
        if len(self._history) > HISTORY_LIMIT:
            del self._history[: len(self._history) - HISTORY_LIMIT]

        async with self._lock:
            targets = list(self._connections)

        if not targets:
            return 0

        message = json.dumps(event.as_dict(), default=str)
        delivered = 0
        stale: List[WebSocket] = []

        for connection in targets:
            try:
                await connection.send_text(message)
                delivered += 1
            except Exception:  # noqa: BLE001 - a dead client must not raise
                stale.append(connection)

        if stale:
            async with self._lock:
                for connection in stale:
                    self._connections.discard(connection)
            self._dropped += len(stale)
            logger.info("Dropped %d stale WebSocket client(s)", len(stale))

        self._sent += delivered
        return delivered

    def stats(self) -> Dict[str, int]:
        return {
            "connections": len(self._connections),
            "events_sent": self._sent,
            "clients_dropped": self._dropped,
            "history": len(self._history),
        }

    async def reset(self) -> None:
        """Test support: forget history and counters."""
        async with self._lock:
            self._connections.clear()
        self._history.clear()
        self._sent = self._dropped = 0


manager = ConnectionManager()

# The server's event loop, captured at startup. Sync route handlers run in
# FastAPI's threadpool, where there is no running loop, so without this every
# event published from a sync route would silently go to history and never
# reach a connected client.
_main_loop: Optional[asyncio.AbstractEventLoop] = None


def bind_event_loop(loop: Optional[asyncio.AbstractEventLoop]) -> None:
    """Registers the server loop so worker threads can broadcast onto it."""
    global _main_loop
    _main_loop = loop


def _remember(event: Event) -> None:
    manager._history.append(event)  # noqa: SLF001 - intentional
    if len(manager._history) > HISTORY_LIMIT:  # noqa: SLF001
        del manager._history[: len(manager._history) - HISTORY_LIMIT]  # noqa: SLF001


def build_event(
    event_type: EventType | str,
    payload: Optional[Dict[str, Any]] = None,
    *,
    at: Optional[datetime] = None,
) -> Event:
    return Event(
        type=str(event_type),
        payload=payload or {},
        at=(at or datetime.now()).isoformat(timespec="seconds"),
    )


def publish(
    event_type: EventType | str,
    payload: Optional[Dict[str, Any]] = None,
    *,
    at: Optional[datetime] = None,
) -> None:
    """Publishes from any code: async handlers, sync routes, worker threads.

    Three cases:
      * called on the server loop           -> schedule the broadcast there
      * called from a threadpool worker     -> hand it to the server loop
      * no server loop at all (unit tests)  -> keep it in history for replay

    Never raises — an engine must not fail because realtime delivery did.
    """
    event = build_event(event_type, payload, at=at)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        loop.create_task(manager.broadcast(event))
        return

    if _main_loop is not None and _main_loop.is_running():
        try:
            asyncio.run_coroutine_threadsafe(manager.broadcast(event), _main_loop)
            return
        except RuntimeError:
            pass  # loop closed between the check and the call

    _remember(event)
