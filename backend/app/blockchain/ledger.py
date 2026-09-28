"""Module 5 ledger service: queue -> submit -> receipt -> confirm -> verify.

Non-blocking by design. Hooks (`submit_nowait`) only schedule work; one worker
task sends transactions sequentially (no nonce races); every Web3 call runs in
a thread. If the node is unreachable, records stay "queued" in TimescaleDB with
the error, the status goes to "unreachable" (pushed as `chain_status`), and the
worker resumes as soon as the health loop reconnects. Queued/submitted records
are re-enqueued on backend restart.

WebSocket messages on /ws/updates:
  {"type": "chain_record", "record": {...}}   new record or any status change
  {"type": "chain_status", "status": {...}}   connection / integrity changes
"""

import asyncio
import logging
from datetime import datetime, timezone

from app.api.ws_manager import manager
from app.blockchain import events, store
from app.blockchain.chain_client import ChainClient, ChainUnavailable
from app.blockchain.hashing import normalize, payload_hash
from app.config import settings

logger = logging.getLogger("sei")

HEALTH_INTERVAL_S = 5.0
RETRY_BACKOFF_S = (2, 5, 10, 20, 30)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _chain_error(exc: Exception) -> str:
    return str(exc) if isinstance(exc, ChainUnavailable) else f"{type(exc).__name__}: {exc}"


