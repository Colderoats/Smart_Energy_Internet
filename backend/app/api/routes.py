import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from app import db
from app.api.ws_manager import manager
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


@router.websocket("/ws/updates")
async def ws_updates(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # This socket is push-only; we still need to await something
            # so we notice a client disconnect.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
