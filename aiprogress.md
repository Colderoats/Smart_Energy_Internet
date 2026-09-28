# AI / Prediction Progress Log — Modules 3 & 4

Tracks **only** the AI/model work: Module 3 (Topology Adaptive GNN) and
Module 4 (adaptive federated learning), plus the fault-prediction and
forecasting model work that feeds them.

Everything else — ingestion, the digital twin, self-healing, API, frontend,
infrastructure — stays in PROGRESS.md. If a change is about *a model*, log it
here. If it is about *the platform*, log it there. A change that touches both
(e.g. adding a training-data export endpoint) gets a one-line pointer in the
other file.

**Status (2026-09-28): Module 3 built and evaluated; Module 4 built and evaluated on the clean scenario (5 seeds); the SIMULATED fault-tolerance comparison is largely NOT run (see EXP-010).** On the held-out test split every federated strategy scores F1 = 0, exactly like Module 3, so the 81% → 94% claim is neither supported nor refuted (§4c).
Module 3's pipeline, three comparable models, live inference and the Digital
Twin tab display all exist and run. **The measured results do NOT demonstrate
that the TA-GNN beats the rule-based detector** — on the pre-specified
held-out test split nothing detects anything (see §4b); the only positive
signal is on the validation split, which is optimistic for the learned models.
Read §4b before quoting any number from this file.

---

## 1. Current state summary

| | |
|---|---|
| Module 3 (TA-GNN) | **Built.** `backend/ai/` (train/evaluate), `backend/app/ai_service/` (live), `GET /ai/predictions`, Digital Twin tab badges. Results: §4b. |
| Module 4 (Federated learning) | **Built.** `backend/ai/federated/` (own venv; Flower 1.38, one client process per turbine). Clean-scenario grid finished (35 runs, 5 seeds). Simulated-degradation comparison: mostly not run (EXP-010). Results: §4c. Serving: `AI_MODEL_SOURCE=federated`. |
| Baseline detector | Exists (`backend/app/twin/fault_detection.py`). Replayed offline with its ground-truth label override OFF it **never fires usefully**: 0 true alarms on test (§4b). |
| Training data used | Real Kelmarsh SCADA, turbines 1–4, **2016–2018** (2017–2018 downloaded for training/eval only, `backend/data/scada/extra_years/`). 228 genuine fault events in total. |
| Blocking issues | Test split has only 5 independent fault events with valid samples (of 25) — the comparison is statistically inconclusive; see §4b and §7 Q10. |

---

## 2. Target metrics (goals, from handwritten notes — NOT results)

These are the numbers the project is aiming at. None of them has been met on
held-out data (measured results and verdicts are in §4b), and the notes do not
state what most of them are measured *against* — see §7 Open questions before
treating any of these as a specification.

### Federated aggregation (Module 4)

| Configuration | Target | Notes |
|---|---|---|
| FedAvg — all nodes weighted equally | **~81%** | Metric undefined in notes; presumed accuracy |
| FedProx + adaptive weighting | **~94%** | Adaptive weighting reduces a node's influence based on its performance history |

The claim under test: adaptive weighting plus a FedProx proximal term
outperforms plain FedAvg when client data is non-IID (which it will be — each
turbine has a different fault mix; see §6).

### Model architecture (Module 3)

| Configuration | Target |
|---|---|
| Plain GNN | Baseline for the architecture comparison |
| Topology Adaptive GNN (TA-GNN) | Should beat plain GNN — margin not specified in notes |

### Task-level improvement targets

| Task | Target improvement | Relative to what? |
|---|---|---|
| Fault **detection** | **5–15%** better | Not stated — see §7 |
| Fault **localization** | **10–20%** better | Not stated — see §7 |
| Service (restoration) time | **20–40%** reduction | Not stated — see §7 |

### Also tracked (no target figure given)

- **Resilience** — definition and measurement method not yet fixed.
- **Critical-load restoration** — the current twin has no notion of a critical
  load; every source node is weighted only by `rated_capacity_kw`. Defining
  critical loads is a prerequisite for measuring this at all.

---

## 3. Baseline-first plan

**The rule: nothing ships as an improvement until it beats the existing
rule-based detector on the same held-out split.**

The baseline is the threshold/statistical detector in
`backend/app/twin/fault_detection.py` — a per-node rolling window of the last
50 temperature readings, flagging `warning` at ≥3σ above the rolling mean and
`fault_predicted` at ≥5σ. Ground-truth `fault_label` from the Kelmarsh status
log overrides both.

Before any of this can run, the baseline has to be measurable offline: today it
only exists as a live, stateful function inside the ingestion pipeline, with no
way to replay it over a fixed dataset and score it. **Experiment 0 is
therefore not optional.**

### Planned experiments, in order

| # | Experiment | Purpose | Status |
|---|---|---|---|
| 0 | Offline harness + baseline scoring | Replay `fault_detection.evaluate` over a fixed split; record precision / recall / F1 / lead time. Produces the number everything else must beat. | **Done** — EXP-002. Baseline scores 0 true alarms on test. |
| 1 | Feature pipeline + train/val/test split | Windowed features per turbine; time-ordered (not random) split so no future data leaks into training. | **Done** — EXP-001/002; hard no-leakage assertions pass. |
| 2 | Plain GNN (centralized) | Does a graph model beat the statistical baseline at all? | **Done** (GCN, 5 seeds) — no on test (F1 0); optimistic yes on val. |
| 3 | TA-GNN (centralized) | Does topology adaptivity beat the plain GNN? | **Done** (5 seeds) — not demonstrated: ≈ GCN ≈ MLP; test F1 0. |
| 4 | FedAvg over 4 turbine clients | Federated floor. Target ~81%. | **Done** (5 seeds) — test F1 0; accuracy 99.9% (all-negative already scores ~99.97%); §4c. |
| 5 | FedProx + adaptive weighting | The headline claim. Target ~94%. | **Done** (5 seeds) — test F1 0, same as FedAvg; only optimistic validation PR-AUC differs (0.119 vs 0.052); §4c. |
| 6 | Localization + restoration-time evaluation | Requires the definitions from §7 before it can start. | Localization: **done** (node-level top-k, §4b). Restoration time: **not measured** (§7 Q4-6 open). |
| 7 | Topology-variation evaluation | Does the same weights run on changed edge sets; how stable are scores? | **Done** — EXP-004 (synthetic topologies, not headline). |

