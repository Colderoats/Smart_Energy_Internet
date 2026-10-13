"""Conference digital-twin fault-risk evaluation (Eqs. 1-6) on the 12-node ring testbed.

  Eq.1  Delta_i(t)  = || S_phys - S_twin ||   (state = [P, V, I] in per-unit of nameplate/nominal)
  Eq.2  Dbar_i(t)   = mean of Delta over the last w samples (causal)
  Eq.3  R_i(t)      = sigma(beta * Dbar - gamma)   beta, gamma fitted on the TRAIN partition (logistic regression, per source type)
  Eq.4  trigger     = R_i(t) > tau   tau chosen on VALIDATION: sweep 0.30..0.90 step 0.05, maximise F1 s.t. FAR <= 1 %
  Eq.5  j*          = argmax over eligible neighbours of  C_avail_j - lambda * dist(i, j)
  Eq.6  F_i->j*(t+1) = F_i->j*(t) + dP_comp
Labels always come from the injection log. All outputs are `simulated_testbed`.
"""
from __future__ import annotations

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from testbed import conference as C

W = 4  # smoothing window (1 h)
TAUS = np.round(np.arange(0.30, 0.9001, 0.05), 2)
FAR_MAX = 0.01
LAMBDA = 0.5  # kW of spare capacity "charged" per unit of ring distance (PREREGISTRATION C3)
STORAGE_KW = 0.0  # conference nodes carry no storage (PREREGISTRATION C3), so fallback (ii) is empty
NONCRIT_SHARE = 0.3  # share of a node's dP that is non-critical, sheddable load (fallback iii)


def deviation(d: dict) -> np.ndarray:
    """Eq. 1 -> [N, T]."""
    phys = d["features"][:, :, :3]
    tw = d["twin"]
    return np.linalg.norm(phys - tw, axis=-1)


def smooth(delta: np.ndarray, w: int = W) -> np.ndarray:
    """Eq. 2 (causal sliding mean)."""
    cs = np.cumsum(np.pad(delta, ((0, 0), (1, 0))), axis=1)
    out = np.empty_like(delta)
    T = delta.shape[1]
    idx = np.arange(T)
    lo = np.maximum(idx - w + 1, 0)
    out = (cs[:, idx + 1] - cs[:, lo]) / (idx - lo + 1)
    return out


def fit_logistic(dbar: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """beta, gamma of Eq. 3 by 1-D logistic regression with balanced class weights."""
    lr = LogisticRegression(class_weight="balanced", C=1e3, max_iter=500)
    lr.fit(dbar.reshape(-1, 1), y.reshape(-1))
    return float(lr.coef_[0, 0]), float(-lr.intercept_[0])


def risk(dbar: np.ndarray, beta: float, gamma: float) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-(beta * dbar - gamma)))


def prf(pred: np.ndarray, y: np.ndarray) -> dict:
    tp = int((pred & (y == 1)).sum())
    fp = int((pred & (y == 0)).sum())
    fn = int((~pred & (y == 1)).sum())
    tn = int((~pred & (y == 0)).sum())
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    far = fp / (fp + tn) if fp + tn else 0.0
    return dict(precision=p, recall=r, f1=f1, far=far, tp=tp, fp=fp, fn=fn, tn=tn)


def _types_idx():
    return {s: [i for i, t in enumerate(C.TYPES) if t == s] for s in ("solar", "wind", "hydro")}


def run_dataset(d: dict) -> dict:
    sp = C.splits()
    tr, va, te = (slice(*sp[k]) for k in ("train", "val", "test"))
    dbar = smooth(deviation(d))
    y = d["label"]
    ti = _types_idx()
    bg = {}
    R = np.zeros_like(dbar)
    for s, idx in ti.items():
        beta, gamma = fit_logistic(dbar[idx][:, tr], y[idx][:, tr])
        bg[s] = (beta, gamma)
        R[idx] = risk(dbar[idx], beta, gamma)
    # tau on validation (all nodes pooled)
    sweep = []
    for tau in TAUS:
        m = prf(R[:, va] > tau, y[:, va])
        sweep.append(dict(tau=float(tau), **m))
    ok = [s for s in sweep if s["far"] <= FAR_MAX]
    best = max(ok, key=lambda s: (s["f1"], -s["tau"])) if ok else max(sweep, key=lambda s: s["tau"])
    tau = best["tau"]
    out = dict(beta_gamma=bg, tau=tau, tau_sweep=sweep, per_source={}, window=W)
    delays, before_end, n_ev = [], 0, 0
    for s, idx in ti.items():
        Rt, yt = R[idx][:, te], y[idx][:, te]
        m = prf(Rt > tau, yt)
        m["auc"] = float(roc_auc_score(yt.reshape(-1), Rt.reshape(-1))) if yt.any() and not yt.all() else float("nan")
        out["per_source"][s] = m
    # detection delay / detected-before-end over test-partition fault events
    for ev in d["faults"]:
        if not (te.start <= ev["start"] < te.stop):
            continue
        n_ev += 1
        seg = R[ev["node"], ev["start"]:min(ev["end"], te.stop)] > tau
        if seg.any():
            delays.append(int(np.argmax(seg)))
            before_end += 1
    out["detection"] = dict(events=n_ev, detected=len(delays), mean_delay_intervals=float(np.mean(delays)) if delays else float("nan"),
                            detected_before_end_pct=100.0 * before_end / n_ev if n_ev else float("nan"))
    # ROC curve per source (test) for Fig 2
    from sklearn.metrics import roc_curve
    out["roc"] = {}
    for s, idx in ti.items():
        fpr, tpr, _ = roc_curve(y[idx][:, te].reshape(-1), R[idx][:, te].reshape(-1))
        k = np.unique(np.linspace(0, len(fpr) - 1, 200).astype(int))
        out["roc"][s] = dict(fpr=fpr[k].tolist(), tpr=tpr[k].tolist())
    out["actions"] = twin_actions(d, R, tau, te)
    return out


