"""WebSocket endpoint: live event stream, reconnect-safe via last_seq."""

import asyncio
import uuid
from collections import defaultdict
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from studio.db.session import AsyncSessionLocal
from studio.events.replay import replay_events
from studio.events.emitter import register_ws_callback, unregister_ws_callback

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["websocket"])

# session_id -> set of connected WebSocket clients
_connections: dict[str, set[WebSocket]] = defaultdict(set)


async def _broadcast(session_id: str, event: dict[str, Any]) -> None:
    """Broadcast an event to all WebSocket clients subscribed to a session."""
    dead: set[WebSocket] = set()
    for ws in list(_connections.get(session_id, set())):
        try:
            await ws.send_json(event)
        except Exception:
            dead.add(ws)
    for ws in dead:
        _connections[session_id].discard(ws)


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str,
    last_seq: int = 0,
) -> None:
    """Connect to the live event stream for a session.

    On connect: replays all events with seq > last_seq so clients can
    catch up after a disconnect. Then streams new events in real-time.
    Sends a JSON ping every 30 seconds to keep the connection alive.
    """
    await websocket.accept()
    logger.info("ws_connected", session_id=session_id, last_seq=last_seq)

    _connections[session_id].add(websocket)
    register_ws_callback(_broadcast)

    try:
        # Replay missed events
        try:
            session_uuid = uuid.UUID(session_id)
            async with AsyncSessionLocal() as db:
                missed = await replay_events(db, session_uuid, since_seq=last_seq)
            for entry in missed:
                await websocket.send_json(
                    {
                        "session_id": session_id,
                        "seq": entry.seq,
                        "event_type": entry.event_type,
                        "agent": entry.agent,
                        "loop": entry.loop,
                        "data": entry.data,
                        "trace_id": entry.trace_id,
                        "timestamp": entry.created_at.isoformat() if entry.created_at else None,
                    }
                )
        except Exception:
            logger.exception("ws_replay_error", session_id=session_id)

        # Keep-alive ping loop
        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"type": "ping"})

    except WebSocketDisconnect:
        logger.info("ws_disconnected", session_id=session_id)
    finally:
        _connections[session_id].discard(websocket)
        if not _connections[session_id]:
            del _connections[session_id]
        try:
            unregister_ws_callback(_broadcast)
        except ValueError:
            pass
