# Description
The Smart Energy Internet is an intelligent smart grid platform integrating module 1: hardware for solar and live data from real sites for hydro and wind. module 2: Self-Healing and self optimizing Digital Twin of microgrid. module 3: Topology Adaptive Graph Neural Networks (TA-GNN). module 4: Adaptive Federated learning (FedProx and adaptive weighting), and module 5: Blockchain for secure, autonomous energy management. ESP32-based IoT nodes deployed across houses, renewable energy plants, and EV charging stations continuously stream voltage, current, and power data through MQTT. A self-optimizing and self-healing Digital Twin mirrors the physical grid in real time, predicts failures, and autonomously reconfigures energy flow to maintain grid stability. Federated TA-GNN learns from distributed energy nodes without transferring raw data, preserving privacy while accurately forecasting demand, detecting faults, and adapting to dynamic grid topology. Ethereum smart contracts securely record peer-to-peer energy trading with transparent, tamper-proof settlement. A React-based dashboard provides live monitoring, AI-driven predictions, self-healing actions, topology visualization, and blockchain transaction logs, enabling a resilient and intelligent energy ecosystem.

# Architecture — Modules 1-5 (current scope; Modules 3, 4 and 5 added at the end)

Scope for this phase: NO solar/hardware yet. Two data sources only:
1. LIVE data — wind/hydro power output + wind speed, pulled from external API
2. HISTORICAL data — public SCADA dataset (vibration, temperature, labeled 
   faults) replayed at a fixed interval, used to drive fault detection

Frontend must show both dynamically — live values updating in near-real-time, 
and node states/health visibly changing (color, position on graph, alerts) 
as new data arrives.

## Data flow

External API (live) ──┐
                       ├──> Ingestion service ──> TimescaleDB ──> FastAPI ──> WebSocket ──> React dashboard
SCADA dataset (replay)─┘                              │
                                                        └──> Digital Twin state (NetworkX graph)
                                                                   │  ▲
                                          (Module 3, added)        ▼  │ health_status = max(rule-based, TA-GNN)
                                            AI inference service (TA-GNN, backend/app/ai_service)
                                            — scores replayed SCADA nodes on the twin's CURRENT edges,
                                              runs alongside the rule-based detector; result rides on the
                                              existing twin_node_update WebSocket message.

Offline (Module 3): Kelmarsh CSVs ──> backend/ai (dataset → train/evaluate → artifacts/) ──> saved model
                                       loaded by the inference service above at backend startup.

Offline (Module 4, federated layer):
  Kelmarsh CSVs ──> ai/dataset (Module 3 pipeline) ──> one SHARD per turbine (ai/federated/artifacts/shards/)
       client process T1..T4 (each opens ONLY its own shard, trains the TA-GNN locally)
            │  ▲   ONLY model weights + allow-listed scalar metrics cross this line (wire.py, audited)
            ▼  │
       Flower server (FedAvg | FedProx | FedProx + adaptive weighting) ──> global model
       global model ──> offline test evaluation (identical Module 3 split) ──> ai/federated/artifacts/
       global model ──export (Module 3 artifact format)──> ai/federated/artifacts/model_federated/
                        loaded by the SAME inference service when AI_MODEL_SOURCE=federated.

## Normalized data schema (all sources conform to this before storage)

{
  "node_id": string,          // e.g. "wind_01", "hydro_01"
  "source_type": "live" | "historical",
  "type": "wind" | "hydro",
  "timestamp": ISO8601,
  "power_output": float,      // kW
  "wind_speed": float | null, // live source only
  "vibration": float | null,  // historical/SCADA source only
  "temperature": float | null,// historical/SCADA source only
  "fault_label": string | null // historical source only, ground truth if present
  "scada_channels": {string: float} | null // Module 3 addition; historical source only: extra REAL
                                           // replayed SCADA channels (wind_speed_ms, rotor_speed_rpm,
                                           // generator_rpm, pitch_angle_deg, gen_bearing_front_temp_c,
                                           // gear_oil_temp_c, nacelle_temp_c, nacelle_ambient_temp_c);
                                           // NaN channels omitted. Not the live-API `wind_speed`.
}

