"""Live prosumer market service: intervals -> orders -> matches -> chain worker -> ledger mirror.

Non-blocking by design (same pattern as app/blockchain/ledger.py):
  * the CLOCK task only does off-chain work (forecast, offers/bids, matching, metering numbers) and
    enqueues jobs; it never waits on the chain, so ingestion and the interval cadence are unaffected;
  * ONE worker task sends the transactions sequentially (no nonce races), every Web3 call runs in a
    thread, failures are retried with backoff once the chain is reachable again (state is persisted
    per step, so a retry resumes where it stopped);
  * if TimescaleDB is down the interval is skipped and logged (like the ledger); if the chain stays
    down the backlog is capped (MAX_BACKLOG intervals) and further intervals are recorded as skipped.

Interval life cycle (MARKET_INTERVAL_SECONDS):
  start  forecast = mean of the latest net_kw samples; surplus prosumers offer
         (qty = forecast surplus kW x interval hours, ask price), deficit prosumers bid
         (qty = forecast deficit, max price); engine.match_orders matches them off-chain;
         job "post": register (idempotent) -> postOffer/postBid per order -> matchTrade per match.
  end    METERED quantities = energy actually delivered, from the readings of that interval
         (engine.allocate_metering); job "settle": submitMeter -> settle (Pay = p x min(q_s, q_b))
         -> mirror the settled trade into EnergyLedger as a P2P_TRADE -> advanceInterval.
  Unmatched deficit = "served by grid", unmatched surplus = "exported to grid" (UI only, not on-chain).

WebSocket messages on /ws/updates: market_prosumer_update, market_registration, market_order,
market_match, market_settlement (+ market_interval), each carrying tx hash / block / status as the
transaction goes pending -> in_block -> confirmed.
"""

import asyncio
import logging
from collections import deque
from datetime import datetime, timedelta, timezone

from app.api.ws_manager import manager
from app.blockchain import events
from app.blockchain.ledger import ledger
from app.config import settings
from app.market import engine, store
from app.market.chain import MarketChain, MarketChainUnavailable
from app.market.prosumers import role_of
from app.twin.digital_twin import PROSUMER_NODES, digital_twin

logger = logging.getLogger("sei")

RETRY_BACKOFF_S = (2, 5, 10, 20, 30)
HEALTH_INTERVAL_S = 5.0
MAX_BACKLOG = 3  # intervals waiting for the chain before new ones are skipped
FORECAST_SAMPLES = 8


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_revert(exc: Exception) -> bool:
    return type(exc).__name__ in ("ContractLogicError", "ContractCustomError")


