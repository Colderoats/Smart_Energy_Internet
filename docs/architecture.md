# Architecture — Module 1 & 2 (current scope)

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

## Explicitly out of scope for this phase
- Solar/EV hardware, MQTT, ESP32 firmware
- TA-GNN, federated learning, blockchain
- Real reconfiguration/actuation logic — self-healing decision layer
- Topology changes (switching) — topology is static for now