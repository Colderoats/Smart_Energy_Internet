"""Conference experiments: Table VII (centralised forecasting, 6 models x 3 seeds) and Table VI (FL ablation).

  python -m ai.testbed_models.train_conf forecast    # Table VII + Fig data
  python -m ai.testbed_models.train_conf fl          # Table VI (mu sweep + FedAvg / FedProx-fixed / FedProx+adaptive x IID/0.5/0.1 x 3 seeds)
In-process federation: clients are processes-free simulations of the same local-train / aggregate loop (weights from ai.federated.weighting_testbed,
the same pure-numpy rule that the Flower strategies use). Everything is `simulated_testbed`.
"""
from __future__ import annotations

import copy
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch

from ai.testbed_models import conf_models as CM
from testbed import conference as C

torch.set_num_threads(1)
OUT = Path(__file__).resolve().parents[2] / "ai" / "artifacts" / "testbed" / "conference"
LR, BS, EPOCHS = 3e-3, 256, 15
SEEDS = (0, 1, 2)
DATA_SEED = 0  # forecasting / FL use dataset 0 (fault classification uses 5 datasets)


def split_windows(w: CM.Windows):
    sp = C.splits()
    tr = np.nonzero((w.t >= sp["train"][0]) & (w.t < sp["train"][1]))[0]
    va = np.nonzero((w.t >= sp["val"][0]) & (w.t < sp["val"][1]))[0]
    te = np.nonzero((w.t >= sp["test"][0]) & (w.t < sp["test"][1]))[0]
    return tr, va, te


def predict(model, w, idx, bs=2048):
    model.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(idx), bs):
            b = torch.from_numpy(idx[i:i + bs])
            out.append(model(w.x[b], w.A_table[w.A_id[b]]))
    return torch.cat(out)


