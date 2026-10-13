"""Journal federated-learning experiments (Table X) on the simulated testbed.

  python experiments/fl_runner.py grid  [--jobs N]   # mu / eta / E grid (+ FedAvg over E, FedProx over mu x E) on iteration 0 of each topology, selection by VALIDATION only
  python experiments/fl_runner.py final [--jobs N]   # selected config of each family on iterations 0-2 (iteration 0 reuses the grid run)
  python experiments/fl_runner.py tables             # aggregate -> experiments/results/j_table10/metrics.json
Targets: rounds until the global validation loss <= (centralised validation loss of the same iteration + 0.0012); the absolute 0.0130 is reported too.
"""
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "experiments"))

import numpy as np  # noqa: E402

from lib import metric, write_run  # noqa: E402

PY = str(ROOT / "backend" / "testbed" / "venv" / "Scripts" / "python.exe")
ART = ROOT / "backend" / "ai" / "artifacts" / "testbed"
TOPS = ("A", "B", "C")
GRID_MU, GRID_ETA, GRID_E = (0.001, 0.01, 0.1), (0, 1, 5, 10), (1, 3, 5)
FAMILIES = {"fedavg": "fedavg", "fedprox": "fedprox", "adaptive_fedprox": "journal_adaptive"}


def tag_of(m, mu, eta, E):
    return f"{m}_mu{float(mu)}_eta{float(eta)}_E{int(E)}"


def configs(family):
    if family == "fedavg":
        return [("fedavg", 0.0, 0.0, E) for E in GRID_E]
    if family == "fedprox":
        return [("fedprox", mu, 0.0, E) for mu in GRID_MU for E in GRID_E]
    return [("journal_adaptive", mu, eta, E) for mu in GRID_MU for eta in GRID_ETA if eta > 0 for E in GRID_E]


def run_cmd(top, it, cfg):
    m, mu, eta, E = cfg
    return [PY, "-m", "ai.testbed_models.fl_journal", "job", top, str(it), m, str(mu), str(eta), str(E)]


def farm(cmds, jobs):
    import os
    env = dict(os.environ, PYTHONPATH=str(ROOT / "backend"))

    def go(c):
        r = subprocess.run(c, cwd=ROOT / "backend", env=env)
        if r.returncode:
            print("FAILED", c, flush=True)
    with ThreadPoolExecutor(jobs) as ex:
        list(ex.map(go, cmds))


def load(top, it, cfg):
    f = ART / f"journal_{top}" / f"it{it}" / "fl" / f"{tag_of(*cfg)}.json"
    return json.loads(f.read_text()) if f.exists() else None


def score(r):
    # selection on VALIDATION only: fewest rounds to the target; ties / not reached -> lowest best validation loss
    return (r["rounds_to_target"] if r["rounds_to_target"] is not None else 10 ** 6, r["best_val_loss"])


def select(tops=TOPS):
    """Topology A: validation-selected over the full grid. Topologies B and C use A's selection (PREREGISTRATION amendment 3: a per-topology grid is infeasible)."""
    sel = json.loads((ART / "fl_selected.json").read_text()) if (ART / "fl_selected.json").exists() else {}
    for t in tops:
        sel[t] = {}
        for fam in FAMILIES:
            if t == "A":
                cand = [(cfg, load(t, 0, cfg)) for cfg in configs(fam)]
                cand = [(c, r) for c, r in cand if r]
                if cand:
                    c, r = min(cand, key=lambda cr: score(cr[1]))
                    sel[t][fam] = dict(cfg=list(c), rounds_to_target=r["rounds_to_target"], best_val_loss=r["best_val_loss"], grid_size=len(cand), tuned_on="A")
            elif fam in sel.get("A", {}):
                c = tuple(sel["A"][fam]["cfg"])
                r = load(t, 0, c)
                sel[t][fam] = dict(cfg=list(c), rounds_to_target=r["rounds_to_target"] if r else None, best_val_loss=r["best_val_loss"] if r else None, grid_size=1, tuned_on="A")
    (ART / "fl_selected.json").write_text(json.dumps(sel, indent=1))
    return sel


