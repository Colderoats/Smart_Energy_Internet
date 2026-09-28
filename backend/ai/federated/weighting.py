"""Aggregation-weight rules (pure numpy, no Flower, no torch).

Two rules, both convex combinations of the participating clients' models:

EQUAL (FedAvg baseline, "all nodes weighted equally")
    w_k = 1 / |P|  for the clients P that took part in the round.
    (Client shards are nearly the same size, ~97k valid samples each, so this
    is also almost identical to sample-count weighting.)

ADAPTIVE ("reduces node influence based on performance history")
    Fixed a priori — NOT tuned on results. Per round, for each participating
    client k:

      1. LOSS SIGNAL. The client reports a scalar validation loss on its OWN
         local validation rows, normalised by the loss of the best constant
         (no-skill) predictor on the same rows:  nl_k = val_loss / val_loss_prior.
         (nl < 1: better than no skill; the normalisation makes clients with
         different fault rates comparable.)
      2. HISTORY. Exponential moving average  s_k <- ALPHA * nl_k + (1-ALPHA) * s_k
         (initialised with the first observation; a client absent in a round
         keeps its previous s_k — its history is not overwritten).
      3. LOSS FACTOR. rel_k = s_k / median_j(s_j);
         f_loss_k = exp(-BETA * max(0, rel_k - 1))   (1 if at least as good as the
         cohort median, decaying as it gets worse than the median).
      4. UPDATE-QUALITY FACTOR. computed by the SERVER from the received weights:
         rho_k = ||w_k - w_global|| / median_j ||w_j - w_global||;
         f_norm_k = min(1, (C / rho_k)^2)   (1 unless the update is more than C x the
         median update norm, then penalised quadratically).
      5. w_k proportional to f_loss_k * f_norm_k, normalised to sum 1, then a FLOOR:
         no participating client gets less than FLOOR (the rest is rescaled), so a
         poor client is down-weighted but never silenced.

    Signals used: only the scalar metrics and the weights that cross the
    wire. The server does not (and cannot) see raw data, and never sees the
    SIMULATED-scenario labels — those are not inputs here.
    The per-round, per-client factors and weights are returned and logged so
    they can be plotted and reused by Module 5.
"""

from __future__ import annotations

import math

import numpy as np

ALPHA = 0.5  # EMA smoothing of the loss signal
BETA = 5.0  # loss-factor steepness
NORM_C = 1.5  # update norms up to 1.5x the cohort median are not penalised
FLOOR = 0.05  # minimum share of any participating client
BAD_LOSS = 2.0  # stand-in for a non-finite reported loss (= clearly worse than no-skill)


def equal_weights(participants: list[int]) -> dict[int, float]:
    return {k: 1.0 / len(participants) for k in participants}


def apply_floor(w: np.ndarray, floor: float) -> np.ndarray:
    """Raise entries below `floor` to `floor` and rescale the rest so the sum stays 1."""
    n = len(w)
    if floor * n >= 1.0:
        return np.full(n, 1.0 / n)
    w = w / w.sum()
    for _ in range(n):
        low = w < floor
        if not low.any():
            break
        rest = ~low
        w = w.copy()
        w[rest] = w[rest] * (1.0 - floor * low.sum()) / w[rest].sum()
        w[low] = floor
    return w


class AdaptiveWeighter:
    """Holds the per-client performance history (EMA of the normalised loss)."""

    def __init__(self, alpha: float = ALPHA, beta: float = BETA, norm_c: float = NORM_C, floor: float = FLOOR) -> None:
        self.alpha, self.beta, self.norm_c, self.floor = alpha, beta, norm_c, floor
        self.ema: dict[int, float] = {}

    def weights(self, norm_loss: dict[int, float], update_norm: dict[int, float]) -> tuple[dict[int, float], dict]:
        """norm_loss / update_norm: {turbine: value} for the participating clients.
        Returns ({turbine: weight}, diagnostics)."""
        ks = sorted(norm_loss)
        for k in ks:
            nl = norm_loss[k]
            nl = nl if (nl is not None and math.isfinite(nl)) else BAD_LOSS
            self.ema[k] = nl if k not in self.ema else self.alpha * nl + (1 - self.alpha) * self.ema[k]
        s = np.array([self.ema[k] for k in ks])
        rel = s / max(float(np.median(s)), 1e-12)
        f_loss = np.exp(-self.beta * np.maximum(0.0, rel - 1.0))

        norms = np.array([update_norm[k] for k in ks], dtype=float)
        med = float(np.median(norms))
        rho = norms / med if med > 0 else np.ones_like(norms)
        f_norm = np.minimum(1.0, (self.norm_c / np.maximum(rho, 1e-12)) ** 2)

        raw = f_loss * f_norm
        w = apply_floor(raw / raw.sum(), self.floor)
        diag = {
            "ema_norm_loss": {k: float(v) for k, v in zip(ks, s)},
            "rel_loss": {k: float(v) for k, v in zip(ks, rel)},
            "f_loss": {k: float(v) for k, v in zip(ks, f_loss)},
            "update_norm": {k: float(v) for k, v in zip(ks, norms)},
            "update_norm_ratio": {k: float(v) for k, v in zip(ks, rho)},
            "f_norm": {k: float(v) for k, v in zip(ks, f_norm)},
            "unfloored_share": {k: float(v) for k, v in zip(ks, raw / raw.sum())},
        }
        return {k: float(v) for k, v in zip(ks, w)}, diag


def aggregate(weights_by_client: dict[int, list[np.ndarray]], w: dict[int, float]) -> list[np.ndarray]:
    """Convex combination of the clients' parameter lists, summed in turbine
    order so the result does not depend on message arrival order."""
    ks = sorted(weights_by_client)
    out = [np.zeros_like(a, dtype=np.float64) for a in weights_by_client[ks[0]]]
    for k in ks:
        for acc, arr in zip(out, weights_by_client[k]):
            acc += w[k] * arr.astype(np.float64)
    return [a.astype(np.float32) for a in out]
