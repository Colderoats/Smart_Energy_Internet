"""Journal federated learning on the testbed (Table X): one client per node, FedAvg / FedProx / adaptive FedProx (Eq. 16).

In-process federation (the exact local-train / weight / aggregate loop that the Flower strategies in
ai/federated/strategies_testbed.py run over gRPC). Weights come from ai.federated.weighting_paper, the same functions the
Flower strategy uses. Only model arrays, n_k and v_k are "transmitted" (checked by the wire allow-list in the Flower path).
PROVENANCE: simulated_testbed.
"""
from __future__ import annotations

import copy
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch

from ai.federated import weighting_paper as WP
from ai.testbed_models import journal_model as JM
from ai.testbed_models.journal_core import client_val, flat, load_flat, local_train
from ai.testbed_models.train_journal import OPTIONS, OUT_ROOT

torch.set_num_threads(int(__import__('os').environ.get('TB_THREADS', '1')))  # 1 by default; fewer, bigger jobs (topology C) may use more
LOCAL_FRACTION = 0.05  # a local epoch passes over a random 5 % of the client's training windows (compute reason, PREREGISTRATION amendment 1)
R_MAX = 100
TOL = 0.0012
GRID_MU = (0.001, 0.01, 0.1)
GRID_ETA = (0, 1, 5, 10)
GRID_E = (1, 3, 5)


def run_fl(top: str, it: int, method: str, mu: float, eta: float, E: int, seed: int, target: float, rounds: int = R_MAX, init_state=None, quiet=True) -> dict:
    """method: fedavg | fedprox | journal_adaptive. Returns per-round logs (global val loss/F1, weights) and rounds-to-target."""
    d, man = JM.load_data(top, it)
    data, stats = JM.make_data(top, d)
    N = data.N
    cfg = OPTIONS[3]
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    glob = JM.JointGNN(data.x.shape[-1], cfg["H"], cfg["K"], cfg["M"], "tag")
    if init_state is not None:
        glob.load_state_dict(init_state)
    n_params = JM.n_params(glob)
    n_tr = data.split
    all_tr = np.arange(n_tr)
    val_all = np.arange(n_tr, len(data.c))
    n_k = {k: float(n_tr) for k in range(N)}  # every node observes the whole training span
    log = []
    first_hit = first_hit_abs = None
    best = 1e9
    t0 = time.time()
    local = JM.JointGNN(data.x.shape[-1], cfg["H"], cfg["K"], cfg["M"], "tag")
    for r in range(1, rounds + 1):
        w_r = flat(glob).clone()
        models, vks = {}, {}
        for k in range(N):
            load_flat(local, w_r)
            local_train(local, data, k, w_r, 0.0 if method == "fedavg" else mu, E, LOCAL_FRACTION, cfg["lr"], rng, n_tr)
            models[k] = flat(local).clone()
            vsel = torch.from_numpy(rng.choice(val_all, min(len(val_all), 512), replace=False))
            vks[k] = client_val(local, data, vsel, k)
        if method == "journal_adaptive":
            w = WP.journal_weights(n_k, vks, eta)
        else:
            w = WP.sample_weights(n_k)
        agg = sum(w[k] * models[k] for k in range(N))
        load_flat(glob, agg)
        ev = JM.evaluate(glob, data, slice(n_tr, None))
        rec = dict(round=r, val_loss=ev["loss"], val_f1=ev["f1_macro"], val_mae_kw=ev["mae_kw"], cos=ev["cos_sim"], v_k=[vks[k] for k in range(N)],
                   weights=[w[k] for k in range(N)])
        log.append(rec)
        best = min(best, ev["loss"])
        if first_hit is None and ev["loss"] <= target:
            first_hit = r
        if first_hit_abs is None and ev["loss"] <= 0.0130:
            first_hit_abs = r
        if not quiet and r % 10 == 0:
            print(f"  {top} it{it} {method} mu={mu} eta={eta} E={E} round {r} val {ev['loss']:.4f} f1 {ev['f1_macro']:.3f} ({time.time() - t0:.0f}s)", flush=True)
    final = JM.evaluate(glob, data, slice(n_tr, None))
    return dict(method=method, mu=mu, eta=eta, E=E, seed=seed, rounds_to_target=first_hit, rounds_to_abs_0130=first_hit_abs, target=target, rounds_run=rounds,
                n_params=n_params, clients=N, comm_bytes_at_hit=WP.comm_cost_bytes(first_hit, N, n_params) if first_hit else None,
                comm_bytes_total=WP.comm_cost_bytes(rounds, N, n_params), best_val_loss=best, final=final, log=log, seconds=time.time() - t0, state=glob.state_dict())


def grid_configs(method_family: str):
    if method_family == "fedavg":
        return [dict(method="fedavg", mu=0.0, eta=0, E=E) for E in GRID_E]
    if method_family == "fedprox":
        return [dict(method="fedprox", mu=mu, eta=0, E=E) for mu in GRID_MU for E in GRID_E]
    return [dict(method="journal_adaptive", mu=mu, eta=eta, E=E) for mu in GRID_MU for eta in GRID_ETA if eta > 0 for E in GRID_E]


def central_target(top: str, it: int) -> float:
    fin = json.loads((OUT_ROOT / f"journal_{top}" / f"it{it}" / "final.json").read_text())
    return fin["runs"]["3_LRS"]["val"]["loss"] + TOL


def run_job(top: str, it: int, cfg: dict, tag: str) -> None:
    out = OUT_ROOT / f"journal_{top}" / f"it{it}" / "fl"
    out.mkdir(parents=True, exist_ok=True)
    f = out / f"{tag}.json"
    if f.exists():
        return
    res = run_fl(top, it, cfg["method"], cfg["mu"], cfg["eta"], cfg["E"], seed=it, target=central_target(top, it))
    res.pop("state")
    f.write_text(json.dumps(res))
    print("done", top, it, tag, "rounds->target", res["rounds_to_target"], "best", round(res["best_val_loss"], 4), flush=True)


def tag_of(cfg):
    return f"{cfg['method']}_mu{cfg['mu']}_eta{cfg['eta']}_E{cfg['E']}"


if __name__ == "__main__":
    # python -m ai.testbed_models.fl_journal job <top> <it> <method> <mu> <eta> <E>
    _, top, it, method, mu, eta, E = sys.argv[1:8]
    cfg = dict(method=method, mu=float(mu), eta=float(eta), E=int(E))
    run_job(top, int(it), cfg, tag_of(cfg))