def grid(jobs):
    cmds = [run_cmd("A", 0, c) for fam in FAMILIES for c in configs(fam)]
    farm(cmds, jobs)
    sel = select(("A",))
    farm([run_cmd(t, 0, tuple(sel["A"][fam]["cfg"])) for t in ("C", "B") for fam in FAMILIES if fam in sel["A"]], jobs)
    print(json.dumps(select(("B", "C")), indent=1))


def final(jobs):
    sel = select()
    cmds = []
    c_iters = int(sys.argv[sys.argv.index("--c-iters") + 1]) if "--c-iters" in sys.argv else 1
    for t in TOPS:
        for fam, v in sel[t].items():
            for it in (1, 2):
                if t == "C" and it >= c_iters:
                    continue  # compute: topology C is run on the first c_iters iterations only (see amendment 3)
                cmds.append(run_cmd(t, it, tuple(v["cfg"])))
    farm(cmds, jobs)


def tables():
    sel = json.loads((ART / "fl_selected.json").read_text())
    ms, weights_A, rawsum = [], None, {}
    for t in TOPS:
        cen = [json.loads((ART / f"journal_{t}" / f"it{i}" / "final.json").read_text())["runs"]["3_LRS"]["val"] for i in range(1 if t == "C" else 3)]
        n_it = [i for i in range(3) if all(load(t, i, tuple(sel[t][f]["cfg"])) for f in sel[t])] if t in sel else []
        ms.append(metric("val_loss", None, target_id="J.T10.central.val_loss", vals=[c["loss"] for c in cen], topology=t, equation="14", formula="validation loss of the centralised option-3 LRS model", conditions="centralised"))
        ms.append(metric("fault_f1", None, target_id="J.T10.central.fault_f1", vals=[c["f1_macro"] for c in cen], topology=t, equation="13", formula="macro-F1 of the TA-GNN fault head (kept separate from the Table VII twin detection F1)", conditions="centralised"))
        best_by_it = {}
        for fam, label in (("fedavg", "fedavg"), ("fedprox", "fedprox"), ("adaptive_fedprox", "adaptive_fedprox")):
            if fam not in sel[t]:
                continue
            cfg = tuple(sel[t][fam]["cfg"])
            runs = [load(t, i, cfg) for i in range(3)]
            runs = [r for r in runs if r]  # topology C may have fewer iterations (amendment 3)
            if not runs:
                continue  # run not finished yet: no value is reported for this cell
            hit = [r["rounds_to_target"] for r in runs if r["rounds_to_target"] is not None]
            cond = f"{fam}; selected on validation: mu={cfg[1]}, eta={cfg[2]}, E={cfg[3]}; K={runs[0]['clients']} clients; max {runs[0]['rounds_run']} rounds"
            note = f"{len(hit)} of {len(runs)} iterations reached the target" + ("" if hit else " - not reached within the round budget (100 rounds)")
            ms.append(metric("rounds_to_target", float(np.mean(hit)) if hit else None, target_id=f"J.T10.{label}.rounds", vals=hit or None, unit="rounds", topology=t,
                             formula="first round whose global validation loss <= (centralised loss + 0.0012)", conditions=cond, note=note, seeds=[0, 1, 2][:len(runs)]))
            ms.append(metric("rounds_to_abs_0130", None, vals=[r["rounds_to_abs_0130"] for r in runs if r["rounds_to_abs_0130"]] or None, unit="rounds", topology=t, formula="first round with validation loss <= 0.0130 (the paper's absolute target)", conditions=cond))
            mb = [r["comm_bytes_at_hit"] / 1e6 for r in runs if r["comm_bytes_at_hit"]]
            ms.append(metric("comm_volume", float(np.mean(mb)) if mb else None, target_id=f"J.T10.{label}.comm_mb", vals=mb or None, unit="MB", topology=t, equation="18",
                             formula="2 R K |w| beta with R = rounds to target, K = clients, |w| = parameters, beta = 4 bytes",
                             inputs=dict(K=runs[0]["clients"], params=runs[0]["n_params"], beta=4), conditions=cond))
            ms.append(metric("comm_volume_full_budget", None, vals=[r["comm_bytes_total"] / 1e6 for r in runs], unit="MB", topology=t, equation="18", formula="2 R K |w| beta over the full round budget", conditions=cond))
            ms.append(metric("val_loss", None, target_id=f"J.T10.{label}.val_loss", vals=[r["final"]["loss"] for r in runs], topology=t, equation="14", formula="global validation loss after the last round", conditions=cond))
            ms.append(metric("fault_f1", None, target_id=f"J.T10.{label}.fault_f1", vals=[r["final"]["f1_macro"] for r in runs], topology=t, equation="13", formula="macro-F1 of the TA-GNN fault head after the last round", conditions=cond))
            best_by_it[fam] = [r["best_val_loss"] for r in runs]
            if t == "A" and fam == "adaptive_fedprox":
                weights_A = dict(clients=runs[0]["clients"], rows=[dict(round=x["round"], **{f"c{k}": w for k, w in enumerate(x["weights"])}) for x in runs[0]["log"]])
        # secondary: a target every method can reach (5 % above the best validation loss any method attained, iteration-wise)
        if best_by_it:
            for fam in best_by_it:
                cfg = tuple(sel[t][fam]["cfg"])
                hits = []
                for i in range(3):
                    r = load(t, i, cfg)
                    if not r:
                        continue
                    ref = 1.05 * min(min(b[i] for b in best_by_it.values() if len(b) > i) for _ in [0])
                    h = next((x["round"] for x in r["log"] if x["val_loss"] <= ref), None)
                    if h:
                        hits.append(h)
                ms.append(metric("rounds_to_common_target", float(np.mean(hits)) if hits else None, vals=hits or None, unit="rounds", topology=t,
                                 formula="first round with validation loss <= 1.05 x the best loss any method reached in that iteration (secondary comparison that every method can satisfy)", conditions=fam))
        rawsum[t] = sel[t]
    # derived reduction (abstract): FedProx -> adaptive FedProx per topology, from the measured rounds
    by = {(m.get("target_id"), m["topology"]): m for m in ms}
    red = []
    for t in TOPS:
        a, b = by.get((f"J.T10.fedprox.rounds", t)), by.get((f"J.T10.adaptive_fedprox.rounds", t))
        if a and b and a["value"] and b["value"]:
            red.append(metric("comm_reduction_pct", 100 * (a["value"] - b["value"]) / a["value"], unit="%", topology=t,
                              formula="(R_FedProx - R_adaptive) / R_FedProx x 100 (depends only on rounds, conflict 7)", inputs=dict(fedprox_rounds=a["value"], adaptive_rounds=b["value"])))
    if red:
        ms += red
        ms.append(metric("comm_reduction_pct_max", max(r["value"] for r in red), target_id="J.ABS.comm", unit="%", formula="max over topologies of the FedProx -> adaptive FedProx communication reduction",
                         inputs={r["topology"]: r["value"] for r in red}))
    out = write_run("j_table10", ms, dict(grid=dict(mu=GRID_MU, eta=GRID_ETA, E=GRID_E), selection=rawsum, rounds_max=100, local_fraction=0.05, target="centralised val loss + 0.0012"))
    if weights_A:
        (out / "weights_A.json").write_text(json.dumps(weights_A))


if __name__ == "__main__":
    cmd = sys.argv[1]
    jobs = int(sys.argv[sys.argv.index("--jobs") + 1]) if "--jobs" in sys.argv else 10
    {"grid": lambda: grid(jobs), "final": lambda: final(jobs), "tables": tables}[cmd]()