class MarketService:
    def __init__(self) -> None:
        self.enabled = settings.market_enabled and settings.blockchain_enabled
        self.chain: MarketChain | None = None
        self.state = "starting" if self.enabled else "disabled"
        self.last_error: str | None = None
        self.db_ready = False
        self.skipped_without_db = 0
        self.last_run: str | None = None
        self.current: dict | None = None
        self.registrations: dict[str, dict] = {}
        self._ids = [n["node_id"] for n in PROSUMER_NODES]
        self._recent: dict[str, deque] = {}
        self._samples: dict[str, list[float]] = {n: [] for n in self._ids}
        self._jobs: asyncio.Queue = asyncio.Queue()
        self._connected = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._backlog = 0
        self._dep_seen: str | None = None

    # -- lifecycle ------------------------------------------------------------

    async def start(self) -> None:
        if not self.enabled:
            logger.info("Prosumer market disabled (MARKET_ENABLED / BLOCKCHAIN_ENABLED)")
            return
        self.chain = MarketChain(self._ids)
        try:
            await store.init_schema()
            self.db_ready = True
            await self._recover()
        except Exception as exc:
            logger.warning("Prosumer market: tables unavailable (TimescaleDB down?): %s", exc)
        self._tasks += [asyncio.create_task(self._check_connection()), asyncio.create_task(self._worker()),
                        asyncio.create_task(self._health_loop()), asyncio.create_task(self._clock())]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()

    async def _recover(self) -> None:
        """After a backend restart: a 'closing' interval already has its metered numbers, so its
        settlement is re-queued; an 'open' one lost its in-memory readings (nothing to meter) and is
        abandoned, as are its not-yet-metered trades (they stay matched on the contract, never settled)."""
        for iv in await store.select("market_intervals", "status IN ('open', 'closing')", order="id ASC"):
            if iv["status"] == "closing":
                self._backlog += 1
                self._jobs.put_nowait(("settle", iv["id"]))
                continue
            await store.update("market_intervals", {"id": iv["id"]}, status="skipped", error="backend restarted before this interval closed; not settled")
            for t in await store.select("market_trades", "interval_id = %s AND status IN ('matched_planned', 'matched')", (iv["id"],)):
                await store.update("market_trades", {"id": t["id"]}, status="failed", error="interval abandoned: backend restarted before metering")

    # -- readings -----------------------------------------------------------------

    def observe(self, node_id: str, net_kw: float | None) -> None:
        if net_kw is None:
            return
        self._recent.setdefault(node_id, deque(maxlen=FORECAST_SAMPLES)).append(net_kw)
        self._samples.setdefault(node_id, []).append(net_kw)

    def prosumer_view(self, node: dict) -> dict:
        r = node.get("latest_reading") or {}
        return {
            "node_id": node["node_id"], "profile": node.get("profile"), "pv_kwp": node.get("pv_kwp"),
            "generation_kw": node.get("generation_kw"), "consumption_kw": node.get("consumption_kw"),
            "net_kw": node.get("net_kw"), "role": node.get("role"), "provenance": node.get("provenance"),
            "provenance_detail": node.get("provenance_detail"), "irradiance_wm2": r.get("irradiance_wm2"),
            "timestamp": r.get("timestamp"), "onchain": node.get("onchain"),
        }

    # -- chain connection ----------------------------------------------------------

    async def _check_connection(self) -> None:
        was = self._connected.is_set()
        try:
            await asyncio.to_thread(self.chain.ensure)
            self.state, self.last_error = "connected", None
            self._connected.set()
            if self.chain.deployment_key != self._dep_seen:
                self._dep_seen = self.chain.deployment_key
                self.registrations = {}
                for nid in self._ids:
                    digital_twin.set_onchain(nid, None)
                logger.info("Prosumer market: connected, EnergyMarket at %s", self.chain.contract_address)
                self._jobs.put_nowait(("register", None))
        except Exception as exc:
            self.state = "unreachable"
            self.last_error = str(exc) if isinstance(exc, MarketChainUnavailable) else f"{type(exc).__name__}: {exc}"
            self._connected.clear()
            if was:
                logger.warning("Prosumer market: chain unavailable: %s", self.last_error)

    async def _health_loop(self) -> None:
        while True:
            await asyncio.sleep(HEALTH_INTERVAL_S)
            try:
                await self._check_connection()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("Prosumer market health loop: %s", exc)

    # -- clock: off-chain interval work only ------------------------------------------

    async def _clock(self) -> None:
        for _ in range(int(settings.prosumer_tick_seconds * 3) + 5):  # wait for the first readings
            if all(n in self._recent for n in self._ids):
                break
            await asyncio.sleep(1)
        while True:
            interval = None
            try:
                interval = await self._open_interval()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Prosumer market: could not open interval: %s", exc)
            ends = interval["ends_dt"] if interval else _now() + timedelta(seconds=settings.market_interval_seconds)
            await asyncio.sleep(max(0.0, (ends - _now()).total_seconds()))
            try:
                if interval and interval.get("id") is not None and not interval.get("skip"):
                    await self._close_interval(interval)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Prosumer market: could not close interval: %s", exc)

    async def _retry_db(self) -> bool:
        try:
            await store.init_schema()
            self.db_ready = True
        except Exception:
            self.db_ready = False
        return self.db_ready

    def _mean(self, values) -> float | None:
        values = list(values)
        return sum(values) / len(values) if values else None

    async def _open_interval(self) -> dict:
        now = _now()
        secs = settings.market_interval_seconds
        hours = secs / 3600.0
        ends = now + timedelta(seconds=secs)
        forecast = {n: self._mean(self._recent.get(n, ())) for n in self._ids}
        self._samples = {n: [] for n in self._ids}
        self.last_run = now.isoformat()
        base = {"ends_dt": ends, "started_dt": now}

        if not self.db_ready and not await self._retry_db():
            self.skipped_without_db += 1
            logger.warning("Prosumer market: TimescaleDB unavailable, interval skipped")
            return {**base, "id": None, "skip": True}

        latest = [digital_twin.get_node(n).get("latest_reading") or {} for n in self._ids]
        irr = next((r.get("irradiance_wm2") for r in latest if r.get("irradiance_wm2") is not None), None)
        prov = next((r.get("provenance") for r in latest if r.get("provenance")), None)
        fc = {n: {"net_kw": None if f is None else round(f, 4), "role": role_of(f, settings.prosumer_role_deadband_kw)} for n, f in forecast.items()}
        row = {"started_at": now, "ends_at": ends, "interval_s": secs, "forecast": fc, "solar_provenance": prov, "irradiance_wm2": irr}

        if not self._connected.is_set() and self._backlog >= MAX_BACKLOG:
            iv = await store.insert("market_intervals", {**row, "status": "skipped", "error": "chain unavailable: backlog full, interval not traded"})
            await self._push("market_interval", {"interval": iv})
            return {**base, "id": iv["id"], "skip": True}

        offers, bids = [], []
        for n in self._ids:
            f = forecast[n]
            price = settings.market_prices.get(n, {})
            if fc[n]["role"] == "surplus":
                qty = engine.energy_wh(f, hours)
                if qty > 0:
                    offers.append(engine.Order(n, qty, int(round(price.get("ask", 5.0) * 1000))))
            elif fc[n]["role"] == "deficit":
                qty = engine.energy_wh(-f, hours)
                if qty > 0:
                    bids.append(engine.Order(n, qty, int(round(price.get("max", 7.0) * 1000))))
        matches, off_rem, bid_rem = engine.match_orders(offers, bids)

        iv = await store.insert("market_intervals", {**row, "status": "open"})
        off_rows, bid_rows = [], []
        for o, rem in zip(offers, off_rem):
            off_rows.append(await store.insert("market_orders", self._order_row(iv, "offer", o, rem)))
        for b, rem in zip(bids, bid_rem):
            bid_rows.append(await store.insert("market_orders", self._order_row(iv, "bid", b, rem)))
        trade_rows = []
        for m in matches:
            trade_rows.append(await store.insert("market_trades", {
                "interval_id": iv["id"], "offer_order_id": off_rows[m.offer_idx]["id"], "bid_order_id": bid_rows[m.bid_idx]["id"],
                "seller": m.seller, "buyer": m.buyer, "matched_wh": m.qty_wh, "price_milli": m.price_milli,
                "status": "matched_planned", "provenance": "simulated", "created_at": now}))
        self.current = iv
        await self._push("market_interval", {"interval": iv})
        for r in off_rows + bid_rows:
            await self._push("market_order", {"order": r})
        for t in trade_rows:
            await self._push("market_match", {"trade": self._trade_public(t, off_rows + bid_rows)})
        self._backlog += 1
        self._jobs.put_nowait(("post", iv["id"]))
        return {**base, "id": iv["id"]}

    @staticmethod
    def _order_row(iv: dict, side: str, o: engine.Order, remaining: int) -> dict:
        return {"interval_id": iv["id"], "side": side, "node_id": o.node_id, "qty_wh": o.qty_wh, "price_milli": o.price_milli,
                "remaining_wh": remaining, "status": "planned", "created_at": _now()}

    async def _close_interval(self, interval: dict) -> None:
        """Metered quantities = actual delivered energy, from this interval's readings."""
        hours = settings.market_interval_seconds / 3600.0
        iv_id = interval["id"]
        actual = {}
        for n in self._ids:
            samples = self._samples.get(n) or list(self._recent.get(n, ()))[-1:]
            actual[n] = self._mean(samples)
        sur = {n: engine.energy_wh(a, hours) for n, a in actual.items() if a is not None and a > 0}
        dfc = {n: engine.energy_wh(-a, hours) for n, a in actual.items() if a is not None and a < 0}
        trades = await store.select("market_trades", "interval_id = %s", (iv_id,), order="id ASC")
        matches = [engine.Match(0, 0, t["seller"], t["buyer"], t["matched_wh"], t["price_milli"]) for t in trades]
        meters = engine.allocate_metering(matches, sur, dfc)
        for t, (s, d) in zip(trades, meters):
            await store.update("market_trades", {"id": t["id"]}, meter_seller_wh=s, meter_buyer_wh=d)
        sold, bought = sum(s for s, _ in meters), sum(d for _, d in meters)
        summary = {
            "interval_hours": hours, "matched_wh": sum(m.qty_wh for m in matches),
            "metered_seller_wh": sold, "metered_buyer_wh": bought,
            "served_by_grid_wh": max(0, sum(dfc.values()) - bought),  # deficit not covered by a trade: bought from the grid (not on-chain)
            "exported_to_grid_wh": max(0, sum(sur.values()) - sold),  # surplus not sold: exported to the grid (not on-chain)
            "actual_mean_net_kw": {n: (None if a is None else round(a, 4)) for n, a in actual.items()},
        }
        iv = await store.update("market_intervals", {"id": iv_id}, status="closing", actuals={n: summary["actual_mean_net_kw"][n] for n in self._ids}, summary=summary)
        await self._push("market_interval", {"interval": iv})
        self._jobs.put_nowait(("settle", iv_id))

    # -- chain worker --------------------------------------------------------------------

    async def _worker(self) -> None:
        while True:
            kind, arg = await self._jobs.get()
            attempt = 0
            while True:
                await self._connected.wait()
                try:
                    await self._run(kind, arg)
                    break
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    msg = str(exc) if isinstance(exc, MarketChainUnavailable) else f"{type(exc).__name__}: {exc}"
                    if _is_revert(exc):
                        logger.warning("Prosumer market: %s %s rejected by the contract (%s)", kind, arg, msg)
                        await self._fail(kind, arg, msg)
                        break
                    logger.warning("Prosumer market: %s %s not done yet (%s); will retry", kind, arg, msg)
                    self.last_error = msg
                    await self._check_connection()
                    await asyncio.sleep(RETRY_BACKOFF_S[min(attempt, len(RETRY_BACKOFF_S) - 1)])
                    attempt += 1
            if kind == "settle":
                self._backlog = max(0, self._backlog - 1)

    async def _run(self, kind: str, arg) -> None:
        if kind == "register":
            await self._register_all()
        elif kind == "post":
            await self._run_post(arg)
        elif kind == "settle":
            await self._run_settle(arg)

    async def _fail(self, kind: str, arg, msg: str) -> None:
        if kind == "register":
            return
        try:
            iv = await store.update("market_intervals", {"id": arg}, status="failed", error=msg)
            await self._push("market_interval", {"interval": iv})
        except Exception:
            pass

    async def _push(self, type_: str, body: dict) -> None:
        await manager.broadcast({"type": type_, **body})

    async def _confirm_state(self, rc: dict) -> str:
        confs = await asyncio.to_thread(self.chain.confirmations, rc["block_number"])
        return "confirmed" if confs >= self.chain.required_confirmations else "in_block"

    # -- registration (EXISTENCE on chain) ---------------------------------------------------

    async def _register_all(self) -> None:
        c = self.chain
        dep = c.deployment_key
        for node_id in self._ids:
            addr = c.accounts[node_id].address
            row = None
            if self.db_ready:
                found = await store.select("market_prosumers", "node_id = %s AND deployment_key = %s", (node_id, dep), order="node_id", limit=1)
                row = found[0] if found else None
            if row and row["status"] == "confirmed":
                self._remember(row)
                continue
            on_chain = await asyncio.to_thread(c.account_of, node_id)
            if on_chain and on_chain.lower() == addr.lower():
                row = await self._save_reg(row, node_id, dep, address=addr, status="confirmed", registered_at=_now(),
                                           error="already registered on chain (registration tx not in the database)")
            else:
                tx = await asyncio.to_thread(c.register, node_id)
                row = await self._save_reg(row, node_id, dep, address=addr, status="pending", tx_hash=tx)
                rc = await asyncio.to_thread(c.wait_receipt, tx)
                if rc["status"] != 1:
                    await self._save_reg(row, node_id, dep, status="failed", error="registration transaction reverted")
                    continue
                row = await self._save_reg(row, node_id, dep, status="in_block", block_number=rc["block_number"], gas_used=rc["gas_used"],
                                           events=rc["events"], registered_at=_now())
                row = await self._save_reg(row, node_id, dep, status=await self._confirm_state(rc))
            self._remember(row)

    async def _save_reg(self, row: dict | None, node_id: str, dep: str, **fields) -> dict:
        merged = {**(row or {"node_id": node_id, "deployment_key": dep}), **fields}
        if self.db_ready:
            try:
                if row is None:
                    merged = await store.insert("market_prosumers", {"node_id": node_id, "deployment_key": dep, **fields})
                else:
                    merged = await store.update("market_prosumers", {"node_id": node_id, "deployment_key": dep}, **fields)
            except Exception as exc:
                logger.warning("Prosumer market: could not persist registration of %s: %s", node_id, exc)
        await self._push("market_registration", {"registration": merged})
        return merged

    def _remember(self, row: dict) -> None:
        self.registrations[row["node_id"]] = row
        if row["status"] in ("in_block", "confirmed"):
            digital_twin.set_onchain(row["node_id"], {
                "address": row.get("address"), "tx_hash": row.get("tx_hash"), "block_number": row.get("block_number"),
                "gas_used": row.get("gas_used"), "status": row["status"], "deployment_key": row.get("deployment_key")})

    # -- job: post orders + match (EXCHANGE on chain) ------------------------------------------

    async def _run_post(self, interval_id: int) -> None:
        c = self.chain
        await self._register_all()
        iv = await store.get("market_intervals", interval_id)
        if iv is None or iv["status"] in ("skipped", "failed"):
            return
        if iv["deployment_key"] and iv["deployment_key"] != c.deployment_key:
            iv = await store.update("market_intervals", {"id": interval_id}, status="skipped", error="the local chain was reset before this interval reached it")
            await self._push("market_interval", {"interval": iv})
            return
        ci = await asyncio.to_thread(c.current_interval)
        iv = await store.update("market_intervals", {"id": interval_id}, chain_interval=ci, deployment_key=c.deployment_key)
        await self._push("market_interval", {"interval": iv})

        for o in await store.select("market_orders", "interval_id = %s", (interval_id,), order="id ASC"):
            if o["block_number"] is None and o["status"] != "failed":
                await self._post_order(o)
        orders = await store.select("market_orders", "interval_id = %s", (interval_id,), order="id ASC")
        by_id = {o["id"]: o for o in orders}
        for t in await store.select("market_trades", "interval_id = %s", (interval_id,), order="id ASC"):
            if t["match_block"] is None and t["status"] != "failed":
                await self._match(t, by_id, orders)

    async def _post_order(self, o: dict) -> None:
        c = self.chain
        send = c.post_offer if o["side"] == "offer" else c.post_bid
        try:
            tx = await asyncio.to_thread(send, o["node_id"], o["qty_wh"], o["price_milli"])
        except Exception as exc:
            if _is_revert(exc):
                row = await store.update("market_orders", {"id": o["id"]}, status="failed", error=str(exc))
                await self._push("market_order", {"order": row})
                return
            raise
        row = await store.update("market_orders", {"id": o["id"]}, status="pending", tx_hash=tx, address=c.accounts[o["node_id"]].address)
        await self._push("market_order", {"order": row})
        rc = await asyncio.to_thread(c.wait_receipt, tx)
        if rc["status"] != 1:
            row = await store.update("market_orders", {"id": o["id"]}, status="failed", error="transaction reverted")
            await self._push("market_order", {"order": row})
            return
        ev = next((e for e in rc["events"] if e["event"] in ("OfferPosted", "BidPosted")), None)
        row = await store.update("market_orders", {"id": o["id"]}, status="in_block", block_number=rc["block_number"], gas_used=rc["gas_used"],
                                 events=rc["events"], chain_order_id=int(ev["args"]["id"]) if ev else None)
        await self._push("market_order", {"order": row})
        row = await store.update("market_orders", {"id": o["id"]}, status=await self._confirm_state(rc))
        await self._push("market_order", {"order": row})

    async def _match(self, t: dict, by_id: dict, orders: list[dict]) -> None:
        c = self.chain
        off, bid = by_id.get(t["offer_order_id"]), by_id.get(t["bid_order_id"])
        if not off or not bid or off["chain_order_id"] is None or bid["chain_order_id"] is None:
            row = await store.update("market_trades", {"id": t["id"]}, status="failed", error="its offer or bid is not on chain")
            await self._push("market_match", {"trade": self._trade_public(row, orders)})
            return
        tx = await asyncio.to_thread(c.match_trade, off["chain_order_id"], bid["chain_order_id"])
        row = await store.update("market_trades", {"id": t["id"]}, match_tx_hash=tx, step_status="pending")
        await self._push("market_match", {"trade": self._trade_public(row, orders)})
        rc = await asyncio.to_thread(c.wait_receipt, tx)
        if rc["status"] != 1:
            row = await store.update("market_trades", {"id": t["id"]}, status="failed", error="match transaction reverted")
        else:
            ev = next((e for e in rc["events"] if e["event"] == "TradeMatched"), None)
            row = await store.update("market_trades", {"id": t["id"]}, status="matched", step_status="in_block", match_block=rc["block_number"], match_gas=rc["gas_used"],
                                     chain_trade_id=int(ev["args"]["id"]) if ev else None, events=rc["events"])
            await self._push("market_match", {"trade": self._trade_public(row, orders)})
            row = await store.update("market_trades", {"id": t["id"]}, step_status=await self._confirm_state(rc))
        await self._push("market_match", {"trade": self._trade_public(row, orders)})

    # -- job: meter, settle, mirror, advance ---------------------------------------------------

    async def _run_settle(self, interval_id: int) -> None:
        c = self.chain
        iv = await store.get("market_intervals", interval_id)
        if iv is None or iv["status"] in ("skipped", "failed"):
            return
        orders = await store.select("market_orders", "interval_id = %s", (interval_id,), order="id ASC")
        for t in await store.select("market_trades", "interval_id = %s", (interval_id,), order="id ASC"):
            if t["status"] == "failed" or t["match_block"] is None or t["chain_trade_id"] is None:
                continue
            try:
                if t["meter_block"] is None:
                    t = await self._meter(t, orders)
                if t["settle_block"] is None and t["meter_block"] is not None:
                    t = await self._settle(t, orders)
            except Exception as exc:
                if _is_revert(exc):
                    t = await store.update("market_trades", {"id": t["id"]}, status="failed", error=f"{type(exc).__name__}: {exc}")
                    await self._push("market_settlement", {"trade": self._trade_public(t, orders)})
                    continue
                raise
            if t["status"] == "settled" and t["ledger_record_id"] is None and (t["settled_wh"] or 0) > 0:
                await self._mirror(t, iv, orders)

        if iv["advance_block"] is None:
            tx = await asyncio.to_thread(c.advance_interval)
            rc = await asyncio.to_thread(c.wait_receipt, tx)
            iv = await store.update("market_intervals", {"id": interval_id}, advance_tx_hash=tx, advance_block=rc["block_number"], advance_gas=rc["gas_used"])
        iv = await store.update("market_intervals", {"id": interval_id}, status="settled", error=None)
        await self._push("market_interval", {"interval": iv})

    async def _meter(self, t: dict, orders: list[dict]) -> dict:
        c = self.chain
        tx = await asyncio.to_thread(c.submit_meter, t["chain_trade_id"], t["meter_seller_wh"] or 0, t["meter_buyer_wh"] or 0)
        row = await store.update("market_trades", {"id": t["id"]}, meter_tx_hash=tx, step_status="pending")
        await self._push("market_settlement", {"trade": self._trade_public(row, orders)})
        rc = await asyncio.to_thread(c.wait_receipt, tx)
        if rc["status"] != 1:
            return await store.update("market_trades", {"id": t["id"]}, status="failed", error="meter transaction reverted")
        row = await store.update("market_trades", {"id": t["id"]}, status="metered", step_status=await self._confirm_state(rc),
                                 meter_block=rc["block_number"], meter_gas=rc["gas_used"], events=[*(t["events"] or []), *rc["events"]])
        await self._push("market_settlement", {"trade": self._trade_public(row, orders)})
        return row

    async def _settle(self, t: dict, orders: list[dict]) -> dict:
        c = self.chain
        tx = await asyncio.to_thread(c.settle, t["chain_trade_id"])
        row = await store.update("market_trades", {"id": t["id"]}, settle_tx_hash=tx, step_status="pending")
        await self._push("market_settlement", {"trade": self._trade_public(row, orders)})
        rc = await asyncio.to_thread(c.wait_receipt, tx)
        if rc["status"] != 1:
            return await store.update("market_trades", {"id": t["id"]}, status="failed", error="settle transaction reverted")
        ev = next((e for e in rc["events"] if e["event"] == "Settled"), None)
        row = await store.update("market_trades", {"id": t["id"]}, status="settled", step_status=await self._confirm_state(rc), settle_block=rc["block_number"],
                                 settle_gas=rc["gas_used"], settled_wh=int(ev["args"]["settledWh"]) if ev else None,
                                 pay_milli=int(ev["args"]["payMilli"]) if ev else None, settled_at=_now(), events=[*(t["events"] or []), *rc["events"]])
        await self._push("market_settlement", {"trade": self._trade_public(row, orders)})
        return row

    async def _mirror(self, t: dict, iv: dict, orders: list[dict]) -> None:
        """Mirror a SETTLED trade into EnergyLedger as a P2P_TRADE (Verify / integrity / tamper demo then cover it)."""
        if not ledger.enabled or ledger.client is None:
            return
        try:
            iv = await store.get("market_intervals", iv["id"]) or iv
            entry = events.live_market_trade(t, iv, self.chain.describe())
            rec = await ledger.record(entry)
            if rec is not None:
                t = await store.update("market_trades", {"id": t["id"]}, ledger_record_id=rec["id"])
                await self._push("market_settlement", {"trade": self._trade_public(t, orders)})
        except Exception as exc:
            logger.warning("Prosumer market: could not mirror trade %s into the ledger: %s", t["id"], exc)

    # -- public shapes ----------------------------------------------------------------------------

    def _trade_public(self, t: dict, orders: list[dict]) -> dict:
        """Trade row + its step-by-step journey (Registered -> ... -> Mirrored to ledger)."""
        def reg(node: str) -> dict:
            r = self.registrations.get(node) or {}
            return {"who": node, "tx_hash": r.get("tx_hash"), "block": r.get("block_number"), "gas": r.get("gas_used")}

        by_id = {o["id"]: o for o in orders}
        off, bid = by_id.get(t.get("offer_order_id")) or {}, by_id.get(t.get("bid_order_id")) or {}

        def step(key: str, label: str, tx: str | None, block, gas, extra=None, done: bool | None = None) -> dict:
            if t.get("status") == "failed" and not block:
                status = "failed" if tx or key in ("matched", "metered", "settled") else "pending"
            else:
                status = "done" if (done if done is not None else block is not None) else ("active" if tx else "pending")
            return {"key": key, "label": label, "status": status, "tx_hash": tx, "block": block, "gas": gas, "extra": extra}

        sreg, breg = reg(t["seller"]), reg(t["buyer"])
        journey = [
            step("registered", "Registered", sreg["tx_hash"], max(filter(None, [sreg["block"], breg["block"]]), default=None), sreg["gas"],
                 extra=[sreg, breg],
                 done=all((self.registrations.get(x) or {}).get("status") in ("in_block", "confirmed") for x in (t["seller"], t["buyer"]))),
            step("offer", "Offer", off.get("tx_hash"), off.get("block_number"), off.get("gas_used")),
            step("bid", "Bid", bid.get("tx_hash"), bid.get("block_number"), bid.get("gas_used")),
            step("matched", "Matched", t.get("match_tx_hash"), t.get("match_block"), t.get("match_gas")),
            step("metered", "Metered", t.get("meter_tx_hash"), t.get("meter_block"), t.get("meter_gas")),
            step("settled", "Settled", t.get("settle_tx_hash"), t.get("settle_block"), t.get("settle_gas")),
            step("mirrored", "Mirrored to ledger", None, None, None, extra={"ledger_record_id": t.get("ledger_record_id")}, done=t.get("ledger_record_id") is not None),
        ]
        return {**t, "journey": journey}

    async def status(self) -> dict:
        from app.ingestion import prosumer_source

        out = {
            "enabled": self.enabled, "state": self.state, "connected": self._connected.is_set(), "last_error": self.last_error,
            "db_ready": self.db_ready, "skipped_without_db": self.skipped_without_db,
            "interval_seconds": settings.market_interval_seconds, "last_run": self.last_run, "queue_depth": self._jobs.qsize(),
            "backlog_intervals": self._backlog, "role_deadband_kw": settings.prosumer_role_deadband_kw,
            "prices_demo_credits_per_kwh": settings.market_prices,
            "price_note": "Illustrative demo credits, not tariffs. Trade price = the seller's ask.",
            "irradiance_override": settings.prosumer_irradiance_override, "demo_irradiance": settings.prosumer_irradiance_override is not None,
            "weather": prosumer_source.current_weather(),
            "location": {"lat": settings.prosumer_lat, "lon": settings.prosumer_lon},
            "community_bus_capacity_kw": settings.community_bus_capacity_kw,
            "provenance_note": "Prosumers are simulated buildings: solar estimated from live weather, load synthetic. Amounts are demo credits.",
            "contract": self.chain.describe() if self.chain and self.chain.contract_address else None,
            "current_interval": None, "counts": None,
        }
        if self.db_ready:
            try:
                out["counts"] = await store.counts()
                current = await store.select("market_intervals", order="id DESC", limit=1)
                out["current_interval"] = current[0] if current else None
            except Exception as exc:
                out["db_error"] = str(exc)
        if self._connected.is_set():
            try:
                out["block_number"] = await asyncio.to_thread(self.chain.block_number)
            except Exception as exc:
                out["last_error"] = str(exc)
        return out

    async def prosumers(self) -> list[dict]:
        out = []
        for n in self._ids:
            node = digital_twin.get_node(n)
            reg = self.registrations.get(n)
            price = settings.market_prices.get(n, {})
            balance = None
            if reg and reg.get("address") and self._connected.is_set():
                try:
                    balance = await asyncio.to_thread(self.chain.balance_milli, reg["address"])
                except Exception:
                    balance = None
            out.append({**self.prosumer_view(node), "ask": price.get("ask"), "max": price.get("max"), "registration": reg,
                        "address": (reg or {}).get("address") or (self.chain.accounts[n].address if self.chain and n in self.chain.accounts else None),
                        "balance_milli": balance})
        return out


market = MarketService()
