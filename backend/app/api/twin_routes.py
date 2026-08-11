"""Module 2 endpoints — the Digital Twin tab's data source. Entirely
separate from app/api/routes.py (Module 1 / Live Data tab), per CLAUDE.md's
requirement that the two tabs not share a view."""

import logging

from fastapi import APIRouter, HTTPException

from app import db
from app.twin.digital_twin import digital_twin

logger = logging.getLogger("sei")

router = APIRouter(prefix="/twin")


@router.get("/nodes")
async def get_twin_nodes():
    return {"nodes": digital_twin.get_all_nodes(), "edges": digital_twin.get_edges()}


@router.get("/nodes/{node_id}/history")
async def get_twin_node_history(node_id: str, limit: int = 100):
    """Raw reading history for one node — same underlying data as Module
    1's GET /nodes/{id}/history, exposed under /twin so the Digital Twin
    tab never has to call into the Live Data tab's API namespace."""
    try:
        digital_twin.get_node(node_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown node: {node_id}")

    try:
        rows = await db.fetch_history(node_id, limit=limit)
    except Exception as exc:
        logger.warning("Failed to fetch history for %s: %s", node_id, exc)
        rows = []
    return {"node_id": node_id, "history": rows}


@router.get("/decisions")
async def get_twin_decisions(node_id: str | None = None, limit: int = 100):
    """Self-healing decision log — what triggered each reconfiguration,
    what candidates were considered, which was chosen and why. This is the
    historical-replay record: paired with a node's reading history above,
    it shows a fault happening AND the twin's response to it."""
    try:
        rows = await db.fetch_decisions(node_id=node_id, limit=limit)
    except Exception as exc:
        logger.warning("Failed to fetch self-healing decisions: %s", exc)
        rows = []
    return {"decisions": rows}
