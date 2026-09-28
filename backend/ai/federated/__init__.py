"""Module 4 — adaptive federated learning (Flower; FedProx + adaptive weighting)
around the Module 3 TA-GNN. README-level guide.

WHAT THIS IS
    Several simulated grid nodes (one federated client per Kelmarsh turbine)
    each train the Module 3 TA-GNN on their OWN data. Only model weights and
    scalar metrics cross the client/server boundary — never readings. Compared,
    on the identical Module 3 held-out test split:
      a. centralized reference   Module 3 TA-GNN on pooled data (Module 3's numbers, reused)
                                 + the same model pooled with the clients' own-turbine view
      b. FedAvg                  all clients weighted equally
      c. FedProx                 FedAvg + proximal term mu in the local objective (sweep over mu)
      d. FedProx + adaptive      per-client aggregation weight from performance history (weighting.py)
    plus SIMULATED fault tolerance: client dropout, a degraded client, corrupted updates.

DATA PROVENANCE (do not blur this)
    Training + evaluation data = the REAL Kelmarsh wind-farm SCADA export
    (turbines 1-4, 2016-2018), REPLAYED — not live, not simulated. A client is a
    PARTITION of that replay, not a physically separate site. The live
    Open-Meteo wind/hydro values (power_output estimated from physics formulas)
    are not used here. Everything injected by simulated.py (dropout, degraded
    client, corrupted update) is SIMULATED, labelled so in code, logs and results.

CLIENT / SERVER BOUNDARY (privacy)
    Each client process opens only its own shard (partition.py). Messages
    contain (a) the model's parameter arrays — exact TA-GNN shapes, float32 —
    and (b) scalar metrics from an allow-list (wire.py; enforced on send and on
    receive, audited per run in wire_audit.json). No raw readings, features
    or labels cross. NOT implemented (possible future work): differential
    privacy and secure aggregation — model weights alone can still leak
    information about training data. Transport here is unencrypted localhost gRPC.

ENVIRONMENT (why a separate venv)
    Flower 1.38 pins fastapi/uvicorn/protobuf versions that conflict with
    backend/venv, and Ray-based simulation is not installable on Windows +
    Python 3.14. So: own venv (requirements.txt) and one OS process per client.
        cd backend
        python -m venv ai\\federated\\venv
        ai\\federated\\venv\\Scripts\\pip install -r ai\\federated\\requirements.txt

RUN (from backend/)
    # 0. build client shards + evaluation bundle (needs the backend's `app` package -> backend venv)
    venv\\Scripts\\python -m ai.federated.partition
    # 1. checks
    ai\\federated\\venv\\Scripts\\python -m ai.federated.selftest
    # 2. one federation by hand: server, then one client per turbine (4 terminals) ...
    ai\\federated\\venv\\Scripts\\python -m ai.federated.server --strategy fedprox_adaptive --mu 0.01 --seed 0 --out ai\\federated\\artifacts\\runs\\demo
    ai\\federated\\venv\\Scripts\\python -m ai.federated.client --turbine 1        # ... 2, 3, 4
    #    ... or all of it (server + 4 clients + test evaluation) in one command:
    ai\\federated\\venv\\Scripts\\python -m ai.federated.run_experiment --strategy fedprox_adaptive --mu 0.01 --seed 0
    # 3. the whole grid (resumable), then the centralized reference and the report
    ai\\federated\\venv\\Scripts\\python -m ai.federated.run_all --stage sweep
    ai\\federated\\venv\\Scripts\\python -m ai.federated.run_all --stage adaptive
    ai\\federated\\venv\\Scripts\\python -m ai.federated.run_all --stage scenarios
    ai\\federated\\venv\\Scripts\\python -m ai.federated.central_reference
    ai\\federated\\venv\\Scripts\\python -m ai.federated.report
    # 4. export the final federated model for the backend, then set AI_MODEL_SOURCE=federated in .env
    ai\\federated\\venv\\Scripts\\python -m ai.federated.export --auto

FILES
    partition.py          per-turbine shards (+ offline eval bundle) from Module 3's dataset pipeline
    local.py              local training (FedProx proximal term), local scalar evaluation, centralized fit
    client.py             Flower NumPyClient, one process per turbine
    weighting.py          equal + adaptive aggregation-weight rules (documented, pure numpy)
    strategies.py         Flower FedProx subclass: modes fedavg | fedprox | fedprox_adaptive, dropout, logging
    server.py             Flower server entry point
    wire.py               the client/server boundary: allow-listed payloads + per-run audit
    simulated.py          SIMULATED dropout / degraded client / corrupted update
    evaluate.py           offline test evaluation (identical Module 3 split, both views)
    run_experiment.py     one federation end to end; run_all.py the grid; central_reference.py; report.py; export.py
    selftest.py           fast checks of the weighting, dropout, wire audit and prox term
    artifacts/            shards/, eval_data.npz, runs/<run>/ (weights, round_log.json with per-round
                          per-client weights, result.json, logs), RESULTS.md, results_federated.json,
                          adaptive_weights_by_round.csv, model_federated/ (exported model)

MODULE 5 HOOK (no blockchain code here)
    runs/<run>/round_log.json and adaptive_weights_by_round.csv keep, per round and
    per client: participation, aggregation weight, loss-EMA, update norm, reported
    validation scalars — the per-node contribution scores a later ledger could record.
"""