## Digital Twin state (NetworkX graph, in-memory in FastAPI backend)

Node attributes: node_id, type, latest reading (per schema above), 
health_status ("normal" | "warning" | "fault_predicted" | "fault"), 
last_updated

Edges: static for now (fixed topology — no switching logic yet, that comes 
with self-healing in a later pass). Just enough structure to place nodes 
on the frontend graph and to give the twin something to eventually 
reconfigure.

## Ingestion

- Live: scheduled poller (interval matches API's update frequency — likely 
  hourly, so simulate finer granularity by interpolating between points if 
  the frontend needs smoother motion — flag this decision, don't just do it)
- Historical: replay script reads the SCADA dataset sequentially and pushes 
  rows into the pipeline at a fixed interval (e.g. one row every N seconds), 
  simulating a live feed for demo purposes — must be clearly labeled as 
  replayed data end-to-end (in code, in API responses, and in the UI)

## Fault detection (basic, for this phase)

Simple threshold/statistical rule on the historical/SCADA stream first 
(e.g. vibration or temperature exceeding a rolling baseline) — NOT the 
TA-GNN yet, that's Module 3. Goal here is just: twin receives data, flags 
a node as "fault_predicted" or "fault", frontend visibly reacts.

## Frontend requirements

- Live-updating graph/topology view (React Flow) — nodes change color/state 
  as health_status changes
- Time-series panel (Recharts) for at least one node showing recent readings
- Clear visual distinction between "live" and "historical/replayed" data 
  sources somewhere in the UI
- WebSocket connection to backend for push updates — no polling from frontend

## API endpoints (initial)

GET  /nodes                  — current state of all nodes
WS   /ws/updates              — push stream of node state changes
GET  /nodes/{id}/history      — recent time-series for one node

Module 2 (added later): GET /twin/nodes, GET /twin/nodes/{id}/history, GET /twin/decisions
(WS messages twin_node_update / twin_decision on the same /ws/updates).

Module 3 (added): GET /ai/predictions — per-node detector verdicts + model card:
  { "model": {loaded, name, source ("centralized"|"federated", Module 4), task, horizon_min, operating_threshold_probability, data_provenance, ...},
    "predictions": [ {node_id, scored, health_status, flagged_by: ["rule_based"|"ta_gnn"...],
                      detectors: {rule_based: {status, flagged, basis},
                                  ta_gnn: {flagged, probability, model, model_source, horizon_min, as_of, data}},
                      last_updated}, ... ] }
  Live API nodes (wind_01, hydro_01) are listed with scored=false — they are never scored.
  The same `detectors` / `flagged_by` fields are on every SCADA node in GET /twin/nodes and in
  twin_node_update WS messages. rule_based.basis is "replayed_ground_truth_label" when the replayed
  status log (not a statistic) set the rule-based fault. TA-GNN output is a FORECAST on REPLAYED data.

## Module 3 — AI layer (TA-GNN fault prediction)

Task: per turbine node, "will a genuine equipment fault START within the next 60 min?", plus node
ranking for localization. Graph = the twin's NetworkX topology (sources → bus_a/bus_b → grid) as an
undirected edge_index taken from the twin's CURRENT edges, so reroute/isolate changes the graph the
model sees with no code change. Only replayed Kelmarsh SCADA nodes are scored; live API nodes and
buses/grid are graph structure only. Training/evaluation code, artifacts and the run instructions are
in backend/ai/ (README-level docstring in backend/ai/__init__.py); serving is backend/app/ai_service/.
`fault_label` is never a model input. The rule-based detector keeps running; the twin's
health_status is the highest severity of the two and each node states which detector flagged it.

Twin node fields added by Module 3: `detectors` (per-detector verdicts) and `flagged_by`.

## Module 4 — federated layer (adaptive federated learning)

Goal: several simulated grid nodes train the Module 3 TA-GNN on their own data; only model updates are
shared. One Flower client PROCESS per Kelmarsh turbine (a client is a partition of the replayed SCADA,
not a separate physical site) plus a Flower server, over localhost gRPC. Code, artifacts and run
instructions are all in backend/ai/federated/ (README-level docstring in its __init__.py). Own
virtualenv (ai/federated/venv): Flower 1.38 pins fastapi/uvicorn/protobuf versions that conflict with
backend/venv, and Ray-based simulation is not installable on Windows + Python 3.14. The backend itself
needs no Flower: the final federated model is exported in Module 3's artifact format.

Client/server boundary. A client's local graph is the twin's 9-node topology with only ITS turbine's
dynamic features filled in (neighbours' raw data is not visible to it); same model, features, labels,
taxonomy, chronological split and normaliser as Module 3. What crosses the boundary:
  client -> server   model weights (exact TA-GNN parameter shapes, float32) + scalar metrics from a fixed
                     allow-list (train/validation loss, PR-AUC, counts). Checked on send AND on receive.
  server -> client   the global weights + round config (mu, epochs, learning rate, seed).
Never crosses: readings, features, labels, windows. The held-out test set and the pooled validation set
are used only by the offline evaluator, never by a client or the server. Not implemented (future work):
differential privacy, secure aggregation, TLS.

Aggregation: FedAvg = equal client weights; FedProx = FedAvg + proximal term (mu/2)||w - w_global||^2 in
the local objective; FedProx + adaptive = per-client weight from an exponential moving average of the
client's normalised validation loss and the server-measured update norm, with a 5% floor (rule in
ai/federated/weighting.py). Per-round, per-client weights and factors are logged (round_log.json,
adaptive_weights_by_round.csv) — the per-node contribution scores a later Module 5 ledger could record.
SIMULATED dropout / degraded client / corrupted updates (ai/federated/simulated.py) are labelled as such
everywhere. Serving: `AI_MODEL_SOURCE=centralized|federated` (default centralized) picks which exported
model the AI service loads; every verdict and the model card state which one produced them.

## Module status map
- Module 1 — ingestion (live Open-Meteo wind/hydro + Kelmarsh SCADA replay): done
- Module 2 — digital twin, self-healing, decision log, Digital Twin tab: done
- Module 3 — TA-GNN fault prediction (backend/ai, backend/app/ai_service, Digital Twin tab badges): built; see aiprogress.md for measured results
- Module 4 — federated learning (Flower, FedProx + adaptive weighting; backend/ai/federated, own venv): built; see aiprogress.md for measured results
- Module 5 — blockchain ledger (Solidity EnergyLedger + Hardhat in blockchain/, Web3.py service in backend/app/blockchain, Blockchain tab): built and verified on a local Hardhat node; Sepolia config ready but not exercised. See PROGRESS.md "Module 5"

## Module 5 — blockchain ledger

Append-only EnergyLedger contract (no update/delete; owner-only append) stores, per record: id, event type
(ENERGY_REDISTRIBUTION | P2P_TRADE | FAULT_ALERT | FL_ROUND), keccak256 of the canonical-JSON payload,
actor/node id, block timestamp. The full payload lives off-chain in TimescaleDB `chain_records`.
Verification = re-hash the stored payload and compare with the on-chain hash.
Flow: self-healing decision (Module 2) -> hook schedules FAULT_ALERT + ENERGY_REDISTRIBUTION -> ledger worker
(async, retries, never blocks ingestion) -> tx -> receipt -> confirmations -> `chain_record` WS message.
P2P trades are SIMULATED (POST /chain/simulate-trade); FL rounds are replayed from the offline Module 4 run.
Every payload carries `provenance` (live_api | replayed_scada | simulated | offline_federated_run).
API: GET /chain/status, GET /chain/records, GET /chain/records/{id}, POST /chain/verify/{id},
POST /chain/simulate-trade, POST /chain/replay-fl-rounds, POST /chain/dev/tamper/{id} (dev only).
WS on /ws/updates: chain_record, chain_status. Network: BLOCKCHAIN_NETWORK=local (default) | sepolia.

## Out of scope (still)
- Solar/EV hardware, MQTT, ESP32 firmware
- Real (non-simulated) P2P energy trading: Module 5 records SIMULATED trades only until hardware exists
- Human-approval gate / real actuation on the self-healing layer
(Topology switching now exists via the Module 2 self-healing layer; the original "static topology" note above is historical.)