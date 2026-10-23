"""Prosumer dashboard endpoints (/p2p/*). Every route requires a prosumer session
(require_prosumer, applied in app/main.py) and acts on the caller's OWN node only:
the node comes from the user row, never from the request; an optional node_id in a
query/body that names another node is answered with 403.

Prosumers are SIMULATED buildings: solar estimated from live weather, load synthetic,
amounts are demo credits. A manual order is queued for the next interval and then runs through
the same MarketService pipeline as the automatic ones (see app/market/service.py).
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.auth.deps import require_prosumer
from app.market import store
from app.market.prosumers import role_of
from app.market.service import market
from app.config import settings
from app.twin.digital_twin import digital_twin

router = APIRouter(prefix="/p2p")

PROVENANCE_NOTE = "Simulated building: solar estimated from live weather, load synthetic. Amounts are demo credits."
# EnergyMarket trade status -> what the dashboard shows (pending -> matched -> settled).
TRADE_STATUS = {"matched_planned": "pending", "matched": "matched", "metered": "matched", "settled": "settled", "failed": "failed"}


class OfferRequest(BaseModel):
    kwh: float
    ask: float
    node_id: str | None = None


class BidRequest(BaseModel):
    kwh: float
    max: float
    node_id: str | None = None


class AutoRequest(BaseModel):
    enabled: bool
    node_id: str | None = None


def own_node(user: dict, node_id: str | None) -> str:
    node = user["prosumer_node_id"]
    if node_id is not None and node_id != node:
        raise HTTPException(status_code=403, detail="That is not your node.")
    return node


async def _need_db() -> None:
    if not market.enabled:
        raise HTTPException(status_code=503, detail="prosumer market disabled (MARKET_ENABLED / BLOCKCHAIN_ENABLED)")
    if not await market.ensure_db():
        raise HTTPException(status_code=503, detail="TimescaleDB unavailable")


def _order_public(o: dict, node: str) -> dict:
    return {"id": o["id"], "side": o["side"], "node_id": o["node_id"], "mine": o["node_id"] == node, "manual": bool(o.get("manual")),
            "qty_wh": o["qty_wh"], "remaining_wh": o["remaining_wh"], "price_milli": o["price_milli"], "status": o["status"],
            "tx_hash": o["tx_hash"], "block_number": o["block_number"], "interval_id": o["interval_id"]}


@router.get("/me")
async def p2p_me(node_id: str | None = Query(None), user: dict = Depends(require_prosumer)):
    node = own_node(user, node_id)
    n = digital_twin.get_node(node)
    reg = market.registrations.get(node) or {}
    address = reg.get("address") or (market.chain.accounts[node].address if market.chain and node in market.chain.accounts else None)
    balance = None
    if address and market.chain and market._connected.is_set():
        try:
            balance = await asyncio.to_thread(market.chain.balance_milli, address)
        except Exception:
            balance = None
    f = market.forecast_kw(node)
    role = role_of(f, settings.prosumer_role_deadband_kw)
    cap_kwh = round(abs(f) * settings.market_interval_seconds / 3600.0, 3) if f is not None and role in ("surplus", "deficit") else 0.0
    price = settings.market_prices.get(node, {})
    return {
        "node_id": node, "profile": n.get("profile"), "pv_kwp": n.get("pv_kwp"),
        "generation_kw": n.get("generation_kw"), "consumption_kw": n.get("consumption_kw"), "net_kw": n.get("net_kw"),
        "role": n.get("role"), "forecast_kw": None if f is None else round(f, 3), "forecast_role": role,
        "max_kwh": cap_kwh, "price_bounds": market.price_bounds(), "default_ask": price.get("ask"), "default_max": price.get("max"),
        "address": address, "registered": reg.get("status") in ("in_block", "confirmed"), "balance_milli": balance,
        "balance_credits": None if balance is None else balance / 1000.0,
        "auto_trade": market.is_auto(node), "interval_seconds": settings.market_interval_seconds,
        "chain_connected": market._connected.is_set(), "provenance": n.get("provenance"), "provenance_note": PROVENANCE_NOTE,
    }


@router.get("/book")
async def p2p_book(node_id: str | None = Query(None), user: dict = Depends(require_prosumer)):
    node = own_node(user, node_id)
    await _need_db()
    ivs = await store.select("market_intervals", "status <> 'skipped'", order="id DESC", limit=1)
    iv = ivs[0] if ivs else None
    orders = await store.select("market_orders", "interval_id = %s", (iv["id"],), order="id ASC") if iv else []
    live = [_order_public(o, node) for o in orders if o["status"] != "failed"]
    queued = [{"id": m["id"], "side": m["side"], "qty_wh": m["qty_wh"], "price_milli": m["price_milli"], "created_at": m["created_at"]}
              for m in await store.select("market_manual_orders", "node_id = %s AND status = 'queued'", (node,), order="id ASC")]
    return {
        "interval": None if iv is None else {k: iv[k] for k in ("id", "status", "started_at", "ends_at", "interval_s")},
        "offers": sorted((o for o in live if o["side"] == "offer"), key=lambda o: o["price_milli"]),
        "bids": sorted((o for o in live if o["side"] == "bid"), key=lambda o: -o["price_milli"]),
        "queued": queued,
    }


@router.post("/offer", status_code=201)
async def p2p_offer(body: OfferRequest, user: dict = Depends(require_prosumer)):
    node = own_node(user, body.node_id)
    await _need_db()
    try:
        row = await market.place_manual(node, "offer", body.kwh, body.ask, user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"order": row, "note": "Queued for the next market interval."}


@router.post("/bid", status_code=201)
async def p2p_bid(body: BidRequest, user: dict = Depends(require_prosumer)):
    node = own_node(user, body.node_id)
    await _need_db()
    try:
        row = await market.place_manual(node, "bid", body.kwh, body.max, user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"order": row, "note": "Queued for the next market interval."}


@router.post("/auto")
async def p2p_auto(body: AutoRequest, user: dict = Depends(require_prosumer)):
    node = own_node(user, body.node_id)
    await _need_db()
    await market.set_auto_trade(node, body.enabled)
    return {"node_id": node, "auto_trade": body.enabled}


@router.get("/trades")
async def p2p_trades(node_id: str | None = Query(None), limit: int = Query(30, ge=1, le=100), user: dict = Depends(require_prosumer)):
    node = own_node(user, node_id)
    await _need_db()
    rows = await store.select("market_trades", "seller = %s OR buyer = %s", (node, node), order="id DESC", limit=limit)
    out = []
    for t in rows:
        sell = t["seller"] == node
        block = t["settle_block"] or t["meter_block"] or t["match_block"]
        tx = t["settle_tx_hash"] or t["meter_tx_hash"] or t["match_tx_hash"]
        out.append({
            "id": t["id"], "interval_id": t["interval_id"], "side": "sell" if sell else "buy",
            "counterparty": t["buyer"] if sell else t["seller"], "matched_wh": t["matched_wh"], "settled_wh": t["settled_wh"],
            "price_milli": t["price_milli"], "pay_milli": t["pay_milli"], "status": TRADE_STATUS.get(t["status"], t["status"]),
            "tx_hash": tx, "block_number": block, "match_block": t["match_block"], "meter_block": t["meter_block"],
            "settle_block": t["settle_block"], "ledger_record_id": t["ledger_record_id"], "error": t["error"], "created_at": t["created_at"],
        })
    return {"node_id": node, "trades": out}
