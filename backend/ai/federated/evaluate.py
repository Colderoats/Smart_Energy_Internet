"""Offline evaluation of a global model on the IDENTICAL Module 3 held-out
split (same rows, same masks, same metric code: ai.evaluation.evaluate_scorer,
ai.metrics, ai.training.predict_logits).

This is the EXPERIMENTER's evaluation, not part of the federated protocol: it
uses the pooled validation/test bundle (artifacts/eval_data.npz) exactly like
Module 3's harness did. No client or server process ever loads that file.
Data: real Kelmarsh SCADA, REPLAYED (test split = H2 2018, 98,392 valid
node-samples, 27 positives from 5 independent events - see aiprogress.md).

Two views of the same test rows (chosen with the user):
  full_view  each snapshot carries all four turbines' features, exactly what
             Module 3 evaluated and what the backend's serving path feeds the model.
  own_view   each turbine scored from its OWN features only (neighbour slots
             empty) - the view the federated clients trained on.

Operating point: threshold maximising F1 on the pooled VALIDATION split in the
same view (Module 3's rule), applied unchanged to test. PR-AUC/ROC-AUC use the
continuous score. Accuracy is reported too (open question Q1 about what the
81%/94% targets measure) but with ~0.03% positives it is near-meaningless:
predicting "never a fault" already scores ~99.97%.

Run (Module 4 venv, from backend/):
    ai\\federated\\venv\\Scripts\\python -m ai.federated.evaluate --run ai\\federated\\artifacts\\runs\\<run_dir>
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

from ai import features as F
from ai import metrics as M
from ai import training as T  # Module 3's predict_logits (unchanged)
from ai.dataset import Labels
from ai.evaluation import evaluate_scorer
from ai.federated import local, partition
from ai.federated.strategies import load_weights
from ai.models import NodeClassifier, set_weights


@dataclass
class EvalBundle:
    static: np.ndarray
    edge_index: np.ndarray
    val_idx: np.ndarray
    test_idx: np.ndarray
    val_dyn: np.ndarray  # [n, 4, 40]
    test_dyn: np.ndarray
    labels: Labels
    normalizer: dict
    meta: dict


_BUNDLE: EvalBundle | None = None


def load_bundle() -> EvalBundle:
    global _BUNDLE
    if _BUNDLE is None:
        b = np.load(partition.EVAL_FILE, allow_pickle=False)
        meta = json.loads(str(b["meta"]))
        _BUNDLE = EvalBundle(
            static=b["static"], edge_index=b["edge_index"], val_idx=b["val_idx"], test_idx=b["test_idx"],
            val_dyn=b["val_dyn"], test_dyn=b["test_dyn"],
            labels=Labels(y=b["label_y"], valid=b["label_valid"], lead_s=b["label_lead_s"], event_start_s=b["label_event_start_s"]),
            normalizer=meta["normalizer"], meta=meta,
        )
    return _BUNDLE


def full_view_logits(model, bundle: EvalBundle, dyn: np.ndarray) -> np.ndarray:
    """[n,4,40] -> logits [n,4] with all turbines' features present (Module 3's input)."""
    x = np.zeros((len(dyn), F.N_NODES, F.NODE_FEATURES), dtype=np.float32)
    x[:, :, : F.STATIC_FEATURES] = bundle.static[None]
    x[:, F.SCORED_IDX, F.STATIC_FEATURES :] = dyn
    return T.predict_logits(model, x, bundle.edge_index)


def own_view_logits_all(model, bundle: EvalBundle, dyn: np.ndarray) -> np.ndarray:
    """[n,4,40] -> logits [n,4], each turbine scored from its OWN features only."""
    batcher = local.OwnViewBatcher(bundle.static, bundle.edge_index)
    out = np.zeros((len(dyn), 4), dtype=np.float32)
    for k in range(4):
        own = np.full(len(dyn), F.SCORED_IDX[k], dtype=np.int64)
        out[:, k] = local.own_view_logits(model, batcher, np.ascontiguousarray(dyn[:, k]), own)
    return out


def _accuracy(det: dict, n: int) -> dict:
    tn = n - det["tp"] - det["fp"] - det["fn"]
    pos, neg = det["tp"] + det["fn"], tn + det["fp"]
    return {
        "accuracy": (det["tp"] + tn) / max(n, 1),
        "balanced_accuracy": 0.5 * ((det["tp"] / pos if pos else float("nan")) + (tn / neg if neg else float("nan"))),
        "specificity": tn / neg if neg else float("nan"),
    }


def score_view(val_logits: np.ndarray, test_logits: np.ndarray, bundle: EvalBundle) -> dict:
    lab = bundle.labels
    vy, vvalid = lab.y[bundle.val_idx], lab.valid[bundle.val_idx]
    thr = M.best_f1_threshold(vy[vvalid], val_logits[vvalid])
    flag = test_logits >= thr
    ev = evaluate_scorer(test_logits, flag, bundle.test_idx, lab, bootstrap=False)
    det = ev["detection"]
    det.update(_accuracy(det, ev["n_valid_node_samples"]))
    ty, tvalid = lab.y[bundle.test_idx], lab.valid[bundle.test_idx]
    per_client = {}
    for k in range(4):
        m = tvalid[:, k]
        yk, fk, sk = ty[m, k], flag[m, k], test_logits[m, k]
        d = M.prf(yk, fk)
        d.update(roc_auc=M.roc_auc(yk, sk), pr_auc=M.pr_auc(yk, sk), n_valid=int(m.sum()), n_positive=int((yk == 1).sum()))
        d.update(_accuracy(d, d["n_valid"]))
        per_client[str(k + 1)] = d  # NaN roc/pr when the turbine has no test positives (T1, T4)
    return {
        "threshold_logit": thr,
        "val_pr_auc": M.pr_auc(vy[vvalid], val_logits[vvalid]),
        "val_roc_auc": M.roc_auc(vy[vvalid], val_logits[vvalid]),
        "n_valid_test": ev["n_valid_node_samples"],
        "n_positive_test": ev["n_positive"],
        "prevalence_test": ev["n_positive"] / max(ev["n_valid_node_samples"], 1),
        "detection": det,
        "localization": ev["localization"],
        "lead_time": ev["lead_time"],
        "per_client": per_client,
    }


def evaluate_weights(weights: list[np.ndarray], bundle: EvalBundle | None = None) -> dict:
    bundle = bundle or load_bundle()
    model = NodeClassifier("tag")
    set_weights(model, weights)
    model.eval()
    with torch.no_grad():
        full = score_view(full_view_logits(model, bundle, bundle.val_dyn), full_view_logits(model, bundle, bundle.test_dyn), bundle)
        own = score_view(own_view_logits_all(model, bundle, bundle.val_dyn), own_view_logits_all(model, bundle, bundle.test_dyn), bundle)
    return {"full_view": full, "own_view": own}


def evaluate_run(run_dir: Path) -> dict:
    """Scores a finished federated run: the validation-selected round (primary,
    like Module 3's best-on-validation restore) and the final round (reference)."""
    run_dir = Path(run_dir)
    meta = json.loads((run_dir / "run_meta.json").read_text())
    bundle = load_bundle()
    result = {
        "config": meta,
        "selected_round": meta["best_round_by_client_val"],
        "selected": evaluate_weights(load_weights(run_dir / "weights_best.npz"), bundle),
        "final": evaluate_weights(load_weights(run_dir / "weights_final.npz"), bundle),
    }
    (run_dir / "result.json").write_text(json.dumps(result, indent=1, default=float))
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    r = evaluate_run(Path(ap.parse_args().run))
    for view in ("full_view", "own_view"):
        d = r["selected"][view]["detection"]
        print(f"{view}: P={d['precision']:.3f} R={d['recall']:.3f} F1={d['f1']:.3f} ROC-AUC={d['roc_auc']:.3f} PR-AUC={d['pr_auc']:.4f} acc={d['accuracy']:.5f}")
