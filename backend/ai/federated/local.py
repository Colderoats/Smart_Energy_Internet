"""Local (client-side) training and evaluation of the Module 3 TA-GNN.

Same model class (ai.models.NodeClassifier, kind="tag"), same 46 node
features, same weighted-BCE objective, same per-epoch negative subsampling
and AdamW settings as Module 3's ai.training.fit — plus the FedProx proximal
term (mu / 2) * ||w - w_global||^2 in the local objective (mu = 0 gives plain
FedAvg local training).

Each sample is ONE turbine's own view: the twin's 9-node graph with only that
turbine's dynamic features filled in (see partition.py). The loss is on that
turbine's node only.

Deliberately imports only ai.models / ai.features / ai.metrics (not
ai.training, whose import sets the global torch thread count) so client
processes can pin themselves to one CPU thread.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

import numpy as np
import torch
import torch.nn.functional as Fn

from ai import features as F
from ai import metrics as M
from ai.models import NodeClassifier, get_weights, set_weights

N = F.N_NODES
S = F.STATIC_FEATURES
D_DYN = F.NODE_FEATURES - S  # 40 dynamic features per turbine


def make_model(seed: int) -> NodeClassifier:
    """The Module 3 TA-GNN with its Module 3 defaults, deterministically initialised."""
    torch.manual_seed(seed)
    np.random.seed(seed)
    model = NodeClassifier("tag")
    assert len(list(model.parameters())) == len(model.state_dict()), "state_dict has non-parameter buffers; prox term would misalign"
    return model


class OwnViewBatcher:
    """Builds batched 9-node graphs where each sample has ONE turbine's dynamic
    features filled in (`own` gives that turbine's node index per sample)."""

    def __init__(self, static: np.ndarray, edge_index: np.ndarray) -> None:
        self.static = torch.from_numpy(np.ascontiguousarray(static, dtype=np.float32))
        self.edge_index = edge_index
        self._edges: dict[int, torch.Tensor] = {}

    def edges(self, b: int) -> torch.Tensor:
        if b not in self._edges:
            self._edges[b] = torch.from_numpy(F.batch_edge_index(self.edge_index, b))
        return self._edges[b]

    def own_logits(self, model, dyn: torch.Tensor, own: torch.Tensor) -> torch.Tensor:
        b = dyn.shape[0]
        x = torch.zeros(b, N, S + D_DYN)
        x[:, :, :S] = self.static
        ar = torch.arange(b)
        x[ar, own, S:] = dyn
        out = model(x.reshape(b * N, -1), self.edges(b)).reshape(b, N)
        return out[ar, own]


@dataclass
class LocalData:
    """One training set: a single client's shard, or (for the centralized
    reference only) the four shards pooled."""

    train_x: np.ndarray
    train_y: np.ndarray
    train_own: np.ndarray  # [n] node index of the owning turbine
    val_x: np.ndarray
    val_y: np.ndarray
    val_own: np.ndarray
    batcher: OwnViewBatcher
    pos_weight: float = field(init=False)

    def __post_init__(self) -> None:
        pos, neg = float((self.train_y == 1).sum()), float((self.train_y == 0).sum())
        self.pos_weight = float(np.sqrt(neg / max(pos, 1.0)))  # same rule as Module 3, on THIS data


def local_data_from_shard(shard, train_x=None, train_y=None, val_x=None, val_y=None) -> LocalData:
    return LocalData(
        train_x=shard.train_x if train_x is None else train_x,
        train_y=shard.train_y if train_y is None else train_y,
        train_own=np.full(len(shard.train_y if train_y is None else train_y), shard.own_idx, dtype=np.int64),
        val_x=shard.val_x if val_x is None else val_x,
        val_y=shard.val_y if val_y is None else val_y,
        val_own=np.full(len(shard.val_y if val_y is None else val_y), shard.own_idx, dtype=np.int64),
        batcher=OwnViewBatcher(shard.static, shard.edge_index),
    )


def pooled_local_data(shards) -> LocalData:
    """Centralized reference: the four clients' data pooled (own-turbine view kept)."""
    cat = lambda name: np.concatenate([getattr(s, name) for s in shards])
    own = lambda name: np.concatenate([np.full(len(getattr(s, name)), s.own_idx, dtype=np.int64) for s in shards])
    return LocalData(
        train_x=cat("train_x"), train_y=cat("train_y"), train_own=own("train_y"),
        val_x=cat("val_x"), val_y=cat("val_y"), val_own=own("val_y"),
        batcher=OwnViewBatcher(shards[0].static, shards[0].edge_index),
    )


def train_epochs(
    model,
    opt,
    data: LocalData,
    *,
    epochs: int,
    rng: np.random.Generator,
    batch_size: int = 256,
    neg_keep_frac: float = 0.3,
    mu: float = 0.0,
    global_weights: list[np.ndarray] | None = None,
) -> dict:
    """Runs `epochs` epochs in place; returns mean data loss / mean prox term."""
    x_all = torch.from_numpy(data.train_x)
    y_all = torch.from_numpy(data.train_y.astype(np.float32))
    own_all = torch.from_numpy(data.train_own)
    pos_rows = np.nonzero(data.train_y == 1)[0]
    neg_rows = np.nonzero(data.train_y == 0)[0]
    pw = torch.tensor(data.pos_weight)
    ref = [torch.as_tensor(w) for w in global_weights] if (mu > 0 and global_weights is not None) else None

    model.train()
    tot_loss = tot_prox = 0.0
    n_batches = 0
    for _ in range(epochs):
        keep = rng.random(len(neg_rows)) < neg_keep_frac
        rows = np.concatenate([pos_rows, neg_rows[keep]])
        rng.shuffle(rows)
        for s in range(0, len(rows), batch_size):
            r = torch.from_numpy(rows[s : s + batch_size])
            logits = data.batcher.own_logits(model, x_all[r], own_all[r])
            loss = Fn.binary_cross_entropy_with_logits(logits, y_all[r], pos_weight=pw)
            total = loss
            if ref is not None:
                prox = sum(((p - g) ** 2).sum() for p, g in zip(model.parameters(), ref))
                total = loss + 0.5 * mu * prox
                tot_prox += float(prox)
            opt.zero_grad()
            total.backward()
            opt.step()
            tot_loss += float(loss)
            n_batches += 1
    n_batches = max(n_batches, 1)
    return {"train_loss": tot_loss / n_batches, "prox_sq_dist": tot_prox / n_batches, "n_batches": n_batches}


def local_train(
    weights: list[np.ndarray],
    data: LocalData,
    *,
    mu: float,
    epochs: int,
    seed: int,
    lr: float = 3e-3,
    weight_decay: float = 1e-4,
    batch_size: int = 256,
    neg_keep_frac: float = 0.3,
) -> tuple[list[np.ndarray], dict]:
    """One federated round of local training starting from the global weights.
    The optimiser is re-created every round (standard for stateless FL clients)."""
    model = make_model(seed)
    set_weights(model, weights)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    stats = train_epochs(
        model, opt, data, epochs=epochs, rng=np.random.default_rng(seed), batch_size=batch_size,
        neg_keep_frac=neg_keep_frac, mu=mu, global_weights=weights,
    )
    return get_weights(model), stats


@torch.no_grad()
def own_view_logits(model, batcher: OwnViewBatcher, dyn: np.ndarray, own: np.ndarray, chunk: int = 2048) -> np.ndarray:
    model.eval()
    out = []
    for s in range(0, len(dyn), chunk):
        out.append(batcher.own_logits(model, torch.from_numpy(dyn[s : s + chunk]), torch.from_numpy(own[s : s + chunk])).numpy())
    return np.concatenate(out) if out else np.zeros(0, dtype=np.float32)


def weighted_bce(logits: np.ndarray, y: np.ndarray, pos_weight: float) -> float:
    z, t = torch.from_numpy(logits.astype(np.float64)), torch.from_numpy(y.astype(np.float64))
    return float(Fn.binary_cross_entropy_with_logits(z, t, pos_weight=torch.tensor(pos_weight, dtype=torch.float64)))


def prior_loss(y: np.ndarray, pos_weight: float) -> float:
    """Weighted-BCE of the best CONSTANT predictor (the 'no skill' reference):
    optimal constant logit is log(pos_weight * pos / neg)."""
    pos, neg = float((y == 1).sum()), float((y == 0).sum())
    if pos == 0 or neg == 0:
        return float("nan")
    z = np.full(len(y), np.log(pos_weight * pos / neg))
    return weighted_bce(z, y, pos_weight)


def evaluate_local(model, data: LocalData, pos_weight: float | None = None) -> dict:
    """Scalar validation metrics on a client's OWN validation rows. Only these
    scalars ever leave the client."""
    pw = data.pos_weight if pos_weight is None else pos_weight
    logits = own_view_logits(model, data.batcher, data.val_x, data.val_own)
    loss = weighted_bce(logits, data.val_y, pw)
    prior = prior_loss(data.val_y, pw)
    return {
        "val_loss": loss,
        "val_loss_prior": prior,
        # loss relative to the no-skill constant predictor: <1 = better than no skill, comparable across clients
        "val_norm_loss": loss / prior if prior == prior and prior > 0 else float("nan"),
        "val_pr_auc": M.pr_auc(data.val_y, logits),
        "val_roc_auc": M.roc_auc(data.val_y, logits),
        "val_n": int(len(data.val_y)),
        "val_pos": int((data.val_y == 1).sum()),
    }


def fit_central(model, data: LocalData, *, seed: int, epochs: int = 40, patience: int = 8, lr: float = 3e-3,
                weight_decay: float = 1e-4, batch_size: int = 256, neg_keep_frac: float = 0.3, log=print) -> dict:
    """Centralized reference on the POOLED own-turbine-view data. Mirrors
    ai.training.fit exactly (persistent AdamW, <=40 epochs, early stopping on
    validation PR-AUC with patience 8, restore best) so it is comparable with
    Module 3's numbers; only the input view differs."""
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    best = {"score": -1.0, "epoch": -1, "state": None}
    hist = {"pos_weight": data.pos_weight, "epochs": []}
    for epoch in range(epochs):
        st = train_epochs(model, opt, data, epochs=1, rng=rng, batch_size=batch_size, neg_keep_frac=neg_keep_frac)
        vl = own_view_logits(model, data.batcher, data.val_x, data.val_own)
        ap = M.pr_auc(data.val_y, vl)
        hist["epochs"].append({"epoch": epoch, "train_loss": st["train_loss"], "val_pr_auc": ap})
        log(f"    epoch {epoch:2d}  loss {st['train_loss']:.4f}  val PR-AUC {ap:.4f}")
        score = ap if ap == ap else -1.0
        if score > best["score"]:
            best = {"score": score, "epoch": epoch, "state": copy.deepcopy(model.state_dict())}
        elif epoch - best["epoch"] >= patience:
            break
    model.load_state_dict(best["state"])
    hist.update(best_epoch=best["epoch"], best_val_pr_auc=best["score"])
    return hist
