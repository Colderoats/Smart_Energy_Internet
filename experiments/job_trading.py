"""Peer redistribution + on-chain settlement for one topology (journal trading scenario, Table XI inputs).

  python experiments/job_trading.py <A|B|C> <normal|postfault> [automine|interval]
Needs a Hardhat node on :8545 (`cd blockchain && npx hardhat node`) and the eval-scenario datasets + saved models.
normal    : base switch state, all 288 five-minute intervals of the held-out day (eval iteration 0)
postfault : switch state after the twin's chosen reconfiguration of the first line outage in that iteration's twin evaluation (islands allowed if the action enabled them)
interval  : 1 s interval mining, first INTERVAL_RUN_K intervals only (latency realism), gas/latency recorded per operation
Writes experiments/results/_raw/trading_<top>_<variant>_<mining>.json.
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
from testbed.market import redistribution as RD  # noqa: E402
from testbed.market.chain import Market  # noqa: E402
from testbed.topologies import build  # noqa: E402

INTERVAL_RUN_K = 12
RAW = ROOT / "experiments" / "results" / "_raw"


def post_fault_status(top, top_name):
    p = RAW / f"twin_{top_name}_eval_it0.json"
    status = top.base_status().copy()
    allow_island = False
    note = "no twin evaluation found: base topology"
    if p.exists():
        r = json.loads(p.read_text())
        for ev in r["results"]["twin"]:
            a = ev.get("action")
            if ev["type"] == 1 and a and (a.get("ops") or a.get("island")):
                line = ev["line"]
                status[line] = False
                for kind, ln in a["ops"]:
                    status[ln] = kind == "close"
                allow_island = bool(a.get("island"))
                note = f"after twin action '{a['label']}' for the outage of line {line + 1} (fault {ev['fault']})"
                break
    return status, allow_island, note


def main(top_name, variant, mining):
    t0 = time.time()
    top = build(top_name)
    d = np.load(JS.DATA_ROOT / f"journal_{top_name}_eval" / "it0" / "data.npz")
    demand, gen = d["demand_kw"].astype(float), d["gen_kw"].astype(float)
    pr = predict.predict_scenario(top_name, 0, kind="eval", model_it=0, eval_it=0)
    yhat = pr["yhat_kw"].astype(float)
    if variant == "postfault":
        status, allow_island, note = post_fault_status(top, top_name)
    else:
        status, allow_island, note = top.base_status().copy(), True, "base topology (normal operation)"
    iv = RD.Intervals(top, status, demand, gen, yhat, allow_island)
    chain = Market(interval_mining_s=1.0 if mining == "interval" else None)
    accounts = {i: chain.new_account(f"{top_name}_{i}") for i in range(top.n)}
    for i, a in accounts.items():
        chain.register(a, f"{top_name}_bus{i}")
    K = RD.INTERVAL_STEPS and len(demand) // RD.INTERVAL_STEPS
    ks = range(INTERVAL_RUN_K) if mining == "interval" else range(K)
    res = RD.run(iv, seed=7, rule="journal", chain=chain, accounts=accounts, k_range=ks)
    summ = chain.summary()
    trades = max(res["kpi"]["trades"], 1)
    res["kpi"]["avg_gas_per_trade_match_meter_settle"] = sum(chain.summary()[o]["gas_mean"] * chain.summary()[o]["n"] for o in ("match", "meter", "settle") if o in summ) / trades
    res["kpi"]["avg_gas_per_trade_all_ops"] = sum(r["gas"] for r in chain.records if r["op"] != "register") / trades
    base_iv = RD.run(iv, seed=7, rule="journal", chain=None, k_range=ks, trade=False)
    out = dict(topology=top_name, variant=variant, mining=mining, note=note, provenance="simulated_testbed", status=status.tolist(), allow_island=allow_island,
               kpi=res["kpi"], series=res["series"], frames=res["frames"][::max(1, len(res["frames"]) // 96)], trades=res["trades"][:400], chain=summ, deploy_gas=chain.deploy_gas,
               baseline_kpi=base_iv["kpi"], seconds=time.time() - t0, intervals=res["intervals"], solidity="0.8.24", node="hardhat")
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / f"trading_{top_name}_{variant}_{mining}.json").write_text(json.dumps(out, default=float))
    print("done", top_name, variant, mining, json.dumps({k: round(v, 3) if isinstance(v, float) else v for k, v in res["kpi"].items()}), f"{out['seconds']:.0f}s", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "automine")