Experiments 2–5 all report against the **same** split and the **same** metric
set as Experiment 0, or the comparison is meaningless.

---

## 4. Experiment log

One entry per run. **Failures and dead ends get logged as carefully as
successes** — a failed approach that isn't written down gets re-attempted.

### Template — copy this block for each run

```
### EXP-NNN — <short name>
- **Date:**
- **Model / config:**        architecture, hyperparameters, aggregation strategy,
                             random seed
- **Dataset & split:**       source files, date ranges, train/val/test boundaries,
                             class balance, which client held which partition
- **Metric(s):**             what was measured and how (exact definition)
- **Result:**                the numbers, including the baseline's number on the
                             same split for comparison
- **What worked:**
- **What failed and why:**   including runs abandoned mid-flight, and what the
                             failure ruled out
- **Artifacts:**             checkpoint path, config hash, log location
- **Follow-up:**             what this implies for the next experiment
```

### Entries

Provenance for every entry below: **real Kelmarsh SCADA, REPLAYED** (not live,
not simulated) unless the entry says "synthetic". Topology is the twin's
illustrative graph.

### EXP-000 — Environment check (PyTorch / PyG on Python 3.14, Windows)
- **Date:** 2026-09-28
- **Model / config:** n/a
- **Dataset & split:** n/a
- **Metric(s):** does it install and run without compilation
- **Result:** CPU `torch 2.14.0` and `torch_geometric 2.8.0.post1` install from prebuilt cp314 wheels; `TAGConv`/`GCNConv`/`SAGEConv` run forward+backward. PyG core only — no torch-scatter/torch-sparse. Only warning: `torch.jit.script` FutureWarning on 3.14.
- **What worked:** dry-run (`pip install --dry-run`) first, then a real install in a throwaway venv, then the project venv.
- **What failed and why:** the first project-venv install run in the background hung (idle sockets in CLOSE_WAIT, no progress) after torch itself had installed; killed and re-run in the foreground, which finished in seconds from cache. No stack change was needed.
- **Artifacts:** `backend/requirements.txt` (pins + CPU index).
- **Follow-up:** none. scikit-learn deliberately not added; metrics are numpy (`ai/metrics.py`). pandapower not installed (the twin doesn't use it; it would bump networkx).

### EXP-001 — 2016-only smoke runs and the thin-split finding
- **Date:** 2026-09-28
- **Model / config:** GCN/TAGConv/MLP, 3–6 epochs, seed 0 (smoke test only)
- **Dataset & split:** 2016 only. train 2016-01-21..08-14, val ..10-19, test ..2017-01-01
- **Metric(s):** pipeline sanity; class balance
- **Result:** test span had **8 genuine fault events / 40 positive samples** (val: 4 events / 24). Far too few to compare models.
- **What worked:** end-to-end pipeline (CSV → windows → labels → masks → 3 models → metrics).
- **What failed and why:** (1) **NaN training loss.** Rows with no reading carried NaN in the presence-flag block; a masked NaN is still NaN after multiplying by 0. Fixed in `Normalizer.apply`. (2) The 2016 data cannot support a credible chronological test: 86 of 105 genuine faults are in Jan–Apr, and the rich SCADA channels only exist from 2016-05-03.
- **Artifacts:** none kept (smoke outputs deleted).
- **Follow-up:** asked the user; approved downloading 2017 and 2018 (Zenodo 8252025) into `backend/data/scada/extra_years/` for training/eval only.

### EXP-002 — Main comparison: Baseline 0 vs GCN vs TA-GNN (+ MLP ablation)
- **Date:** 2026-09-28
- **Model / config:** GCN, TAGConv (K=3), MLP; 2 layers, hidden 64, dropout 0.2, AdamW lr 3e-3 wd 1e-4, batch 256 snapshots, ≤40 epochs, early stopping on validation PR-AUC (patience 8). **No hyperparameter search**: identical settings for every model. Seeds 0–4. Parameter counts: GCN/MLP 7,233, TAGConv 28,353. Class weighting: `pos_weight = sqrt(neg/pos) = 32.9` (raw neg/pos = 1,082) plus per-epoch subsampling (30%) of negative-only snapshots; masked samples get zero loss weight. Operating threshold = max-F1 on **validation**, applied unchanged to test. Probability = Platt scaling on validation logits.
- **Dataset & split:** Kelmarsh turbines 1–4, 2016-01-21..2018-12-31, 10-min rows. Chronological: **train 2016-01-21..2017-12-31, val 2018-01-01..06-30, test 2018-07-01..12-31**, 120-min purge gaps; hard assertions in `ai/dataset.check_no_leakage` pass. Boundaries were chosen from genuine-fault counts per month only.
- **Task / label:** per turbine node, does a *genuine* fault START within the next 60 min (look-back 60 min). Planned/routine/external stops and already-stopped states are **masked**, not labelled 0 (taxonomy in §5.6). `fault_label` is never a model input.
- **Class balance (valid node-samples):** train 389,763 (360 pos, 0.09%, 172 events); val 101,278 (115 pos, 0.11%, 31 events); **test 98,392 (27 pos, 0.03%, 25 events — but only 5 events have any valid positive sample)**.
- **Metric(s):** precision/recall/F1 at the val-selected threshold; ROC-AUC, PR-AUC on the continuous score; false-alarm samples per node-day; node-level localization top-1/top-2 vs chance; event recall and lead time; day-block bootstrap CIs are computed and stored in `results_main.json`.
- **Result:** §4b. **Test: every scorer has F1 = 0 (0 true alarms). Learned models' test ROC-AUC is below 0.5 (0.32–0.44).**
- **What worked:** the harness; reproducing the production rule offline (its z-score mirror matches the production status exactly, asserted); no-leakage checks; runs are fast (30–90 s each).
- **What failed and why:** the models do not generalise to the test period. Diagnosis (read-only, no tuning on test): train and val positives are storm-type faults (val positives: median wind 13.2 m/s, median power 2,028 kW ≈ rated) so the models learn "very high wind → fault soon"; the 27 test positives come from 5 events (19 of the 25 test events are ~2-minute "Frequency converter not ready" blips inside restart sequences whose look-back samples are masked) at ordinary wind (median 5.2 m/s, 365 kW — identical to test negatives). So the test result reflects a regime shift plus n≈5, not a demonstration either way. Also: early stopping picked epoch 0–1 for several seeds, i.e. the signal is weak and easily overfit.
- **Artifacts:** `backend/ai/artifacts/results_main.json`; deployable best-on-validation seed per kind in `ai/artifacts/{tag,gcn,mlp}/` (`model.pt`, `weights.npz`, `meta.json`); cache in `ai/artifacts/cache/`. Deployed: TA-GNN seed 3 (threshold logit +1.96 ⇒ calibrated p ≥ 0.025).
- **Follow-up:** do NOT re-split after seeing test (that would be tuning the evaluation). Options for the user in §7 Q10: more years (2019–2022), or an evaluation design with more independent events.

### EXP-003 — Supplementary evaluation on the validation split (OPTIMISTIC for learned models)
- **Date:** 2026-09-28
- **Model / config:** the saved best-on-validation artifact of each kind + the rule variants
- **Dataset & split:** validation split (2018 H1): 115 positive samples over 23 events
- **Metric(s):** same code path as EXP-002 (`ai/eval_validation.py`)
- **Result:** §4b. The learned models show real but modest signal here (PR-AUC 0.11–0.12 vs ~0.001 chance); the rule detector is near chance.
- **What worked / failed:** the learned-model numbers were used for early stopping and threshold selection, so they are biased upward and must never be quoted as held-out results. The rule baseline is unbiased here (no fitted parameters).
- **Artifacts:** `ai/artifacts/eval_validation.json`
- **Follow-up:** the honest reading is "some learnable signal exists in-distribution; whether it transfers is undetermined".

### EXP-004 — Topology variation (SYNTHETIC edge sets on real test features)
- **Date:** 2026-09-28
- **Model / config:** deployed TA-GNN, GCN, MLP artifacts, unchanged weights
- **Dataset & split:** real test-split features/labels; **synthetic** topologies: 60 routing states sampled from the 3^6 = 729 states the twin can reach (each source on bus_a, bus_b or isolated), built with the twin's own `reroute_node`/`isolate_node` on private instances; 60 distinct edge sets, 4–8 undirected edges, up to 4 isolated sources.
- **Metric(s):** ROC-AUC/PR-AUC/F1 across variants; mean |logit shift| vs the default topology
- **Result:** the same saved weights run on every edge set with no code change (edge_index is an input). TA-GNN test ROC-AUC across variants: mean 0.448, range 0.179–0.754 (default topology: 0.363); mean |logit shift| 1.83. GCN: mean 0.412, range 0.198–0.674, shift 0.97. MLP: invariant by construction.
- **What worked:** demonstrating that the model runs on varied topologies without retraining code changes.
- **What failed and why / limits:** **the real data contains exactly one topology**, and no fault label depends on topology, so this cannot show that TAGConv's topology adaptivity *helps*. It shows the scores are quite sensitive to neighbours' edges (TAGConv more than GCN), which — with test AUC below 0.5 — mostly reads as noise. Synthetic; excluded from headline metrics.
- **Artifacts:** `ai/artifacts/topology_eval.json`
- **Follow-up:** a real test of topology adaptation needs faults whose labels depend on routing (not available), or training with synthetic-topology augmentation (not run; would need to be labelled synthetic and needs user approval).

### EXP-005 — Serving parity, and a train/serve skew found and fixed
- **Date:** 2026-09-28
- **Model / config:** deployed TA-GNN in `app/ai_service`
- **Dataset & split:** real replayed rows streamed in live (round-robin) order
- **Metric(s):** max |online logit − offline logit| for the same snapshot (`ai/check_serving_parity.py`)
- **Result:** after the fix, max difference 9.5e-7 over 948 node-scores / 60 snapshots.
- **What failed and why:** the first serving design scored a turbine when its own reading arrived, while its neighbours were still one step behind. Because the model reads neighbours' windows, a real validation-period flag (offline logit 2.87 ≥ threshold 1.96) was served as probability 0.020 (below threshold). My first parity check missed it because it only scored after all four nodes had arrived; an in-process wiring test with real data exposed it. Fix: score all turbines as one snapshot anchored at a common reference step (the slowest node's newest step) and refresh all four verdicts together when it advances. Cost: each verdict's `as_of` can trail a node's newest reading by up to ~3 dataset steps (≤30 min of dataset time).
- **Artifacts:** `ai/check_serving_parity.py`
- **Follow-up:** live replay covers Jan 2016 (inside the training period), so live flags there are in-sample and say nothing about generalisation.

