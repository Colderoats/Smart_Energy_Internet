# Paper gap analysis: conference + journal vs the SEI implementation

Papers read: `SIE_Conference_Revised_Final.docx` (conference, **C**) and `SEI_Journal_Draft5_Revised.docx` (journal, **J**), from `C:\Users\deepa\subcode\`.
Every paper number is in `experiments/paper_targets.json` (217 entries). Measured values come only from runs on the **simulated testbed** (`provenance: "simulated_testbed"`), never from the real Kelmarsh pipeline, and are compared in `experiments/results/comparison.md`.

Legend: **AD** implemented as described, **DIFF** implemented differently (reason given), **MISS** missing / not reproducible.

## 1. Conflicts between the papers and how they are resolved (defaults)
| # | Conflict | Resolution |
|---|---|---|
| 1 | Three adaptive-weighting rules: J Eq. 16 `alpha_k = n_k exp(-eta v_k)/sum`, C Eqs. 11-12 `rho_k = 1/(1+L_k/Lbar)`, `omega_k ∝ n_k rho_k`, and the existing EMA + update-norm rule | All three coexist. `ai/federated/weighting_paper.py` adds `fedprox_journal_adaptive` and `fedprox_conf_adaptive` as new named strategies; the existing rule and its Kelmarsh runs are untouched. Each paper is reported against its own tables. |
| 2 | Two testbeds: C = 12 nodes (4 solar/4 wind/4 hydro) ring + chords, 365 d @ 15 min, 70/15/15; J = topologies A/B/C, 24 h @ 5 s (17,280 samples), 3 iterations, 80/20 | Both built. The conference testbed is an experiment config (conference Tables II, IV-VIII only). The three journal topologies are the dashboard topologies. |
| 3 | Two TA-GNN configs (C: H=32, 2 layers, K=2; J: H=128, 3 layers, K=2, joint heads) | Each paper's experiments use that paper's configuration. |
| 4 | Contracts and gas: C settle ≈ 53.9k / offer-request ≈ 118k / register ≈ 65.6k on Ganache, Solidity 0.8.24; J Table XI on Hardhat, 0.8.20 | One `EnergyMarket` contract on Hardhat (Solidity 0.8.24, the repo's locked config). Measured against both tables; differences are explained by design (stored fields, events, access checks) and the contract was not reshaped to hit either. |
| 5 | Latency: J 0.85-1.82 s per operation vs ≈ 50 ms on a Hardhat automine chain | Both measured and labelled: automine, and 1 s interval mining (chosen for realism before running). |
| 6 | Unfilled placeholders in J | See section 2. The bracketed value is used and flagged. |
| 7 | J Table X communication volume is ≈ 1.39 MB/round for every method (118.2/85 = 86.2/62 = 58.5/42) and does not name its topology | C_comm computed from the real parameter count and K of each run (Eq. 18, float32); Table X run on all three topologies; the % reduction depends only on rounds. |
| 8 | "Fault F1" means two things: Table VII detection F1 (twin) vs Table X fault F1 (TA-GNN head) | Both computed and kept separately labelled (`detection_f1` vs `fault_head_f1`). |

## 2. Unfilled placeholders in the journal (flagged; bracketed value used as the setting)
1. `Δt is set to [5 s]` -> 5 s.
2. MQTT `level [1]` -> QoS 1 (not exercised by the simulator; ingestion layer is unchanged).
3. `5[n] faults of each type` -> 5 per type (consistent with Table III's "4 types × 5").
4. `a learning rate of [0.0001] from the start` (Option 4's LR; Table IV) -> 0.0001.
5. Table X target: `[the validation loss of the centralised model plus a tolerance of 0.0012]` (Table X quotes 0.0130 = 0.0118 + 0.0012) -> target = measured centralised validation loss + 0.0012; the absolute 0.0130 is also reported.
6. `option [3]` / `options [2] and [4]` in the Table IV discussion are references to rows, not settings.

## 3. Method / setting / experiment classification
### Journal
| Item | Status | Notes |
|---|---|---|
| Time-varying graph G(t), A(t) from switch states, A_hat (Eq. 10) recomputed on every switch change | AD | `testbed/topologies.py:a_hat`, tested. |
| Topologies A/B/C with Table III counts | AD | A: 6/5/2/1; B: 14/20/4/2 (IEEE-14 graph rebuilt as 11 kV microgrid); C: case33bw 33 buses + 5 ties = 37 lines, 6 solar + 3 wind/hydro. |
| Node features gen/cons/V/I/SOC, min-max (Eq. 9) | AD | Per-feature train-set min/max. |
| TA-GNN, one TA layer (Eq. 11), demand head (Eq. 12), fault head (Eq. 13), loss Eq. 14 | AD | Dense batched form equals PyG TAGConv (tested). Fault head = mean-pooled embedding -> 5-class softmax. |
| Training: Adam, batch = N, 80/20 chronological, 25-epoch search (Table IV), 250-epoch LRS (Table V) | AD / DIFF | "Batch equals the number of nodes" read as N snapshots per batch. Dropout unspecified -> none; sequence length L unspecified -> 12. |
| GCN baseline, first-order, same tuning budget | AD | Same 4 (LR, H, M) options for 25 epochs, best then 250 epochs with the scheduler. |
| Digital Twin: Omega = open switches, close tie, island, curtail/shift; J = w1 E_uns + w2 V_viol + w3 N_sw on pandapower; reject infeasible; apply a* | AD | `testbed/twin_eval/journal_twin.py`. Weights (0.6/0.3/0.1) are not given by the paper. |
| Default scheme = threshold protection + fixed rule-based restoration; T_rec (Eq. 22); E_uns | AD | Timing constants (2 s/switch, 1 sample verification) pre-registered. |
| Self-optimisation against forecast Ŷ(t+1) | DIFF | Implemented as storage rescheduling in the redistribution layer; no separate paper table. |
| Adaptive FL Eq. 16, FedProx Eq. 15, C_comm Eq. 18, K = one client per node | AD / DIFF | A local epoch is a random 10 % pass (compute reason). Client k's loss uses its own node's demand + fault CE. |
| mu / eta / E grid and rounds to target | AD | Run on iteration 0, selection by validation only. |
| Trading contract: register, offer, bid, match (sorted by price), settle Eq. 19, oracle-only metering, expiry, events | AD | New `EnergyMarket.sol`; price sorting is done by the gateway off-chain (contract enforces compatibility). |
| ONNX export of the model (Sec 5.1.2) | MISS | `onnx` dependency not approved (locked stack). |
| ESP32 / MQTT / Mosquitto / Table II software versions | DIFF | Real hardware path exists in the live pipeline; the testbed is a simulator. Versions used are recorded, not Table II's. |
| Hardware CPU (i7-1355U) | n/a | This machine's CPU is used. |

### Conference
| Item | Status | Notes |
|---|---|---|
| 12-node ring testbed, 365 d @ 15 min, 420,480 samples, 70/15/15 | AD | Nameplate (50 kW), pickup fraction (50 %), voltage twin error (1 %) are not in the paper: pre-registered. |
| Twin Eqs. 1-4, tau sweep (0.30-0.90, FAR ≤ 1 %), 5 datasets, 5-fold blocked CV by season / load band | AD | Window w and beta/gamma loss unspecified -> w=4 samples, balanced logistic regression. |
| Compensating-node selection Eq. 5 + fallbacks (split, storage, shed, alert), flow update Eq. 6 | AD | Conference nodes have no storage, so fallback (ii) is empty. |
| Forecasting TA-GNN (8×7 -> 32, 2 TA layers K=2, 2-layer MLP, Adam 3e-3, batch 256, MSE, 15 epochs, best epoch) and 5 baselines, 3 seeds | AD | LSTM/GRU width 32 (unspecified). |
| FL: 6 clients, 30 rounds, 2 local epochs, mu sweep, IID / Dirichlet 0.5 / 0.1 by season × load regime, Eqs. 10-13 | AD | Client partition = 6 (season × load-half) groups; rounds metric as defined by the paper. |
| Matching Eqs. 14-15 as an option | AD | `rule="conference"` in `market/redistribution.py`. |
| Settlement bench at 5/10/20/50 nodes, 5 rounds × 3 repeats | AD | Hardhat, not Ganache v7 (stack). |

## 3b. Update 2026-10-20: live prosumer P2P trading on the platform
The live platform (not only the simulated testbed) now has prosumer P2P trading: four simulated prosumers (solar estimated from live
Open-Meteo weather, synthetic load) on a community bus register on the `EnergyMarket` contract and, every interval, post
offers/bids, are matched (ask ascending / max descending, price = seller's ask), metered (computed from the interval's readings) and
settled on a local Hardhat chain with `Pay = p * min(q_s, q_b)`; each settled trade is mirrored into the `EnergyLedger`. This closes
the "contract exists but is only exercised by the testbed" gap for the registration/offer/bid/match/meter/settle path. It is still
simulated: no physical meters (the ESP32 -> MQTT sensor path is only a documented seam), demo credits, local chain only, kW
arithmetic instead of power flow, no prosumer self-healing, and the AI excludes prosumers. See PROGRESS.md "Prosumer market (live)".

## 4. Not reproducible by construction
* The papers' absolute loss values (e.g. 0.0128) depend on their data normalisation and noise, which are not published; targets are compared as stated but a mismatch is not evidence of a defect.
* The papers' Table II software versions (Python 3.10.12, PyTorch 2.1.0, PyG 2.4.0, React 18) are not used; the repository's versions are recorded in every `metrics.json`.
