"""Self-Healing Analytics: per-event record of every self-healing run on the LIVE 9-node twin.

Additive to app/twin/self_healing.py: that module calls start() / rerouting() / finish() around its existing
decision. Each event is kept in memory (newest last, capped) and pushed over the existing /ws/updates socket as
`healing_event` (same id re-sent as the status moves detected -> rerouting -> restored). Nothing here can fail a
self-healing decision: self_healing wraps every call in try/except.

Times: detect_ms = age of the node's latest reading when the fault was acted on (real); compute_ms = measured
time to generate + score the candidates and apply the winner (real); est_complete_ms = detect + compute + switching
time, where the switching time is an ASSUMED figure per switch operation (SWITCH_OP_MS), not measured.

Live protection events (app/twin/grid_protection.py: bus overload / node fault / line fault) use the same record but
carry more: `kind`, `why`, an ordered `steps` list (OPEN / CLOSE / ISOLATE / CURTAIL, each `done` with `at_ms` since the
fault), `impact` (bus load before / after) and an `incident` lifecycle (active -> repairing -> repaired, with
`repaired_ms` / `outage_ms`). Their switching is EXECUTED step by step with SWITCH_OP_MS of simulated switch time each,
so their `est_complete_ms` is the measured wall-clock fault -> restored time (which includes those simulated times).
"""

import asyncio
from collections import deque
from datetime import datetime, timezone
from time import perf_counter

from app.api.ws_manager import manager
from app.twin.digital_twin import GRID

SWITCH_OP_MS = 500.0  # assumed time for one breaker/switch operation (no switch hardware exists)
_MAX_EVENTS = 200
_events: deque[dict] = deque(maxlen=_MAX_EVENTS)
_open_by_fixture: dict[str, dict] = {}  # fixture -> its active incident (isolated node / faulted line / overloaded bus)
_seq = 0


def list_events() -> list[dict]:
    return list(_events)


def _age_ms(node: dict) -> float:
    try:
        return max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(node["last_updated"])).total_seconds() * 1000)
    except Exception:
        return 0.0


async def _push(event: dict) -> None:
    await manager.broadcast({"type": "healing_event", "event": event})


async def start(node: dict) -> dict:
    global _seq
    _seq += 1
    status = node["health_status"]
    event = {
        "id": f"live-{_seq}",
        "topology": "live",
        "kind": "node_fault",
        "simulated": False,
        "time": datetime.now(timezone.utc).isoformat(),
        "problem": "Predicted equipment fault (TA-GNN)" if status == "fault_predicted" else "Equipment fault / node outage",
        "why": f"{node['node_id']} health status went to '{status}' -> the faulty node is isolated until it is fixed",
        "fixture": node["node_id"],
        "detect_ms": round(_age_ms(node), 1),
        "compute_ms": None,
        "reroute_ms": None,
        "est_complete_ms": None,
        "action": None,
        "path": None,
        "steps": [],
        "impact": None,
        "incident": "active",
        "repaired_ms": None,
        "status": "detected",
        "_t0": perf_counter(),
    }
    _events.append(event)
    _open_by_fixture[node["node_id"]] = event
    await _push(_public(event))
    return event


async def rerouting(event: dict) -> None:
    event["status"] = "rerouting"
    await _push(_public(event))


async def finish(event: dict, node: dict, chosen: dict) -> None:
    """`node` is the pre-decision snapshot (its active_connection is the route that was cut)."""
    node_id, prev, action = node["node_id"], node.get("active_connection"), chosen["action"]
    event["compute_ms"] = round((perf_counter() - event["_t0"]) * 1000, 2)
    event["reroute_ms"] = round(event["detect_ms"] + event["compute_ms"], 2)
    old_line = [[node_id, prev]] if prev else []
    if action == "reroute":
        via = chosen["params"]["via"]
        steps = [("OPEN", f"Open feeder switch {node_id}–{prev}"), ("CLOSE", f"Close tie switch {node_id}–{via}")]
        event["path"] = {"from": node_id, "to": GRID, "via": via, "lines": [[node_id, via], [via, GRID]], "isolated_lines": old_line}
    elif action == "isolate":
        steps = [("OPEN", f"Open switch at {node_id} end of {node_id}–{prev}"), ("OPEN", f"Open switch at {prev} end of {node_id}–{prev}")] if prev else []
        event["path"] = {"from": node_id, "to": None, "via": None, "lines": [], "isolated_lines": old_line}
    else:  # reduce_load_share: stays on its bus at a reduced share
        steps = [("CURTAIL", f"Curtail {node_id} to {chosen['params']['fraction'] * 100:.0f}% of rated")]
        event["path"] = {"from": node_id, "to": GRID, "via": prev, "lines": [[node_id, prev], [prev, GRID]] if prev else [], "isolated_lines": []}
    event["action"] = action
    # The twin applies the decision instantly; the step times below are the ASSUMED cumulative switch times.
    event["steps"] = [{"op": op, "text": text, "state": "done", "at_ms": round(event["reroute_ms"] + (i + 1) * SWITCH_OP_MS, 1)} for i, (op, text) in enumerate(steps)]
    event["est_complete_ms"] = round(event["reroute_ms"] + len(steps) * SWITCH_OP_MS, 1)
    event["status"] = "restored"
    await _push(_public(event))