### EXP-006 — Module 4 environment check (Flower on Python 3.14 / Windows)
- **Date:** 2026-09-28
- **Model / config:** n/a (Flower 1.38.0, torch 2.14.0+cpu, PyG 2.8.0.post1)
- **Result:** Flower core installs from prebuilt wheels. `flwr[simulation]` pulls Ray only for non-Windows on Python >= 3.13, so **Ray simulation cannot run here**. Flower also hard-pins fastapi 0.138 / uvicorn 0.49 / starlette 1.3 / protobuf < 7, which conflicts with `backend/venv` (fastapi 0.115.6, protobuf 7.35).
- **What worked:** a throwaway venv, then a Flower gRPC server plus two client processes ran FedProx rounds on Windows.
- **Decision (user):** separate venv `backend/ai/federated/venv`, server and clients as separate OS processes. `backend/venv` untouched.

### EXP-007 — Partitioning and pipeline bring-up
- **Dataset & split:** Module 3's exact pipeline and split; one client per turbine. Per-client class balance is in §4c. A client's graph holds only its own turbine's features (approved), the other slots empty.
- **What failed and why:** (1) the wire audit demanded parameter arrays on evaluation replies that carry only metrics; (2) after the server crashed the launcher waited on orphaned clients; (3) the report writer used the Windows default encoding. All fixed. A 3-round smoke run showed T1's local validation loss already worse than the no-skill baseline, so the adaptive rule floored T1 immediately. That is a real result of the pre-specified rule, not a bug; the rule was not tuned afterwards.
- **Artifacts:** `ai/federated/artifacts/partition_report.json`, `shards/`, `eval_data.npz`.

