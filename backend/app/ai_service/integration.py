"""Glue between the ingestion pipeline and the TA-GNN predictor.

Called from app/ingestion/pipeline.py right after the twin's own state update
and BEFORE its WebSocket broadcast, so the existing `twin_node_update` message
carries the prediction fields — no new WS message type.

Both detectors keep running side by side. Each node's `detectors` dict says
what each one concluded and `flagged_by` says which raised the flag:

  rule_based  Module 2's fault_detection.evaluate (unchanged). On replayed
              SCADA nodes its "fault" usually comes from the REPLAYED status
              log's ground-truth label overriding the statistic, not from a
              prediction — `basis` says which.
  ta_gnn      Module 3 model prediction: "a genuine fault will START within
              horizon_min" (a forecast on REPLAYED data — not sensed).

health_status = highest severity of the two; a TA-GNN flag raises a node to at
least "fault_predicted" and never downgrades "fault".

The model reads all four turbines as one graph snapshot, so the TA-GNN verdict
is computed at a common reference step (see FaultPredictor.score) and refreshed
for ALL turbine nodes together whenever that snapshot advances; `as_of` on each
verdict is the snapshot's (dataset) time, which can trail a node's newest
reading by a few 10-minute steps under round-robin replay.
"""

from __future__ import annotations

from app.ai_service.predictor import predictor
from app.api.ws_manager import manager
from app.models.reading import NormalizedReading
from app.twin import self_healing
from app.twin.digital_twin import digital_twin
from app.twin.graph import HealthStatus

_FLAGGING = {"fault", "fault_predicted"}
_last_ref_step: int | None = None


def rule_based_verdict(reading: NormalizedReading, status: HealthStatus) -> dict:
    if reading.fault_label:
        basis = "replayed_ground_truth_label"
    elif reading.source_type == "historical" and reading.temperature is not None:
        basis = "rolling_temperature_zscore"
    else:
        basis = "not_applicable"
    return {"status": status, "flagged": status in _FLAGGING, "basis": basis}


def _ta_gnn_verdict(score: dict, as_of: str) -> dict:
    return {
        "flagged": score["flagged"],
        "probability": round(score["probability"], 4),
        "model": predictor.meta["display_name"],
        "horizon_min": predictor.meta["features"]["horizon_steps"] * predictor.meta["features"]["step_minutes"],
        "as_of": as_of,
        "data": "replayed_scada_not_live",
    }


def _merge_and_set(node_id: str, detectors: dict, rule_status: HealthStatus) -> dict:
    health: HealthStatus = rule_status
    if detectors.get("ta_gnn", {}).get("flagged") and health not in _FLAGGING:
        health = "fault_predicted"
    flagged_by = [name for name in ("rule_based", "ta_gnn") if detectors.get(name, {}).get("flagged")]
    return digital_twin.set_detectors(node_id, detectors, flagged_by, health)


async def apply_detectors(reading: NormalizedReading, reading_dict: dict, rule_status: HealthStatus) -> dict | None:
    """Returns the arriving node's fresh twin state, or None when there is
    nothing to add (live API nodes are never scored)."""
    global _last_ref_step
    if reading.source_type != "historical":
        return None

    node_id = reading.node_id
    detectors: dict = {"rule_based": rule_based_verdict(reading, rule_status)}
    previous = digital_twin.get_node(node_id).get("detectors") or {}
    if "ta_gnn" in previous:
        detectors["ta_gnn"] = previous["ta_gnn"]  # latest known verdict until the snapshot advances

    refreshed_others: dict[str, dict] = {}
    if predictor.loaded:
        predictor.observe(node_id, reading_dict)
        result = predictor.score(digital_twin.get_all_nodes(), digital_twin.get_edges())
        if result is not None and result["ref_step"] != _last_ref_step:
            _last_ref_step = result["ref_step"]
            for nid, score in result["nodes"].items():
                verdict = _ta_gnn_verdict(score, result["as_of"])
                if nid == node_id:
                    detectors["ta_gnn"] = verdict
                else:
                    refreshed_others[nid] = verdict

    state = _merge_and_set(node_id, detectors, rule_status)

    # Other turbines whose verdict just refreshed: update, push, and let the
    # existing edge-triggered self-healing react (the pipeline only calls it
    # for the arriving node).
    for nid, verdict in refreshed_others.items():
        other = dict(digital_twin.get_node(nid).get("detectors") or {})
        other["ta_gnn"] = verdict
        other_rule = other.get("rule_based", {}).get("status", "normal")
        other_state = _merge_and_set(nid, other, other_rule)
        await manager.broadcast({"type": "twin_node_update", "node": other_state})
        await self_healing.maybe_trigger(nid)
    return state
