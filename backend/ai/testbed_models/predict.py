"""Inference helpers for saved journal models on a held-out scenario (fault-head classes, demand forecasts, ROC data)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch

from ai.testbed_models import journal_model as JM
from ai.testbed_models.train_journal import OUT_ROOT
from testbed import journal_sim as JS


def load_model(top: str, it: int, name: str = "3_LRS"):
    ck = torch.load(OUT_ROOT / f"journal_{top}" / f"it{it}" / f"model_{name}.pt", weights_only=False)
    cfg = ck["cfg"]
    m = JM.JointGNN(JM.L_WIN * JM.F_NODE, cfg["H"], cfg["K"], cfg["M"], ck["kind"])
    m.load_state_dict(ck["state"])
    m.eval()
    return m, ck["stats"]


@torch.no_grad()
def predict_scenario(top: str, it: int, kind: str = "eval", name: str = "3_LRS", model_it: int | None = None, eval_it: int | None = None) -> dict:
    """Run model (trained on training iteration `model_it`) on scenario `kind` iteration `eval_it`. Steps before the first full window get class 0."""
    model_it = it if model_it is None else model_it
    eval_it = it if eval_it is None else eval_it
    m, stats = load_model(top, model_it, name)
    d, man = JM.load_data(top, eval_it, kind=kind)
    data, _ = JM.make_data(top, d, stats=dict(stats))
    T = len(d["label"])
    pred = np.zeros(T, np.int64)
    probs = np.zeros((T, JM.N_CLASSES), np.float32)
    yhat = np.zeros((T, data.N), np.float32)
    ids = np.arange(len(data.c))
    for i in range(0, len(ids), 2048):
        b = torch.from_numpy(ids[i:i + 2048])
        A = data.A_table[data.A_id[b]]
        yh, ch = m(data.x[b], A)
        t = data.t_index[i:i + 2048]
        pred[t] = ch.argmax(1).numpy()
        probs[t] = torch.softmax(ch, 1).numpy()
        yhat[t] = (yh * data.y_scale + data.y_min).numpy()
    return dict(pred=pred, probs=probs, yhat_kw=yhat, y_kw=d["Y"], label=d["label"], manifest=man)
