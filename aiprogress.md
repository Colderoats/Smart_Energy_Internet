# AI / Prediction Progress Log — Modules 3 & 4

Tracks **only** the AI/model work: Module 3 (Topology Adaptive GNN) and
Module 4 (adaptive federated learning), plus the fault-prediction and
forecasting model work that feeds them.

Everything else — ingestion, the digital twin, self-healing, API, frontend,
infrastructure — stays in PROGRESS.md. If a change is about *a model*, log it
here. If it is about *the platform*, log it there. A change that touches both
(e.g. adding a training-data export endpoint) gets a one-line pointer in the
other file.

**Status: not started.** No Module 3/4 code exists yet. Everything below is a
plan, a target, or an open question — nothing here is a result.

---

## 1. Current state summary

| | |
|---|---|
| Module 3 (TA-GNN) | Not started — no code, no dataset export, no splits |
| Module 4 (Federated learning) | Not started — no Flower setup, no node partitions |
| Baseline detector | Exists (`backend/app/twin/fault_detection.py`), **but has never fired on real data** — see §5 |
| Training data available | Kelmarsh 2016, turbines 1–4, ~191k usable rows, ~6.1k fault-labeled (3.2%) |
| Blocking issues | Feature/label coverage gap and label quality — see §5 |

---

## 2. Target metrics (goals, from handwritten notes — NOT results)

These are the numbers the project is aiming at. None of them has been measured
yet, and the notes do not state what most of them are measured *against* — see
§7 Open questions before treating any of these as a specification.

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
| 0 | Offline harness + baseline scoring | Replay `fault_detection.evaluate` over a fixed split; record precision / recall / F1 / lead time. Produces the number everything else must beat. | Not started |
| 1 | Feature pipeline + train/val/test split | Windowed features per turbine; time-ordered (not random) split so no future data leaks into training. | Not started |
| 2 | Plain GNN (centralized) | Does a graph model beat the statistical baseline at all? | Not started |
| 3 | TA-GNN (centralized) | Does topology adaptivity beat the plain GNN? | Not started |
| 4 | FedAvg over 4 turbine clients | Federated floor. Target ~81%. | Not started |
| 5 | FedProx + adaptive weighting | The headline claim. Target ~94%. | Not started |
| 6 | Localization + restoration-time evaluation | Requires the definitions from §7 before it can start. | Blocked on §7 |

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

_None yet._

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

**5.5 — No vibration channel.** Confirmed: the export has no accelerometer
scalar. `vibration` is `None` everywhere and will stay that way. Any target
metric that assumes vibration features needs restating.

---

## 6. Data provenance

Consistent with the data-sourcing rules in the project instructions file.
**No simulated or derived value is ever to be presented as measured.** Every
model, dataset export and reported metric must carry its provenance class.

| Class | What it is | Nodes | Use in Modules 3/4 |
|---|---|---|---|
| **Real measured (replayed)** | Kelmarsh wind farm SCADA, 6× Senvion MM92, Northamptonshire UK, Cubico Sustainable Investments, CC BY 4.0, [Zenodo 8252025](https://zenodo.org/records/8252025). Genuine 10-minute plant telemetry and a genuine operator event log with real timestamps and messages. Currently 2016 only, turbines 1–4. **Replayed at 2s/row — the replay clock is not real elapsed time.** | `wind_scada_kelmarsh_1..4` | **The only source suitable for supervised training and evaluation.** |
| **Live API-derived (estimated)** | Open-Meteo Forecast API (real current wind speed) and Flood/GloFAS API (real daily river discharge). Real measurements — but **`power_output` is computed** from them via a generic cubic turbine power curve and `P = ρgQHη` with an assumed 30 m head. Not metered, not any real plant's spec. | `wind_01`, `hydro_01` | Usable for forecasting inputs. **Not usable as fault-prediction ground truth** — these nodes carry no temperature, no vibration and no fault labels, and always evaluate `normal`. |
| **Simulated / illustrative** | Twin topology (`bus_a`/`bus_b`), bus capacities, per-source `rated_capacity_kw`, the 50% curtailment fraction, and the self-healing scoring weights. Demo figures chosen so rerouting is a non-trivial tradeoff — not a load-flow study. | `bus_a`, `bus_b`, `grid` | Fine as graph structure for the GNN. **Any restoration-time or resilience metric computed on this topology is a simulation result and must be labeled as such.** |
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
