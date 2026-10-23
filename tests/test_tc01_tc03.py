"""TC01 (out-of-limit wind/hydro reading) and TC03 (prediction service stopped).
Both drive the REAL ingestion path (app.ingestion.pipeline.ingest_reading) in-process.
Only DB persistence and the blockchain-ledger hook are stubbed so no external service is needed."""
import asyncio
from datetime import datetime, timezone

import pytest

from app import db
from app.ai_service.predictor import predictor
from app.blockchain import ledger as ledger_hooks
from app.config import settings
from app.ingestion import pipeline
from app.models.reading import NormalizedReading
from app.twin import fault_detection, self_healing
from app.twin.digital_twin import digital_twin

decisions: list[dict] = []


@pytest.fixture(autouse=True)
def stubs(monkeypatch):
    async def noop(*a, **k):
        return None

    async def keep(d):
        decisions.append(d)

    monkeypatch.setattr(db, "insert_reading", noop)
    monkeypatch.setattr(db, "insert_decision", keep)
    monkeypatch.setattr(ledger_hooks, "on_self_healing", lambda *a, **k: None)
    decisions.clear()


def _live(node_id, typ, power, wind=None):
    return NormalizedReading(node_id=node_id, source_type="live", type=typ, timestamp=datetime.now(timezone.utc),
                             power_output=power, wind_speed=wind)


def _scada(node_id, temp, label=None):
    return NormalizedReading(node_id=node_id, source_type="historical", type="wind", timestamp=datetime.now(timezone.utc),
                             power_output=900.0, temperature=temp, vibration=2.0, fault_label=label)


# ------------------------------------------------------------------ TC01
@pytest.mark.parametrize("node,typ,good,bad,wind_good,wind_bad", [
    ("wind_01", "wind", 1200.0, 9.9e6, 9.0, 400.0),     # 9.9 GW and 400 m/s: far outside rating (2 MW) / cut-out (25 m/s)
    ("hydro_01", "hydro", 5000.0, -7.0e5, None, None),  # negative power
])
def test_tc01_out_of_limit_reading_is_flagged_and_replaced(node, typ, good, bad, wind_good, wind_bad):
    asyncio.run(pipeline.ingest_reading(_live(node, typ, good, wind_good)))
    asyncio.run(pipeline.ingest_reading(_live(node, typ, bad, wind_bad)))
    state = digital_twin.get_node(node)
    r = state["latest_reading"]
    print(f"\n[TC01] {node}: sent power={bad} wind={wind_bad}; twin now holds power={r['power_output']} "
          f"wind={r.get('wind_speed')} health={state['health_status']} normalized={r['normalized']}")
    # expected by the test case: invalid sample replaced by the last valid value
    assert r["power_output"] == good, "out-of-limit value was NOT replaced by the last valid value"


# ------------------------------------------------------------------ TC03
def test_tc03_prediction_service_stopped_falls_back_to_rules(monkeypatch):
    # make the REAL load path fail (artifact dir does not exist) -> predictor.loaded False
    import app.ai_service.predictor as pm
    monkeypatch.setattr(settings, "ai_model_source", "centralized")
    monkeypatch.setattr(pm, "ARTIFACT_ROOT", pm.ARTIFACT_ROOT.parent / "no_such_artifacts_dir")
    predictor.loaded = False
    predictor.load()
    assert predictor.loaded is False and predictor.error

    node = "wind_scada_kelmarsh_2"
    # fault injection #1: statistical threshold (temperature 40 sigma above a stable rolling baseline)
    fault_detection._temperature_history.clear()
    for i in range(15):
        asyncio.run(pipeline.ingest_reading(_scada(node, 40.0 + (i % 3) * 0.1)))
    assert digital_twin.get_node(node)["health_status"] == "normal"
    asyncio.run(pipeline.ingest_reading(_scada(node, 95.0)))
    s = digital_twin.get_node(node)
    print(f"\n[TC03] threshold fault: health={s['health_status']} flagged_by={s['flagged_by']} detectors={list(s['detectors'])}")
    assert s["health_status"] in ("fault_predicted", "fault")
    assert s["flagged_by"] == ["rule_based"] and "ta_gnn" not in s["detectors"]
    assert decisions and decisions[-1]["node_id"] == node, "no rule-based restoration decision recorded"
    d = decisions[-1]
    print(f"[TC03] restoration: {d['chosen_action']} {d['chosen_params']} | {d['trigger_summary']}")
    assert d["chosen_action"] in ("reroute", "isolate", "reduce_load_share")

    # fault injection #2: ground-truth fault label on another turbine
    node2 = "wind_scada_kelmarsh_3"
    asyncio.run(pipeline.ingest_reading(_scada(node2, 45.0, label="Stop: gearbox fault")))
    s2 = digital_twin.get_node(node2)
    print(f"[TC03] labelled fault: health={s2['health_status']} flagged_by={s2['flagged_by']}")
    assert s2["health_status"] == "fault" and s2["flagged_by"] == ["rule_based"]
    assert decisions[-1]["node_id"] == node2


def test_tc01_valid_reading_untouched_nan_replaced_and_no_history_dropped():
    from app.ingestion import validation
    validation._last_valid.pop("hydro_01", None)
    # no earlier valid value -> dropped, twin keeps whatever it had
    assert validation.validate_live(_live("hydro_01", "hydro", -5.0), 400.0) is None
    ok = _live("hydro_01", "hydro", 5000.0)  # live hydro estimate above the 400 kW rating is legitimate
    assert validation.validate_live(ok, 400.0) is ok
    fixed = validation.validate_live(_live("hydro_01", "hydro", float("nan")), 400.0)
    assert fixed.power_output == 5000.0
    scada = _scada("wind_scada_kelmarsh_1", 40.0)
    assert validation.validate_live(scada, 2050.0) is scada  # replayed SCADA is not validated here
