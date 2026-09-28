import asyncio
import logging
import time

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from app import db
from app.api.ws_manager import manager
from app.auth.deps import authenticate_websocket, origin_allowed
from app.twin.graph import twin

logger = logging.getLogger("sei")

router = APIRouter()


@router.get("/nodes")
async def get_nodes():
    return {"nodes": twin.get_all_nodes(), "edges": twin.get_edges()}


@router.get("/nodes/{node_id}/history")
async def get_node_history(node_id: str, limit: int = 100):
    try:
        twin.get_node(node_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown node: {node_id}")

    try:
        rows = await db.fetch_history(node_id, limit=limit)
    except Exception as exc:
        logger.warning("Failed to fetch history for %s: %s", node_id, exc)
        rows = []
    return {"node_id": node_id, "history": rows}


# The WebSocket has its own router: REST routers carry require_admin as a
# router-level dependency (app/main.py), which cannot apply to a WebSocket.
ws_router = APIRouter()


@ws_router.websocket("/ws/updates")
async def ws_updates(websocket: WebSocket):
    # Authenticate on connect. Rejections accept-then-close so the browser sees
    # the close code: 4403 = foreign Origin, 4401 = missing/invalid/expired
    # access token (the frontend refreshes and reconnects on 4401).
    if not origin_allowed(websocket):
        await websocket.accept()
        await websocket.close(code=4403, reason="origin not allowed")
        return
    found = await authenticate_websocket(websocket)
    if found is None:
        await websocket.accept()
        await websocket.close(code=4401, reason="unauthenticated")
        return
    _, claims = found
    expires_at = float(claims["exp"])

    await manager.connect(websocket)
    try:
        while True:
            # This socket is push-only; we still need to await something
            # so we notice a client disconnect. The wait is bounded by the
            # access token's expiry: the socket is closed with 4401 when it
            # expires, and the client reconnects with its refreshed token.
            remaining = expires_at - time.time()
            if remaining <= 0:
                await websocket.close(code=4401, reason="token expired")
                break
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=remaining)
            except asyncio.TimeoutError:
                await websocket.close(code=4401, reason="token expired")
                break
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)
