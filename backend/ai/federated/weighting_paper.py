"""The two paper aggregation rules as NEW, separately named strategies (pure numpy; no Flower, no torch).
The existing rule in weighting.py (EMA of normalised validation loss + update norm, 5 % floor) is untouched.

fedprox_journal_adaptive (journal Eq. 16)
    alpha_k = n_k * exp(-eta * v_k) / sum_j n_j * exp(-eta * v_j)
    v_k = validation loss client k reports on a held-out part of its own data; eta = 0 reduces to FedProx's n_k weighting.
    Computed in a numerically stable form (v is shifted by min v, which cancels in the ratio).

fedprox_conf_adaptive (conference Eqs. 11-12)
    rho_k = 1 / (1 + L_k / Lbar)           Lbar = mean of the clients' validation losses
    omega_k = n_k * rho_k / sum_j n_j * rho_j

Only n_k and a scalar validation loss cross the wire (wire.ALLOWED_METRIC_KEYS gained `n_k` and `v_k`, which the journal says are transmitted).
"""
from __future__ import annotations

import numpy as np


def sample_weights(n: dict[int, float]) -> dict[int, float]:
    tot = float(sum(n.values()))
    return {k: v / tot for k, v in n.items()}


def journal_weights(n: dict[int, float], v: dict[int, float], eta: float) -> dict[int, float]:
    ks = sorted(n)
    nv = np.array([n[k] for k in ks], float)
    vv = np.array([v[k] for k in ks], float)
    vv = np.where(np.isfinite(vv), vv, np.nanmax(vv[np.isfinite(vv)]) if np.isfinite(vv).any() else 0.0)
    w = nv * np.exp(-eta * (vv - vv.min()))
    w = w / w.sum()
    return {k: float(x) for k, x in zip(ks, w)}


def conf_weights(n: dict[int, float], loss: dict[int, float]) -> dict[int, float]:
    ks = sorted(n)
    nv = np.array([n[k] for k in ks], float)
    L = np.array([loss[k] for k in ks], float)
    L = np.where(np.isfinite(L), L, np.nanmax(L[np.isfinite(L)]) if np.isfinite(L).any() else 1.0)
    lbar = L.mean()
    rho = 1.0 / (1.0 + L / max(lbar, 1e-12))
    w = nv * rho
    w = w / w.sum()
    return {k: float(x) for k, x in zip(ks, w)}


def comm_cost_bytes(rounds: int, clients: int, n_params: int, bytes_per_param: int = 4) -> int:
    """Journal Eq. 18: C_comm = 2 R K |w| beta  (all clients take part in every round; beta = 4 for float32)."""
    return 2 * rounds * clients * n_params * bytes_per_param
