"""Graph + feature construction shared by training (ai/dataset.py) and live
inference (app/ai_service) so the served model sees exactly the features it
was trained and evaluated on.

Graph: the digital twin's NetworkX topology — 6 sources -> bus_a/bus_b ->
grid — as an undirected edge_index (messages must flow source -> bus ->
other sources for neighbours to inform each other). Edges come from the twin's
CURRENT routing (`get_edges()`), so rerouting/isolating a node changes the
graph the model sees with no code change.

Node features (dimension NODE_FEATURES):
  static  (6): node-type one-hot [scada_turbine, live_wind, live_hydro, bus,
               grid] + rated/capacity kW normalised. Routing state
               (isolated / load_share) is deliberately NOT an input: it is
               constant in the real data, so topology influences the model
               only through edges, never through a feature it never trained on.
  dynamic (40): only for `source_type == "historical"` nodes (the Kelmarsh
               replay). For each of CHANNELS (power_output, temperature +
               8 SCADA channels): [last, window-mean, window-delta] and one
               presence flag. Live wind/hydro nodes and buses/grid carry
               ALL-ZERO dynamic features: the live nodes have no fault-relevant
               channels (no temperature, no labels) and are pure graph
               structure here.

Null handling (explicit, per source type): a channel absent from the whole
window is imputed with 0 AFTER z-normalisation (= the training-set mean) and
its presence flag is 0, so the model can tell "missing" from "average". The
imputation is a modelling choice; it is never presented as a measurement.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

STEP_MINUTES = 10  # Kelmarsh SCADA export cadence
WINDOW_STEPS = 6  # look-back: 60 min of history per sample
HORIZON_STEPS = 6  # prediction horizon: fault START within the next 60 min

# Order matters: it fixes the feature layout. Must match the keys of
# app.ingestion.scada_replay.SCADA_CHANNELS (checked in ai/dataset.py).
SCADA_CHANNEL_KEYS = [
    "wind_speed_ms",
    "rotor_speed_rpm",
    "generator_rpm",
    "pitch_angle_deg",
    "gen_bearing_front_temp_c",
    "gear_oil_temp_c",
    "nacelle_temp_c",
    "nacelle_ambient_temp_c",
]
CHANNELS = ["power_output", "temperature", *SCADA_CHANNEL_KEYS]
N_CHANNELS = len(CHANNELS)

STATIC_FEATURES = 6
DYNAMIC_FEATURES = 4 * N_CHANNELS  # last, mean, delta, presence
NODE_FEATURES = STATIC_FEATURES + DYNAMIC_FEATURES

# Fixed node ordering = fixed feature/label alignment across train/serve.
NODE_ORDER = [
    "wind_01",
    "hydro_01",
    "wind_scada_kelmarsh_1",
    "wind_scada_kelmarsh_2",
    "wind_scada_kelmarsh_3",
    "wind_scada_kelmarsh_4",
    "bus_a",
    "bus_b",
    "grid",
]
N_NODES = len(NODE_ORDER)
SCORED_NODES = [n for n in NODE_ORDER if n.startswith("wind_scada_kelmarsh_")]
SCORED_IDX = [NODE_ORDER.index(n) for n in SCORED_NODES]

_RATED_NORM_KW = 2050.0


def reading_vector(reading: dict) -> np.ndarray:
    """One reading (a NormalizedReading dict) -> [N_CHANNELS] with NaN for
    anything missing. `fault_label` and live-only `wind_speed` are never read."""
    vec = np.full(N_CHANNELS, np.nan, dtype=np.float64)
    power = reading.get("power_output")
    if power is not None:
        vec[0] = power
    temperature = reading.get("temperature")
    if temperature is not None:
        vec[1] = temperature
    channels = reading.get("scada_channels") or {}
    for j, key in enumerate(SCADA_CHANNEL_KEYS):
        value = channels.get(key)
        if value is not None:
            vec[2 + j] = value
    return vec


def window_features(win: np.ndarray) -> np.ndarray:
    """[W, C] window (NaN = missing) -> raw [4C] = last | mean | delta | present.
    Un-normalised; missing entries are NaN in the value blocks."""
    present = ~np.isnan(win)
    any_present = present.any(axis=0)
    last = np.full(N_CHANNELS, np.nan)
    first = np.full(N_CHANNELS, np.nan)
    mean = np.full(N_CHANNELS, np.nan)
    for c in np.nonzero(any_present)[0]:
        col = win[present[:, c], c]
        last[c], first[c], mean[c] = col[-1], col[0], col.mean()
    delta = last - first
    return np.concatenate([last, mean, delta, any_present.astype(np.float64)])


@dataclass
class Normalizer:
    """Per-feature z-score statistics fit on the TRAIN split only (no
    leakage from validation/test). Serialised next to the model weights."""

    mean: np.ndarray  # [3C]
    std: np.ndarray  # [3C]

    @classmethod
    def fit(cls, raw: np.ndarray) -> "Normalizer":
        """raw: [n, 4C] window features from the training split (NaN = missing)."""
        vals = raw[:, : 3 * N_CHANNELS]
        with np.errstate(all="ignore"):
            mean = np.nanmean(vals, axis=0)
            std = np.nanstd(vals, axis=0)
        mean = np.where(np.isnan(mean), 0.0, mean)
        std = np.where(np.isnan(std) | (std < 1e-6), 1.0, std)
        return cls(mean=mean, std=std)

    def apply(self, raw: np.ndarray) -> np.ndarray:
        """[..., 4C] raw -> [..., 4C] normalised, missing -> 0, presence kept."""
        vals = (raw[..., : 3 * N_CHANNELS] - self.mean) / self.std
        vals = np.where(np.isnan(vals), 0.0, vals)
        # clip extreme z-scores (sensor glitches) so one bad reading can't dominate
        vals = np.clip(vals, -8.0, 8.0)
        presence = np.nan_to_num(raw[..., 3 * N_CHANNELS :], nan=0.0)  # no reading at all -> nothing present
        return np.concatenate([vals, presence], axis=-1).astype(np.float32)

    def to_dict(self) -> dict:
        return {"mean": self.mean.tolist(), "std": self.std.tolist()}

    @classmethod
    def from_dict(cls, d: dict) -> "Normalizer":
        return cls(mean=np.asarray(d["mean"]), std=np.asarray(d["std"]))


# -- wind-regime-relative features (EXP-015) ---------------------------

# Channels expressed relative to what is typical AT THE CURRENT WIND SPEED, so
# the model can see "abnormal for this wind" instead of only "high wind".
REGIME_CHANNELS = ["power_output", "temperature", "rotor_speed_rpm", "pitch_angle_deg", "gear_oil_temp_c"]
REGIME_FEATURES = 2 * len(REGIME_CHANNELS)  # residual of window-last and of window-mean
_WIND = CHANNELS.index("wind_speed_ms")
_REGIME_IDX = [CHANNELS.index(c) for c in REGIME_CHANNELS]


@dataclass
class RegimeResiduals:
    """Per-channel median as a function of wind speed (0.5 m/s bins), fit on
    TRAIN valid rows only, then residual = value - median(wind bin), z-scored
    with train statistics. A pure function of the raw [4C] window vector, so
    serving computes it exactly like training. Missing -> 0, clipped to +-8."""

    edges: np.ndarray  # [B+1] wind-speed bin edges
    medians: np.ndarray  # [R, B] per-channel median per bin (NaN-free)
    mean: np.ndarray  # [2R]
    std: np.ndarray  # [2R]

    @staticmethod
    def _residuals(raw: np.ndarray, edges: np.ndarray, medians: np.ndarray) -> np.ndarray:
        out = []
        for block in (0, 1):  # last, mean
            w = raw[..., block * N_CHANNELS + _WIND]
            b = np.clip(np.digitize(np.nan_to_num(w, nan=0.0), edges) - 1, 0, medians.shape[1] - 1)
            for r, c in enumerate(_REGIME_IDX):
                res = raw[..., block * N_CHANNELS + c] - medians[r][b]
                out.append(np.where(np.isnan(w), np.nan, res))
        return np.stack(out, axis=-1)

    @classmethod
    def fit(cls, raw: np.ndarray) -> "RegimeResiduals":
        edges = np.arange(0.0, 25.5, 0.5)
        w = raw[:, _WIND]
        b = np.digitize(w, edges) - 1
        medians = np.zeros((len(_REGIME_IDX), len(edges) - 1))
        for r, c in enumerate(_REGIME_IDX):
            v = raw[:, c]
            glob = np.nanmedian(v) if np.isfinite(v).any() else 0.0
            for j in range(len(edges) - 1):
                sel = (b == j) & np.isfinite(v) & np.isfinite(w)
                medians[r, j] = np.median(v[sel]) if sel.sum() >= 20 else np.nan
            # sparse bins: carry the nearest populated bin (then the global median)
            good = np.nonzero(np.isfinite(medians[r]))[0]
            if len(good):
                nearest = good[np.abs(np.arange(len(edges) - 1)[:, None] - good[None]).argmin(axis=1)]
                medians[r] = medians[r][nearest]
            else:
                medians[r] = glob
        res = cls._residuals(raw, edges, medians)
        with np.errstate(all="ignore"):
            mean, std = np.nanmean(res, axis=0), np.nanstd(res, axis=0)
        mean = np.where(np.isnan(mean), 0.0, mean)
        std = np.where(np.isnan(std) | (std < 1e-6), 1.0, std)
        return cls(edges=edges, medians=medians, mean=mean, std=std)

    def transform(self, raw: np.ndarray) -> np.ndarray:
        """[..., 4C] raw window features -> [..., REGIME_FEATURES] normalised."""
        z = (self._residuals(raw, self.edges, self.medians) - self.mean) / self.std
        return np.clip(np.where(np.isnan(z), 0.0, z), -8.0, 8.0).astype(np.float32)

    def to_dict(self) -> dict:
        return {"channels": REGIME_CHANNELS, "edges": self.edges.tolist(), "medians": self.medians.tolist(),
                "mean": self.mean.tolist(), "std": self.std.tolist()}

    @classmethod
    def from_dict(cls, d: dict) -> "RegimeResiduals":
        assert d["channels"] == REGIME_CHANNELS, "regime channel layout changed since this artifact was trained"
        return cls(np.asarray(d["edges"]), np.asarray(d["medians"]), np.asarray(d["mean"]), np.asarray(d["std"]))


# -- graph ------------------------------------------------------------


def static_features(twin_nodes: list[dict]) -> np.ndarray:
    """[N_NODES, STATIC_FEATURES] from the twin's node dicts (GET /twin/nodes
    shape). Only node *type* and size are used — see module docstring."""
    by_id = {n["node_id"]: n for n in twin_nodes}
    out = np.zeros((N_NODES, STATIC_FEATURES), dtype=np.float32)
    for k, node_id in enumerate(NODE_ORDER):
        node = by_id[node_id]
        ntype, source_type = node["type"], node.get("source_type")
        if ntype == "wind" and source_type == "historical":
            out[k, 0] = 1.0
        elif ntype == "wind":
            out[k, 1] = 1.0
        elif ntype == "hydro":
            out[k, 2] = 1.0
        elif ntype == "bus":
            out[k, 3] = 1.0
        elif ntype == "grid":
            out[k, 4] = 1.0
        size = node.get("rated_capacity_kw", node.get("capacity_kw", 0.0)) or 0.0
        out[k, 5] = size / _RATED_NORM_KW
    return out


def edge_index_from_edges(edges: list[dict]) -> np.ndarray:
    """Twin edges ([{source, target}, ...]) -> undirected [2, E] over NODE_ORDER."""
    idx = {n: i for i, n in enumerate(NODE_ORDER)}
    pairs = []
    for e in edges:
        u, v = idx[e["source"]], idx[e["target"]]
        pairs.append((u, v))
        pairs.append((v, u))
    if not pairs:
        return np.zeros((2, 0), dtype=np.int64)
    return np.asarray(pairs, dtype=np.int64).T


def assemble_node_features(static: np.ndarray, dynamic_by_node: dict[str, np.ndarray]) -> np.ndarray:
    """static [N, S] + {node_id: normalised [4C] dynamic} -> [N, NODE_FEATURES].
    Nodes not in `dynamic_by_node` keep all-zero dynamic features."""
    x = np.zeros((N_NODES, NODE_FEATURES), dtype=np.float32)
    x[:, :STATIC_FEATURES] = static
    for node_id, dyn in dynamic_by_node.items():
        x[NODE_ORDER.index(node_id), STATIC_FEATURES:] = dyn
    return x


def default_topology() -> tuple[np.ndarray, np.ndarray]:
    """(static_features, edge_index) from a FRESH DigitalTwin — the default
    primary routing. Builds a private instance; the live singleton is not touched."""
    from app.twin.digital_twin import DigitalTwin

    twin = DigitalTwin()
    return static_features(twin.get_all_nodes()), edge_index_from_edges(twin.get_edges())


def batch_edge_index(edge_index: np.ndarray, batch_size: int) -> np.ndarray:
    """Repeat one topology across `batch_size` stacked snapshots (block-diagonal)."""
    offsets = (np.arange(batch_size, dtype=np.int64) * N_NODES)[:, None, None]
    tiled = np.broadcast_to(edge_index[None], (batch_size, *edge_index.shape)) + offsets
    return np.concatenate(list(tiled), axis=1)
