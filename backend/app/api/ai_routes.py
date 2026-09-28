"""Module 3 endpoint — model predictions per twin node, with the detector
that raised each flag stated explicitly. Separate router (like twin_routes.py)
so nothing here is shared with Module 1's Live Data API."""

from fastapi import APIRouter

from app.ai_service.predictor import predictor
from app.twin.digital_twin import digital_twin

router = APIRouter(prefix="/ai")


@router.get("/predictions")
async def get_predictions():
    """Per-node detector verdicts. `flagged_by` lists which of "rule_based" /
    "ta_gnn" raised the flag; `health_status` is the merged twin state. TA-GNN
    predictions are forecasts on REPLAYED Kelmarsh SCADA, never live sensing.
    Live Open-Meteo wind/hydro nodes are not scored (no fault-relevant
    channels)."""
    predictions = []
    for node in digital_twin.get_all_nodes():
        if node.get("type") not in ("wind", "hydro"):
            continue  # buses / grid carry no detector
        if node.get("source_type") != "historical":
            predictions.append(
                {
                    "node_id": node["node_id"],
                    "scored": False,
                    "reason": "live API node: no fault-relevant channels (no temperature, labels or SCADA channels)",
                    "health_status": node["health_status"],
                    "flagged_by": [],
                    "detectors": None,
                }
            )
            continue
        predictions.append(
            {
                "node_id": node["node_id"],
                "scored": bool((node.get("detectors") or {}).get("ta_gnn")),
                "health_status": node["health_status"],
                "flagged_by": node.get("flagged_by") or [],
                "detectors": node.get("detectors"),
                "last_updated": node.get("last_updated"),
            }
        )
    return {"model": predictor.describe(), "predictions": predictions}