def _public(event: dict) -> dict:
    return {k: v for k, v in event.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------------------------------------------
# Incident lifecycle helpers (used by grid_protection.py and by self_healing's recovery path)
# ---------------------------------------------------------------------------------------------------------------

def find_open(fixture: str) -> dict | None:
    ev = _open_by_fixture.get(fixture)
    return ev if ev and ev.get("incident") == "active" else None


def get_event(event_id: str) -> dict | None:
    return next((e for e in _events if e["id"] == event_id), None)


async def open_event(kind: str, fixture: str, problem: str, why: str, *, t0: float, simulated: bool, impact_before: dict) -> dict:
    """New event for a protection incident. `t0` = perf_counter() at the moment the fault condition appeared."""
    global _seq
    _seq += 1
    event = {
        "id": f"live-{_seq}", "topology": "live", "kind": kind, "simulated": simulated,
        "time": datetime.now(timezone.utc).isoformat(), "problem": problem, "why": why, "fixture": fixture,
        "detect_ms": round((perf_counter() - t0) * 1000, 2), "compute_ms": None, "reroute_ms": None, "est_complete_ms": None,
        "action": None, "path": None, "status": "detected", "steps": [],
        "impact": {"before": impact_before, "after": None, "moved_kw": 0.0, "unserved_kw": 0.0},
        "incident": "active", "repaired_ms": None, "outage_ms": None, "_t0": t0,
    }
    _events.append(event)
    _open_by_fixture[fixture] = event
    await _push(_public(event))
    return event


async def set_plan(event: dict, steps: list[tuple[str, str]], path: dict | None, action: str) -> None:
    """Analysis done (compute_ms). The switch steps are listed as pending; execution then marks them done one by one."""
    event["compute_ms"] = round((perf_counter() - event["_t0"]) * 1000 - event["detect_ms"], 2)
    event["reroute_ms"] = round(event["detect_ms"] + event["compute_ms"], 2)
    event["steps"] = [{"op": op, "text": text, "state": "pending", "at_ms": None} for op, text in steps]
    event["path"], event["action"], event["status"] = path, action, "rerouting"
    await _push(_public(event))


async def step_done(event: dict, i: int) -> None:
    event["steps"][i].update(state="done", at_ms=round((perf_counter() - event["_t0"]) * 1000, 1))
    await _push(_public(event))


async def complete(event: dict, impact_after: dict, moved_kw: float, unserved_kw: float, note: str | None = None) -> None:
    event["impact"].update({"after": impact_after, "moved_kw": round(moved_kw, 1), "unserved_kw": round(unserved_kw, 1)})
    event["est_complete_ms"] = round((perf_counter() - event["_t0"]) * 1000, 1)
    if note:
        event["note"] = note
    event["status"] = "restored"
    await _push(_public(event))


async def repair(event: dict, steps: list[tuple[str, str]], apply) -> None:
    """Run the repair switching (`apply(i)` performs step i on the twin), then close the incident."""
    t_rep = perf_counter()
    event["repair_steps"] = [{"op": op, "text": text, "state": "pending", "at_ms": None} for op, text in steps]
    event["incident"] = "repairing"
    await _push(_public(event))
    for i in range(len(steps)):
        await asyncio.sleep(SWITCH_OP_MS / 1000)
        apply(i)
        event["repair_steps"][i].update(state="done", at_ms=round((perf_counter() - t_rep) * 1000, 1))
        await _push(_public(event))
    now = datetime.now(timezone.utc)
    event["incident"] = "repaired"
    event["repaired_at"] = now.isoformat()
    event["repaired_ms"] = round((perf_counter() - t_rep) * 1000, 1)
    event["outage_ms"] = round((now - datetime.fromisoformat(event["time"])).total_seconds() * 1000 + event["detect_ms"], 1)
    if _open_by_fixture.get(event["fixture"]) is event:
        del _open_by_fixture[event["fixture"]]
    await _push(_public(event))