### EXP-008 — Clean-scenario grid (REAL replayed data, no injected degradation)
- **Config (fixed a priori):** 30 rounds, 1 local epoch per round, AdamW lr 3e-3 wd 1e-4, batch 256, 30% negative subsampling, per-client `pos_weight = sqrt(neg/pos)`, seeds 0-4. FedAvg: equal client weights. FedProx: mu in {0.001, 0.01, 0.1, 1.0}. Adaptive rule (`ai/federated/weighting.py`, defined before any run): EMA (alpha 0.5) of each client's validation loss divided by its no-skill constant-predictor loss; loss factor `exp(-5·max(0, rel-1))` with rel = EMA / cohort median; update-norm factor `min(1, (1.5/rho)^2)` with rho = update norm / median update norm (measured by the server); weight proportional to the product, normalised, 5% floor.
- **Selection:** the global model of each run is the round with the best mean client validation PR-AUC; mu* was chosen from the sweep by validation only (mean over seeds): 0.001 → 0.1305, 0.01 → 0.1292, 0.1 → 0.1292, **1.0 → 0.1355 (chosen)**. The differences are within seed noise and 1.0 is the edge of the sweep, so a larger mu was not explored.
- **Result:** §4c. Test F1 is 0 for every strategy and seed.
- **Artifacts:** `ai/federated/artifacts/runs/<run>/` (weights, `round_log.json` with per-round per-client weights, `result.json`, logs), `RESULTS.md`, `results_federated.json`, `adaptive_weights_by_round.csv`, `mu_selection.json`.

### EXP-009 — Adaptive weighting alone (mu = 0 ablation), clean, 5 seeds
- Test F1 0; optimistic validation PR-AUC 0.055 ± 0.005 vs FedAvg 0.052 ± 0.010, so adaptive weighting on its own changed nothing measurable.

### EXP-010 — SIMULATED fault tolerance (dropout / degraded client / corrupted updates) — MOSTLY NOT RUN
- **Built and tested:** all three scenarios exist in `ai/federated/simulated.py` (labelled SIMULATED in code, logs, run metadata). Dropout: each client unavailable with probability 0.3 per round. Degraded client (T3): feature noise sigma 2 plus 50% of positive labels dropped. Corrupted updates (T3): sign-flipped x3 update.
- **Actually run:** only seed 0 dropout for FedAvg and FedProx (mu 1), both with test F1 0. The FedProx + adaptive dropout run and every degraded-client and corrupted-update run were **not completed**: each run takes about 10 to 30 minutes on this laptop and the user asked to finish quickly. **No claim about how adaptive weighting responds to a faulty client is supported by measurement.**
- **Follow-up:** `python -m ai.federated.run_all --stage scenarios` (resumable; `--seeds`) runs the rest.

### EXP-011 — Centralized own-view reference
- Seed 0 only (of 5 planned): best epoch 8, validation PR-AUC 0.0815, full-view test F1 0. Module 3's five-seed numbers are the main centralized baseline (reused).

### EXP-012 — Backend serving of the federated model
- The final model (best validation seed of FedProx + adaptive, mu 1: run `fedprox_adaptive_mu1_clean_s3`) is exported in Module 3's format to `ai/federated/artifacts/model_federated/`. With `AI_MODEL_SOURCE=federated` the backend loaded it, `GET /ai/predictions` reported `source: federated` and each `ta_gnn` verdict carried `model_source: federated`; the default setting still loads the Module 3 model (`source: centralized`). `GET /nodes` (7/6), `GET /twin/nodes` (9/8) and `GET /twin/decisions` were unchanged. The flags were essentially all below threshold at that moment, so no organic federated flag was observed.

---

## 4b. Measured results (identical held-out test split; real replayed SCADA)

**Test split, H2 2018: 98,392 valid node-samples, 27 positives from 5 independent events.**
All learned-model rows are mean ± std over 5 seeds at each seed's validation-chosen threshold. Localization is node-level top-k over the 4 turbines on the 27 snapshots that contain a positive; chance is stated per row.

| Scorer | Precision | Recall | F1 | ROC-AUC | PR-AUC | Loc. top-1 (chance 0.259) | Loc. top-2 (chance 0.519) | Event recall | Lead time |
|---|---|---|---|---|---|---|---|---|---|
| **Baseline 0** — Module 2 rule, alarm at ≥5σ (production "fault_predicted", label override OFF) | 0 (0 TP / 11 FP) | 0 | 0 | 0.575 | 0.0004 | 0.259 | 0.519 | 0/5 | n/a |
| Baseline 0 — alarm at ≥3σ ("warning") | 0 (0 TP / 806 FP) | 0 | 0 | 0.575 | 0.0004 | 0.259 | 0.519 | 0/5 | n/a |
| Baseline 0 — ≥5σ fired anywhere in last 60 min | 0 (0 TP / 43 FP) | 0 | 0 | 0.640 | 0.0008 | 0.370 | 0.667 | 0/5 | n/a |
| **Baseline 1** — plain GNN (GCN) | 0 | 0 | 0 | 0.324 ± 0.045 | 0.0002 | 0.030 ± 0.015 | 0.444 ± 0.112 | 0/5 | n/a |
| **TA-GNN** (TAGConv) | 0 | 0 | 0 | 0.338 ± 0.088 | 0.0002 | 0.237 ± 0.195 | 0.682 ± 0.119 | 0/5 | n/a |
| MLP, no graph (ablation) | 0 | 0 | 0 | 0.444 ± 0.039 | 0.0002 | 0.511 ± 0.086 | 0.667 ± 0.105 | 0/5 | n/a |