def twin_actions(d: dict, R: np.ndarray, tau: float, te: slice) -> dict:
    """Eqs. 5-6 at the alarm instant of every detected test fault, with the four fallbacks (split -> storage -> shed non-critical -> operator alert)."""
    nbrs = [[] for _ in range(C.N_NODES)]
    for a, b in C.EDGES:
        nbrs[a].append(b)
        nbrs[b].append(a)
    P = d["power_kw"]
    H = d["healthy_kw"]
    tiers = dict(single_neighbour=0, split_neighbours=0, storage=0, shed_noncritical=0, operator_alert=0)
    flow: dict[tuple[int, int], float] = {}
    n = 0
    for ev in d["faults"]:
        if not (te.start <= ev["start"] < te.stop):
            continue
        seg = R[ev["node"], ev["start"]:ev["end"]] > tau
        if not seg.any():
            continue
        t = ev["start"] + int(np.argmax(seg))
        i = ev["node"]
        dp = float(max(H[i, t] - P[i, t], 0.0))  # power to compensate (twin expectation - measured)
        n += 1
        live = [j for j in nbrs[i] if not d["down"][j, t]]
        avail = {j: C.CAP_KW - float(P[j, t]) for j in live}
        elig = {j: a for j, a in avail.items() if a >= dp}
        if elig:
            dist = lambda j: min((i - j) % C.N_NODES, (j - i) % C.N_NODES)
            jstar = max(elig, key=lambda j: elig[j] - LAMBDA * dist(j))
            tiers["single_neighbour"] += 1
            flow[(i, jstar)] = flow.get((i, jstar), 0.0) + dp  # Eq. 6
        elif sum(avail.values()) >= dp > 0:
            tiers["split_neighbours"] += 1
            for j, a in avail.items():
                flow[(i, j)] = flow.get((i, j), 0.0) + dp * a / sum(avail.values())
        elif STORAGE_KW >= dp - sum(avail.values()) > 0:
            tiers["storage"] += 1
        elif NONCRIT_SHARE * dp >= dp - sum(avail.values()) > 0:
            tiers["shed_noncritical"] += 1
        else:
            tiers["operator_alert"] += 1
    return dict(events=n, tiers=tiers, total_flow_updates=len(flow))


def blocked_cv(d: dict) -> dict:
    """Table V: out-of-fold F1 at fixed tau, 5 contiguous year blocks; by season and load band (output > 60 % / 5-30 % of nameplate)."""
    T = C.STEPS
    dbar = smooth(deviation(d))
    y = d["label"]
    ti = _types_idx()
    folds = np.array_split(np.arange(T), 5)
    out = {float(t): {} for t in (0.3, 0.5, 0.7, 0.9)}
    R = {t: np.zeros_like(dbar) for t in out}
    for k, te_idx in enumerate(folds):
        tr_idx = np.concatenate([f for j, f in enumerate(folds) if j != k])
        for s, idx in ti.items():
            beta, gamma = fit_logistic(dbar[idx][:, tr_idx], y[idx][:, tr_idx])
            for t in out:
                R[t][np.ix_(idx, te_idx)] = risk(dbar[idx][:, te_idx], beta, gamma)
    pw = d["power_kw"] / C.CAP_KW
    cond = dict(summer=np.broadcast_to(d["season"] == 0, y.shape), monsoon=np.broadcast_to(d["season"] == 1, y.shape),
                winter=np.broadcast_to(d["season"] == 2, y.shape), high_load=pw > 0.60, low_load=(pw >= 0.05) & (pw <= 0.30))
    for t in out:
        pred = R[t] > t
        for name, m in cond.items():
            out[t][name] = prf(pred[m], y[m])["f1"]
    return out
