"""Module 3 live inference: loads the saved TA-GNN artifact and scores the
digital twin's turbine nodes as replayed readings arrive.

Data provenance: the turbine nodes' readings are the REAL Kelmarsh SCADA
export, REPLAYED (source_type="historical") — the model's output is a
prediction on replayed data, never a live physical measurement. Live
Open-Meteo wind/hydro nodes are graph structure only and are never scored
(no fault-relevant channels; see ai/features.py).

Leakage guard: features come from ai.features.reading_vector, which reads only
power_output, temperature and scada_channels. `fault_label` (the replayed
ground truth the rule-based detector overrides on) is never an input.

The model artifact lives in backend/ai/artifacts/<kind>/ (model.pt +
meta.json, written by ai/run_experiments.py). If torch or the artifact is
missing, the service disables itself and the twin keeps running on the
rule-based detector alone.
"""

from __future__ import annotations

import json
import logging
import math
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

logger = logging.getLogger("sei")

ARTIFACT_ROOT = Path(__file__).resolve().parents[2] / "ai" / "artifacts"
# Module 4: the federated global model, exported in the same format (ai/federated/export.py).
FEDERATED_ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "ai" / "federated" / "artifacts" / "model_federated"
DEFAULT_KIND = "tag"
MODEL_KIND_ENV_DEFAULT = DEFAULT_KIND


class FaultPredictor:
    def __init__(self, kind: str = DEFAULT_KIND) -> None:
        self.kind = kind
        self.loaded = False
        self.error: str | None = None
        self.meta: dict = {}
        self._buffers: dict[str, deque] = {}
        self._last_step: dict[str, int] = {}

    # -- loading --------------------------------------------------------

    def load(self) -> None:
        try:
            import torch  # heavy import: kept out of module import time

            from ai import features as F
            from ai.models import NodeClassifier

            from app.config import settings

            # AI_MODEL_SOURCE=federated selects the Module 4 model; default is the Module 3 model.
            art = FEDERATED_ARTIFACT_DIR if settings.ai_model_source == "federated" else ARTIFACT_ROOT / self.kind
            meta = json.loads((art / "meta.json").read_text())
            model = NodeClassifier(**meta["model_config"])
            model.load_state_dict(torch.load(art / "model.pt", weights_only=True))
            model.eval()
            torch.set_num_threads(1)
            self._torch, self._F = torch, F
            self._model = model
            self._norm = F.Normalizer.from_dict(meta["normalizer"])
            self._threshold = float(meta["threshold_logit"])
            self._platt = (float(meta["platt"]["a"]), float(meta["platt"]["b"]))
            self.meta = meta
            self.loaded = True
            logger.info("AI service: loaded %s from %s", meta["display_name"], art)
        except Exception as exc:  # missing torch / artifact must never take the backend down
            self.loaded = False
            self.error = f"{type(exc).__name__}: {exc}"
            logger.warning("AI service disabled (%s) — twin continues on the rule-based detector only", self.error)

    # -- streaming state ------------------------------------------------

    def observe(self, node_id: str, reading: dict) -> None:
        """Buffer one replayed reading (turbine nodes only)."""
        if not self.loaded or reading.get("source_type") != "historical":
            return
        F = self._F
        step = int(round(datetime.fromisoformat(reading["timestamp"]).timestamp() / (F.STEP_MINUTES * 60)))
        buf = self._buffers.setdefault(node_id, deque(maxlen=4 * F.WINDOW_STEPS))
        if node_id in self._last_step and step <= self._last_step[node_id]:
            buf.clear()  # replay looped back to the start of the dataset
        self._last_step[node_id] = step
        buf.append((step, F.reading_vector(reading)))

    def _window(self, node_id: str, ref: int) -> np.ndarray | None:
        """[W, C] window of this node's readings ending at step `ref` (rows
        after `ref` are ignored; steps without a reading stay NaN)."""
        F = self._F
        buf = self._buffers.get(node_id)
        if not buf:
            return None
        win = np.full((F.WINDOW_STEPS, F.N_CHANNELS), np.nan)
        for step, vec in buf:
            row = step - (ref - F.WINDOW_STEPS + 1)
            if 0 <= row < F.WINDOW_STEPS:
                win[row] = vec
        return win

    # -- scoring --------------------------------------------------------

    def score(self, twin_nodes: list[dict], twin_edges: list[dict]) -> dict | None:
        """Score the turbine nodes as ONE graph snapshot at a common
        reference step = the slowest node's newest step. Anchoring every
        node's window to the same step reproduces the offline evaluation
        exactly (the model reads its neighbours' windows, so scoring a node
        while a neighbour is still a step behind would feed it a misaligned
        snapshot). Nodes with no reading at the reference step are not scored,
        matching the offline 'row present' rule. Uses the twin's CURRENT edges
        (reroute/isolate changes the graph, no code change).

        Returns None, or {"ref_step", "as_of" (ISO, dataset time), "nodes":
        {node_id: {"logit","probability","flagged"}}}."""
        if not self.loaded or not self._last_step:
            return None
        F, torch = self._F, self._torch
        ref = min(self._last_step[n] for n in F.SCORED_NODES if n in self._last_step)
        dynamic = {}
        for node_id in F.SCORED_NODES:
            win = self._window(node_id, ref)
            if win is not None and not np.isnan(win[-1]).all():
                dynamic[node_id] = self._norm.apply(F.window_features(win))
        if not dynamic:
            return None
        x = F.assemble_node_features(F.static_features(twin_nodes), dynamic)
        edge_index = F.edge_index_from_edges(twin_edges)
        with torch.no_grad():
            logits = self._model(torch.from_numpy(x), torch.from_numpy(edge_index)).numpy()
        a, b = self._platt
        nodes = {}
        for node_id in dynamic:
            z = float(logits[F.NODE_ORDER.index(node_id)])
            nodes[node_id] = {
                "logit": z,
                "probability": 1.0 / (1.0 + math.exp(-(a * z + b))),
                "flagged": z >= self._threshold,
            }
        as_of = datetime.fromtimestamp(ref * F.STEP_MINUTES * 60, tz=timezone.utc).isoformat()
        return {"ref_step": ref, "as_of": as_of, "nodes": nodes}

    # -- model card -----------------------------------------------------

    def describe(self) -> dict:
        if not self.loaded:
            return {"loaded": False, "error": self.error}
        a, b = self._platt
        thr_prob = 1.0 / (1.0 + math.exp(-(a * self._threshold + b)))
        return {
            "loaded": True,
            "name": self.meta["display_name"],
            "kind": self.meta["kind"],
            "source": self.meta.get("model_source", "centralized"),  # "centralized" | "federated"
            "task": f"fault START within the next {self.meta['features']['horizon_steps'] * self.meta['features']['step_minutes']} min, per turbine node",
            "horizon_min": self.meta["features"]["horizon_steps"] * self.meta["features"]["step_minutes"],
            "operating_threshold_probability": round(thr_prob, 4),
            "probability_note": "Platt-calibrated on the validation split; small validation positive counts make it approximate.",
            "trained_at": self.meta["trained_at"],
            "split": self.meta.get("split"),
            "data_provenance": self.meta["provenance"],
        }


predictor = FaultPredictor()
