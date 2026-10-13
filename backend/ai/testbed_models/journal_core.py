"""Torch-only core (no pandapower / testbed import, so the Flower venv can use it): joint TA-GNN (Eqs. 11-14) and the first-order GCN baseline, on testbed data.

PROVENANCE: trained and evaluated on `simulated_testbed` data only (backend/testbed). Not related to the
Module 3 Kelmarsh model, which is untouched.

The TA layer is Eq. 11 in dense batched form: H' = relu( sum_{k=0..K} A_hat^k H W_k + b ), with A_hat of Eq. 10
recomputed from the switch states of every snapshot. For N <= 33 this is exactly PyG's TAGConv(normalize=False)
fed with A_hat as edge weights; tests/test_testbed.py checks the two agree numerically. Dense form is used because
the paper trains with a batch of N snapshots for hundreds of epochs and the per-step overhead of sparse
batching dominates on CPU.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as Fn

L_WIN = 12  # PREREGISTRATION F1
N_CLASSES = 5
F_NODE = 5
BATCH = 32  # snapshots per optimisation step (journal: 'batch size equals the number of nodes'; 32 ~ N of topology C - PREREGISTRATION amendment 1)


class TALayer(nn.Module):
    """Eq. 11: H' = sum_k A_hat^k H W_k + b. The K+1 hop-wise weight matrices are stored as ONE linear map on the concatenated hop features
    [H, A H, ..., A^K H] (identical function class and parameter count: (K+1) d_in d_out + d_out); fewer small ops per step on CPU."""

    def __init__(self, d_in: int, d_out: int, K: int):
        super().__init__()
        self.K = K
        self.d_in = d_in
        self.lin = nn.Linear(d_in * (K + 1), d_out)

    def forward(self, h, A):  # h [B,N,d], A [B,N,N]
        feats = [h]
        p = h
        for _ in range(self.K):
            p = torch.bmm(A, p)
            feats.append(p)
        return self.lin(torch.cat(feats, dim=-1))


class GCNLayer(nn.Module):
    def __init__(self, d_in: int, d_out: int, K: int = 1):
        super().__init__()
        self.W = nn.Linear(d_in, d_out)

    def forward(self, h, A):
        return self.W(torch.bmm(A, h))


class JointGNN(nn.Module):
    """Encoder of M layers + demand head (Eq. 12) + fault head on the pooled embedding (Eq. 13)."""

    def __init__(self, d_in: int, hidden: int, K: int, M: int, kind: str = "tag", n_classes: int = N_CLASSES):
        super().__init__()
        layer = TALayer if kind == "tag" else GCNLayer
        self.layers = nn.ModuleList([layer(d_in if i == 0 else hidden, hidden, K) for i in range(M)])
        self.head_y = nn.Linear(hidden, 1)
        self.head_c = nn.Linear(hidden, n_classes)
        self.kind, self.K, self.M, self.hidden = kind, K, M, hidden

    def forward(self, x, A):
        h = x
        for lyr in self.layers:
            h = Fn.relu(lyr(h, A))
        return self.head_y(h).squeeze(-1), self.head_c(h.mean(1))


def n_params(m: nn.Module) -> int:
    return int(sum(p.numel() for p in m.parameters()))


@dataclass
class Data:
    top_name: str
    N: int
    x: torch.Tensor  # [S, N, L*F] normalised windows
    A_id: torch.Tensor  # [S] index into A_table
    A_table: torch.Tensor  # [U, N, N] A_hat
    y: torch.Tensor  # [S, N] normalised demand Y(t+1)
    y_kw: torch.Tensor  # [S, N]
    c: torch.Tensor  # [S] fault class
    mask: torch.Tensor  # [N] nodes with a demand (loads)
    y_min: float
    y_scale: float
    t_index: np.ndarray  # absolute step of each sample
    split: int  # first validation sample


def batch_loss(model, data: Data, idx, lam_f=1.0, lam_c=1.0):
    x = data.x[idx]
    A = data.A_table[data.A_id[idx]]
    yh, ch = model(x, A)
    m = data.mask
    mse = ((yh - data.y[idx]) ** 2)[:, m].mean()
    ce = Fn.cross_entropy(ch, data.c[idx])
    return lam_f * mse + lam_c * ce, mse, ce, yh, ch


@torch.no_grad()
def evaluate(model, data: Data, sl: slice | np.ndarray, bs: int = 2048) -> dict:
    model.eval()
    ids = np.arange(len(data.c))[sl]
    tot, n = 0.0, 0
    ys, cs, ph, pc, probs = [], [], [], [], []
    mse_s = ce_s = 0.0
    for i in range(0, len(ids), bs):
        b = torch.from_numpy(ids[i:i + bs])
        loss, mse, ce, yh, ch = batch_loss(model, data, b)
        mse_s += float(mse) * len(b)
        ce_s += float(ce) * len(b)
        n += len(b)
        ph.append(yh * data.y_scale + data.y_min)
        ys.append(data.y_kw[b])
        pc.append(ch.argmax(1))
        probs.append(torch.softmax(ch, 1))
        cs.append(data.c[b])
    yh, y = torch.cat(ph), torch.cat(ys)
    m = data.mask
    err = (yh - y)[:, m]
    c, pcl, pr = torch.cat(cs).numpy(), torch.cat(pc).numpy(), torch.cat(probs).numpy()
    from sklearn.metrics import f1_score
    f1m = float(f1_score(c, pcl, average="macro", labels=sorted(set(c.tolist()) | set(pcl.tolist())), zero_division=0))
    f1b = float(f1_score(c > 0, pcl > 0, zero_division=0))
    per_node_rmse = torch.sqrt(((yh - y) ** 2).mean(0)).numpy()
    return dict(loss=(mse_s + ce_s) / n, mse=mse_s / n, ce=ce_s / n, mae_kw=float(err.abs().mean()), rmse_kw=float(torch.sqrt((err ** 2).mean())),
                f1_macro=f1m, f1_fault_binary=f1b, accuracy=float((pcl == c).mean()), per_node_rmse_kw=per_node_rmse.tolist(),
                cos_sim=float(Fn.cosine_similarity(yh[:, m].reshape(-1), y[:, m].reshape(-1), dim=0)))


def lr_schedule(epoch: int, use_lrs: bool, base_lr: float, scale: float = 1.0) -> float:
    """Journal Sec. V-A: 0.001 up to epoch 50, 0.0001 from 50 to 150, 0.00001 beyond 150 (relative to the base LR of 0.001)."""
    if not use_lrs:
        return base_lr
    return base_lr * (1.0 if epoch < 50 * scale else 0.1 if epoch < 150 * scale else 0.01)


# ----------------------------------------------------------------------- federated local training (shared by the in-process
# simulation in fl_journal.py and the Flower client in ai/federated/client_testbed.py: one implementation, so both paths agree)
def flat(model) -> torch.Tensor:
    return torch.cat([p.detach().flatten() for p in model.parameters()])


def load_flat(model, vec: torch.Tensor) -> None:
    i = 0
    for p in model.parameters():
        n = p.numel()
        p.data.copy_(vec[i:i + n].view_as(p))
        i += n


def client_loss(model, data: Data, idx, k: int, lam_f=1.0, lam_c=1.0):
    """Eq. 14 for client k: demand MSE over ITS node only (if the node has a demand) + fault cross-entropy."""
    x = data.x[idx]
    A = data.A_table[data.A_id[idx]]
    yh, ch = model(x, A)
    ce = Fn.cross_entropy(ch, data.c[idx])
    if bool(data.mask[k]):
        mse = ((yh[:, k] - data.y[idx][:, k]) ** 2).mean()
        return lam_f * mse + lam_c * ce
    return lam_c * ce


@torch.no_grad()
def client_val(model, data: Data, val_idx, k: int) -> float:
    model.eval()
    return float(client_loss(model, data, val_idx, k))


def local_train(model, data: Data, k: int, w_ref: torch.Tensor, mu: float, epochs: int, frac: float, lr: float, rng, n_train: int) -> float:
    """E local epochs of Adam on client k's loss + (mu/2)||w - w_ref||^2 (mu = 0: plain FedAvg local step). A local epoch passes over a random
    `frac` of the training windows in batches of N snapshots (batch = number of nodes, journal Sec. V-A). Returns the mean training loss."""
    opt = torch.optim.Adam(model.parameters(), lr=lr, fused=True)
    model.train()
    n_loc = int(frac * n_train)
    bs = BATCH
    tot, nb = 0.0, 0
    for _ in range(epochs):
        sel = torch.from_numpy(rng.choice(n_train, n_loc, replace=False))
        for i in range(0, n_loc - bs + 1, bs):
            loss = client_loss(model, data, sel[i:i + bs], k)
            if mu > 0:
                cur = torch.cat([p.flatten() for p in model.parameters()])
                loss = loss + 0.5 * mu * ((cur - w_ref) ** 2).sum()
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            tot += float(loss)
            nb += 1
    return tot / max(nb, 1)
