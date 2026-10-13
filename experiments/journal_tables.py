"""Aggregators: saved training / evaluation artifacts -> experiments/results/<run_id>/metrics.json for the JOURNAL tables.

Nothing here knows a paper number. Table IX and the abstract claims are computed from the measured Table VI / VII / X runs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "experiments"))

import lib  # noqa: E402
from lib import metric, pct_reduction, write_run, read_run  # noqa: E402

ART = ROOT / "backend" / "ai" / "artifacts" / "testbed"
RAW = ROOT / "experiments" / "results" / "_raw"
TOPS = ("A", "B", "C")
ITERS = (0, 1, 2)


def its(t):
    return (0,) if t == "C" else ITERS  # amendment 4: topology C trains on iteration 0 only


def _load(top, it, name):
    return json.loads((ART / f"journal_{top}" / f"it{it}" / name).read_text())


def t3():
    from testbed import journal_sim as JS
    from testbed.topologies import build
    ms = []
    for t in TOPS:
        c = build(t).counts()
        ms += [metric("nodes", c["nodes"], target_id=f"J.T3.{t}.nodes", topology=t, formula="structural count"),
               metric("lines", c["lines"], target_id=f"J.T3.{t}.lines", topology=t, formula="structural count (incl. normally-open ties)"),
               metric("solar_nodes", c["solar"], target_id=f"J.T3.{t}.solar_nodes", topology=t),
               metric("wind_hydro_sources", c["wind_hydro"], target_id=f"J.T3.{t}.wind_hydro_sources", topology=t),
               metric("clients", c["nodes"], target_id=f"J.T3.{t}.clients", topology=t, formula="one federated client per node"),
               metric("tie_switches", c["ties"], topology=t), metric("hours", 24, target_id=f"J.T3.{t}.hours", topology=t)]
        man = json.loads((JS.DATA_ROOT / f"journal_{t}" / "it0" / "manifest.json").read_text())
        ms += [metric("faults_per_iteration", man["faults"], target_id=f"J.T3.{t}.faults", topology=t, conditions=json.dumps(man["faults_per_type"])),
               metric("samples", man["samples"], target_id="J.T3.samples", topology=t, formula="86400 s / 5 s", conditions=f"config_hash {man['config_hash']}")]
    write_run("j_table3", ms, dict(topologies=TOPS, iterations=3, dt_s=5))


def t4_t5():
    m4, m5, raw4, raw5 = [], [], {}, {}
    for t in TOPS:
        S = [_load(t, it, "search.json") for it in its(t)]
        F = [_load(t, it, "final.json") for it in its(t)]
        for o in (1, 2, 3, 4):
            for key, mname, tid in (("train", "train_loss", "train_loss"), ("val", "val_loss", "val_loss"), ("val", "val_f1", "val_f1")):
                if mname == "val_f1":
                    vals = [s["runs"][f"tag_o{o}"]["val"]["f1_macro"] for s in S]
                else:
                    vals = [s["runs"][f"tag_o{o}"][key]["loss"] for s in S]
                m4.append(metric(mname, None, target_id=f"J.T4.o{o}.{tid}", vals=vals, topology=t, formula="Eq.14 loss (normalised units)" if "loss" in mname else "macro-F1 of fault head",
                                 equation="14" if "loss" in mname else "13", conditions=f"Option {o}, 25 epochs, TA-GNN", split="80/20 chronological", seeds=list(its(t))))
            raw4[f"{t}_o{o}"] = [s["runs"][f"tag_o{o}"]["curves"] for s in S]
        for n in ("3_LRS", "3_NLRS", "2_NLRS"):
            for mname, getter in (("train_loss", lambda f: f["runs"][n]["train"]["loss"]), ("val_loss", lambda f: f["runs"][n]["val"]["loss"]),
                                  ("val_f1", lambda f: f["runs"][n]["val"]["f1_macro"])):
                m5.append(metric(mname, None, target_id=f"J.T5.{n}.{mname}", vals=[getter(f) for f in F], topology=t, formula="Eq.14" if "loss" in mname else "macro-F1",
                                 equation="14" if "loss" in mname else "13", conditions=f"Option {n}", split="80/20 chronological", seeds=list(its(t))))
            raw5[f"{t}_{n}"] = [f["runs"][n]["curves"] for f in F]
        g = F[0]["gcn_selected"]
        raw5[f"{t}_gcn"] = [f["runs"][[k for k in f["runs"] if k.startswith("gcn")][0]]["curves"] for f in F]
        raw4[f"{t}_ranking"] = [f["search_ranking_tag"] for f in F]
    cfg = dict(options="J Table IV", epochs=dict(search=25, final=250), batch="N snapshots", split="80/20")
    write_run("j_table4", m4, cfg, raw=dict(curves=raw4))
    write_run("j_table5", m5, cfg, raw=dict(curves=raw5))


def t6():
    ms = []
    for t in TOPS:
        F = [_load(t, it, "final.json") for it in its(t)]
        gk = [[k for k in f["runs"] if k.startswith("gcn")][0] for f in F]
        for mdl, getter in (("ta_gnn", lambda f, i: f["runs"]["3_LRS"]["val"]), ("gcn", lambda f, i: f["runs"][gk[i]]["val"])):
            for mn, key, eq in (("mae", "mae_kw", "20"), ("rmse", "rmse_kw", "21")):
                vals = [getter(f, i)[key] for i, f in enumerate(F)]
                ms.append(metric(mn, None, target_id=f"J.T6.{t}.{mdl}.{mn}", vals=vals, unit="kW", topology=t, equation=eq, conditions=f"{mdl}, validation (last 20 %)",
                                 formula="mean|Yhat-Y| over load buses" if mn == "mae" else "sqrt(mean (Yhat-Y)^2)", split="80/20 chronological", seeds=list(its(t))))
    write_run("j_table6", ms, dict(models="TA-GNN option 3 LRS vs GCN (equal tuning budget)", iterations=3))


def _group(res_list, key):
    return [r[key] for r in res_list]


def t7_t8_t9():
    ms7, ms8 = [], []
    per_top = {}
    for t in TOPS:
        runs = [json.loads(p.read_text()) for p in sorted(RAW.glob(f"twin_{t}_eval_it*.json"))]
        if not runs:
            continue
        det = {s: [r["detection"][s]["f1"] for r in runs] for s in ("default", "twin")}
        trec = {s: [r["summary"][s]["t_rec_mean_s"] for r in runs] for s in ("default", "twin", "none")}
        euns = {s: [r["summary"][s]["e_uns_total_kwh"] for r in runs] for s in ("default", "twin", "none")}
        per_top[t] = dict(det=det, trec=trec, euns=euns, n=len(runs))
        for s in ("default", "twin"):
            ms7 += [metric("detection_f1", None, target_id=f"J.T7.{t}.{s}.detection_f1", vals=det[s], topology=t, formula="F1 of the alarm signal vs injection-log label (sample level)",
                           conditions=f"{s} scheme; {'threshold protection' if s == 'default' else 'TA-GNN fault head + 2-sample persistence'}", split="held-out scenarios", seeds=list(range(len(runs)))),
                    metric("t_rec", None, target_id=f"J.T7.{t}.{s}.t_rec", vals=trec[s], unit="s", topology=t, equation="22", formula="t_restored - t_fault, mean over faults that interrupted supply",
                           conditions=f"{s} scheme", seeds=list(range(len(runs)))),
                    metric("e_uns", None, target_id=f"J.T7.{t}.{s}.e_uns", vals=euns[s], unit="kWh", topology=t, equation="7", formula="integral of unserved power, total over the scenario's 20 faults",
                           conditions=f"{s} scheme", seeds=list(range(len(runs))))]
    write_run("j_table7", ms7, dict(scenario="20 faults (4 types x 5) per held-out iteration x 3", schemes=["default", "twin"]), raw=dict(per_topology=per_top))
    # Table VIII
    p = RAW / "twin_C_c1213_it0.json"
    if p.exists():
        r = json.loads(p.read_text())
        from collections import Counter
        cnt = Counter((x["action"] or {}).get("label", "undetected") for x in r["results"]["twin"])
        for lab in ("open+close_tie", "open+close_tie+island", "open+close_tie+curtail", "open+island"):
            ms8.append(metric("action_sequence_count", cnt.get(lab, 0), target_id=f"J.T8.C.{lab}", topology="C", unit="events", conditions="line outage between buses 12-13; 20 events at random instants",
                              formula="count of chosen a*", equation="5"))
        other = {k: v for k, v in cnt.items() if k not in ("open+close_tie", "open+close_tie+island", "open+close_tie+curtail", "open+island")}
        costs = [x["action"]["J"] for x in r["results"]["twin"] if x.get("action") and "J" in x["action"]]
        ms8.append(metric("lowest_J_min", min(costs) if costs else None, target_id="J.T8.C.example_cost", topology="C", equation="7",
                          formula="smallest chosen J over the 20 events (the paper quotes one example event, 0.42)", note=f"other chosen sequences: {json.dumps(other)}"))
        ms8.append(metric("lowest_J_median", float(np.median(costs)) if costs else None, topology="C", equation="7", formula="median chosen J"))
        write_run("j_table8", ms8, dict(scenario="C, 20 outages of the line between buses 12-13"),
                  raw=dict(events=[dict(fault=x["fault"], delay=x["detect_delay_s"], action=x["action"], t_rec=x["t_rec_s"], e_uns=x["e_uns_kwh"]) for x in r["results"]["twin"]],
                           default_events=[dict(fault=x["fault"], delay=x["detect_delay_s"], action=x["action"], t_rec=x["t_rec_s"], e_uns=x["e_uns_kwh"]) for x in r["results"]["default"]]))
    return per_top


def t9():
    t6_, t7_ = read_run("j_table6"), read_run("j_table7")
    idx6 = {(m["target_id"], m["topology"]): m for m in t6_["metrics"]}
    idx7 = {(m["target_id"], m["topology"]): m for m in t7_["metrics"]}
    ms = []
    for t in TOPS:
        g, ta = idx6.get((f"J.T6.{t}.gcn.mae", t)), idx6.get((f"J.T6.{t}.ta_gnn.mae", t))
        if g and ta:
            ms.append(metric("forecast_mae_reduction_pct", pct_reduction(g["value"], ta["value"]), target_id=f"J.T9.{t}.forecast_mae_improvement", unit="%", topology=t,
                             formula="(GCN MAE - TA-GNN MAE) / GCN MAE x 100", inputs=dict(gcn_mae=g["value"], ta_gnn_mae=ta["value"])))
        d, w = idx7.get((f"J.T7.{t}.default.detection_f1", t)), idx7.get((f"J.T7.{t}.twin.detection_f1", t))
        if d and w:
            ms.append(metric("fault_f1_gain_pct", 100 * (w["value"] - d["value"]) / d["value"], target_id=f"J.T9.{t}.fault_f1_improvement", unit="%", topology=t,
                             formula="(twin F1 - default F1) / default F1 x 100", inputs=dict(default_f1=d["value"], twin_f1=w["value"])))
        d, w = idx7.get((f"J.T7.{t}.default.t_rec", t)), idx7.get((f"J.T7.{t}.twin.t_rec", t))
        if d and w:
            ms.append(metric("recovery_time_reduction_pct", pct_reduction(d["value"], w["value"]), target_id=f"J.T9.{t}.recovery_improvement", unit="%", topology=t,
                             formula="(T_rec default - T_rec twin) / T_rec default x 100", inputs=dict(default_t_rec=d["value"], twin_t_rec=w["value"])))
    by = {m["name"]: [] for m in ms}
    for m in ms:
        by[m["name"]].append(m)
    abstract = []
    if by.get("forecast_mae_reduction_pct"):
        abstract.append(metric("max_forecast_error_reduction_pct", max(m["value"] for m in by["forecast_mae_reduction_pct"]), target_id="J.ABS.forecast", unit="%",
                               formula="max over topologies of Table IX forecast reduction", inputs={m["topology"]: m["value"] for m in by["forecast_mae_reduction_pct"]}))
    if by.get("recovery_time_reduction_pct"):
        abstract.append(metric("max_recovery_time_reduction_pct", max(m["value"] for m in by["recovery_time_reduction_pct"]), target_id="J.ABS.recovery", unit="%",
                               formula="max over topologies of Table IX recovery reduction", inputs={m["topology"]: m["value"] for m in by["recovery_time_reduction_pct"]}))
    write_run("j_table9", ms + abstract, dict(derived_from=["j_table6", "j_table7"]))


if __name__ == "__main__":
    cmd = sys.argv[1]
    {"t3": t3, "t4_t5": t4_t5, "t6": t6, "t7_t8": t7_t8_t9, "t9": t9}[cmd]()
