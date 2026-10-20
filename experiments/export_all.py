"""Export view-ready JSON for the dashboard from the saved measured runs (nothing here invents a number):

  experiments/results/topologies.json        nodes / lines / layout / N-1 connectivity     (export_topologies.py)
  experiments/results/topology_kpis.json     per-topology KPI panel
  experiments/results/redistribution_<T>.json playback frames + KPIs (normal topology and after the twin's reconfiguration)
  experiments/results/fault_replay_<T>.json  recorded fault scenarios (stages, candidate actions with J, T_rec, E_uns)
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


def main():
    subprocess.run([sys.executable, str(ROOT / "experiments" / "export_topologies.py")], check=True)
    for f in (kpis, redistribution, fault_replay):
        try:
            f()
        except Exception as e:  # keep exporting what exists
            import traceback
            traceback.print_exc()
            print("export step failed:", f.__name__, e)


if __name__ == "__main__":
    main()
