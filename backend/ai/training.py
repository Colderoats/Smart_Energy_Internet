"""Train / predict helpers shared by every model kind (one comparable harness).

Class imbalance is handled with a positively-weighted BCE (pos_weight =
sqrt(neg/pos) on the TRAIN split — the full neg/pos ratio is ~hundreds and
destabilises training) plus per-epoch negative subsampling of snapshots that
contain no positive node. The decision threshold is NOT the loss weighting's
concern: it is chosen on the validation split (max F1) afterwards.

Masked samples (planned/external stops, missing rows — see ai/dataset.py)
carry zero loss weight.
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn.functional as Fn

from ai import features as F
from ai import metrics as M

torch.set_num_threads(max(1, min(4, torch.get_num_threads())))


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


@dataclass
class SnapshotData:
    x: np.ndarray  # [n, N_NODES, NODE_FEATURES] float32
    y: np.ndarray  # [n, 4] uint8   (scored nodes only)
    valid: np.ndarray  # [n, 4] bool
    edge_index: np.ndarray  # [2, E]  shared topology


_edge_cache: dict[tuple[int, int, int], torch.Tensor] = {}


def _batched_edges(edge_index: np.ndarray, b: int) -> torch.Tensor:
    key = (id(edge_index), edge_index.shape[1], b)
    if key not in _edge_cache:
        _edge_cache[key] = torch.from_numpy(F.batch_edge_index(edge_index, b))
    return _edge_cache[key]


@torch.no_grad()
def predict_logits(model, x: np.ndarray, edge_index: np.ndarray, batch_size: int = 1024) -> np.ndarray:
    """[n, N_NODES, F] -> logits [n, 4] for the scored turbine nodes."""
    model.eval()
    out = []
    for s in range(0, len(x), batch_size):
        xb = torch.from_numpy(x[s : s + batch_size])
        b = xb.shape[0]
        logits = model(xb.reshape(b * F.N_NODES, -1), _batched_edges(edge_index, b)).reshape(b, F.N_NODES)
        out.append(logits[:, F.SCORED_IDX].numpy())
    return np.concatenate(out, axis=0)


def pos_weight_from(y: np.ndarray, valid: np.ndarray) -> float:
    pos = float(((y == 1) & valid).sum())
    neg = float(((y == 0) & valid).sum())
    return float(np.sqrt(neg / max(pos, 1.0)))


def fit(
    model,
    train: SnapshotData,
    val: SnapshotData,
    *,
    seed: int,
    epochs: int = 40,
    lr: float = 3e-3,
    weight_decay: float = 1e-4,
    batch_size: int = 256,
    patience: int = 8,
    neg_keep_frac: float = 0.3,
    log=print,
) -> dict:
    """Trains in place; restores the best-on-validation (PR-AUC) weights.
    Returns a history dict (also what goes in the experiment log)."""
    set_seed(seed)
    rng = np.random.default_rng(seed)
    pw = pos_weight_from(train.y, train.valid)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)

    has_valid = train.valid.any(axis=1)
    has_pos = ((train.y == 1) & train.valid).any(axis=1)
    pos_rows = np.nonzero(has_pos)[0]
    neg_rows = np.nonzero(has_valid & ~has_pos)[0]

    best = {"score": -1.0, "epoch": -1, "state": None}
    hist = {"pos_weight": pw, "epochs": []}
    x_all = torch.from_numpy(train.x)
    y_all = torch.from_numpy(train.y.astype(np.float32))
    v_all = torch.from_numpy(train.valid.astype(np.float32))

    for epoch in range(epochs):
        model.train()
        keep = rng.random(len(neg_rows)) < neg_keep_frac
        rows = np.concatenate([pos_rows, neg_rows[keep]])
        rng.shuffle(rows)
        total, n_batches = 0.0, 0
        for s in range(0, len(rows), batch_size):
            r = torch.from_numpy(rows[s : s + batch_size])
            b = len(r)
            logits = model(x_all[r].reshape(b * F.N_NODES, -1), _batched_edges(train.edge_index, b))
            logits = logits.reshape(b, F.N_NODES)[:, F.SCORED_IDX]
            loss_el = Fn.binary_cross_entropy_with_logits(
                logits, y_all[r], pos_weight=torch.tensor(pw), reduction="none"
            )
            loss = (loss_el * v_all[r]).sum() / v_all[r].sum().clamp(min=1.0)
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += float(loss)
            n_batches += 1

        vl = predict_logits(model, val.x, val.edge_index)
        m = val.valid
        val_ap = M.pr_auc(val.y[m], vl[m])
        val_auc = M.roc_auc(val.y[m], vl[m])
        hist["epochs"].append({"epoch": epoch, "train_loss": total / max(n_batches, 1), "val_pr_auc": val_ap, "val_roc_auc": val_auc})
        log(f"    epoch {epoch:2d}  loss {total / max(n_batches, 1):.4f}  val PR-AUC {val_ap:.4f}  ROC-AUC {val_auc:.4f}")
        score = val_ap if not np.isnan(val_ap) else -1.0
        if score > best["score"]:
            best = {"score": score, "epoch": epoch, "state": copy.deepcopy(model.state_dict())}
        elif epoch - best["epoch"] >= patience:
            break

    model.load_state_dict(best["state"])
    hist["best_epoch"] = best["epoch"]
    hist["best_val_pr_auc"] = best["score"]
    return hist


def fit_platt(logits: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Post-hoc Platt scaling p = sigmoid(a*logit + b) on VALIDATION logits so
    the served 'probability' is not distorted by the class weighting."""
    z = torch.tensor(logits, dtype=torch.float64)
    t = torch.tensor(y, dtype=torch.float64)
    a = torch.ones((), dtype=torch.float64, requires_grad=True)
    b = torch.zeros((), dtype=torch.float64, requires_grad=True)
    opt = torch.optim.LBFGS([a, b], lr=0.5, max_iter=200)

    def closure():
        opt.zero_grad()
        loss = Fn.binary_cross_entropy_with_logits(a * z + b, t)
        loss.backward()
        return loss

    opt.step(closure)
    return float(a), float(b)
