# Architecture — Module 1, 2 & 3 (current scope; Module 3 added at the end)

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
  { "model": {loaded, name, task, horizon_min, operating_threshold_probability, data_provenance, ...},
    "predictions": [ {node_id, scored, health_status, flagged_by: ["rule_based"|"ta_gnn"...],
                      detectors: {rule_based: {status, flagged, basis},
                                  ta_gnn: {flagged, probability, model, horizon_min, as_of, data}},
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

## Module status map
- Module 1 — ingestion (live Open-Meteo wind/hydro + Kelmarsh SCADA replay): done
- Module 2 — digital twin, self-healing, decision log, Digital Twin tab: done
- Module 3 — TA-GNN fault prediction (backend/ai, backend/app/ai_service, Digital Twin tab badges): built; see aiprogress.md for measured results
- Module 4 — federated learning (Flower, FedProx + adaptive weighting): not started
- Module 5 — blockchain: not started

## Out of scope (still)
- Solar/EV hardware, MQTT, ESP32 firmware
- Federated learning, blockchain
- Human-approval gate / real actuation on the self-healing layer
(Topology switching now exists via the Module 2 self-healing layer; the original "static topology" note above is historical.)