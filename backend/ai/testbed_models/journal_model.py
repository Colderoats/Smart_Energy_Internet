"""Journal joint TA-GNN on testbed data: model/loss/evaluation live in journal_core (torch only); this module adds the testbed data pipeline
(Eq. 9 normalisation, Eq. 10 A_hat per snapshot) and re-exports the core API under the old names."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch

from ai.testbed_models.journal_core import *  # noqa: F401,F403
from ai.testbed_models.journal_core import Data, F_NODE, L_WIN
from testbed import journal_sim as JS
from testbed.topologies import a_hat, build


def load_data(top_name: str, it: int, root: Path | None = None, kind: str = "train") -> tuple[dict, dict]:
    root = Path(root or JS.DATA_ROOT)
    p = root / JS.SCENARIO_KINDS[kind][0].format(t=top_name) / f"it{it}"
    d = np.load(p / "data.npz")
    man = json.loads((p / "manifest.json").read_text())
    return {k: d[k] for k in d.files}, man


def make_data(top_name: str, d: dict, stats: dict | None = None, L: int = L_WIN) -> tuple[Data, dict]:
    top = build(top_name)
    X, Y, lab, status = d["X"], d["Y"], d["label"], d["status"]
    T, N, _ = X.shape
    n_train_steps = int(0.8 * T)
    if stats is None:  # Eq. 9: min / max per feature over the TRAIN part only
        flat = X[:n_train_steps].reshape(-1, F_NODE)
        mn, mx = flat.min(0), flat.max(0)
        mx = np.where(mx - mn < 1e-9, mn + 1.0, mx)
        stats = dict(min=mn.tolist(), max=mx.tolist())
    mn, mx = np.array(stats["min"], np.float32), np.array(stats["max"], np.float32)
    Xn = (X - mn) / (mx - mn)
    ts = np.arange(L - 1, T)
    # windows: [S, N, L, F] -> [S, N, L*F]
    idx = ts[:, None] + np.arange(-L + 1, 1)[None, :]
    w = Xn[idx]  # [S, L, N, F]
    w = np.transpose(w, (0, 2, 1, 3)).reshape(len(ts), N, L * F_NODE).astype(np.float32)
    uniq, inv = np.unique(status[ts], axis=0, return_inverse=True)
    A_table = np.stack([a_hat(top.adjacency(u)) for u in uniq]).astype(np.float32)
    mask = np.array([nd.load_kw > 0 and nd.kind != "grid" for nd in top.nodes])
    ymin = float(Y[:n_train_steps][:, mask].min())
    yscale = float(Y[:n_train_steps][:, mask].max() - ymin)
    stats.update(y_min=ymin, y_scale=yscale)
    yn = (Y[ts] - ymin) / yscale
    split = int((n_train_steps - (L - 1)))
    data = Data(top_name, N, torch.from_numpy(w), torch.from_numpy(inv.reshape(-1).astype(np.int64)), torch.from_numpy(A_table),
                torch.from_numpy(yn.astype(np.float32)), torch.from_numpy(Y[ts].astype(np.float32)), torch.from_numpy(lab[ts].astype(np.int64)),
                torch.from_numpy(mask), ymin, yscale, ts, split)
    return data, stats
