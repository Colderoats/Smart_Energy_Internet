"""Module 5 endpoints — the Blockchain tab's data source (app/blockchain/).

Every record carries `provenance` (live_api | replayed_scada | simulated |
offline_federated_run); P2P trades are always SIMULATED (no hardware yet).
"""

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.blockchain import events, store
from app.blockchain.chain_client import EVENT_TYPES
from app.blockchain.ledger import ledger

logger = logging.getLogger("sei")

router = APIRouter(prefix="/chain")


def _require_db() -> None:
    if not ledger.enabled:
        raise HTTPException(status_code=503, detail="blockchain ledger disabled (BLOCKCHAIN_ENABLED=false)")
    if not ledger.db_ready:
        raise HTTPException(status_code=503, detail="TimescaleDB unavailable: ledger records cannot be read or written")


@router.get("/status")
async def chain_status(check_integrity: bool = True):
    """Connection, network, contract, counts, and (by default) a fresh
    integrity check: every stored payload re-hashed and compared on-chain."""
    return await ledger.status(check_integrity=check_integrity)


@router.get("/records")
async def list_records(
    event_type: str | None = Query(None, description=f"one of {EVENT_TYPES}"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    _require_db()
    if event_type is not None and event_type not in EVENT_TYPES:
        raise HTTPException(status_code=400, detail=f"event_type must be one of {EVENT_TYPES}")

    rows, total = await store.list_records(event_type, limit, offset)
    return {"records": [ledger.public(r) for r in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/records/{record_id}")
async def get_record(record_id: int):
    _require_db()

    row = await store.get(record_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown record {record_id}")
    return {"record": ledger.public(row), "steps": ledger.steps(row)}


@router.post("/verify/{record_id}")
async def verify_record(record_id: int):
    _require_db()
    try:
        return await ledger.verify_record(record_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown record {record_id}")


class TradeRequest(BaseModel):
    seller: str | None = None
    buyer: str | None = None
    kwh: float | None = Field(None, gt=0, le=100000)
    price_per_kwh: float | None = Field(None, gt=0, le=1000)


@router.post("/simulate-trade")
async def simulate_trade(req: TradeRequest | None = None):
    """Create a SIMULATED P2P trade between two twin nodes (demo only)."""
    _require_db()
    req = req or TradeRequest()
    try:
        entry = events.simulated_trade(req.seller, req.buyer, req.kwh, req.price_per_kwh)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    row = await ledger.record(entry)
    return {"record": ledger.public(row), "provenance": "simulated"}


@router.post("/replay-fl-rounds")
async def replay_fl_rounds(run: str = events.DEFAULT_FL_RUN):
    """Record each round of an OFFLINE Module 4 federated run (from its
    round_log.json). Idempotent: rounds already on the ledger are skipped."""
    _require_db()
    try:
        entries = events.fl_round_entries(run)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    created = []
    for entry in entries:
        row = await ledger.record(entry)
        if row is not None:
            created.append(row["id"])
    return {"run": run, "rounds_in_run": len(entries), "recorded": len(created),
            "skipped_already_recorded": len(entries) - len(created), "record_ids": created,
            "provenance": "offline_federated_run"}


@router.post("/dev/tamper/{record_id}")
async def dev_tamper(record_id: int):
    """DEV-ONLY demo: edit the OFF-CHAIN payload copy so Verify visibly fails.
    Disabled unless BLOCKCHAIN_DEV_TOOLS is on (default: on for the local node only)."""
    if not ledger.dev_tools:
        raise HTTPException(status_code=403, detail="dev tools disabled (BLOCKCHAIN_DEV_TOOLS)")
    _require_db()
    try:
        return {"record_id": record_id, "tampered": await ledger.tamper(record_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown record {record_id}")
