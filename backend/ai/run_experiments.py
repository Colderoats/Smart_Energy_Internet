"""Module 3 experiment harness: Baseline 0 (rule-based) vs Baseline 1 (plain
GNN) vs TA-GNN (plus a no-graph MLP ablation), one dataset, one split, one
metric code path, fixed seeds.

Run from backend/ :
    venv\\Scripts\\python -m ai.run_experiments                 # full: 5 seeds
    venv\\Scripts\\python -m ai.run_experiments --seeds 0 --epochs 3   # smoke test

Writes ai/artifacts/results.json and, per model kind, the best-on-validation
seed's deployable artifact under ai/artifacts/<kind>/ (model.pt, meta.json).
All data is the REAL Kelmarsh SCADA export, REPLAYED (not live). The split is
a named entry of ai/dataset.SPLITS (--split; default ACTIVE_SPLIT); its test
span is touched only for the final report. Use a --tag other than "main" to
keep the deployed ai/artifacts/<kind>/ untouched.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch

warnings.filterwarnings("ignore", message=".*torch.jit.script.*")

from ai import dataset as D  # noqa: E402
from ai import features as F  # noqa: E402
from ai import metrics as M  # noqa: E402
from ai import training as T  # noqa: E402
from ai.evaluation import evaluate_scorer, rule_scorer  # noqa: E402
from ai.models import DISPLAY_NAME, NodeClassifier, get_weights  # noqa: E402

ARTIFACT_DIR = D.BACKEND_DIR / "ai" / "artifacts"
PROVENANCE = (
    "Real Kelmarsh wind-farm SCADA (Zenodo 8252025, CC BY 4.0), turbines 1-4, 2016-2022 (years actually loaded are listed under class_balance), REPLAYED historical data - "
    "not live, not simulated. Topology (bus_a/bus_b/grid) is the twin's illustrative graph."
)


def _snapshot_data(arr, labels, idx, norm, static, edge_index, regime=None) -> T.SnapshotData:
    return T.SnapshotData(
        x=D.snapshot_tensor(arr, idx, norm, static, regime),
        y=labels.y[idx],
        valid=labels.valid[idx],
        edge_index=edge_index,
    )


def _scale_flags(val_logits, val, test_logits):
    """Operating point: threshold maximising F1 on VALIDATION, applied to test."""
    m = val.valid
    thr = M.best_f1_threshold(val.y[m], val_logits[m])
    return thr, test_logits >= thr


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2, 3, 4])
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--kinds", nargs="+", default=["gcn", "tag", "mlp"])
    ap.add_argument("--hidden", type=int, default=64)
    ap.add_argument("--K", type=int, default=3)
    ap.add_argument("--tag", default="main", help="results file suffix")
    ap.add_argument("--regime", action="store_true", help="EXP-015: add wind-regime-relative residual features")
    ap.add_argument("--split", default=None, choices=sorted(D.SPLITS), help="named split in ai/dataset.SPLITS (default: ACTIVE_SPLIT)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    t_start = time.time()

    arr = D.build_arrays()
    labels = D.make_labels(arr)
    splits = D.make_splits(arr, args.split)
    split_name = args.split or D.ACTIVE_SPLIT
    print(f"split: {split_name}")
    leak = D.check_no_leakage(arr, labels, splits)
    print(f"no-leakage checks {leak['checks']} (purge gap {leak['gap_minutes']} min between splits)")
    balance = D.class_balance(arr, labels, splits)
    print("\n== class balance (valid node-samples; positive = genuine fault starts within 60 min) ==")
    for k, v in balance.items():
        print(f"  {k:5s} {v['from']}..{v['to']}  valid={v['valid_node_samples']:7d}  masked={v['masked_node_samples']:6d}  "
              f"pos={v['positives']:5d} ({100 * v['positive_rate']:.2f}%)  fault events={v['genuine_fault_events']}  other stops={v['non_fault_stop_events']}")

    norm = D.fit_normalizer(arr, labels, splits)
    regime = D.fit_regime(arr, labels, splits) if args.regime else None
    in_dim = F.NODE_FEATURES + (F.REGIME_FEATURES if regime is not None else 0)
    static, edge_index = F.default_topology()
    train = _snapshot_data(arr, labels, splits.train, norm, static, edge_index, regime)
    val = _snapshot_data(arr, labels, splits.val, norm, static, edge_index, regime)
    test = _snapshot_data(arr, labels, splits.test, norm, static, edge_index, regime)
    pw = T.pos_weight_from(train.y, train.valid)
    print(f"  loss class weight: pos_weight = sqrt(neg/pos) = {pw:.1f} (raw neg/pos = {pw**2:.0f})")

    results: dict = {
        "provenance": PROVENANCE,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "horizon_min": F.HORIZON_STEPS * F.STEP_MINUTES,
        "window_min": F.WINDOW_STEPS * F.STEP_MINUTES,
        "leakage_checks": leak,
        "class_balance": balance,
        "class_weight": {"pos_weight": pw, "rule": "sqrt(neg/pos) on train valid samples"},
        "split": split_name,
        "regime_features": regime is not None,
        "seeds": args.seeds,
        "models": {},
    }

    # ---- Baseline 0: production rule-based detector -------------------
    results["baseline0_rule"] = {}
    for variant in ("fault_predicted", "warning", "fault_predicted_w"):
        s, f = rule_scorer(arr, splits.test, variant)
        results["baseline0_rule"][variant] = evaluate_scorer(s, f, splits.test, labels)
    r = results["baseline0_rule"]["fault_predicted"]["detection"]
    print(f"\n== Baseline 0 (rule, label override OFF) test: P={r['precision']:.3f} R={r['recall']:.3f} F1={r['f1']:.3f} "
          f"ROC-AUC={r['roc_auc']:.3f} PR-AUC={r['pr_auc']:.3f}")

    # ---- learned models ---------------------------------------------
    for kind in args.kinds:
        runs = []
        best = None
        for seed in args.seeds:
            print(f"\n== {DISPLAY_NAME[kind]}  seed {seed}")
            T.set_seed(seed)
            model = NodeClassifier(kind, in_dim=in_dim, hidden=args.hidden, K=args.K)
            t0 = time.time()
            hist = T.fit(model, train, val, seed=seed, epochs=args.epochs, log=lambda s: print(s))
            val_logits = T.predict_logits(model, val.x, val.edge_index)
            test_logits = T.predict_logits(model, test.x, test.edge_index)
            thr, flag = _scale_flags(val_logits, val, test_logits)
            ev = evaluate_scorer(test_logits, flag, splits.test, labels)
            ev.update(
                seed=seed,
                threshold_logit=thr,
                best_epoch=hist["best_epoch"],
                best_val_pr_auc=hist["best_val_pr_auc"],
                train_seconds=round(time.time() - t0, 1),
                n_params=model.n_params(),
            )
            d = ev["detection"]
            print(f"   -> val PR-AUC {hist['best_val_pr_auc']:.4f} | test P={d['precision']:.3f} R={d['recall']:.3f} F1={d['f1']:.3f} "
                  f"ROC-AUC={d['roc_auc']:.3f} PR-AUC={d['pr_auc']:.3f}  ({ev['train_seconds']}s)")
            runs.append(ev)
            if best is None or hist["best_val_pr_auc"] > best["val"]:
                a, b = T.fit_platt(val_logits[val.valid], val.y[val.valid])
                best = {"val": hist["best_val_pr_auc"], "model": model, "seed": seed, "thr": thr, "platt": (a, b), "hist": hist}
                best["state"] = {k: v.clone() for k, v in model.state_dict().items()}

        def agg(get):
            v = np.array([get(r) for r in runs], dtype=float)
            return {"mean": float(np.nanmean(v)), "std": float(np.nanstd(v))}

        results["models"][kind] = {
            "display_name": DISPLAY_NAME[kind],
            "runs": runs,
            "aggregate": {
                "precision": agg(lambda r: r["detection"]["precision"]),
                "recall": agg(lambda r: r["detection"]["recall"]),
                "f1": agg(lambda r: r["detection"]["f1"]),
                "roc_auc": agg(lambda r: r["detection"]["roc_auc"]),
                "pr_auc": agg(lambda r: r["detection"]["pr_auc"]),
                "top1": agg(lambda r: r["localization"].get("top1", float("nan"))),
                "top2": agg(lambda r: r["localization"].get("top2", float("nan"))),
                "event_recall": agg(lambda r: r["lead_time"]["event_recall"]),
                "median_lead_min": agg(lambda r: r["lead_time"]["median_lead_min"]),
            },
            "deployed_seed": best["seed"],
        }

        # deployable artifact = best-on-validation seed (test set never used to choose)
        out = ARTIFACT_DIR / (kind if args.tag == "main" else f"{kind}_{args.tag}")
        out.mkdir(parents=True, exist_ok=True)
        torch.save(best["state"], out / "model.pt")
        meta = {
            "kind": kind,
            "display_name": DISPLAY_NAME[kind],
            "model_config": best["model"].config,
            "seed": best["seed"],
            "threshold_logit": best["thr"],
            "platt": {"a": best["platt"][0], "b": best["platt"][1]},
            "normalizer": norm.to_dict(),
            **({"regime": regime.to_dict()} if regime is not None else {}),
            "features": {"channels": F.CHANNELS, "window_steps": F.WINDOW_STEPS, "step_minutes": F.STEP_MINUTES,
                         "horizon_steps": F.HORIZON_STEPS, "node_order": F.NODE_ORDER, "node_features": in_dim},
            "provenance": PROVENANCE,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "split_name": split_name,
            "split": {k: {"from": v["from"], "to": v["to"]} for k, v in balance.items()},
            "best_epoch": best["hist"]["best_epoch"],
        }
        (out / "meta.json").write_text(json.dumps(meta, indent=2))
        np.savez(out / "weights.npz", *get_weights(best["model"]))  # Flower-style ndarray list

    results["wall_seconds"] = round(time.time() - t_start, 1)
    # one file per kind subset, so kinds can run as parallel processes without overwriting each other
    suffix = "" if args.kinds == ["gcn", "tag", "mlp"] else "_" + "-".join(args.kinds)
    path = ARTIFACT_DIR / f"results_{args.tag}{suffix}.json"
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2, default=float))
    print(f"\nwrote {path}")
    _print_summary(results)


def _print_summary(res: dict) -> None:
    print("\n================ TEST-SET SUMMARY (identical held-out split) ================")
    print(f"{'model':28s} {'P':>6} {'R':>6} {'F1':>6} {'ROC':>6} {'PR':>6} {'top1':>6} {'top2':>6} {'evRec':>6} {'lead(min)':>9}")
    for variant, r in res["baseline0_rule"].items():
        d, l, lt = r["detection"], r["localization"], r["lead_time"]
        print(f"{'Rule: ' + variant:28s} {d['precision']:6.3f} {d['recall']:6.3f} {d['f1']:6.3f} {d['roc_auc']:6.3f} {d['pr_auc']:6.3f} "
              f"{l.get('top1', float('nan')):6.3f} {l.get('top2', float('nan')):6.3f} {lt['event_recall']:6.3f} {lt['median_lead_min']:9.1f}")
    for kind, m in res["models"].items():
        a = m["aggregate"]
        f = lambda k: f"{a[k]['mean']:6.3f}"
        print(f"{m['display_name'] + ' (mean/' + str(len(res['seeds'])) + ' seeds)':28s} {f('precision')} {f('recall')} {f('f1')} {f('roc_auc')} {f('pr_auc')} "
              f"{f('top1')} {f('top2')} {f('event_recall')} {a['median_lead_min']['mean']:9.1f}")


if __name__ == "__main__":
    main()
