"""Aggregate the trading / contract runs: j_trading (per-topology redistribution KPIs) and j_table11 (gas and latency per operation, journal Table XI)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "experiments"))

import numpy as np  # noqa: E402

from lib import metric, write_run  # noqa: E402

RAW = ROOT / "experiments" / "results" / "_raw"
TOPS = ("A", "B", "C")
OPMAP = {"register": "register", "sell_offer": "sell_offer", "buy_bid": "buy_bid", "match": "match", "settle": "settle"}


def trading():
    ms = []
    for t in TOPS:
        for v in ("normal", "postfault"):
            f = RAW / f"trading_{t}_{v}_automine.json"
            if not f.exists():
                continue
            r = json.loads(f.read_text())
            k = r["kpi"]
            c = f"topology {t}, {v} switch state, {r['intervals']} five-minute intervals, journal matching; {r['note']}"
            for name, key, unit, fm in (("energy_redistributed", "energy_redistributed_kwh", "kWh", "sum of energy received by buyers"),
                                        ("network_losses", "network_losses_kwh", "kWh", "pandapower line losses with the accepted trades"),
                                        ("local_self_sufficiency", "local_self_sufficiency", "", "1 - grid import / consumption"),
                                        ("grid_import_reduction", "grid_import_reduction", "", "(import without trading - import with trading) / import without trading"),
                                        ("trades", "trades", "count", "settled trades"), ("infeasible_matches_rejected", "infeasible_rejected", "count", "candidate matches that failed the pandapower check even after halving"),
                                        ("avg_gas_per_trade", "avg_gas_per_trade_match_meter_settle", "gas", "(match + meter + settle gas) / trades"),
                                        ("avg_gas_per_trade_all_ops", "avg_gas_per_trade_all_ops", "gas", "all non-registration gas / trades")):
                ms.append(metric(f"{name}_{v}", k.get(key), unit=unit, topology=t, formula=fm, conditions=c))
    write_run("j_trading", ms, dict(intervals="5 min", prices="ask U(60,110), bid max U(120,140), milli/kWh", chain="EnergyMarket on Hardhat, Solidity 0.8.24"))


def table11():
    ops = json.loads((RAW / "contract_ops.json").read_text()) if (RAW / "contract_ops.json").exists() else None
    ms = []
    # day-run gas pooled over topologies (many operations of each kind)
    pooled = {}
    for t in TOPS:
        f = RAW / f"trading_{t}_normal_automine.json"
        if f.exists():
            for op, v in json.loads(f.read_text())["chain"].items():
                pooled.setdefault(op, []).append((v["gas_mean"], v["n"], v["latency_mean_s"]))
    for tgt, op in OPMAP.items():
        if op in pooled:
            n = sum(x[1] for x in pooled[op])
            gas = sum(x[0] * x[1] for x in pooled[op]) / n
            ms.append(metric("gas", gas, target_id=f"J.T11.{tgt}.gas", unit="gas", formula="mean receipt.gasUsed over all operations of the simulated trading days (3 topologies)",
                             conditions=f"{tgt}; n = {n}; Solidity 0.8.24 optimizer 200 runs", note="Differences from Table XI are explained by the contract design (stored fields / events), not tuned."))
        if ops:
            if op in ops["automine"]:
                ms.append(metric("latency_automine", ops["automine"][op]["latency_mean_s"], target_id=f"J.T11.{tgt}.latency", unit="s", formula="submission-to-receipt wall time, automine (instant mining), local Hardhat node",
                                 conditions=f"{tgt}; automine", note="labelled AUTOMINE: not comparable to a real network; see the 1 s interval-mining row"))
                ms.append(metric("latency_interval_1s", ops["interval"][op]["latency_mean_s"], target_id=f"J.T11.{tgt}.latency", unit="s", formula="submission-to-receipt wall time with 1 s interval mining", conditions=f"{tgt}; interval mining 1 s"))
    if ops and "meter" in ops["automine"]:
        ms.append(metric("gas", ops["automine"]["meter"]["gas_mean"], unit="gas", formula="receipt.gasUsed of submitMeter", conditions="meter (oracle-only metering; no Table XI row)"))
    write_run("j_table11", ms, dict(chain="local Hardhat node; automine and 1 s interval mining", contract="EnergyMarket"))


if __name__ == "__main__":
    trading()
    table11()
