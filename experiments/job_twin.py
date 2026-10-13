"""One self-healing evaluation job (Table VII / VIII).

  python experiments/job_twin.py <topology> <iteration> eval     # held-out scenario set `it` with the model trained on training iteration `it`
  python experiments/job_twin.py C 0 c1213                         # Table VIII: 20 outages between buses 12-13, model of training iteration 0
Writes experiments/results/_raw/twin_<top>_<kind>_it<it>.json. Needs the saved 3_LRS model and the scenario datasets.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import numpy as np  # noqa: E402

from ai.testbed_models import predict  # noqa: E402
from testbed import journal_sim as JS  # noqa: E402
from testbed.topologies import build  # noqa: E402
from testbed.twin_eval import journal_twin as JT  # noqa: E402


def main(top_name: str, it: int, kind: str):
    t0 = time.time()
    top = build(top_name)
    scen = JS.SCENARIO_KINDS[kind][0].format(t=top_name)
    sc = JT.load_scenario(top, JS.DATA_ROOT, f"{scen}/it{it}")
    pr = predict.predict_scenario(top_name, it, kind=kind, model_it=it, eval_it=it)
    res = JT.evaluate_scenario(sc, pr["pred"])
    # model-side detection facts for the fault-head F1 of the SAME scenario (Table X-style, kept separate from the twin detection F1 of Table VII)
    from sklearn.metrics import f1_score
    y = sc.label
    out = dict(topology=top_name, iteration=it, kind=kind, provenance="simulated_testbed", n_faults=len(sc.faults), detection=res["detection"],
               fault_head_f1_macro=float(f1_score(y, pr["pred"], average="macro", labels=sorted(set(y.tolist()) | set(pr["pred"].tolist())), zero_division=0)),
               summary={s: JT.summarise(res["results"][s]) for s in ("default", "twin", "none")}, results=res["results"],
               seconds=time.time() - t0, constants={k: getattr(JT, k) for k in ("W_E", "W_V", "W_SW", "HORIZON_S", "T_SWITCH_S", "VERIFY_STEPS", "PROT_STEPS", "TWIN_PERSIST",
                                                                                      "DECISION_STEPS", "TRIP_LOADING", "DET_I", "DET_V", "DET_GEN_DROP", "HARD_V", "HARD_LOADING")})
    d = ROOT / "experiments" / "results" / "_raw"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"twin_{top_name}_{kind}_it{it}.json").write_text(json.dumps(out, default=float))
    print("done", top_name, kind, it, json.dumps(out["summary"]["twin"]), json.dumps(out["summary"]["default"]), f"{out['seconds']:.0f}s", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), sys.argv[3])
