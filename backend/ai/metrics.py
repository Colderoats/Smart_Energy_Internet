"""Evaluation metrics — plain numpy, no scikit-learn (not in the locked stack).

Everything here works on flat arrays of VALID node-samples (masked samples
are dropped by the caller). All models and the rule-based baseline go through
these same functions on the identical test split.
"""

from __future__ import annotations

import numpy as np


def prf(y: np.ndarray, pred: np.ndarray) -> dict:
    y, pred = y.astype(bool), pred.astype(bool)
    tp, fp, fn = int((y & pred).sum()), int((~y & pred).sum()), int((y & ~pred).sum())
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": p, "recall": r, "f1": f1, "tp": tp, "fp": fp, "fn": fn}


def _avg_ranks(x: np.ndarray) -> np.ndarray:
    _, inv, counts = np.unique(x, return_inverse=True, return_counts=True)
    csum = np.cumsum(counts)
    avg = csum - (counts - 1) / 2.0  # 1-based average rank per unique value
    return avg[inv]


def roc_auc(y: np.ndarray, score: np.ndarray) -> float:
    y = y.astype(bool)
    n_pos, n_neg = int(y.sum()), int((~y).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    ranks = _avg_ranks(score)
    return float((ranks[y].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def pr_auc(y: np.ndarray, score: np.ndarray) -> float:
    """Average precision (step-wise area under the PR curve)."""
    y = y.astype(bool)
    n_pos = int(y.sum())
    if n_pos == 0:
        return float("nan")
    order = np.argsort(-score, kind="mergesort")
    ys = y[order]
    tp = np.cumsum(ys)
    prec = tp / np.arange(1, len(ys) + 1)
    # ties: evaluate only at the last index of each tied score group
    s_sorted = score[order]
    last_of_group = np.r_[s_sorted[1:] != s_sorted[:-1], True]
    tp_g, prec_g = tp[last_of_group], prec[last_of_group]
    recall_g = tp_g / n_pos
    prev = np.r_[0.0, recall_g[:-1]]
    return float(((recall_g - prev) * prec_g).sum())


def best_f1_threshold(y: np.ndarray, score: np.ndarray) -> float:
    """Threshold maximising F1 on (validation) data; ties -> higher threshold."""
    y = y.astype(bool)
    if y.sum() == 0:
        return float(np.max(score)) + 1.0
    order = np.argsort(-score, kind="mergesort")
    ys, ss = y[order], score[order]
    tp = np.cumsum(ys)
    fp = np.cumsum(~ys)
    fn = y.sum() - tp
    f1 = 2 * tp / np.maximum(2 * tp + fp + fn, 1)
    last_of_group = np.r_[ss[1:] != ss[:-1], True]
    f1 = np.where(last_of_group, f1, -1.0)
    return float(ss[int(np.argmax(f1))])


def day_block_bootstrap_prf(
    y: np.ndarray, pred: np.ndarray, day_id: np.ndarray, n_boot: int = 1000, seed: int = 0
) -> dict:
    """95% CI for precision/recall/F1 by resampling whole DAYS with
    replacement (samples within a day are strongly autocorrelated, so a
    per-sample bootstrap would be far too optimistic)."""
    rng = np.random.default_rng(seed)
    days = np.unique(day_id)
    tp = np.array([(y[day_id == d].astype(bool) & pred[day_id == d].astype(bool)).sum() for d in days])
    fp = np.array([(~y[day_id == d].astype(bool) & pred[day_id == d].astype(bool)).sum() for d in days])
    fn = np.array([(y[day_id == d].astype(bool) & ~pred[day_id == d].astype(bool)).sum() for d in days])
    out = {"precision": [], "recall": [], "f1": []}
    for _ in range(n_boot):
        pick = rng.integers(0, len(days), len(days))
        a, b, c = tp[pick].sum(), fp[pick].sum(), fn[pick].sum()
        p = a / (a + b) if a + b else 0.0
        r = a / (a + c) if a + c else 0.0
        out["precision"].append(p)
        out["recall"].append(r)
        out["f1"].append(2 * p * r / (p + r) if p + r else 0.0)
    return {k: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] for k, v in out.items()}


def localization_topk(
    y: np.ndarray, valid: np.ndarray, score: np.ndarray, ks=(1, 2), n_draws: int = 20, seed: int = 0
) -> dict:
    """Node-level localization. y/valid/score are [n_steps, n_nodes].

    Only snapshots with >=1 valid positive node are evaluated. Within a
    snapshot the valid nodes are ranked by score; top-k accuracy = fraction
    of snapshots where at least one of the k highest-ranked nodes is a true
    positive. Score ties are broken randomly (averaged over `n_draws`), so a
    scorer with no information (e.g. the rule detector when temperature is
    missing) is credited chance-level accuracy, not an arbitrary node order.
    Also returns the chance level for the same snapshots."""
    rng = np.random.default_rng(seed)
    has_pos = ((y == 1) & valid).any(axis=1)
    rows = np.nonzero(has_pos)[0]
    if len(rows) == 0:
        return {"n_snapshots": 0}
    res = {f"top{k}": 0.0 for k in ks}
    chance = {f"top{k}": 0.0 for k in ks}
    for r in rows:
        nodes = np.nonzero(valid[r])[0]
        pos = (y[r, nodes] == 1)
        for k in ks:
            kk = min(k, len(nodes))
            # chance: P(no positive among kk random picks)
            n, m = len(nodes), int(pos.sum())
            p_miss = 1.0
            for i in range(kk):
                p_miss *= max(n - m - i, 0) / (n - i)
            chance[f"top{k}"] += 1 - p_miss
            acc = 0.0
            for _ in range(n_draws):
                jitter = rng.random(len(nodes)) * 1e-9
                order = np.argsort(-(score[r, nodes] + jitter), kind="mergesort")
                acc += float(pos[order[:kk]].any())
            res[f"top{k}"] += acc / n_draws
    n_snap = len(rows)
    out = {"n_snapshots": int(n_snap), "mean_positive_nodes": float(((y == 1) & valid)[rows].sum(axis=1).mean())}
    for k in ks:
        out[f"top{k}"] = res[f"top{k}"] / n_snap
        out[f"chance_top{k}"] = chance[f"top{k}"] / n_snap
    return out


def lead_time_stats(
    event_start_s: np.ndarray, lead_s: np.ndarray, flagged: np.ndarray, node_of_sample: np.ndarray
) -> dict:
    """Per genuine fault event: detected if any of its valid positive samples is
    flagged; lead time = seconds between the EARLIEST flag and the fault start
    (at most the 60 min horizon). Inputs are flat arrays over valid POSITIVE
    samples only (event_start_s identifies the event; node_of_sample the turbine)."""
    key = np.stack([node_of_sample.astype(np.float64), event_start_s], axis=1)
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    leads, detected = [], 0
    for e in range(len(uniq)):
        m = inv == e
        f = flagged[m]
        if f.any():
            detected += 1
            leads.append(lead_s[m][f].max())
    n = len(uniq)
    return {
        "events_with_valid_positive_samples": int(n),
        "events_detected": int(detected),
        "event_recall": detected / n if n else float("nan"),
        "median_lead_min": float(np.median(leads) / 60) if leads else float("nan"),
        "mean_lead_min": float(np.mean(leads) / 60) if leads else float("nan"),
    }
