"""Module 2 Stage 2 — self-healing decision layer.

Reacts to the digital twin's own state (app/twin/digital_twin.py), not
Module 1's graph. `maybe_trigger()` is called from the ingestion pipeline
right after every digital-twin state update; it only actually acts when a
node's health_status *transitions into* "fault" or "fault_predicted" (edge-
triggered), not on every subsequent reading while it stays faulted — the
Kelmarsh replay can hold a node in "fault" for many ticks in a row, and
re-deciding + re-logging identically each tick would just spam the decision
log without saying anything new.

No human-approval gate in this basic pass, per architecture scope — see the
human-override comments on DigitalTwin.reroute_node/isolate_node/
set_load_share. Before any of this drives real actuation hardware, a
human-approval step belongs between `_choose_best` and `_apply`.
"""

import logging
from datetime import datetime, timezone

from app import db
from app.api.ws_manager import manager
from app.twin.digital_twin import BUS_A, BUS_B, BUS_CAPACITY_KW, digital_twin

logger = logging.getLogger("sei")

_FAULT_STATES = {"fault", "fault_predicted"}
_last_health_status: dict[str, str] = {}

# "Reduce load share" candidate: halve the node's contribution as a fixed,
# simple demo figure — not derived from any real curtailment constraint.
CURTAIL_FRACTION = 0.5

# Equal weights: a basic, explainable weighted-sum scoring function per
# architecture scope, not a solver. Unserved load and bus overload are
# both expressed in kW so the weights are directly comparable; tune here if
# one should matter more than the other.
WEIGHT_UNSERVED = 1.0
WEIGHT_OVERLOAD = 1.0


async def maybe_trigger(node_id: str) -> None:
    node = digital_twin.get_node(node_id)
    status = node["health_status"]
    previous = _last_health_status.get(node_id, "normal")
    _last_health_status[node_id] = status

    if status not in _FAULT_STATES or previous in _FAULT_STATES:
        return

    await _handle_fault(node)


async def _handle_fault(node: dict) -> None:
    node_id = node["node_id"]
    candidates = _generate_candidates(node)
    scored = [(_score(node, c), c) for c in candidates]
    (best_unserved, best_overload), best = min(scored, key=lambda pair: _combined(pair[0]))

    updated_node = _apply(node_id, best)
    # The reconfiguration itself (new active_connection/isolated/load_share,
    # and the knock-on change to both buses' current_load_kw) needs its own
    # push — pipeline.py's twin_node_update broadcast already fired for
    # this reading *before* this decision was made, so the frontend
    # wouldn't otherwise see the routing/load change until its next
    # unrelated update.
    await manager.broadcast({"type": "twin_node_update", "node": updated_node})
    for bus_id in (BUS_A, BUS_B):
        await manager.broadcast({"type": "twin_node_update", "node": digital_twin.get_node(bus_id)})

    decision = {
        "time": datetime.now(timezone.utc),
        "node_id": node_id,
        "trigger_health_status": node["health_status"],
        "trigger_summary": _trigger_summary(node),
        "candidates": [
            {
                "action": c["action"],
                "params": c["params"],
                "unserved_kw": round(u, 1),
                "overload_kw": round(o, 1),
                "score": round(_combined((u, o)), 1),
            }
            for (u, o), c in scored
        ],
        "chosen_action": best["action"],
        "chosen_params": best["params"],
        "chosen_score": round(_combined((best_unserved, best_overload)), 1),
        "reason": _reason(best, scored),
    }

    await _record(decision)


def _combined(score: tuple[float, float]) -> float:
    unserved, overload = score
    return WEIGHT_UNSERVED * unserved + WEIGHT_OVERLOAD * overload


def _generate_candidates(node: dict) -> list[dict]:
    current = node["active_connection"]
    alt_buses = [via for via in node["possible_connections"] if via != current]

    candidates = [{"action": "reroute", "params": {"via": via}} for via in alt_buses]
    candidates.append({"action": "isolate", "params": {}})
    if current is not None:
        candidates.append({"action": "reduce_load_share", "params": {"fraction": CURTAIL_FRACTION}})
    return candidates


def _score(node: dict, candidate: dict) -> tuple[float, float]:
    """Returns (unserved_kw, overload_kw) this candidate would produce, per
    architecture's two explicit criteria: minimize load left unserved,
    minimize overload on any single remaining path. Current output is
    approximated by rated_capacity_kw * load_share (no power-flow model in
    this phase — that's pandapower's job later)."""
    rated = node["rated_capacity_kw"]
    contribution = rated * node["load_share"]
    action = candidate["action"]

    if action == "isolate":
        return contribution, 0.0

    if action == "reduce_load_share":
        new_share = candidate["params"]["fraction"]
        unserved = max(0.0, contribution - rated * new_share)
        bus = node["active_connection"]
        projected = digital_twin.bus_load_kw(bus) - contribution + rated * new_share
        overload = max(0.0, projected - BUS_CAPACITY_KW[bus])
        return unserved, overload

    if action == "reroute":
        via = candidate["params"]["via"]
        projected = digital_twin.bus_load_kw(via) + contribution
        overload = max(0.0, projected - BUS_CAPACITY_KW[via])
        return 0.0, overload

    raise ValueError(f"unknown candidate action: {action}")


def _apply(node_id: str, candidate: dict) -> dict:
    action = candidate["action"]
    if action == "reroute":
        return digital_twin.reroute_node(node_id, candidate["params"]["via"])
    if action == "isolate":
        return digital_twin.isolate_node(node_id)
    return digital_twin.set_load_share(node_id, candidate["params"]["fraction"])


def _describe(candidate: dict) -> str:
    action, params = candidate["action"], candidate["params"]
    if action == "reroute":
        return f"reroute via {params['via']}"
    if action == "isolate":
        return "isolate"
    return f"reduce load share to {params['fraction'] * 100:.0f}%"


def _reason(chosen: dict, scored: list[tuple[tuple[float, float], dict]]) -> str:
    breakdown = "; ".join(
        f"{_describe(c)} -> unserved {u:.0f}kW + overload {o:.0f}kW = {_combined((u, o)):.0f}"
        for (u, o), c in scored
    )
    return f"chose '{_describe(chosen)}' — lowest combined score. Considered: {breakdown}"


def _trigger_summary(node: dict) -> str:
    reading = node.get("latest_reading") or {}
    fault_label = reading.get("fault_label")
    if fault_label:
        return f"ground-truth fault label: {fault_label!r}"
    temperature = reading.get("temperature")
    if temperature is not None:
        return f"statistical threshold exceeded (temperature={temperature}°C vs rolling baseline)"
    return "flagged by fault detection"


async def _record(decision: dict) -> None:
    try:
        await db.insert_decision(decision)
    except Exception as exc:
        logger.warning("Failed to persist self-healing decision for %s: %s", decision["node_id"], exc)

    logger.info("Self-healing: %s -> %s (%s)", decision["node_id"], decision["chosen_action"], decision["reason"])

    ws_payload = {**decision, "time": decision["time"].isoformat()}
    await manager.broadcast({"type": "twin_decision", "decision": ws_payload})