class Ledger:
    def __init__(self) -> None:
        self.enabled = settings.blockchain_enabled
        self.client: ChainClient | None = None
        self.state = "disabled" if not self.enabled else "starting"
        self.last_error: str | None = None
        self.db_ready = False
        self.skipped_without_db = 0
        self.integrity: dict | None = None
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._connected = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._pending_tasks: set[asyncio.Task] = set()

    @property
    def dev_tools(self) -> bool:
        if settings.blockchain_dev_tools is not None:
            return settings.blockchain_dev_tools
        return settings.blockchain_network.lower() == "local"

    # -- lifecycle ------------------------------------------------------

    async def start(self) -> None:
        if not self.enabled:
            logger.info("Module 5: blockchain ledger disabled (BLOCKCHAIN_ENABLED=false)")
            return
        try:
            self.client = ChainClient()
        except ValueError as exc:
            self.state, self.last_error = "misconfigured", str(exc)
            logger.warning("Module 5: %s", exc)
            return
        try:
            await store.init_schema()
            self.db_ready = True
            for row in await store.pending():
                self._queue.put_nowait(row["id"])
        except Exception as exc:
            logger.warning("Module 5: chain_records table unavailable (TimescaleDB down?): %s", exc)
        # First connection attempt runs in the background (the RPC timeout is
        # 10 s) so an unreachable node never delays backend startup.
        self._tasks.append(asyncio.create_task(self._check_connection()))
        self._tasks.append(asyncio.create_task(self._worker()))
        self._tasks.append(asyncio.create_task(self._health_loop()))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()

    # -- recording --------------------------------------------------------

    def submit_nowait(self, *builders: tuple) -> None:
        """Fire-and-forget from the twin's code path. Each builder is
        (entry_factory, *args); entries are built now (from the caller's
        snapshot) and recorded IN ORDER by one task. Failures are logged,
        never raised into the caller."""
        if not self.enabled or self.client is None:
            return
        entries = []
        for factory, *args in builders:
            try:
                entries.append(factory(*args))
            except Exception as exc:
                logger.warning("Module 5: could not build ledger entry (%s): %s", getattr(factory, "__name__", "?"), exc)
        if not entries:
            return
        task = asyncio.create_task(self._safe_record_all(entries))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _safe_record_all(self, entries: list[dict]) -> None:
        for entry in entries:
            await self._safe_record(entry)

    async def _safe_record(self, entry: dict) -> None:
        try:
            await self.record(entry)
        except Exception as exc:
            logger.warning("Module 5: failed to record %s: %s", entry.get("event_type"), exc)

    async def record(self, entry: dict) -> dict | None:
        """Persist the payload + fingerprint, push it, and queue it for the chain.
        Returns the new row (None if a dedupe_key already existed or no DB)."""
        if not self.db_ready:
            if not await self._retry_db_init():
                self.skipped_without_db += 1
                logger.warning("Module 5: TimescaleDB unavailable, %s not recorded", entry["event_type"])
                return None
        payload = normalize(entry["payload"])
        row = await store.insert(
            {
                "created_at": _now(),
                "event_type": entry["event_type"],
                "actor": entry["actor"],
                "provenance": entry["provenance"],
                "summary": entry["summary"],
                "source_ref": entry.get("source_ref"),
                "dedupe_key": entry.get("dedupe_key"),
                "payload": payload,
                "payload_hash": payload_hash(payload),
            }
        )
        if row is None:
            return None
        await self._push_record(row)
        self._queue.put_nowait(row["id"])
        return row

    async def _retry_db_init(self) -> bool:
        try:
            await store.init_schema()
            self.db_ready = True
        except Exception:
            self.db_ready = False
        return self.db_ready

    # -- worker -----------------------------------------------------------

    async def _worker(self) -> None:
        while True:
            record_id = await self._queue.get()
            attempt = 0
            while True:
                await self._connected.wait()
                try:
                    requeue_after = await self._process(record_id)
                    if requeue_after is not None:
                        asyncio.get_running_loop().call_later(requeue_after, self._queue.put_nowait, record_id)
                    break
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    msg = _chain_error(exc)
                    logger.warning("Module 5: record %s not sent yet (%s); will retry", record_id, msg)
                    try:
                        row = await store.update(record_id, last_error=msg)
                        if row:
                            await self._push_record(row)
                    except Exception:
                        pass
                    await self._check_connection()
                    await asyncio.sleep(RETRY_BACKOFF_S[min(attempt, len(RETRY_BACKOFF_S) - 1)])
                    attempt += 1

    async def _process(self, record_id: int) -> float | None:
        """Drive one record as far as it can go. Returns seconds after which to
        look at it again (receipt not yet available), or None when done."""
        row = await store.get(record_id)
        if row is None or row["status"] in ("included", "confirmed", "failed"):
            return None
        client = self.client

        if row["status"] == "submitted" and row["tx_hash"]:
            if row["deployment_key"] != client.deployment_key:
                # Submitted to a chain that no longer exists (local node restarted):
                # the tx is gone; send it again to the current contract.
                row = await store.update(record_id, status="queued", tx_hash=None,
                                         last_error="previous local chain was reset; resubmitting")
            else:
                receipt = await asyncio.to_thread(client.get_receipt, row["tx_hash"])
                if receipt is None:
                    return 5.0 if client.network == "sepolia" else 1.0
                await self._apply_receipt(row, receipt)
                return None

        tx_hash = await asyncio.to_thread(client.send_append, row["event_type"], row["payload_hash"], row["actor"])
        row = await store.update(
            record_id,
            status="submitted",
            tx_hash=tx_hash,
            network=client.network,
            chain_id=client.chain_id,
            contract_address=client.contract_address,
            deployment_key=client.deployment_key,
            submitted_at=_now(),
            attempts=(row["attempts"] or 0) + 1,
            last_error=None,
        )
        await self._push_record(row)

        timeout = 30 if client.network == "local" else 180
        try:
            receipt = await asyncio.to_thread(client.wait_receipt, tx_hash, timeout)
        except Exception as exc:
            if type(exc).__name__ == "TimeExhausted":
                return 10.0  # still pending in the mempool; look again later
            raise
        await self._apply_receipt(row, receipt)
        return None

    async def _apply_receipt(self, row: dict, receipt: dict) -> None:
        client = self.client
        if receipt["status"] != 1:
            row = await store.update(row["id"], status="failed", block_number=receipt["block_number"],
                                     block_hash=receipt["block_hash"], gas_used=receipt["gas_used"],
                                     last_error="transaction reverted on-chain")
            await self._push_record(row)
            return
        latest = await asyncio.to_thread(client.block_number)
        block_time = await asyncio.to_thread(client.block_timestamp, receipt["block_number"])
        confirmations = max(0, latest - receipt["block_number"] + 1)
        locked = confirmations >= client.required_confirmations
        row = await store.update(
            row["id"],
            status="confirmed" if locked else "included",
            chain_record_id=receipt["chain_record_id"],
            block_number=receipt["block_number"],
            block_hash=receipt["block_hash"],
            gas_used=receipt["gas_used"],
            included_at=_now(),
            block_timestamp=block_time,
            confirmations=confirmations,
            confirmed_at=_now() if locked else None,
            last_error=None,
        )
        await self._push_record(row)
        if locked:
            await self._push_status()

    async def _update_confirmations(self) -> None:
        if not self.db_ready:
            return
        rows = await store.awaiting_confirmations()
        if not rows:
            return
        latest = await asyncio.to_thread(self.client.block_number)
        for row in rows:
            if row["deployment_key"] != self.client.deployment_key:
                continue
            confirmations = max(0, latest - row["block_number"] + 1)
            if confirmations == row["confirmations"]:
                continue
            locked = confirmations >= self.client.required_confirmations
            row = await store.update(row["id"], confirmations=confirmations,
                                     status="confirmed" if locked else "included",
                                     confirmed_at=_now() if locked else None)
            await self._push_record(row)

    # -- connection health ------------------------------------------------------

    async def _health_loop(self) -> None:
        while True:
            await asyncio.sleep(HEALTH_INTERVAL_S)
            try:
                await self._check_connection()
                if self._connected.is_set():
                    await self._update_confirmations()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("Module 5 health loop: %s", exc)

    async def _check_connection(self) -> None:
        before = (self.state, self.client.deployment_key if self.client else None)
        try:
            await asyncio.to_thread(self.client.ensure)
            if not self._connected.is_set():
                await self._backfill_deployment_keys()
            self.state, self.last_error = "connected", None
            self._connected.set()
        except Exception as exc:
            self.state = "unreachable"
            self.last_error = _chain_error(exc)
            self._connected.clear()
        if (self.state, self.client.deployment_key) != before:
            if self.state == "connected":
                logger.info("Module 5: connected to %s, EnergyLedger at %s", self.client.network, self.client.contract_address)
            else:
                logger.warning("Module 5: chain unavailable: %s", self.last_error)
            await self._push_status(check_integrity=self.state == "connected")

    async def _backfill_deployment_keys(self) -> None:
        """Rows sent before deployment_key existed: tag them with the current
        deployment if their tx is in the same block on this chain, otherwise
        mark them as belonging to a previous (reset) chain."""
        if not self.db_ready:
            return
        try:
            rows = await store.missing_deployment_key()
        except Exception:
            return
        for row in rows:
            receipt = await asyncio.to_thread(self.client.get_receipt, row["tx_hash"])
            same_chain = receipt is not None and (row["block_hash"] is None or receipt["block_hash"] == row["block_hash"])
            key = self.client.deployment_key if same_chain else f"{row['contract_address']}@previous-chain"
            await store.update(row["id"], deployment_key=key)

    # -- verification -----------------------------------------------------------

    async def verify_record(self, record_id: int) -> dict:
        row = await store.get(record_id)
        if row is None:
            raise KeyError(record_id)
        recomputed = payload_hash(row["payload"])
        detail = {
            "checked_at": _now().isoformat(),
            "recomputed_hash": recomputed,
            "hash_at_submission": row["payload_hash"],
            "onchain_hash": None,
            "chain_record_id": row["chain_record_id"],
        }
        if row["status"] not in ("included", "confirmed") or row["chain_record_id"] is None:
            result = "not_on_chain_yet"
            detail["explanation"] = "This record has not been written to a block yet, so there is nothing to compare against."
        elif row["deployment_key"] != (self.client.deployment_key if self.client else None):
            result = "unavailable"
            detail["explanation"] = ("This record was written to an earlier ledger contract that is no longer on the "
                                     "connected chain (the local dev node was restarted).")
        elif not self._connected.is_set():
            result = "unavailable"
            detail["explanation"] = f"The blockchain node is unreachable right now ({self.last_error})."
        else:
            try:
                onchain = await asyncio.to_thread(self.client.get_record, int(row["chain_record_id"]))
            except Exception as exc:
                onchain = None
                result = "unavailable"
                detail["explanation"] = f"Could not read the on-chain record: {_chain_error(exc)}"
            if onchain is not None:
                detail["onchain_hash"] = onchain["payload_hash"]
                detail["onchain_actor"] = onchain["actor"]
                detail["onchain_event_type"] = onchain["event_type"]
                detail["onchain_timestamp"] = datetime.fromtimestamp(onchain["timestamp"], tz=timezone.utc).isoformat()
                if onchain["payload_hash"].lower() == recomputed.lower():
                    result = "match"
                    detail["explanation"] = ("The stored data produces exactly the fingerprint locked on the blockchain: "
                                             "it has not been changed since it was recorded.")
                else:
                    result = "mismatch"
                    detail["explanation"] = ("The stored data no longer produces the fingerprint locked on the blockchain: "
                                             "the off-chain copy was changed after it was recorded.")
        row = await store.update(record_id, verified_at=_now(), verify_result=result, verify_detail=detail)
        await self._push_record(row)
        if result in ("match", "mismatch"):
            await self._push_status(check_integrity=True)
        return {"record_id": record_id, "result": result, **detail}

    async def integrity_check(self) -> dict:
        """Re-hash every stored payload of the current contract and compare with
        the chain; also detect records present on-chain but missing off-chain."""
        if not self.db_ready or not self._connected.is_set():
            return {"state": "unknown", "checked_at": _now().isoformat(),
                    "reason": "database or chain unavailable"}
        rows = await store.confirmed_for_deployment(self.client.deployment_key)

        def _check() -> tuple[list[int], int]:
            bad = []
            for r in rows:
                if r["chain_record_id"] is None:
                    continue
                onchain = self.client.get_record(int(r["chain_record_id"]))
                if onchain["payload_hash"].lower() != payload_hash(r["payload"]).lower():
                    bad.append(r["id"])
            return bad, self.client.record_count()

        mismatched, onchain_count = await asyncio.to_thread(_check)
        missing_offchain = max(0, onchain_count - len(rows)) if len(rows) < 500 else 0
        self.integrity = {
            "state": "intact" if not mismatched and not missing_offchain else "compromised",
            "checked_records": len(rows),
            "onchain_records": onchain_count,
            "mismatched_record_ids": mismatched,
            "missing_offchain": missing_offchain,
            "checked_at": _now().isoformat(),
        }
        return self.integrity

    # -- dev-only tamper demo --------------------------------------------------------

    async def tamper(self, record_id: int) -> dict:
        row = await store.get(record_id)
        if row is None:
            raise KeyError(record_id)
        payload = dict(row["payload"])
        et = row["event_type"]
        if et == "P2P_TRADE":
            field, old = "kwh", payload.get("kwh")
            payload["kwh"] = round((old or 1) * 10, 2)
        elif et == "ENERGY_REDISTRIBUTION":
            field, old = "kw_affected", payload.get("kw_affected")
            payload["kw_affected"] = round((old or 0) + 500, 1)
        elif et == "FAULT_ALERT":
            field, old = "health_status", payload.get("health_status")
            payload["health_status"] = "normal"
        else:
            weights = dict(payload.get("client_weights") or {})
            key = sorted(weights)[0] if weights else "T1"
            field, old = f"client_weights.{key}", weights.get(key)
            weights[key] = 0.99
            payload["client_weights"] = weights
        new = payload["client_weights"].get(field.split(".")[1]) if field.startswith("client_weights.") else payload[field]
        detail = {"field": field, "old_value": old, "new_value": new, "at": _now().isoformat(),
                  "note": "DEV-ONLY tamper demo: the OFF-CHAIN copy in TimescaleDB was edited. The blockchain copy cannot be edited."}
        row = await store.update(record_id, payload=payload, tampered_at=_now(), tamper_detail=detail,
                                 verify_result=None, verify_detail=None, verified_at=None)
        await self._push_record(row)
        return detail

    # -- status / public shapes -----------------------------------------------------

    async def status(self, check_integrity: bool = False) -> dict:
        info = self.client.describe() if self.client else {"network": settings.blockchain_network}
        out = {
            "enabled": self.enabled,
            "state": self.state,
            "connected": self._connected.is_set(),
            "last_error": self.last_error,
            **info,
            "dev_tools": self.dev_tools,
            "db_ready": self.db_ready,
            "queue_depth": self._queue.qsize(),
            "skipped_without_db": self.skipped_without_db,
            "provenance_labels": events.PROVENANCE_NOTES,
        }
        if self._connected.is_set():
            try:
                out["block_number"] = await asyncio.to_thread(self.client.block_number)
                out["onchain_record_count"] = await asyncio.to_thread(self.client.record_count)
            except Exception as exc:
                out["last_error"] = _chain_error(exc)
        if self.db_ready:
            try:
                out["offchain"] = await store.counts()
            except Exception as exc:
                out["offchain"] = None
                out["db_error"] = str(exc)
        if check_integrity:
            try:
                await self.integrity_check()
            except Exception as exc:
                self.integrity = {"state": "unknown", "reason": _chain_error(exc), "checked_at": _now().isoformat()}
        out["integrity"] = self.integrity
        return out

    def public(self, row: dict) -> dict:
        current = self.client.deployment_key if self.client else None
        required = self.client.required_confirmations if self.client else None
        return {
            **row,
            "required_confirmations": required,
            "locked": row["status"] == "confirmed",
            "deployment_current": row["deployment_key"] is None or row["deployment_key"] == current,
            "explorer_url": self.client.explorer_tx_url(row["tx_hash"]) if self.client else None,
        }

    def steps(self, row: dict) -> list[dict]:
        """The record's journey, one entry per step (status: done | active | pending | failed)."""
        s = row["status"]
        on_chain = s in ("included", "confirmed")
        tx_status = "done" if row["tx_hash"] else ("active" if row["last_error"] or row["attempts"] else "pending")
        if s == "failed":
            block_status = "failed"
        elif on_chain:
            block_status = "done"
        else:
            block_status = "active" if s == "submitted" else "pending"
        verify = row["verify_result"]
        return [
            {"n": 1, "key": "what_happened", "status": "done", "at": row["created_at"],
             "data": {"summary": row["summary"], "event_type": row["event_type"], "actor": row["actor"],
                      "source_ref": row["source_ref"], "provenance": row["provenance"]}},
            {"n": 2, "key": "data_packaged", "status": "done", "at": row["created_at"],
             "data": {"payload": row["payload"]}},
            {"n": 3, "key": "fingerprint", "status": "done", "at": row["created_at"],
             "data": {"payload_hash": row["payload_hash"], "algorithm": "keccak256 over canonical JSON (sorted keys, no spaces, UTF-8)"}},
            {"n": 4, "key": "tx_sent", "status": tx_status, "at": row["submitted_at"],
             "data": {"tx_hash": row["tx_hash"], "network": row["network"], "attempts": row["attempts"],
                      "last_error": row["last_error"], "explorer_url": self.client.explorer_tx_url(row["tx_hash"]) if self.client else None}},
            {"n": 5, "key": "in_block", "status": block_status, "at": row["included_at"],
             "data": {"block_number": row["block_number"], "block_hash": row["block_hash"], "gas_used": row["gas_used"], "block_timestamp": row.get("block_timestamp"),
                      "chain_record_id": row["chain_record_id"], "contract_address": row["contract_address"]}},
            {"n": 6, "key": "confirmed_locked", "status": "done" if s == "confirmed" else ("active" if s == "included" else "pending"),
             "at": row["confirmed_at"],
             "data": {"confirmations": row["confirmations"], "required_confirmations": self.client.required_confirmations if self.client else None}},
            {"n": 7, "key": "verified", "status": {"match": "done", "mismatch": "failed"}.get(verify, "pending"),
             "at": row["verified_at"], "data": {"result": verify, **(row["verify_detail"] or {})}},
        ]

    async def _push_record(self, row: dict | None) -> None:
        if row is not None:
            await manager.broadcast({"type": "chain_record", "record": self.public(row)})

    async def _push_status(self, check_integrity: bool = False) -> None:
        try:
            await manager.broadcast({"type": "chain_status", "status": await self.status(check_integrity=check_integrity)})
        except Exception as exc:
            logger.debug("Module 5: status push failed: %s", exc)


ledger = Ledger()


# -- twin hook ------------------------------------------------------------------


def on_self_healing(node_before: dict, decision: dict) -> None:
    """Called by the Module 2 self-healing layer after a decision is logged.
    Records the fault that triggered it and the redistribution itself.
    Never raises, never waits on the chain."""
    try:
        ledger.submit_nowait(
            (events.fault_alert, node_before, decision.get("trigger_summary") or "", decision["time"]),
            (events.energy_redistribution, node_before, decision),
        )
    except Exception as exc:
        logger.warning("Module 5 hook failed (ignored): %s", exc)
