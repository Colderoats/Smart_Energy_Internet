"""Conference forecasting models on the 12-node ring testbed (Tables III, VI, VII).

Input window 8 steps x 7 features per node, horizon 1 step (15 min), target = next-step power.
  TA-GNN       : window -> 32 hidden units, 2 TA-conv layers (K=2, ReLU) on A_hat(t), 2-layer MLP head
  TA-GNN-fixed : same on the fixed base adjacency (conference "TA-GNN without adaptation")
  LSTM / GRU   : per-node sequence models (graph ignored)
  GCN-fixed    : 2 first-order GCN layers on the fixed adjacency, skip connections
  TGNN         : per-step GCN, then GRU over time, skip connection
A_hat(t) comes from the CURRENT topology: nodes producing < 2 % of nameplate are tripped and their links drop (A_hat of journal
Eq. 10 / conference Eq. 7). PROVENANCE: simulated_testbed.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch
import torch.nn as nn

from testbed import conference as C
from testbed.topologies import a_hat

H = 32
FIXED_A = None


def base_adj() -> np.ndarray:
    A = np.zeros((C.N_NODES, C.N_NODES), np.float32)
    for a, b in C.EDGES:
        A[a, b] = A[b, a] = 1.0
    return A


def adj_from_down(down: np.ndarray) -> np.ndarray:
    A = base_adj()
    A[down, :] = 0
    A[:, down] = 0
    return a_hat(A)


class TAL(nn.Module):
    def __init__(self, d_in, d_out, K):
        super().__init__()
        self.W = nn.ModuleList([nn.Linear(d_in, d_out, bias=(k == 0)) for k in range(K + 1)])
        self.K = K

    def forward(self, h, A):
        out = self.W[0](h)
        p = h
        for k in range(1, self.K + 1):
            p = torch.matmul(A, p)
            out = out + self.W[k](p)
        return out


class TAGNN(nn.Module):
    def __init__(self, adaptive=True):
        super().__init__()
        self.adaptive = adaptive
        self.inp = nn.Linear(C.WINDOW * C.N_FEATURES, H)
        self.l1, self.l2 = TAL(H, H, 2), TAL(H, H, 2)
        self.mlp = nn.Sequential(nn.Linear(H, H), nn.ReLU(), nn.Linear(H, 1))
        self.register_buffer("A0", torch.from_numpy(a_hat(base_adj())))

    def forward(self, x, A):  # x [B,N,8,7], A [B,N,N]
        A = A if self.adaptive else self.A0.expand(x.shape[0], -1, -1)
        h = torch.relu(self.inp(x.flatten(2)))
        h = torch.relu(self.l1(h, A))
        h = torch.relu(self.l2(h, A))
        return self.mlp(h).squeeze(-1)


class GCNFixed(nn.Module):
    def __init__(self):
        super().__init__()
        self.inp = nn.Linear(C.WINDOW * C.N_FEATURES, H)
        self.w1, self.w2 = nn.Linear(H, H), nn.Linear(H, H)
        self.mlp = nn.Sequential(nn.Linear(H, H), nn.ReLU(), nn.Linear(H, 1))
        self.register_buffer("A0", torch.from_numpy(a_hat(base_adj())))

    def forward(self, x, A):
        h0 = torch.relu(self.inp(x.flatten(2)))
        h1 = torch.relu(self.w1(torch.matmul(self.A0, h0))) + h0  # skip
        h2 = torch.relu(self.w2(torch.matmul(self.A0, h1))) + h1  # skip
        return self.mlp(h2).squeeze(-1)


class TGNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.g = nn.Linear(C.N_FEATURES, H)
        self.gru = nn.GRU(H, H, batch_first=True)
        self.skip = nn.Linear(C.N_FEATURES, H)
        self.mlp = nn.Sequential(nn.Linear(H, H), nn.ReLU(), nn.Linear(H, 1))
        self.register_buffer("A0", torch.from_numpy(a_hat(base_adj())))

    def forward(self, x, A):
        B, N, W, F = x.shape
        xs = x.permute(0, 2, 1, 3)  # [B,W,N,F]
        h = torch.relu(self.g(torch.matmul(self.A0, xs)))  # graph conv per time step [B,W,N,H]
        h = h.permute(0, 2, 1, 3).reshape(B * N, W, H)
        _, last = self.gru(h)
        out = last[0].reshape(B, N, H) + torch.relu(self.skip(x[:, :, -1]))
        return self.mlp(out).squeeze(-1)


class SeqModel(nn.Module):
    def __init__(self, cell="lstm"):
        super().__init__()
        self.rnn = (nn.LSTM if cell == "lstm" else nn.GRU)(C.N_FEATURES, H, batch_first=True)
        self.cell = cell
        self.mlp = nn.Sequential(nn.Linear(H, H), nn.ReLU(), nn.Linear(H, 1))

    def forward(self, x, A):
        B, N, W, F = x.shape
        o, hn = self.rnn(x.reshape(B * N, W, F))
        last = hn[0][-1] if self.cell == "lstm" else hn[-1]
        return self.mlp(last).reshape(B, N)


def make(name: str) -> nn.Module:
    return {"ta_gnn": lambda: TAGNN(True), "ta_gnn_no_adapt": lambda: TAGNN(False), "gcn_fixed": GCNFixed, "tgnn": TGNN,
            "lstm": lambda: SeqModel("lstm"), "gru": lambda: SeqModel("gru")}[name]()


@dataclass
class Windows:
    x: torch.Tensor      # [S,N,8,7]
    A_id: torch.Tensor   # [S]
    A_table: torch.Tensor  # [U,N,N]
    y: torch.Tensor      # [S,N] next-step power / cap
    t: np.ndarray        # absolute step of the target
    season: np.ndarray   # [S]
    load_high: np.ndarray  # [S] mean output of the window above the median


def build_windows(d: dict) -> Windows:
    f = d["features"]  # [N,T,7]
    N, T, _ = f.shape
    ts = np.arange(C.WINDOW - 1, T - 1)  # window ends at ts, target at ts+1
    idx = ts[:, None] + np.arange(-C.WINDOW + 1, 1)[None, :]
    x = np.transpose(f[:, idx, :], (1, 0, 2, 3)).astype(np.float32)  # [S,N,8,7]
    y = (d["power_kw"][:, ts + 1] / C.CAP_KW).T.astype(np.float32)
    down = d["down"][:, ts].T  # topology at the window's last step
    uniq, inv = np.unique(down, axis=0, return_inverse=True)
    A = np.stack([adj_from_down(u) for u in uniq]).astype(np.float32)
    pw = f[:, :, 0].mean(0)
    mean_out = np.convolve(pw, np.ones(C.WINDOW) / C.WINDOW, mode="full")[ts]
    return Windows(torch.from_numpy(x), torch.from_numpy(inv.reshape(-1).astype(np.int64)), torch.from_numpy(A), torch.from_numpy(y), ts,
                   d["season"][ts], mean_out > np.median(mean_out))
