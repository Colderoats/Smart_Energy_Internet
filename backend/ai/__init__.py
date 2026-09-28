"""Module 3 — Topology Adaptive GNN (TA-GNN) fault prediction. README-level guide.

WHAT THIS IS
    Predicts, per turbine node of the digital-twin graph, whether a genuine
    equipment fault will START within the next 60 minutes, and (by ranking
    nodes) WHERE. Compared on one identical held-out split against:
      Baseline 0  the Module 2 rule-based detector (app/twin/fault_detection.py,
                  replayed offline with its ground-truth label override OFF)
      Baseline 1  a plain GCN
      TA-GNN      PyG TAGConv (the main model)
      (ablation)  an MLP with no message passing, to show what the graph adds.

DATA PROVENANCE (do not blur this)
    Training + evaluation data = the REAL Kelmarsh wind-farm SCADA export
    (turbines 1-4, 2016), REPLAYED — not live, not simulated. Live Open-Meteo
    wind/hydro nodes are graph structure only (no fault labels/temperature).
    The bus_a/bus_b/grid topology is the twin's illustrative graph. Anything
    synthetic (topology variants in ai/topology_eval.py) is labelled synthetic
    and kept out of headline metrics.

RUN (from backend/, using the project venv)
    venv\\Scripts\\python -m ai.run_experiments                 # train + evaluate all models, 5 seeds
    venv\\Scripts\\python -m ai.run_experiments --seeds 0 --epochs 3   # quick smoke test
    venv\\Scripts\\python -m ai.topology_eval                   # TA-GNN vs GCN on varied edge sets
    venv\\Scripts\\python -m ai.print_taxonomy                  # Stop-event -> fault / not-fault mapping

FILES
    taxonomy.py        which Stop events are genuine faults (planned/external = masked)
    features.py        graph + node-feature construction (shared with app/ai_service)
    dataset.py         CSV -> 10-min graph snapshots, labels, masks, splits, class balance
    models.py          NodeClassifier (tag | gcn | sage | mlp); get_weights/set_weights
    training.py        one train/predict harness for every model kind
    metrics.py         P/R/F1, ROC/PR-AUC, top-k localization, lead time, bootstrap CIs
    evaluation.py      the single evaluation routine (models AND rule baseline)
    run_experiments.py the comparable harness
    topology_eval.py   varied-topology evaluation (synthetic edge sets)
    artifacts/         results_*.json, <kind>/model.pt + meta.json (+ cache/). Model
                       files live ONLY in this directory.

FEDERATED-READY (Module 4 — no Flower code here)
    models.get_weights()/set_weights() exchange lists of numpy arrays;
    training.fit()/predict_logits() are the train/evaluate entry points.
"""