def metrics(model, w, idx) -> dict:
    p = predict(model, w, idx) * C.CAP_KW
    y = w.y[idx] * C.CAP_KW
    e = p - y
    ss_res = float((e ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    return dict(rmse=float(torch.sqrt((e ** 2).mean())), mae=float(e.abs().mean()), r2=1 - ss_res / ss_tot)


def train_central(name: str, w, tr, va, seed: int, epochs=EPOCHS):
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    model = CM.make(name)
    opt = torch.optim.Adam(model.parameters(), lr=LR)
    best, best_state, curve = 1e9, None, []
    for ep in range(epochs):
        model.train()
        perm = rng.permutation(tr)
        for i in range(0, len(perm), BS):
            b = torch.from_numpy(perm[i:i + BS])
            loss = torch.mean((model(w.x[b], w.A_table[w.A_id[b]]) - w.y[b]) ** 2)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
        v = metrics(model, w, va)["rmse"]
        curve.append(v)
        if v < best:
            best, best_state = v, copy.deepcopy(model.state_dict())
    model.load_state_dict(best_state)
    return model, dict(val_curve=curve, best_val_rmse=best, best_epoch=int(np.argmin(curve)) + 1)


def run_forecast():
    OUT.mkdir(parents=True, exist_ok=True)
    d = C.simulate(DATA_SEED)
    w = CM.build_windows(d)
    tr, va, te = split_windows(w)
    res = {}
    for name in ("lstm", "gru", "gcn_fixed", "tgnn", "ta_gnn_no_adapt", "ta_gnn"):
        runs = []
        for s in SEEDS:
            t0 = time.time()
            model, info = train_central(name, w, tr, va, s)
            m = metrics(model, w, te)
            runs.append(dict(seed=s, test=m, **info, seconds=time.time() - t0, n_params=int(sum(p.numel() for p in model.parameters()))))
            print(name, s, m, f"{time.time() - t0:.0f}s", flush=True)
        res[name] = runs
    (OUT / "forecast.json").write_text(json.dumps(dict(provenance="simulated_testbed", config_hash=C.config_hash(), data_seed=DATA_SEED, epochs=EPOCHS, lr=LR, batch=BS,
                                                       split=C.splits(), runs=res), indent=1, default=float))


# ----------------------------------------------------------------------------------------------- federated (Table VI)
FL_CLIENTS, FL_ROUNDS, FL_EPOCHS = 6, 30, 2
MU_GRID = (0.001, 0.01, 0.1, 1.0)


def flat(m):
    return torch.cat([p.detach().flatten() for p in m.parameters()])


def put(m, v):
    i = 0
    for p in m.parameters():
        n = p.numel()
        p.data.copy_(v[i:i + n].view_as(p))
        i += n


def partition(w: CM.Windows, tr: np.ndarray, kind: str, seed: int) -> list[np.ndarray]:
    """6 clients. Groups = season (3) x load half (2) of the training windows. IID: random equal split. Dirichlet(alpha): each group is spread over the clients with Dir(alpha) proportions."""
    rng = np.random.default_rng(1000 + seed)
    if kind == "iid":
        p = rng.permutation(tr)
        return [a for a in np.array_split(p, FL_CLIENTS)]
    alpha = float(kind.replace("alpha", ""))
    groups = [tr[(w.season[tr] == s) & (w.load_high[tr] == h)] for s in range(3) for h in (False, True)]
    parts = [[] for _ in range(FL_CLIENTS)]
    for g in groups:
        g = rng.permutation(g)
        pr = rng.dirichlet([alpha] * FL_CLIENTS)
        cuts = (np.cumsum(pr) * len(g)).astype(int)[:-1]
        for c, chunk in enumerate(np.split(g, cuts)):
            parts[c].append(chunk)
    return [np.concatenate(p) if p else np.array([], dtype=int) for p in parts]


def run_fl_conf(w, parts, va, te, method: str, mu: float, seed: int, rounds=FL_ROUNDS, epochs=FL_EPOCHS):
    """method: fedavg (mu=0, n_k weights) | fedprox (mu, n_k weights) | fedprox_conf_adaptive (mu, Eqs 11-12)."""
    from ai.federated import weighting_paper as WP
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    glob = CM.make("ta_gnn")
    loc = CM.make("ta_gnn")
    val_curve, weights_log = [], []
    for r in range(rounds):
        w0 = flat(glob).clone()
        models, n_k, L_k = {}, {}, {}
        for k, idx in enumerate(parts):
            if len(idx) == 0:
                continue
            put(loc, w0)
            nv = max(int(0.1 * len(idx)), 1)  # the last 10 % of the client's own windows are its held-out local validation data
            idx_tr, idx_va = idx[:-nv], idx[-nv:]
            opt = torch.optim.Adam(loc.parameters(), lr=LR)
            for _ in range(epochs):
                loc.train()
                perm = rng.permutation(idx_tr)
                for i in range(0, len(perm), BS):
                    b = torch.from_numpy(perm[i:i + BS])
                    loss = torch.mean((loc(w.x[b], w.A_table[w.A_id[b]]) - w.y[b]) ** 2)
                    if method != "fedavg" and mu > 0:
                        loss = loss + 0.5 * mu * ((torch.cat([p.flatten() for p in loc.parameters()]) - w0) ** 2).sum()
                    opt.zero_grad(set_to_none=True)
                    loss.backward()
                    opt.step()
            models[k] = flat(loc).clone()
            n_k[k] = float(len(idx_tr))
            loc.eval()
            with torch.no_grad():  # only this scalar loss (and n_k) crosses the wire
                L_k[k] = float(torch.mean((predict(loc, w, idx_va) - w.y[torch.from_numpy(idx_va)]) ** 2))
        wt = WP.conf_weights(n_k, L_k) if method == "fedprox_conf_adaptive" else WP.sample_weights(n_k)
        put(glob, sum(wt[k] * models[k] for k in models))
        val_curve.append(metrics(glob, w, va)["rmse"])
        weights_log.append({str(k): v for k, v in wt.items()})
    best = min(val_curve)
    rounds_to = next(i + 1 for i, v in enumerate(val_curve) if v <= 1.05 * best)
    return dict(test=metrics(glob, w, te), val_curve=val_curve, rounds_within_5pct=rounds_to, weights=weights_log, n_k=[len(p) for p in parts])


def run_fl():
    OUT.mkdir(parents=True, exist_ok=True)
    d = C.simulate(DATA_SEED)
    w = CM.build_windows(d)
    tr, va, te = split_windows(w)
    # mu selection: FedProx (fixed weights), alpha = 0.5, seed 0, validation RMSE
    sweep = {}
    parts = partition(w, tr, "alpha0.5", 0)
    for mu in MU_GRID:
        r = run_fl_conf(w, parts, va, te, "fedprox", mu, 0)
        sweep[str(mu)] = r["val_curve"][-1]
        print("mu", mu, "val rmse", sweep[str(mu)], flush=True)
    mu_sel = float(min(sweep, key=lambda k: sweep[k]))
    res = {}
    for split in ("iid", "alpha0.5", "alpha0.1"):
        for method in ("fedavg", "fedprox", "fedprox_conf_adaptive"):
            runs = []
            for s in SEEDS:
                parts = partition(w, tr, split, s)
                r = run_fl_conf(w, parts, va, te, method, 0.0 if method == "fedavg" else mu_sel, s)
                runs.append(dict(seed=s, **r))
                print(split, method, s, r["test"]["rmse"], r["rounds_within_5pct"], flush=True)
            res[f"{method}|{split}"] = runs
    (OUT / "fl.json").write_text(json.dumps(dict(provenance="simulated_testbed", config_hash=C.config_hash(), mu_sweep_val_rmse=sweep, mu_selected=mu_sel, clients=FL_CLIENTS, rounds=FL_ROUNDS,
                                                 local_epochs=FL_EPOCHS, runs=res), default=float))


if __name__ == "__main__":
    {"forecast": run_forecast, "fl": run_fl}[sys.argv[1]]()
