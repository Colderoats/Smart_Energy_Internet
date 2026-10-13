"""EnergyMarket benchmarks.

  python experiments/contract_bench.py conf      # conference Table VIII: 5/10/20/50 registered nodes, 5 rounds x 3 repeats, settle latency / gas / throughput (automine)
  python experiments/contract_bench.py ops       # per-operation gas of every function in isolation (automine + 1 s interval mining)
Needs a Hardhat node on :8545. Provenance: simulated_testbed (local Hardhat chain; not a public network).
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "experiments"))

import numpy as np  # noqa: E402

from lib import metric, write_run  # noqa: E402
from testbed.market.chain import Market  # noqa: E402

ROUNDS, REPEATS = 5, 3


def conf():
    ms, raw = [], {}
    for n in (5, 10, 20, 50):
        lat, gas, tps = [], [], []
        for rep in range(REPEATS):
            m = Market()
            accts = [m.new_account(f"n{n}_{rep}_{i}") for i in range(n)]
            for i, a in enumerate(accts):
                m.register(a, f"node{i}")
            m.records.clear()
            for rnd in range(ROUNDS):
                pairs = [(accts[2 * i], accts[2 * i + 1]) for i in range(n // 2)]
                trades = []
                for s, b in pairs:
                    o = m.post_offer(s, 5000, 100)
                    q = m.post_bid(b, 5000, 120)
                    t = m.match(o, q)["id"]
                    m.meter(t, 5000, 5000)
                    trades.append(t)
                t0 = time.perf_counter()
                n0 = len(m.records)
                for t in trades:
                    m.settle(t)
                dt = time.perf_counter() - t0
                tps.append(len(trades) / dt)
                m.advance()
            st = [r for r in m.records if r["op"] == "settle"]
            lat += [r["latency_s"] * 1000 for r in st]
            gas += [r["gas"] for r in st]
        raw[str(n)] = dict(latency_ms=lat, gas=gas, tps=tps)
        c = f"{n} nodes, {ROUNDS} rounds x {REPEATS} repeats, automine, sequential submission"
        ms += [metric("settle_latency", None, target_id=f"C.T8.n{n}.latency_ms", vals=lat, unit="ms", formula="receipt time - submission time of settle()", conditions=c),
               metric("settle_gas", None, target_id=f"C.T8.n{n}.gas", vals=gas, unit="gas", formula="receipt.gasUsed of settle()", conditions=c),
               metric("throughput", None, target_id=f"C.T8.n{n}.tps", vals=tps, unit="tx/s", formula="settle transactions / wall time of the settlement phase", conditions=c)]
    write_run("c_table8", ms, dict(nodes=[5, 10, 20, 50], rounds=ROUNDS, repeats=REPEATS, chain="hardhat node, automine", solidity="0.8.24"), raw=dict(samples=raw))


def ops():
    out = {}
    for mining in ("automine", "interval"):
        m = Market(interval_mining_s=1.0 if mining == "interval" else None)
        a, b = m.new_account("s"), m.new_account("b")
        reps = 8 if mining == "automine" else 4
        for r in range(reps):
            if r == 0:
                m.register(a, "seller")
                m.register(b, "buyer")
            o = m.post_offer(a, 5000, 100)
            q = m.post_bid(b, 5000, 120)
            t = m.match(o, q)["id"]
            m.meter(t, 5000, 5000)
            m.settle(t)
        out[mining] = m.summary()
        print(mining, json.dumps({k: (v["gas_mean"], round(v["latency_mean_s"], 3)) for k, v in out[mining].items()}), flush=True)
    RAWD = ROOT / "experiments" / "results" / "_raw"
    RAWD.mkdir(parents=True, exist_ok=True)
    (RAWD / "contract_ops.json").write_text(json.dumps(out, default=float))


if __name__ == "__main__":
    {"conf": conf, "ops": ops}[sys.argv[1]]()
