"""WebSocket endpoint — SH.docx §9 `WS /ws/live`.

Carries the tick stream and plan-change events to screens that stay open.
Clients may send `{"type": "ping"}` to keep the socket alive and
`{"type": "replay"}` to re-request recent history.
"""

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.core.logging import get_logger
from app.core.security import verify_websocket_token
from app.services.events import build_event, manager

logger = get_logger(__name__)

router = APIRouter(tags=["realtime"])


@router.websocket("/ws/live")
async def live(
    websocket: WebSocket, token: Optional[str] = Query(default=None)
) -> None:
    """Streams engine events to a connected dashboard.

    Browsers cannot set headers on a WebSocket handshake, so the Firebase ID
    token arrives as `?token=`. An unauthenticated socket is closed before it
    is accepted: over a real network the handshake is refused (HTTP 403); the
    in-process test client reports this as close code 1008.
    """
    # Verification may fetch Google's signing keys over the network;
    # keep that off the event loop.
    user = await asyncio.to_thread(verify_websocket_token, token)
    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await manager.connect(websocket)

    try:
        # Send recent history immediately so a client joining mid-demo sees
        # state rather than an empty screen until the next tick.
        await websocket.send_text(
            json.dumps(
                {
                    "type": "welcome",
                    "payload": {
                        "history": manager.history(),
                        "connections": manager.connection_count,
                    },
                },
                default=str,
            )
        )

        while True:
            raw = await websocket.receive_text()

            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(
                    json.dumps({"type": "error", "payload": {"detail": "invalid JSON"}})
                )
                continue

            kind = message.get("type")

            if kind == "ping":
                await websocket.send_text(json.dumps({"type": "pong", "payload": {}}))
            elif kind == "replay":
                await websocket.send_text(
                    json.dumps(
                        {"type": "replay", "payload": {"history": manager.history()}},
                        default=str,
                    )
                )
            else:
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "error",
                            "payload": {"detail": f"unknown message type: {kind}"},
                        }
                    )
                )

    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception:  # noqa: BLE001 - one bad client must not kill the server
        logger.exception("WebSocket error; closing connection")
        await manager.disconnect(websocket)


@router.get("/ws/stats", tags=["realtime"], summary="WebSocket diagnostics")
def websocket_stats() -> dict:
    """Open connections and delivery counters."""
    return manager.stats()
