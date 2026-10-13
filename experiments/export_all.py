"""Export view-ready JSON for the dashboard from the saved measured runs (nothing here invents a number):

  experiments/results/topologies.json        nodes / lines / layout / N-1 connectivity     (export_topologies.py)
  experiments/results/topology_kpis.json     per-topology KPI panel
  experiments/results/redistribution_<T>.json playback frames + KPIs (normal topology and after the twin's reconfiguration)
  experiments/results/fault_replay_<T>.json  recorded fault scenarios (stages, candidate actions with J, T_rec, E_uns)
  experiments/results/graphs.json            every chart on the Graphs view with caption + run id
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "experiments"))

import numpy as np  # noqa: E402

from lib import read_run  # noqa: E402

RES = ROOT / "experiments" / "results"
RAW = RES / "_raw"
ART = ROOT / "backend" / "ai" / "artifacts" / "testbed"
TOPS = ("A", "B", "C")
ITERS = (0, 1, 2)
COL = {"A": "#14b8a6", "B": "#3b82f6", "C": "#7c3aed"}


def jl(p):
    return json.loads(Path(p).read_text())


def maybe(p):
    return jl(p) if Path(p).exists() else None


def metric_map(run_id):
    try:
        doc = read_run(run_id)
    except FileNotFoundError:
        return {}
    return {(m.get("target_id"), m.get("topology")): m for m in doc["metrics"]}


# ------------------------------------------------------------------------------------------------------------ KPIs
def kpis():
    m6, m7 = metric_map("j_table6"), metric_map("j_table7")
    out = {}
    for t in TOPS:
        k = {}
        g = lambda mm, tid: (mm.get((tid, t)) or {}).get("value")
        k["forecast_mae_kw"] = g(m6, f"J.T6.{t}.ta_gnn.mae")
        k["forecast_rmse_kw"] = g(m6, f"J.T6.{t}.ta_gnn.rmse")
        for s in ("twin", "default"):
            k[f"detection_f1_{s}"] = g(m7, f"J.T7.{t}.{s}.detection_f1")
            k[f"t_rec_{s}_s"] = g(m7, f"J.T7.{t}.{s}.t_rec")
            k[f"e_uns_{s}_kwh"] = g(m7, f"J.T7.{t}.{s}.e_uns")
        tr = maybe(RAW / f"trading_{t}_normal_automine.json")
        if tr:
            kp = tr["kpi"]
            k.update(energy_redistributed_kwh=kp["energy_redistributed_kwh"], self_sufficiency=kp["local_self_sufficiency"], losses_kwh=kp["network_losses_kwh"], trades=kp["trades"],
                     avg_gas_per_trade=kp.get("avg_gas_per_trade_match_meter_settle"), import_reduction=kp["grid_import_reduction"], infeasible_rejected=kp["infeasible_rejected"])
        out[t] = k
    (RES / "topology_kpis.json").write_text(json.dumps(out))


# ------------------------------------------------------------------------------------------------------ redistribution
def redistribution():
    for t in TOPS:
        d = {}
        for v in ("normal", "postfault"):
            r = maybe(RAW / f"trading_{t}_{v}_automine.json")
            if r:
                d[v] = dict(note=r["note"], status=r["status"], allow_island=r["allow_island"], kpi=r["kpi"], baseline_kpi=r["baseline_kpi"], series=r["series"], frames=r["frames"],
                            chain=r["chain"], intervals=r["intervals"])
        iv = maybe(RAW / f"trading_{t}_normal_interval.json")
        if iv:
            d["interval_mining"] = dict(chain=iv["chain"], intervals=iv["intervals"], note="1 s interval mining, first 12 trading intervals")
        if d:
            (RES / f"redistribution_{t}.json").write_text(json.dumps(d))


# ---------------------------------------------------------------------------------------------------------- fault replay
def fault_replay():
    from testbed import journal_sim as JS
    from testbed import powerflow as pf
    from testbed.topologies import FLEX_SHARE, build
    from testbed.twin_eval import journal_twin as jt

    for t in TOPS:
        top = build(t)
        ev_ = pf.Evaluator(top)
        scen_files = [("eval_it0", RAW / f"twin_{t}_eval_it0.json", JS.DATA_ROOT / f"journal_{t}_eval" / "it0")]
        if t == "C":
            scen_files.append(("c1213", RAW / "twin_C_c1213_it0.json", JS.DATA_ROOT / "journal_C_1213" / "it0"))
        scenarios = []
        for tag, rawp, datap in scen_files:
            r = maybe(rawp)
            if not r:
                continue
            sc = jt.load_scenario(top, datap.parent, datap.name)
            picks = []
            if tag == "c1213":
                picks = list(range(min(3, len(sc.faults))))
            else:
                seen = set()
                for k, ev in enumerate(sc.faults):
                    if ev["type"] not in seen and r["results"]["twin"][k].get("interrupted", False) or (ev["type"] not in seen and ev["type"] in (3, 4)):
                        seen.add(ev["type"])
                        picks.append(k)
            for k in picks:
                ev = sc.faults[k]
                S = {}
                for scheme in ("twin", "default"):
                    res = r["results"][scheme][k]
                    t0 = ev["start"]
                    base = jt.physical_state(sc, ev, t0)
                    stages = []

                    def snap(name, desc, t_s, applied, trips, cand=None):
                        st = jt._build(top, base, applied, trips)
                        rr = ev_.evaluate(st)
                        stages.append(dict(name=name, description=desc, t_s=float(t_s), status=[bool(x) for x in st["status"]], energised=[bool(x) for x in rr.energised],
                                           unserved_kw=float(rr.unserved_kw.sum()), highlight_lines=[int(applied_line) for applied_line in ([ev["line"]] if "line" in ev else [])],
                                           candidates=cand, e_uns_kwh=0.0))
                    snap("Fault injected", f"{ev['class_name'].replace('_', ' ')}" + (f" on line {ev['line'] + 1}" if "line" in ev else f" at node {ev['node'] + 1}") + ".", 0.0, None, [])
                    tl = res["timeline"]
                    if res["t_alarm_step"] is not None:
                        snap("Detection", f"Alarm after {res['detect_delay_s']:.0f} s " + ("(TA-GNN fault head, 2-sample persistence)." if scheme == "twin" else "(threshold protection, 3-sample persistence)."), res["detect_delay_s"], None, [])
                    else:
                        snap("Not detected", "This scheme raised no alarm during the fault (the backstop protection may still trip an overloaded feeder).", 0.0, None, [])
                    act = res.get("action")
                    if scheme == "twin" and act and act.get("costs"):
                        best = (act["label"], act["J"])
                        cands = [dict(label=c["label"], J=c["J"], n_sw=c["n_sw"], feasible=c["feasible"], chosen=(c["label"] == best[0] and abs(c["J"] - best[1]) < 1e-9)) for c in act["costs"][:8]]
                        snap("Candidate actions", f"{act['n_candidates']} candidates simulated on the twin, {act['n_rejected']} rejected as infeasible. Lowest-cost feasible action is chosen.", res["detect_delay_s"] or 0.0, None, [], cands)
                    if scheme == "default":
                        snap("Fixed restoration sequence", "Isolate the faulted section, then try the tie switches in list order, keeping the first feasible one.", res["detect_delay_s"] or 0.0, None, [])
                    for p in res.get("plan", []):
                        applied = dict(ops=[(o[0], int(o[1])) for o in p["ops"]], curtail=[int(i) for i in p["curtail"]], island=bool(p["island"]), storage=bool(p["storage"]))
                        snap(f"Action applied: {p['label']}", "Switch operations: " + (", ".join(f"{o[0]} line {int(o[1]) + 1}" for o in p["ops"]) or "none") + (", island enabled" if p["island"] else "") + (", flexible load curtailed" if p["curtail"] else "") + ".", p["time"], applied, res.get("trips", []))
                    # E_uns accumulation along the timeline
                    cum = 0.0
                    for s in stages:
                        s["e_uns_kwh"] = sum((min(seg["t1"], s["t_s"]) - seg["t0"]) / 3600.0 * seg["unserved_kw"] for seg in tl if seg["t0"] < s["t_s"])
                    stages.append(dict(name="Restored" if res["t_rec_s"] is not None else "Final state", description=(f"Restorable load re-energised after {res['t_rec_s']:.0f} s." if res["t_rec_s"] is not None else "No supply interruption in this scheme."),
                                       t_s=float(res["duration_s"]), status=stages[-1]["status"], energised=stages[-1]["energised"], unserved_kw=float(tl[-1]["unserved_kw"]), highlight_lines=stages[-1]["highlight_lines"],
                                       candidates=None, e_uns_kwh=float(res["e_uns_kwh"])))
                    S[scheme] = dict(stages=stages, t_rec_s=res["t_rec_s"], e_uns_kwh=res["e_uns_kwh"], detected=res["t_alarm_step"] is not None, detect_delay_s=res["detect_delay_s"],
                                     action=(res.get("action") or {}).get("label"))
                nodes = [ev["node"]] if "node" in ev else []
                scenarios.append(dict(id=f"{tag}_{k}", title=f"{ev['class_name'].replace('_', ' ').title()}" + (f" – line {ev['line'] + 1}" if "line" in ev else f" – node {ev['node'] + 1}") + (" (Table VIII)" if tag == "c1213" else ""),
                                      type=int(ev["type"]), start=int(ev["start"]), fault_nodes=nodes, summary=f"{ev['duration'] * JS.DT_S} s fault; twin T_rec {S['twin']['t_rec_s']}, default T_rec {S['default']['t_rec_s']}", **S))
        if scenarios:
            (RES / f"fault_replay_{t}.json").write_text(json.dumps(scenarios and dict(scenarios=scenarios), default=float))


# --------------------------------------------------------------------------------------------------------------- graphs
def mean_curves(curves_list, key):
    n = min(len(c[key]) for c in curves_list)
    return np.mean([c[key][:n] for c in curves_list], axis=0)


def graphs():
    charts = []

    def add(group, id, title, reproduces, caption, run_id, kind, data, series, xKey, xLabel="", yLabel="", **kw):
        charts.append(dict(group=group, id=id, title=title, reproduces=reproduces, caption=caption, run_id=run_id, kind=kind, data=data, series=series, xKey=xKey, xLabel=xLabel, yLabel=yLabel, **kw))

    # ---- journal Figs 2-5 from Table IV / V curves ----
    c4 = maybe(RES / "j_table4" / "curves.json")
    c5 = maybe(RES / "j_table5" / "curves.json")
    if c4:
        for t in TOPS:
            n = len(c4[f"{t}_o1"][0]["epoch"])
            data = [{"epoch": e + 1, **{f"o{o}": float(np.mean([c["val_loss"][e] for c in c4[f"{t}_o{o}"]])) for o in (1, 2, 3, 4)}} for e in range(n)]
            add("Journal Fig. 2 – initial validation loss", f"j_fig2_{t}", f"Topology {t}: validation loss of the four options", "Reproduces journal Fig. 2 (initial hyperparameter search, Table IV)",
                "Mean over 3 iterations of the Eq. 14 validation loss during the 25-epoch search.", "j_table4", "line", data,
                [dict(key=f"o{o}", label=f"Option {o}") for o in (1, 2, 3, 4)], "epoch", "epoch", "validation loss")
    if c5:
        for t in TOPS:
            L = c5[f"{t}_3_LRS"]
            n = len(L[0]["epoch"])
            data = [{"epoch": e + 1, "train": float(np.mean([c["train_loss"][e] for c in L])), "val": float(np.mean([c["val_loss"][e] for c in L])), "lr": float(L[0]["lr"][e])} for e in range(n)]
            add("Journal Fig. 3 – training with learning-rate scheduler", f"j_fig3_{t}", f"Topology {t}: option 3 with LRS", "Reproduces journal Fig. 3 (LRS training, Table V)",
                "Training and validation loss over 250 epochs; the learning rate drops at epochs 50 and 150.", "j_table5", "line", data,
                [dict(key="train", label="training loss"), dict(key="val", label="validation loss")], "epoch", "epoch", "loss", logY=True)
            for fig, key, name in (("Fig. 4 – fine-tuned training loss", "train_loss", "training"), ("Fig. 5 – fine-tuned validation loss", "val_loss", "validation")):
                runs = {"3_LRS": c5[f"{t}_3_LRS"], "3_NLRS": c5[f"{t}_3_NLRS"], "2_NLRS": c5[f"{t}_2_NLRS"]}
                nmax = max(len(v[0]["epoch"]) for v in runs.values())
                data = []
                for e in range(nmax):
                    row = {"epoch": e + 1}
                    for k, v in runs.items():
                        if e < len(v[0]["epoch"]):
                            row[k] = float(np.mean([c[key][e] for c in v]))
                    data.append(row)
                add(f"Journal {fig}", f"j_{fig.split('.')[0].lower().replace(' ', '')}{fig.split('.')[1][:2].strip()}_{t}".replace(" ", ""), f"Topology {t}: {name} loss, options 3_LRS / 3_NLRS / 2_NLRS",
                    f"Reproduces journal {fig.split(' –')[0]} (Table V)", f"Mean over 3 iterations of the {name} loss with and without the scheduler.", "j_table5", "line", data,
                    [dict(key="3_LRS", label="3_LRS"), dict(key="3_NLRS", label="3_NLRS"), dict(key="2_NLRS", label="2_NLRS")], "epoch", "epoch", f"{name} loss", logY=True)
    # ---- Fig 8 node-wise RMSE, Fig 9 ROC, Fig 10 forecast ----
    for t in TOPS:
        F = [maybe(ART / f"journal_{t}" / f"it{i}" / "final.json") for i in ((0,) if t == "C" else ITERS)]
        if all(F):
            gk = [[k for k in f["runs"] if k.startswith("gcn")][0] for f in F]
            ta = np.mean([f["runs"]["3_LRS"]["val"]["per_node_rmse_kw"] for f in F], axis=0)
            gc = np.mean([f["runs"][gk[i]]["val"]["per_node_rmse_kw"] for i, f in enumerate(F)], axis=0)
            top_nodes = jl(RES / "topologies.json")[t]["nodes"] if (RES / "topologies.json").exists() else None
            data = [{"node": f"{i + 1}", "ta_gnn": float(ta[i]), "gcn": float(gc[i])} for i in range(len(ta)) if (top_nodes is None or top_nodes[i]["load_kw"] > 0)]
            add("Journal Fig. 8 – node-wise RMSE", f"j_fig8_{t}", f"Topology {t}: RMSE per load-carrying node", "Reproduces journal Fig. 8", "Demand-forecast RMSE (kW) per node on the validation split, TA-GNN vs GCN, mean of 3 iterations.",
                "j_table6", "bar", data, [dict(key="ta_gnn", label="TA-GNN"), dict(key="gcn", label="GCN")], "node", "node (bus number)", "RMSE (kW)")
    try:
        from ai.testbed_models import predict
        from sklearn.metrics import roc_curve
        for t in TOPS:
            pr = predict.predict_scenario(t, 0, kind="eval", model_it=0, eval_it=0)
            y = pr["label"] > 0
            score = 1 - pr["probs"][:, 0]
            fpr, tpr, _ = roc_curve(y, score)
            idx = np.unique(np.linspace(0, len(fpr) - 1, 120).astype(int))
            add("Journal Fig. 9 – ROC", f"j_fig9_{t}", f"Topology {t}: ROC of the fault head (fault vs normal)", "Reproduces journal Fig. 9", "Held-out scenario of iteration 0; score = 1 − P(normal) of the TA-GNN fault head.",
                "j_table7", "line", [dict(fpr=float(fpr[i]), tpr=float(tpr[i]), chance=float(fpr[i])) for i in idx], [dict(key="tpr", label="TA-GNN fault head"), dict(key="chance", label="chance")], "fpr", "false-positive rate", "true-positive rate")
            node = int(np.argmax(pr["y_kw"].mean(0)))
            a, b = 36 * 120, 36 * 120 + 360  # a 30-minute window around mid-day
            add("Journal Fig. 10 – demand forecast", f"j_fig10_{t}", f"Topology {t}: demand forecast of bus {node + 1}", "Reproduces journal Fig. 10", "Predicted next-interval demand vs actual, one bus, 30 minutes of the held-out day.",
                "j_table6", "line", [dict(t_min=float((i - a) * 5 / 60), actual=float(pr["y_kw"][i, node]), predicted=float(pr["yhat_kw"][i, node])) for i in range(a, b)],
                [dict(key="actual", label="actual"), dict(key="predicted", label="TA-GNN")], "t_min", "minutes", "kW")
    except Exception as e:  # models/datasets not available yet
        print("skip Fig 9/10:", e)
    # ---- conference Fig 2 ROC per source ----
    r = maybe(RES / "c_table4" / "roc.json")
    if r:
        n = min(len(v["fpr"]) for v in r.values())
        grid = np.linspace(0, 1, 101)
        data = [{"fpr": float(x), **{s: float(np.interp(x, r[s]["fpr"], r[s]["tpr"])) for s in r}, "chance": float(x)} for x in grid]
        add("Conference Fig. 2 – ROC per source", "c_fig2", "Digital-twin fault-risk ROC per source", "Reproduces conference Fig. 2", "Test partition of one simulated dataset (seed 0); score = risk R_i(t) of Eq. 3.", "c_table4", "line", data,
            [dict(key=s, label=s) for s in r] + [dict(key="chance", label="chance")], "fpr", "false-positive rate", "true-positive rate")
    # ---- topology comparison bars ----
    m6, m7 = metric_map("j_table6"), metric_map("j_table7")
    if m6:
        add("Topology comparison (journal Tables VI / VII)", "j_cmp_forecast", "Forecast error by topology", "Compares journal Table VI", "Demand-forecast MAE and RMSE of GCN vs TA-GNN, mean of 3 iterations.", "j_table6", "bar",
            [dict(topology=t, gcn_mae=(m6.get((f"J.T6.{t}.gcn.mae", t)) or {}).get("value"), ta_mae=(m6.get((f"J.T6.{t}.ta_gnn.mae", t)) or {}).get("value"), gcn_rmse=(m6.get((f"J.T6.{t}.gcn.rmse", t)) or {}).get("value"), ta_rmse=(m6.get((f"J.T6.{t}.ta_gnn.rmse", t)) or {}).get("value")) for t in TOPS],
            [dict(key="gcn_mae", label="GCN MAE"), dict(key="ta_mae", label="TA-GNN MAE"), dict(key="gcn_rmse", label="GCN RMSE"), dict(key="ta_rmse", label="TA-GNN RMSE")], "topology", "topology", "kW")
    if m7:
        for key, ttl, unit, tid in (("detection_f1", "Fault-detection F1", "F1", "detection_f1"), ("t_rec", "Recovery time", "s", "t_rec"), ("e_uns", "Unserved energy", "kWh", "e_uns")):
            add("Topology comparison (journal Tables VI / VII)", f"j_cmp_{key}", f"{ttl}: default scheme vs twin", "Compares journal Table VII", f"{ttl} per topology on held-out fault scenarios, mean of 3 iterations.", "j_table7", "bar",
                [dict(topology=t, default=(m7.get((f"J.T7.{t}.default.{tid}", t)) or {}).get("value"), twin=(m7.get((f"J.T7.{t}.twin.{tid}", t)) or {}).get("value")) for t in TOPS],
                [dict(key="default", label="default scheme"), dict(key="twin", label="twin")], "topology", "topology", unit)
    # ---- FL bars + weights ----
    fl = maybe(RES / "j_table10" / "metrics.json")
    if fl:
        rows = {(m.get("target_id") or m["name"], m.get("topology")): m for m in fl["metrics"]}
        data = []
        for t in TOPS:
            row = {"topology": t}
            for mth in ("fedavg", "fedprox", "adaptive_fedprox"):
                mm = rows.get((f"J.T10.{mth}.rounds", t))
                row[mth] = None if not mm else mm["value"]
            data.append(row)
        add("Federated learning (journal Table X)", "j_fl_rounds", "Rounds to the target loss", "Compares journal Table X", "Rounds until the global validation loss reaches (centralised loss + 0.0012); blank = not reached in 150 rounds.", "j_table10", "bar", data,
            [dict(key="fedavg", label="FedAvg"), dict(key="fedprox", label="FedProx"), dict(key="adaptive_fedprox", label="adaptive FedProx")], "topology", "topology", "rounds")
        data = []
        for t in TOPS:
            row = {"topology": t}
            for mth in ("fedavg", "fedprox", "adaptive_fedprox"):
                mm = rows.get((f"J.T10.{mth}.comm_mb", t))
                row[mth] = None if not mm else mm["value"]
            data.append(row)
        add("Federated learning (journal Table X)", "j_fl_comm", "Communication volume C_comm", "Compares journal Table X (Eq. 18)", "2·R·K·|w|·4 bytes with the real parameter count of each topology's model.", "j_table10", "bar", data,
            [dict(key="fedavg", label="FedAvg"), dict(key="fedprox", label="FedProx"), dict(key="adaptive_fedprox", label="adaptive FedProx")], "topology", "topology", "MB")
    wl = maybe(RES / "j_table10" / "weights_A.json")
    if wl:
        add("Federated learning (journal Table X)", "j_fl_weights", "Adaptive client weights per round (topology A)", "Journal Eq. 16", "α_k per round for the 6 clients of topology A (η from the validation grid); equal weights would be 1/6.", "j_table10", "line", wl["rows"],
            [dict(key=f"c{k}", label=f"client {k + 1}") for k in range(wl["clients"])], "round", "round", "weight α_k")
    # ---- tau sensitivity lines ----
    c5m = maybe(RES / "c_table5" / "metrics.json")
    if c5m:
        data = []
        for tau in (0.3, 0.5, 0.7, 0.9):
            row = {"tau": tau}
            for cond in ("summer", "monsoon", "winter", "high_load", "low_load"):
                mm = next((m for m in c5m["metrics"] if m.get("target_id") == f"C.T5.tau{tau}.{cond}"), None)
                row[cond] = mm["value"] if mm else None
            data.append(row)
        add("Conference", "c_tau", "F1 vs threshold τ", "Reproduces conference Table V", "Out-of-fold F1 (5-fold blocked CV over the full year) by season and load band.", "c_table5", "line", data,
            [dict(key=c, label=c.replace("_", " ")) for c in ("summer", "monsoon", "winter", "high_load", "low_load")], "tau", "τ", "F1", dots=True)
    # ---- gas / latency ----
    ops = maybe(RAW / "contract_ops.json")
    if ops:
        names = ["register", "sell_offer", "buy_bid", "match", "meter", "settle"]
        add("Smart contract (journal Table XI)", "j_gas", "Gas per operation", "Compares journal Table XI", "receipt.gasUsed of every EnergyMarket function on the local Hardhat node.", "j_table11", "bar",
            [dict(op=o, gas=ops["automine"][o]["gas_mean"]) for o in names if o in ops["automine"]], [dict(key="gas", label="gas")], "op", "operation", "gas")
        add("Smart contract (journal Table XI)", "j_latency", "Latency per operation", "Compares journal Table XI", "Submission-to-receipt time: instant mining (automine) vs 1 s interval mining.", "j_table11", "bar",
            [dict(op=o, automine=ops["automine"][o]["latency_mean_s"], interval=ops["interval"][o]["latency_mean_s"]) for o in names if o in ops["automine"] and o in ops["interval"]],
            [dict(key="automine", label="automine"), dict(key="interval", label="1 s interval mining")], "op", "operation", "seconds")
    # ---- energy balance ----
    for t in TOPS:
        d = maybe(RES / f"redistribution_{t}.json")
        if d and "normal" in d:
            s = d["normal"]["series"]
            add("Energy balance and redistribution", f"j_energy_{t}", f"Topology {t}: energy balance over the day", "Journal trading scenario (Sec. V-B)", "Generation, consumption, power traded between buses and grid import per 5-minute interval (kW).",
                "j_trading", "line", [dict(hour=x["hour"], generation=x["generation_kw"], consumption=x["consumption_kw"], traded=x["traded_kw"], import_with=x["import_kw"], import_without=x["import_notrade_kw"]) for x in s],
                [dict(key="generation", label="generation"), dict(key="consumption", label="consumption"), dict(key="traded", label="traded"), dict(key="import_with", label="grid import with trading"), dict(key="import_without", label="grid import without trading")], "hour", "hour of day", "kW")
    (RES / "graphs.json").write_text(json.dumps(dict(charts=charts), default=float))
    print(len(charts), "charts")


def main():
    subprocess.run([sys.executable, str(ROOT / "experiments" / "export_topologies.py")], check=True)
    for f in (kpis, redistribution, fault_replay, graphs):
        try:
            f()
        except Exception as e:  # keep exporting what exists
            import traceback
            traceback.print_exc()
            print("export step failed:", f.__name__, e)


if __name__ == "__main__":
    main()
