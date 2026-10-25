"""Self-Healing Analytics: per-event record of every self-healing run on the LIVE 9-node twin.

Additive to app/twin/self_healing.py: that module calls start() / rerouting() / finish() around its existing
decision. Each event is kept in memory (newest last, capped) and pushed over the existing /ws/updates socket as
`healing_event` (same id re-sent as the status moves detected -> rerouting -> restored). Nothing here can fail a
self-healing decision: self_healing wraps every call in try/except.

Times: detect_ms = age of the node's latest reading when the fault was acted on (real); compute_ms = measured
time to generate + score the candidates and apply the winner (real); est_complete_ms = detect + compute + switching
time, where the switching time is an ASSUMED figure per switch operation (SWITCH_OP_MS), not measured.
"""

from collections import deque
from datetime import datetime, timezone
from time import perf_counter

from app.api.ws_manager import manager
from app.twin.digital_twin import GRID

SWITCH_OP_MS = 500.0  # assumed time for one breaker/switch operation (no switch hardware exists)
_MAX_EVENTS = 200
_events: deque[dict] = deque(maxlen=_MAX_EVENTS)
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
        "time": datetime.now(timezone.utc).isoformat(),
        "problem": "Predicted equipment fault (TA-GNN)" if status == "fault_predicted" else "Equipment fault / node outage",
        "fixture": node["node_id"],
        "detect_ms": round(_age_ms(node), 1),
        "compute_ms": None,
        "reroute_ms": None,
        "est_complete_ms": None,
        "action": None,
        "path": None,
        "status": "detected",
        "_t0": perf_counter(),
    }
    _events.append(event)
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
        ops = 2  # open the old feeder, close the new one
        event["path"] = {"from": node_id, "to": GRID, "via": via, "lines": [[node_id, via], [via, GRID]], "isolated_lines": old_line}
    elif action == "isolate":
        ops = 1
        event["path"] = {"from": node_id, "to": None, "via": None, "lines": [], "isolated_lines": old_line}
    else:  # reduce_load_share: stays on its bus at a reduced share
        ops = 1
        event["path"] = {"from": node_id, "to": GRID, "via": prev, "lines": [[node_id, prev], [prev, GRID]] if prev else [], "isolated_lines": []}
    event["action"] = action
    event["est_complete_ms"] = round(event["reroute_ms"] + ops * SWITCH_OP_MS, 1)
    event["status"] = "restored"
    await _push(_public(event))


def _public(event: dict) -> dict:
    return {k: v for k, v in event.items() if not k.startswith("_")}