**Reading of the test table.** No scorer detects any of the 5 testable events; F1 = 0 everywhere, so a relative "improvement over baseline" is undefined (0 vs 0). Learned models' ROC-AUC < 0.5 means they rank the test positives *below* typical negatives (regime shift, see EXP-002). Localization is within noise of chance for every scorer (top-1 chance 0.259; n = 27 snapshots from 5 events). **Nothing here supports the 5–15% detection or 10–20% localization targets, and nothing here refutes them either: the test set cannot tell.**

**Validation split (2018 H1; 115 positives, 23 events) — OPTIMISTIC for learned models** (used for early stopping/threshold; rule rows are fair). Deployed seed per kind:

| Scorer | Precision | Recall | F1 | ROC-AUC | PR-AUC | top-1 (chance 0.377) | top-2 (chance 0.620) | Event recall | Median lead |
|---|---|---|---|---|---|---|---|---|---|
| Rule ≥5σ | 0 | 0 | 0 | 0.687 | 0.004 | 0.435 | 0.635 | 0.00 | n/a |
| Rule ≥3σ | 0.011 | 0.096 | 0.020 | 0.687 | 0.004 | 0.435 | 0.635 | 0.09 | 54.8 min |
| GCN [optimistic] | 0.151 | 0.217 | 0.178 | 0.735 | 0.109 | 0.282 | 0.612 | 0.48 | 17.4 min |
| **TA-GNN** [optimistic] | 0.168 | 0.287 | 0.212 | 0.835 | 0.114 | 0.400 | 0.635 | 0.52 | 19.3 min |
| MLP [optimistic] | 0.309 | 0.148 | 0.200 | 0.775 | 0.121 | 0.435 | 0.659 | 0.30 | 17.9 min |

What this does and does not say: in-distribution (adjacent-in-time, storm-season) the learned models carry signal the rule detector lacks (F1 ≈ 0.18–0.21 vs ≈ 0.02; PR-AUC ~0.11 vs ~0.004). It does **not** show the graph helps: TA-GNN ≈ GCN ≈ MLP within seed noise (single deployed seeds, no CIs here), and localization is at chance level on val too. Precision ~17% means most flags are false alarms — with TA-GNN flags driving self-healing (user decision) expect spurious reroutes.

**Targets vs measured (goals, not results):**

| Target (from notes) | Measured | Verdict |
|---|---|---|
| Fault detection +5–15% vs baseline | Test: F1 0 vs 0 (undefined). Val (optimistic): F1 0.212 vs 0.020 rule ≥3σ; TA-GNN vs GCN 0.212 vs 0.178. | Not demonstrated on held-out data |
| Fault localization +10–20% | Test: top-1 0.237 ± 0.195 vs chance 0.259 (rule 0.259). Val: 0.400 vs chance 0.377. | Not demonstrated; at chance |
| Service/restoration time −20–40% | Not measured (§7 Q4–6 unanswered; twin healing is instantaneous). | Not measured |
| FedAvg ~81% → FedProx+adaptive ~94% | Test F1 0 vs 0; accuracy 99.92% vs 99.84% (all-negative scores ~99.97%). See §4c. | Not demonstrated, not refuted |

Class balance, weighting and everything else needed to reproduce is in EXP-002.

---

## 4c. Module 4 measured results (identical held-out test split; real replayed SCADA; clean scenario)

Full tables (both views, per client, mean ± std over seeds 0-4): `ai/federated/artifacts/RESULTS.md`. A federated "client" is a partition of the Kelmarsh replay, not a separate site. Test = H2 2018, 27 positives from 5 independent events, so **the test set cannot separate any two methods**.

**Per-client partitions (train / validation / test valid samples and positives):**

| Client | Train samples | Train positives | Train fault events | Val positives | Test positives |
|---|---|---|---|---|---|
| T1 | 96,850 | 112 | 48 | 22 | 0 |
| T2 | 98,303 | 130 | 58 | 34 | 15 |
| T3 | 97,257 | 81 | 34 | 31 | 12 |
| T4 | 97,353 | 37 (7 events with a valid positive) | 32 | 28 | 0 |

Non-IID and imbalanced, kept as is. T4 is thin but trainable. T1 and T4 have no test positives, so their per-client test recall and AUCs are undefined.

