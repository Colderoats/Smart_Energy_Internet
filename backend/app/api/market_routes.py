"""Prosumer market endpoints (app/market/). All GET, all protected (see app/main.py).

Prosumers are SIMULATED buildings: solar estimated from live weather, load synthetic,
amounts are demo credits. Quantities are Wh / milli-credits as on the EnergyMarket contract.
"""

from fastapi import APIRouter, HTTPException, Query

from app import db
from app.market import store
from app.market.service import market
from app.twin.digital_twin import PROSUMER_NODES

router = APIRouter(prefix="/market")


def _require_db() -> None:
    if not market.enabled:
        raise HTTPException(status_code=503, detail="prosumer market disabled (MARKET_ENABLED / BLOCKCHAIN_ENABLED)")
    if not market.db_ready:
        raise HTTPException(status_code=503, detail="TimescaleDB unavailable: market records cannot be read")


@router.get("/status")
async def market_status():
    return await market.status()


@router.get("/prosumers")
async def market_prosumers():
    return {"prosumers": await market.prosumers()}


@router.get("/prosumers/{node_id}/series")
async def prosumer_series(node_id: str, hours: int = Query(24, ge=1, le=72)):
    """Generation vs consumption for one prosumer, 5-minute averages (TimescaleDB time_bucket).
    Generation = ESTIMATED from live weather (or demo irradiance), consumption = SYNTHETIC."""
    if node_id not in {p["node_id"] for p in PROSUMER_NODES}:
        raise HTTPException(status_code=404, detail=f"unknown prosumer: {node_id}")
    try:
        points = await db.fetch_prosumer_series(node_id, hours)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"TimescaleDB unavailable: {exc}")
    return {"node_id": node_id, "hours": hours, "bucket_minutes": 5, "points": points,
            "provenance": {"generation": "live_api_estimated (or simulated with a demo irradiance)", "consumption": "simulated"}}


@router.get("/intervals")
async def market_intervals(limit: int = Query(20, ge=1, le=200)):
    _require_db()
    return {"intervals": await store.select("market_intervals", order="id DESC", limit=limit)}


@router.get("/intervals/{interval_id}")
async def market_interval(interval_id: int):
    _require_db()
    iv = await store.get("market_intervals", interval_id)
    if iv is None:
        raise HTTPException(status_code=404, detail=f"unknown interval {interval_id}")
    orders = await store.select("market_orders", "interval_id = %s", (interval_id,), order="id ASC")
    trades = [market._trade_public(t, orders) for t in await store.select("market_trades", "interval_id = %s", (interval_id,), order="id ASC")]
    return {
        "interval": iv, "orders": orders, "matches": trades,
        "settlements": [t for t in trades if t["status"] == "settled"],
        "tx_hashes": sorted({h for t in trades for h in (t["match_tx_hash"], t["meter_tx_hash"], t["settle_tx_hash"]) if h}
                            | {o["tx_hash"] for o in orders if o["tx_hash"]} | ({iv["advance_tx_hash"]} if iv["advance_tx_hash"] else set())),
    }


@router.get("/trades")
async def market_trades(limit: int = Query(20, ge=1, le=200)):
    _require_db()
    trades = await store.select("market_trades", order="id DESC", limit=limit)
    ids = sorted({t["interval_id"] for t in trades})
    orders = await store.select("market_orders", "interval_id = ANY(%s)", (ids,), order="id ASC") if ids else []
    return {"trades": [market._trade_public(t, orders) for t in trades]}
