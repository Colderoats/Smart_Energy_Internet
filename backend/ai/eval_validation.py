"""SUPPLEMENTARY evaluation on the VALIDATION split (H1 2018).

Why it exists: the held-out TEST split (H2 2018) has only ~5 independent
fault events with valid samples (see aiprogress.md), so it cannot separate
models. The validation split has ~31 events, but it was used for early
stopping and to pick each model's operating threshold, so:

  * numbers for the LEARNED models here are OPTIMISTIC (selection bias) and
    must never be quoted as held-out results;
  * numbers for the rule-based Baseline 0 are fair (it has no fitted
    parameters, and its 3/5-sigma thresholds are fixed by Module 2).

Uses the saved best-on-validation artifact of each kind. Writes
ai/artifacts/eval_validation.json.

    venv\\Scripts\\python -m ai.eval_validation [--kinds tag gcn mlp]
"""

from __future__ import annotations

import argparse
import json
import warnings

warnings.filterwarnings("ignore")

import numpy as np

from ai import dataset as D
from ai import features as F
from ai import training as T
from ai.evaluation import evaluate_scorer, rule_scorer
from ai.run_experiments import ARTIFACT_DIR
from ai.topology_eval import load_artifact


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kinds", nargs="+", default=["tag", "gcn", "mlp"])
    args = ap.parse_args()

    arr = D.build_arrays()
    labels = D.make_labels(arr)
    splits = D.make_splits(arr)
    idx = splits.val
    static, edges = F.default_topology()

    out = {
        "note": "VALIDATION split. Learned models: optimistic (used for early stopping + threshold). Rule baseline: fair.",
        "rule": {},
        "models": {},
    }
    rows = []
    for variant in ("fault_predicted", "warning", "fault_predicted_w"):
        s, f = rule_scorer(arr, idx, variant)
        out["rule"][variant] = evaluate_scorer(s, f, idx, labels)
        rows.append((f"Rule: {variant}", out["rule"][variant]))
    for kind in args.kinds:
        model, meta = load_artifact(kind)
        norm = F.Normalizer.from_dict(meta["normalizer"])
        logits = T.predict_logits(model, D.snapshot_tensor(arr, idx, norm, static), edges)
        res = evaluate_scorer(logits, logits >= meta["threshold_logit"], idx, labels)
        out["models"][kind] = res
        rows.append((f"{meta['display_name']} [optimistic]", res))

    print(f"{'VALIDATION split':40s} {'P':>6} {'R':>6} {'F1':>6} {'ROC':>6} {'PR':>6} {'top1':>6} {'top2':>6} {'evRec':>6} {'lead':>6}")
    for name, r in rows:
        d, l, lt = r["detection"], r["localization"], r["lead_time"]
        print(f"{name:40s} {d['precision']:6.3f} {d['recall']:6.3f} {d['f1']:6.3f} {d['roc_auc']:6.3f} {d['pr_auc']:6.3f} "
              f"{l.get('top1', float('nan')):6.3f} {l.get('top2', float('nan')):6.3f} {lt['event_recall']:6.3f} {lt['median_lead_min']:6.1f}")
    print(f"(val: {rows[0][1]['n_positive']} positive node-samples over {rows[0][1]['lead_time']['events_with_valid_positive_samples']} events; "
          f"chance top1/top2 = {rows[0][1]['localization'].get('chance_top1', float('nan')):.3f}/{rows[0][1]['localization'].get('chance_top2', float('nan')):.3f})")
    (ARTIFACT_DIR / "eval_validation.json").write_text(json.dumps(out, indent=2, default=float))


if __name__ == "__main__":
    main()
