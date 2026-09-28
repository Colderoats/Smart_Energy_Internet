"""Train/serve parity check: streams REAL replayed readings (round-robin, scoring after every reading) through the live
FaultPredictor (app/ai_service) step by step and compares its logits with the
offline evaluation path (ai.dataset + ai.training.predict_logits) for the same
steps. They must agree to float precision — otherwise the served model is not
the evaluated model.

    venv\\Scripts\\python -m ai.check_serving_parity [--kind tag] [--steps 60]
"""

from __future__ import annotations

import argparse
import warnings

warnings.filterwarnings("ignore")

import numpy as np

from ai import dataset as D
from ai import features as F
from ai import training as T


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="tag")
    ap.add_argument("--steps", type=int, default=60)
    ap.add_argument("--start", default="2018-12-10", help="UTC date to start the streamed stretch")
    args = ap.parse_args()

    from datetime import datetime, timezone

    from app.ai_service.predictor import FaultPredictor
    from app.ingestion.scada_replay import _iter_turbine_readings

    predictor = FaultPredictor(args.kind)
    predictor.load()
    assert predictor.loaded, predictor.error

    arr = D.build_arrays()
    start = int((datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc) - arr.t0).total_seconds() // D.STEP_S)
    steps = np.arange(start, start + args.steps)

    # offline path: cached windows -> normalise -> model
    static, edges = F.default_topology()
    norm = F.Normalizer.from_dict(predictor.meta["normalizer"])
    x = D.snapshot_tensor(arr, steps, norm, static)
    offline = T.predict_logits(predictor._model, x, edges)  # [n, 4]

    # online path: stream the same replayed rows in time order
    readings = {}
    for n, node_id in D.TURBINES.items():
        rows = {}
        for r in _iter_turbine_readings(D.EXTRA_DATA_DIR, n, node_id):
            step = int((r.timestamp - D.T0).total_seconds() // D.STEP_S)
            if start - F.WINDOW_STEPS <= step < start + args.steps:
                rows[step] = r.model_dump(mode="json")
        readings[node_id] = rows

    from app.twin.digital_twin import DigitalTwin

    twin = DigitalTwin()
    diffs, compared, snapshots = [], 0, set()
    # Live order: turbines deliver round-robin, so the service is asked to score
    # after EVERY reading, while neighbours are still a step behind.
    for s in range(start - F.WINDOW_STEPS, start + args.steps):
        for node_id in F.SCORED_NODES:
            if s not in readings[node_id]:
                continue
            predictor.observe(node_id, readings[node_id][s])
            res = predictor.score(twin.get_all_nodes(), twin.get_edges())
            if res is None:
                continue
            ref = res["ref_step"] - int(D.T0.timestamp() // D.STEP_S)  # service uses epoch steps
            if ref < start:
                continue
            snapshots.add(ref)
            for k, nid in enumerate(F.SCORED_NODES):
                if nid in res["nodes"]:
                    diffs.append(abs(res["nodes"][nid]["logit"] - float(offline[ref - start, k])))
                    compared += 1
    diffs = np.array(diffs)
    print(f"{len(snapshots)} distinct snapshots, {compared} node-scores compared; max |online - offline| logit difference = {diffs.max():.2e}")
    assert diffs.max() < 1e-3, "serving path does NOT reproduce the offline path"
    print("PARITY OK")


if __name__ == "__main__":
    main()
