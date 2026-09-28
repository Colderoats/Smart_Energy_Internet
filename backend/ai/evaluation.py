"""One evaluation routine for every scorer (rule-based baseline, plain GNN,
TA-GNN, ablation) so all numbers come from the identical test samples,
masks and metric code."""

from __future__ import annotations

import numpy as np

from ai import features as F
from ai import metrics as M
from ai.dataset import KelmarshArrays, Labels

STEPS_PER_DAY = 24 * 60 // F.STEP_MINUTES


def evaluate_scorer(
    score: np.ndarray,
    flag: np.ndarray,
    idx: np.ndarray,
    labels: Labels,
    *,
    bootstrap: bool = True,
) -> dict:
    """score/flag: [len(idx), 4] — continuous score (higher = more likely a
    fault start within 60 min) and the binary alarm at the scorer's operating
    point. idx: the split's step indices."""
    y, valid = labels.y[idx], labels.valid[idx]
    m = valid
    out: dict = {"n_valid_node_samples": int(m.sum()), "n_positive": int((y[m] == 1).sum())}

    det = M.prf(y[m], flag[m])
    det["roc_auc"] = M.roc_auc(y[m], score[m])
    det["pr_auc"] = M.pr_auc(y[m], score[m])
    det["false_alarm_samples_per_node_day"] = det["fp"] / max(m.sum() / STEPS_PER_DAY, 1e-9)
    if bootstrap and det["tp"] + det["fn"] > 0:
        day = np.broadcast_to((idx // STEPS_PER_DAY)[:, None], y.shape)
        det["ci95"] = M.day_block_bootstrap_prf(y[m], flag[m], day[m])
    out["detection"] = det

    out["localization"] = M.localization_topk(y, valid, score)

    pos = m & (y == 1)
    node = np.broadcast_to(np.arange(4)[None], y.shape)
    out["lead_time"] = M.lead_time_stats(
        labels.event_start_s[idx][pos], labels.lead_s[idx][pos], flag[pos], node[pos]
    )
    return out


def rule_scorer(arr: KelmarshArrays, idx: np.ndarray, variant: str) -> tuple[np.ndarray, np.ndarray]:
    """Module 2's rule-based detector as a (score, flag) pair.

    score  = its rolling temperature z-score (continuous, for AUC/ranking).
    variant:
      "fault_predicted"   alarm iff the PRODUCTION rule output is >= "fault_predicted" (>=5 sigma) at this step
                          — this is the level that triggers the twin's self-healing.
      "warning"           alarm iff output >= "warning" (>=3 sigma).
      "fault_predicted_w" as above but alarm if it fired anywhere in the last 60 min (window parity with the models).
    The label override is OFF in all variants (see ai/dataset.py)."""
    status = arr.rule_status[idx].astype(np.int8)
    z = arr.rule_z[idx].astype(np.float64)
    if variant == "fault_predicted":
        return z, status >= 2
    if variant == "warning":
        return z, status >= 1
    if variant == "fault_predicted_w":
        full = arr.rule_status.astype(np.int8)
        padded = np.concatenate([np.zeros((F.WINDOW_STEPS - 1, 4), dtype=np.int8), full], axis=0)
        win = np.stack([padded[s : s + len(full)] for s in range(F.WINDOW_STEPS)], axis=0).max(axis=0)
        zfull = arr.rule_z.astype(np.float64)
        zpad = np.concatenate([np.zeros((F.WINDOW_STEPS - 1, 4)), zfull], axis=0)
        zwin = np.stack([zpad[s : s + len(full)] for s in range(F.WINDOW_STEPS)], axis=0).max(axis=0)
        return zwin[idx], win[idx] >= 2
    raise ValueError(variant)
