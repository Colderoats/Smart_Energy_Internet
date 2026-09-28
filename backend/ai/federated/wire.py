"""The client/server boundary, enforced and audited.

What may cross the wire between a client and the Flower server:
  * model parameters: a list of float32 arrays whose shapes are EXACTLY the
    TA-GNN's parameter shapes (no extra arrays, so no room for readings);
  * scalar metrics: numbers (or short strings) under a fixed allow-list of keys
    — losses, AUCs and counts computed on the client's own data.

`check_payload` is called by the client BEFORE sending and by the server on
every received message; a violation raises (the run fails loudly instead of
leaking). The server also accumulates an audit record, saved with every run as
wire_audit.json, so "no raw readings crossed the boundary" is checked, not just
asserted. Limits of this evidence: it audits message CONTENT/SHAPE on one
machine; model weights themselves can still leak information about training
data (membership/gradient inversion), which is what differential privacy and
secure aggregation address — NOT implemented here (future work, see README docs).
"""

from __future__ import annotations

import numpy as np

ALLOWED_METRIC_KEYS = frozenset(
    {
        "train_loss", "prox_sq_dist", "n_batches", "train_seconds",
        "val_loss", "val_loss_prior", "val_norm_loss", "val_pr_auc", "val_roc_auc", "val_n", "val_pos",
        "turbine", "sim_scenario",  # sim_scenario is a LABEL for logs only; no aggregation rule reads it
    }
)
MAX_SCALARS_PER_MESSAGE = len(ALLOWED_METRIC_KEYS)


class WireViolation(RuntimeError):
    pass


def check_payload(arrays: list[np.ndarray], metrics: dict, ref_shapes: list[tuple[int, ...]]) -> dict:
    """Validates one message; returns a summary for the audit log."""
    if len(arrays) != len(ref_shapes):
        raise WireViolation(f"expected {len(ref_shapes)} parameter arrays, got {len(arrays)}")
    n_elems = 0
    for a, shape in zip(arrays, ref_shapes):
        if tuple(a.shape) != tuple(shape):
            raise WireViolation(f"array shape {a.shape} is not a model parameter shape {shape}")
        if a.dtype != np.float32:
            raise WireViolation(f"array dtype {a.dtype} is not float32")
        n_elems += int(a.size)
    extra = set(metrics) - ALLOWED_METRIC_KEYS
    if extra:
        raise WireViolation(f"metric keys not on the allow-list: {sorted(extra)}")
    for k, v in metrics.items():
        if not isinstance(v, (int, float, str, bool)):
            raise WireViolation(f"metric {k!r} is not a scalar ({type(v).__name__})")
    return {"param_elements": n_elems, "metric_keys": sorted(metrics)}


class WireAudit:
    """Accumulates per-run evidence of what crossed the boundary (server side)."""

    def __init__(self, ref_shapes: list[tuple[int, ...]]) -> None:
        self.ref_shapes = ref_shapes
        self.messages = 0
        self.param_elements_received = 0
        self.metric_keys: set[str] = set()

    def check(self, arrays, metrics) -> None:
        s = check_payload(arrays, metrics, self.ref_shapes)
        self.messages += 1
        self.param_elements_received += s["param_elements"]
        self.metric_keys.update(s["metric_keys"])

    def check_metrics(self, metrics) -> None:
        """Metric-only message (client evaluation replies carry no parameters)."""
        s = check_payload([], metrics, [])
        self.messages += 1
        self.metric_keys.update(s["metric_keys"])

    def summary(self) -> dict:
        return {
            "messages_audited": self.messages,
            "param_elements_received": self.param_elements_received,
            "parameter_shapes": [list(s) for s in self.ref_shapes],
            "metric_keys_seen": sorted(self.metric_keys),
            "allowed_metric_keys": sorted(ALLOWED_METRIC_KEYS),
            "violations": 0,  # a violation raises WireViolation and fails the run
            "note": "content/shape audit on one machine; does not cover weight-based leakage (no DP / secure aggregation)",
        }