**Full-view test (all four turbines' features, as Module 3 and the backend serve), val-selected round:**

| Strategy | F1 | ROC-AUC | Accuracy | Optimistic val PR-AUC | Rounds to convergence | Rounds × params |
|---|---|---|---|---|---|---|
| Centralized Module 3 (reused, 5 seeds) | 0.000 | 0.338 ± 0.088 | 0.9994 | n/a | n/a | n/a |
| FedAvg (equal weights) | 0.000 | 0.256 ± 0.026 | 0.9992 | 0.052 ± 0.010 | 3.4 ± 0.5 | 96,400 |
| FedProx mu 0.001 / 0.01 / 0.1 | 0.000 | 0.228 / 0.311 / 0.275 | ~0.999 | 0.070 / 0.074 / 0.091 | 3.2 / 1.4 / 3.8 | 90,730 / 39,694 / 107,741 |
| FedProx mu 1 | 0.000 | 0.404 ± 0.072 | 0.9985 | 0.096 ± 0.024 | 17.4 ± 9.0 | 493,342 |
| FedProx mu 1 + adaptive | 0.000 | 0.392 ± 0.058 | 0.9984 | 0.119 ± 0.010 | 18.0 ± 4.0 | 510,354 |
| Adaptive alone (mu 0) | 0.000 | 0.261 ± 0.034 | 0.9991 | 0.055 ± 0.005 | 5.6 ± 4.3 | 158,777 |

Precision, recall, event recall are 0 everywhere; PR-AUC is about 0.0002 (chance 0.0003); ROC-AUC is below 0.5 for every method, the same regime-shift signature as Module 3 (EXP-002). Own-view test numbers are similar (RESULTS.md). Parameters: 28,353 per model.

**Reading.**
- **The 81% → 94% target:** the notes do not define the metric (§7 Q1); the user asked for all metrics with F1 as the headline. Accuracy is 99.8% to 99.97% for every method including plain FedAvg, because all-negative already scores about 99.97%, so it cannot reach or miss 81% and 94% meaningfully. On F1 (0 vs 0) the claim is undefined. **Not demonstrated, not refuted.**
- **The only separating signal is optimistic** (validation PR-AUC, used for round and mu selection): it rises from FedAvg 0.052 to FedProx mu 1 at 0.096 to FedProx + adaptive at 0.119. Adaptive weighting alone (mu 0) did not help (0.055). The mu = 1 gain also costs about 5x more rounds.
- **Adaptive weights (clean data, mean over rounds and seeds; equal = 0.25):** at mu 1, T1 0.113, T2 0.322, T3 0.236, T4 0.329. T1 is down-weighted because its local validation loss is worse than the no-skill baseline. Whether that helps is not measurable on this test set.
- **Fault detection +5-15%, localization +10-20%, restoration time -20-40%:** not demonstrated (F1 0; full-view top-1 localization between 0.00 and 0.16 across federated strategies vs chance 0.26); restoration time not measured.
- **Fault tolerance:** see EXP-010; not measured.

---

## 5. Blocking data issues found during the 2026-09-28 audit

These were found by running the stack and reading the raw Kelmarsh files
directly. They shape everything in §3 and need resolving before Experiment 1.

**5.1 — The baseline detector has never actually fired on real data.**
`fault_detection.evaluate` keys entirely off `temperature`. In the Kelmarsh
2016 export, `Generator bearing rear temperature (°C)` is `NaN` for every row
before **2016-05-03**, which is roughly row 12,500–14,200 of each turbine's
~47–48k usable rows. At the current 2s round-robin replay interval that is
**~28–31 hours of continuous runtime** before the first temperature value even
reaches the detector. Every `fault` the system has ever shown came from the
ground-truth `fault_label` override, not from the statistical rule. Scoring the
baseline offline (Experiment 0) is the only way to get a real number out of it.

**5.2 — Feature and label coverage barely overlap.**
Across turbines 1–4: ~191,342 usable rows, of which 6,086 carry a fault label
(3.2%), but only **1,408 rows have both a label and a temperature value**. A
supervised model trained on the current single feature would have ~1.4k
positive examples to learn from. Widening the feature set (the export has 299
columns, 13 temperature channels with ~34k non-null rows each, plus wind speed,
rotor speed, pitch, nacelle position) is effectively mandatory.

**5.3 — The `fault_label` ground truth is not all faults.**
`Status == "Stop"` is currently treated as a fault. By labeled-row share, the
top causes are:

| Share | Message | Actually a fault? |
|---|---|---|
| 23.4% | Manual stop - on site | No — planned intervention |
| 19.9% | Frequency converter error | Yes |
| 11.2% | Park master stop | No — operator/grid curtailment |
| 10.2% | Repeating error BP52 | Yes |
| 6.3% | Anemometer defect | Yes — sensor fault |
| 5.7% | Feedback brake 1 | Yes |
| 2.7% | Manual stop - remote | No — planned |
| 1.2% | Battery test | No — routine test |
| 1.1% | Cable autounwind | No — routine operation |

Roughly **40% of the positive class is planned or routine activity**, not
equipment failure. A model trained on this learns to predict maintenance
scheduling. The live system already shows the consequence: self-healing
decisions in the log read `Trigger: ground-truth fault label: 'Manual stop -
on site'` — the twin is rerouting the grid around a technician doing planned
work. A curated fault/non-fault message taxonomy is needed before Experiment 1.

**5.4 — "Front-loaded fault cluster" is a replay artifact, not a dataset
property.** PROGRESS.md notes the Kelmarsh fault cluster is front-loaded. That
is true of what a short demo run *sees*, but not of the dataset: labeled rows
are spread across all twelve months of 2016 (heaviest in Jan/Feb/Apr, lightest
in Jul/Aug). For training purposes the whole year is available and usable.

> **Correction (2026-09-28, Module 3 build):** 5.4 is true for *any-Stop*
> labelled rows but **not for genuine equipment faults**, which are strongly
> winter-clustered: 2016 has 105 (86 in Jan–Apr), 2017 has 67 (61 in Jan–Feb),
> 2018 has 56 (22 in Jan, 22 in Nov–Dec). Outside those storm clusters there are
> ~0–4 per month. This is what makes a chronological test split thin (EXP-001/002).
> Also, the rich SCADA channels (temperatures, rotor/generator RPM, pitch)
> exist only from 2016-05-03 (all of 2017–2018 have them).

**5.5 — No vibration channel.** Confirmed: the export has no accelerometer
scalar. `vibration` is `None` everywhere and will stay that way. Any target
metric that assumes vibration features needs restating.

**5.6 — Fault taxonomy actually applied (decided with the user: planned stops
are masked, not positives).** Basis: the status log's own *IEC category*
column, refined by a short explicit message list in `backend/ai/taxonomy.py`
(`venv\Scripts\python -m ai.print_taxonomy` prints the live mapping with counts;
in 2016 alone it gives 105 genuine-fault and 404 masked events, and over 2016–2018
228 genuine faults in total).

| Class | IEC category / rule | Examples |
|---|---|---|
| **Genuine fault (positive)** | "Forced outage" except the human/grid messages below; plus blank-category component faults | Frequency converter not ready / error, Oscillation encoder tower, Repeating error BP52, Safety chain open, High rotor speed, Feedback brake 1, Tower oscillation X/Y, Yaw errors, Anemometer defect, Rotor sensor defective, Pitch deviation, Low hydraulic pressure, Vane defect |
| **Masked (not a fault, not a negative)** | Technical Standby, Scheduled Maintenance, Requested Shutdown, Out of Electrical/Environmental Specification, plus in "Forced outage": Manual stop - remote, Emergency stop base/nacelle/top box, Externally stopped, Maximum grid frequency, WEC shut down; blank-category "Test brake program …" | Battery test (168 in 2016), Manual stop - on site, Cable autounwind, Grid loss, Park master stop, Hydraulic oil flushing, Overvoltage, Max. wind speed, Icing (anemometer), Drive train monitor level 1/2 |

Judgement calls worth a second look: "Emergency stop *" (a person pressed a
button), "Overvoltage"/"Grid loss" (grid-side), "Drive train monitor level 2"
(arguably a real drivetrain alarm, but categorised Technical Standby). Two
"Emergency stop top box" events have unparseable timestamps and are dropped by
the existing replay parser, as they always were.

---

## 6. Data provenance

Consistent with the data-sourcing rules in the project instructions file.
**No simulated or derived value is ever to be presented as measured.** Every
model, dataset export and reported metric must carry its provenance class.

| Class | What it is | Nodes | Use in Modules 3/4 |
|---|---|---|---|
| **Real measured (replayed)** | Kelmarsh wind farm SCADA, 6× Senvion MM92, Northamptonshire UK, Cubico Sustainable Investments, CC BY 4.0, [Zenodo 8252025](https://zenodo.org/records/8252025). Genuine 10-minute plant telemetry and a genuine operator event log with real timestamps and messages. Turbines 1–4; **2016 is loaded for Module 1's replay, 2017–2018 additionally sit in `backend/data/scada/extra_years/` for Module 3 training/evaluation only.** **Replayed at 2s/row — the replay clock is not real elapsed time.** The live demo replays 2016, which is inside the model's training period, so live TA-GNN flags there are in-sample. | `wind_scada_kelmarsh_1..4` | **The only source suitable for supervised training and evaluation.** |
| **Live API-derived (estimated)** | Open-Meteo Forecast API (real current wind speed) and Flood/GloFAS API (real daily river discharge). Real measurements — but **`power_output` is computed** from them via a generic cubic turbine power curve and `P = ρgQHη` with an assumed 30 m head. Not metered, not any real plant's spec. | `wind_01`, `hydro_01` | Usable for forecasting inputs. **Not usable as fault-prediction ground truth** — these nodes carry no temperature, no vibration and no fault labels, and always evaluate `normal`. |
| **Simulated / illustrative** | Twin topology (`bus_a`/`bus_b`), bus capacities, per-source `rated_capacity_kw`, the 50% curtailment fraction, and the self-healing scoring weights. Demo figures chosen so rerouting is a non-trivial tradeoff — not a load-flow study. | `bus_a`, `bus_b`, `grid` | Fine as graph structure for the GNN. **Any restoration-time or resilience metric computed on this topology is a simulation result and must be labeled as such.** |
| **Synthetic (Module 3)** | Topology variants in `ai/topology_eval.py`: real test features on edge sets generated by the twin's own reroute/isolate primitives. Labelled `synthetic` in code, JSON and here. | — | Robustness/“does it run” only; never in headline metrics. |
| **Model outputs** | TA-GNN predictions served by `GET /ai/predictions` and shown on the Digital Twin tab are **forecasts on replayed data**, labelled as such in the API (`data: "replayed_scada_not_live"`), the tooltip and the tab header. | — | Not sensed values. |
| **Not present** | Solar and EV hardware, ESP32 firmware, MQTT. | — | Described in the project description but not built. No solar/EV data exists. |

Reporting rules for this module:
- Every number in §4 states which class(es) it was computed on.
- A metric computed on the simulated topology is never reported as a
  measurement of real grid behaviour.
- A federated "client" is a partition of the Kelmarsh replay, not a physically
  separate site — say so wherever client counts are reported.

---

## 7. Open questions — need answers before targets become specifications

The handwritten notes give numbers but not definitions. Each of these changes
what gets built, so please define them:

**Status after the Module 3 build (2026-09-28):**

| Q | Status |
|---|---|
| 1 (81%/94%) | **Handled for Module 4 by reporting every metric** (accuracy, balanced accuracy, precision, recall, F1, ROC/PR-AUC) with F1 as the headline; the metric behind the notes' numbers is still undefined. Accuracy cannot distinguish methods at ~0.03% positives. |
| 2 (detection, relative to what) | **Answered:** per node, fault *start* within the next 60 min; primary metric F1 (plus PR-AUC) against the Module 2 rule-based detector on the identical split, label override off. |
| 3 (localization) | **Answered:** node-level over the 4 labelled turbines; top-1/top-2 vs a rule-based ranking and vs chance. |
| 4, 5, 6 (restoration time, resilience, critical loads) | Still open. Not measured; a restoration-time result would be a simulation on the illustrative topology. |
| 7 (federated clients) | Partly: 2017–2018 downloaded (Module 3 only). Turbines 5–6 and 2019–2022 not used. Revisit for Module 4. |
| 8 (fault taxonomy) | **Answered:** planned/routine/external stops are masked (§5.6). |
| 9 (forecasting) | Not added (no demand data); not asked again. |

**New questions from this build:**

10. **The test split cannot separate the models** (5 independent events with valid samples; §4b). Options: (a) download 2019–2022 (Zenodo: 2019 ≈ 311 MB, 2020 ≈ 474 MB, 2021 ≈ 468 MB, 2022 ≈ 486 MB) for a larger, later test span; (b) keep the split and treat Module 3 results as inconclusive; (c) add a rolling-origin (walk-forward) evaluation over all years to use every event. I did not change the split after seeing the test result — that would be tuning the evaluation.
11. **Precision on validation is ~17% for the deployed TA-GNN** and its flags drive the existing self-healing (per your decision), so live false-alarm reroutes will occur. Keep, or switch to display-only?
12. **Does the graph help at all?** TA-GNN ≈ GCN ≈ MLP here. If topology adaptation is meant to matter, the data would need faults whose labels depend on routing; the Kelmarsh data has one topology. Do you want a labelled-synthetic topology-augmentation experiment?
13. **Taxonomy judgement calls** in §5.6 (emergency-stop buttons, grid-side events, "Drive train monitor level 2") — confirm or adjust.

1. **81% / 94% — what do these measure?** Accuracy, F1, AUC, or something
   else? On which task (fault detection? demand forecasting? both)? Accuracy on
   a 3.2%-positive class is near-meaningless — a model predicting "never a
   fault" scores 96.8%. If accuracy is intended, on what balanced or resampled
   set?

2. **Fault detection +5–15% — relative to what baseline?** The rule-based
   detector in Module 2? A plain GNN? A published paper's figure? And which
   metric improves by 5–15% — recall, F1, precision?

3. **Fault localization +10–20% — what is "localization" here?** The twin has
   6 source nodes. Is localization "which node faulted" (a 6-way
   classification), "which bus/segment", or a sub-component within a turbine?
   And relative to which baseline — there is no localization baseline today.

4. **Service/restoration time −20–40% — measured how?** The twin's self-healing
   is instantaneous (a dict mutation), so wall-clock is zero. Is this
   simulated restoration time on the twin's topology, and against what
   comparator — no self-healing at all, or a non-AI-assisted policy?

5. **Resilience — what definition?** Options include unserved energy over a
   fault episode, fraction of load restored within N steps, or N-1 contingency
   survival. This determines what the twin needs to record.

6. **Critical-load restoration — which loads are critical?** No node is marked
   critical today. This needs a per-node criticality weight before it can be
   measured.

7. **Federated clients — how many, partitioned how?** Four Kelmarsh turbines
   gives four clients with genuinely non-IID fault distributions (T1 has 2,509
   labeled rows, T4 has 636 — a 4× imbalance, which is realistic and good for
   demonstrating adaptive weighting). Is four enough, or should turbines 5–6
   and additional years (2017–2022, also on Zenodo) be downloaded to get more?

8. **Fault taxonomy (§5.3)** — should planned stops ("Manual stop", "Park
   master stop", "Battery test", "Cable autounwind", "Hydraulic oil flushing")
   be excluded from the positive class, kept as a separate "planned outage"
   class, or left as-is?

9. **Forecasting scope** — the module description mentions demand forecasting.
   There is no demand/load data anywhere in the system, only generation. Is
   forecasting in scope for Module 3, and if so against what data?

---

## 8. Verification record (2026-09-28) — what was and was not checked

**Verified:**
- Offline pipeline end to end on real data; hard no-leakage assertions (120-min purge gaps; labels never reach the next split); the rule baseline's z-score mirror equals the production `fault_detection.evaluate` status for every row (asserted at build time).
- Serving parity: live-order (round-robin, score-after-every-reading) predictor reproduces offline logits to 9.5e-7 (`ai/check_serving_parity.py`).
- Backend wiring with the real saved model on real validation-period data (in-process): a node the rule-based detector rated `normal` was flagged by TA-GNN (p = 0.043), its `health_status` became `fault_predicted`, `flagged_by = ['ta_gnn']`, the decision-log trigger named TA-GNN, and the existing self-healing reacted (curtailed to 50%).
- Clean backend restart (not `reload=True`): the model loads at startup; `GET /ai/predictions` returns the model card and per-node verdicts (live API nodes listed `scored: false`); WebSocket `twin_node_update` messages carry `detectors` and `flagged_by`, with rule-based and TA-GNN verdicts side by side.
- Module 1/2 unchanged: `GET /nodes` still 7 nodes / 6 edges with the same node keys (the SCADA `latest_reading` gained an extra `scada_channels` key, see PROGRESS.md), `GET /twin/nodes` 9 nodes / 8 edges, `GET /twin/decisions` returns the persisted log. Live Data tab untouched.
- Digital Twin tab in headless Chromium (Playwright): detector rows, "Flagged: rule-based" badges and TA-GNN probability render with zero console errors. A **mocked** WebSocket message (UI-rendering test only, not model output) confirmed the TA-GNN-flagged rendering: orange "Fault predicted", purple "Flagged: TA-GNN", "TA-GNN FLAG 31% ≤60min", rule-based "clear". A layout regression I introduced (taller cards overlapping) was found in the first screenshot and fixed.

**Not verified:**
- **A live, organic TA-GNN flag in the running backend + browser.** I watched ~8 min (REST polling) and a 90 s WebSocket window; none occurred (the live replay starts in early Jan 2016 where most nodes are in labelled stopped states). The backend mechanics were proven in-process on real data and the UI rendering with a mocked message, but the two were not seen together in the running app.
- **Held-out generalisation.** The test split (5 independent events) is inconclusive; the deployed model has no demonstrated out-of-distribution skill.
- Restoration/service-time and resilience improvements (not defined or measured).
- The 81%/94% federated targets: measured (§4c) but inconclusive on the held-out test set.
- **Module 4 not verified:** the SIMULATED fault-tolerance comparison (EXP-010; only 2 seed-0 dropout runs finished); seeds 1-4 of the centralized own-view reference; adaptive weighting's response to a degraded or corrupted client; an organic live flag from the federated model; the Digital Twin tab in a browser (no frontend edit); TLS, differential privacy and secure aggregation (not implemented; localhost, unencrypted).
- **Module 4 open decisions:** mu = 1 is the edge of the sweep (a larger mu was not tried); Module 3's test split is too thin to compare anything (§7 Q10) and this limits Module 4 equally.
- Confidence intervals for the validation-split table, and CIs on test are degenerate (0 true alarms everywhere).
- Long-run stability of the live service (memory, replay looping) beyond a few minutes; the per-reading cost is small (a 9-node graph forward pass) but I did not load-test it.
- Frontend production build (`vite build`) and cross-browser behaviour.
