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

**Normalised values (added).** `ingest_reading` (app/ingestion/pipeline.py) attaches `normalized` to every reading before the twin,
detectors, WebSocket and DB history see it: `power_output` = per-unit of rated capacity, `wind_speed` / 25 m/s, `temperature`
min-max over -20..120 degC, `vibration` / 10, all clipped to [0, 1] (`normalized_values` in app/models/reading.py). Raw fields are
unchanged. `db.fetch_history` adds the same `normalized` dict to history rows. The node-level views (Dashboard stream, node side
panel, Sources cards, node time series, topology nodes) show these normalised values; totals/aggregates remain in kW.

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
- Admin authentication (invite-only admins, cookie JWT + rotating refresh tokens, every REST route and the WebSocket protected): built and tested. See "Admin authentication" below and PROGRESS.md
- UI redesign (presentation layer only: design system, sidebar shell, 7 screens incl. new Federated Learning and Analytics views): built and verified in a browser. See "Frontend structure (UI redesign)" at the end and PROGRESS.md

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
- 2FA/TOTP for admin login (the table and login flow are ready for it; see "Admin authentication")

## Admin authentication (added 2026-09-28)

Only registered admins can use the platform. There is no public registration. Unauthenticated visitors
see only `/login`, plus `/register` when they have a valid invite token. Code: `backend/app/auth/`
(passwords, tokens, store, rate limiting, dependencies), `backend/app/api/auth_routes.py`,
`backend/scripts/create_admin.py`, and `frontend/src/auth/` + `frontend/src/pages/`.

**Bootstrap and invites.** The first admin is created with `backend/scripts/create_admin.py`, which
refuses to run if an admin already exists unless `--force` is passed. After that, an admin creates a
single-use invite on the "Invite admin" page. It expires after `INVITE_TTL_HOURS` (48 by default). The
raw token is shown once, and only its SHA-256 hash is stored. `POST /auth/register` checks the
invite (it exists, is unused and has not expired), creates the user and marks the invite used, all in
one transaction with the invite row locked `FOR UPDATE`.

**Tables** (same migration approach as the rest of the backend: idempotent `CREATE ... IF NOT EXISTS`
in `app/auth/store.py`, run at startup):
- `users(id, email UNIQUE + CHECK lowercase, password_hash, role DEFAULT 'admin', is_active,
  failed_login_count, locked_until, created_at, last_login_at, mfa_enabled DEFAULT false, mfa_secret NULL)`
- `invites(id, token_hash UNIQUE, created_by -> users, created_at, expires_at, used_at, used_by -> users)`
- `auth_audit_log(id, event_type, user_id NULL, email_attempted, ip, user_agent, created_at)`. Events:
  `login_success`, `login_failure`, `login_failure_locked`, `account_locked`, `logout`, `invite_created`,
  `invite_used`, `register_failure_invite`, `register_failure_email_taken`, `refresh_token_reuse`,
  `admin_created_cli`, `admin_password_reset_cli`.
- `refresh_tokens(id, user_id -> users, token_hash UNIQUE, family_id, created_at, expires_at, revoked_at,
  replaced_by)`. This table is extra to the spec; it is needed so refresh tokens can be rotated and revoked.

**Endpoints**

| Method | Path | Access | Purpose |
|---|---|---|---|
| POST | /auth/login | public, rate-limited | email + password -> session cookies. Always returns the generic "Invalid credentials" on failure |
| POST | /auth/refresh | public (refresh cookie), rate-limited | rotates the refresh token and issues a new access token |
| POST | /auth/logout | public | revokes the refresh-token family and clears cookies. Works with an expired access token |
| POST | /auth/register | public (invite token), rate-limited | creates an admin from an invite |
| GET | /auth/me | admin | current user |
| POST | /auth/invites | admin | creates an invite and returns the raw token + link **once** |
| GET | /auth/invites | admin | lists invites (status pending/used/expired). Never returns tokens or hashes |

**Tokens and cookies.** The access token is an HS256 JWT (`sub`, `email`, `role`, `type=access`, `iat`,
`exp`, `jti`) that lives `ACCESS_TOKEN_MINUTES` (15). The refresh token is an opaque 256-bit random value
that lives `REFRESH_TOKEN_DAYS` (7) and is stored hashed. Every refresh rotates it. If a rotated token is
presented again more than 10 s later, that is treated as reuse and the whole token family is revoked.
Within 10 s it is treated as a benign race between two tabs. Both tokens travel only as `HttpOnly`,
`SameSite=Strict` cookies: `sei_access` on path `/` and `sei_refresh` on path `/auth`. They are `Secure`
unless `COOKIE_SECURE=false` (local http dev only). The frontend never stores tokens in
localStorage or sessionStorage. On each request, `require_admin` also reloads the user from the DB, so a
deactivated account is locked out immediately.

**CSRF: SameSite=Strict + Origin check.** Every POST/PUT/PATCH/DELETE must carry an `Origin` (or, failing
that, a `Referer`) equal to `FRONTEND_ORIGIN`; otherwise it gets 403 (`origin_check_middleware` in
`app/auth/deps.py`). No CSRF token is used. CORS allows only `FRONTEND_ORIGIN`, with credentials, and
has no wildcard.

**Login hardening.** Passwords are hashed with argon2id (argon2-cffi). The policy is at least 12 and at
most 128 characters, not a common word or a common word padded with digits/symbols, and not a
sequential-digit or ≤3-distinct-character string. It is mirrored client-side in
`frontend/src/auth/passwordPolicy.js`, and a test keeps the two copies identical. An unknown email is
still verified against a dummy hash, so it takes the same time as a wrong password. After 5 consecutive
failures (`LOCKOUT_THRESHOLD`) the account is locked for 15 min (`LOCKOUT_MINUTES`). A locked account
returns the same generic error. There are per-IP sliding-window limits: login 10/60 s, register 5/60 s,
refresh 30/60 s. They are kept in memory (one uvicorn worker). `X-Forwarded-For` is trusted only from
`TRUSTED_PROXIES` (the Vite dev proxy, which sets `xfwd`).

**Server-side enforcement.** `require_admin` (`app/auth/deps.py`) is attached as a router-level
dependency in `app/main.py`. The WebSocket authenticates itself on connect. Protected (verified by
`tests/test_auth.py::test_every_non_public_route_requires_auth`, which pins this exact list):
- `GET /nodes`, `GET /nodes/{node_id}/history`
- `GET /twin/nodes`, `GET /twin/nodes/{node_id}/history`, `GET /twin/decisions`
- `GET /ai/predictions`
- `GET /chain/status`, `GET /chain/records`, `GET /chain/records/{record_id}`, `POST /chain/verify/{record_id}`,
  `POST /chain/simulate-trade`, `POST /chain/replay-fl-rounds`, `POST /chain/dev/tamper/{record_id}`
- `GET /market/status`, `GET /market/prosumers`, `GET /market/prosumers/{node_id}/series`,
  `GET /market/intervals`, `GET /market/intervals/{interval_id}`, `GET /market/trades` (prosumer market, read-only)
- `GET /auth/me`, `POST /auth/invites`, `GET /auth/invites`
- `WS /ws/updates`. It checks the Origin and access cookie on connect. It accepts and then immediately
  closes with **4403** (foreign origin) or **4401** (missing, invalid or expired token). An authenticated
  socket is closed with 4401 when its access token expires. The frontend then refreshes once and
  reconnects.

Public: `GET /health`, `POST /auth/login`, `POST /auth/register`, `POST /auth/refresh`,
`POST /auth/logout`. FastAPI's `/docs`, `/redoc` and `/openapi.json` are disabled unless
`API_DOCS_ENABLED=true`.

**Configuration** (repo-root `.env`, documented in `.env.example`): `JWT_SECRET` is required, at least 32
characters, and the backend refuses to start without it. Also `FRONTEND_ORIGIN`, `COOKIE_SECURE`,
`COOKIE_DOMAIN`, `ACCESS_TOKEN_MINUTES`, `REFRESH_TOKEN_DAYS`, `INVITE_TTL_HOURS`, `LOCKOUT_*`, `*_RATE_LIMIT`,
`TRUSTED_PROXIES`, `API_DOCS_ENABLED`.

**Frontend.** `AuthProvider` checks `/auth/me` on load. The route guard sends every `/dashboard/*` view
to `/login?next=<path>` and returns the user there after login (`next` is limited to `/dashboard*`, so it
cannot be used as an open redirect). Views live at `/dashboard/<view>` (since the UI redesign:
`home|map|sources|chain|ai|analytics|settings`; the older `live|twin|invite` URLs redirect). They must not
share the `/twin`, `/chain`, `/nodes` or `/ai` prefixes, which the Vite proxy forwards to the backend. Routing
uses a small history-API helper (`src/auth/router.js`), so no router dependency was added. All API calls
go through `apiFetch`. On a 401 it makes one deduplicated silent refresh and then retries. If that
fails, the user is sent to `/login`. WebSockets open only inside the authenticated dashboard, through
`openAuthedSocket`. The header shows the admin's email and a Log out button.

**Future TOTP (out of scope now).** `users.mfa_enabled` / `mfa_secret` already exist. `POST /auth/login`
branches on `mfa_enabled` after the password check and before `_issue_session()`. A TOTP step slots in
there: it issues a short-lived `mfa_pending` token instead of a session, and a new `POST /auth/login/totp`
verifies the code and calls `_issue_session()`. The cookie, refresh and guard code does not change.

## Frontend structure (UI redesign, added 2026-09-28)

Presentation layer only. It reads the same hooks and endpoints as before and adds no backend
contract. Code is in `frontend/src/`.

**Shell.** `ui/AppShell.jsx`: a dark navy sidebar (order fixed in `ui/nav.js`), a light content area
and a top bar (page title, live indicator, admin avatar). The live indicator shows the mounted
page's own socket via `useReportConnection(connected)`. The shell opens no socket and never polls.
Only one view is mounted at a time.

**Design tokens** (`ui/theme.js`). Colour means the same thing on every screen: Solar amber, Wind
teal, Hydro blue, Grid/Storage slate, blockchain violet, one indigo UI accent. Green, amber and red are
used only for status. Primitives are in `ui/components.jsx` and icons are inline SVG in `ui/icons.jsx`
(no icon dependency).

| View (route) | Component | Data source (existing) |
|---|---|---|
| Dashboard (`home`) | `tabs/DashboardTab` | `useDigitalTwinSocket` (twin nodes + decisions) |
| Grid Map (`map`) Topology: Live View / Digital Twin | `tabs/GridMapTab` -> `LiveDataTab` / `DigitalTwinTab` | `useTwinSocket` / `useDigitalTwinSocket` (still separate) |
| Grid Map (`map?tab=fl`) Federated Learning | `components/FederatedPanel` | `useBlockchainSocket('FL_ROUND')`, fallback snapshot |
| Sources (`sources`) | `tabs/SourcesTab` | `useDigitalTwinSocket` + `GET /twin/nodes/{id}/history` |
| Redistribution (`chain`) | `tabs/RedistributionTab` (+ existing `BlockchainTab` as the ledger explorer) | `useBlockchainSocket` (all, and `P2P_TRADE`), `useDigitalTwinSocket` decisions |
| AI Insights (`ai`) | `tabs/AIInsightsTab` | twin node `detectors` + `GET /ai/predictions` model card |
| Analytics (`analytics`) | `tabs/AnalyticsTab` | twin nodes/decisions, `P2P_TRADE` records, snapshots, mocks |
| Settings (`settings`) | `tabs/SettingsTab` (+ existing `InviteAdminPage` as "Admins") | `useAuth` user, `/health`, `/chain/status`, `/ai/predictions` |

**Topology rendering.** Nodes are compact icon cards whose colour shows status. The Live/Replayed
badge stays always visible (data-sourcing rule). `components/FlowEdge.jsx` sets stroke width from the
power on the line (source output x load share; bus -> grid = bus load) and animates a dot in the
direction of flow. Twin edges are still derived live from each node's `active_connection` /
`isolated`.

**Topology changes on chain.** A twin decision is joined to its `ENERGY_REDISTRIBUTION` ledger record
by `payload.twin_decision_id` (`<node_id>@<decision time>`, the same key as Module 5), which gives the
block number. The block strip shows only `deployment_current` records, so blocks from a restarted
local chain do not mix in.

**Mocks.** Any value no endpoint exposes lives in `src/mocks/uiMocks.js`, tagged MOCK (invented
placeholder) or SNAPSHOT (measured numbers copied from a repo artifact). The UI marks MOCK values with
a "Mock data" tag. The current list is in PROGRESS.md "UI redesign". Replace a mock by wiring the
real source in the view and deleting the export.

Vite proxy: `/ai` was added (for `GET /ai/predictions`) next to `/nodes`, `/twin`, `/chain`, `/auth`,
`/health` and `/ws`.


## Testbed + paper reproduction (additive; nothing above changes)

Added to make the implementation do what the conference and journal papers describe and to reproduce their experiments from real runs.
**Everything here is `provenance: "simulated_testbed"`** and is kept apart from the real Kelmarsh results (Module 3/4 artifacts are only read, never written).
Settings are fixed in `backend/testbed/PREREGISTRATION.md` before the first measured run; paper numbers live only in `experiments/paper_targets.json` (generated by
`experiments/build_targets.py`) and are shown next to measured values as "Paper target" - no simulator, trainer or evaluator reads them.

| Part | Where | Notes |
|---|---|---|
| Topologies A (radial, 6/5), B (meshed, 14/20), C (IEEE 33-bus + 5 ties = 37 lines) | `backend/testbed/topologies.py` | pandapower networks; node kinds only solar / wind / hydro / load bus / collector / grid (+ storage component); A(t) from switch states, A_hat (journal Eq. 10) in `a_hat` |
| Power flow incl. islanded sections | `backend/testbed/powerflow.py` | anti-islanding unless an action enables islanding |
| Journal simulator (24 h @ 5 s = 17,280 samples, 4 fault types x 5, 3 iterations) | `backend/testbed/journal_sim.py` | datasets under `backend/testbed/data/` with a manifest (counts, seeds, config hash) |
| Conference testbed (12-node ring + chords, 365 d @ 15 min = 420,480 samples) | `backend/testbed/conference.py` | experiment config only |
| Twin evaluation | `backend/testbed/twin_eval/` | journal: Omega, cost J (Eq. 7), default scheme vs twin, T_rec (Eq. 22); conference: Eqs. 1-6 |
| Models | `backend/ai/testbed_models/` | joint TA-GNN (Eqs. 11-14, torch-only core), GCN baseline, conference forecasting models |
| Federated learning | `backend/ai/federated/weighting_paper.py`, `strategies_testbed.py`, `client_testbed.py`, `server_testbed.py`, `run_testbed.py` | new strategies `fedprox_journal_adaptive` (Eq. 16) and `fedprox_conf_adaptive` (Eqs. 11-12); allow-list gained `n_k`, `v_k`; existing strategies untouched |
| Trading contract | `blockchain/contracts/EnergyMarket.sol` (+ test, `scripts/deploy_market.js`) | register / offer / bid / match / oracle-only metering / settle `Pay = p * min(q_s, q_b)` / expiry; EnergyLedger untouched |
| Redistribution | `backend/testbed/market/` | topology-aware matching with pandapower feasibility check; on-chain settlement through web3 |
| Runner | `experiments/run_all.py` | one named config per paper table; results in `experiments/results/<run_id>/metrics.json` |
| API | `backend/app/api/testbed_routes.py` (prefix `/testbed`, `dependencies=protected`) | read-only |
| Views | `frontend/src/tabs/{TopologiesTab,GraphsTab}.jsx`, `src/testbed/` | `/dashboard/topologies`, `/dashboard/graphs` (the Results tab was removed); proxy prefix `/testbed` |

**Environments.** `backend/testbed/venv` (Python 3.14.6; torch 2.14.0, torch_geometric 2.8.0.post1, pandapower 3.5.6, scikit-learn, web3 8.0.0) is separate from `backend/venv`
(pandapower would upgrade its networkx/numpy pins) and from `backend/ai/federated/venv` (Flower). The FastAPI app does not import pandapower; it only reads result files.

**Protected routes added** (all `GET`, listed in `tests/test_auth.py`): `/testbed/status`, `/testbed/results`, `/testbed/runs/{run_id}`, `/testbed/comparison`, `/testbed/kelmarsh`,
`/testbed/topologies`, `/testbed/topologies/{name}/redistribution`, `/testbed/topologies/{name}/faults`, `/testbed/topologies/{name}/faults/{scenario_id}`, `/testbed/graphs`.

**Reproduce.** `backend\testbed\venv\Scripts\python experiments\run_all.py list` shows the configs; `docs/paper_gap_analysis.md` lists conflicts between the papers and how each is resolved;
`experiments/results/comparison.md` lists every paper number against the measured one.


## Prosumer market (live) - added 2026-10-20 (additive)

Four SIMULATED buildings (prosumers) on a new `community_bus` trade surplus solar for demo credits every
`MARKET_INTERVAL_SECONDS`. Their registration and every exchange step are transactions on the `EnergyMarket`
contract, and each settled trade is mirrored into `EnergyLedger` as a `P2P_TRADE` record. Module 1's `twin` graph,
`bus_a` / `bus_b`, their 6 sources, Module 3/4 code and both contracts are unchanged.

**Provenance (part of the spec).** Solar = REAL Open-Meteo shortwave irradiance (GHI) + air temperature at
`PROSUMER_LAT/LON` (default Chennai), PV output ESTIMATED: `kW = kWp * GHI/1000 * 0.80 * (1 - 0.004 * max(0, Tcell - 25))`,
`Tcell = Tair + 0.03 * GHI` -> reading provenance `live_api_estimated`. Load = deterministic SYNTHETIC hourly profile per
building type (local time via `PROSUMER_UTC_OFFSET_HOURS`, weekday/weekend, linear per minute, +-5 % noise seeded by node and
minute) -> `simulated`. `PROSUMER_IRRADIANCE_OVERRIDE` (W/m2, dev only) makes the irradiance itself made up: solar provenance
becomes `simulated` and the UI shows "Demo irradiance". "Metered" quantities are computed from those readings (no meter).
Sensor seam (not built): an ESP32 (INA219/ACS712) -> MQTT -> TimescaleDB source would emit the same `NormalizedReading`
(`type="prosumer"`, `provenance="sensed"`) in place of `ingestion/prosumer_source.build_reading`; nothing downstream changes.

**Nodes** (in `digital_twin`, not in Module 1's graph; only the live singleton `DigitalTwin(with_market=True)` has them, a fresh
`DigitalTwin()` - AI training's `default_topology`, the parity check - stays the original 9 nodes / 8 edges):

| node_id | profile | PV kWp | load |
|---|---|---|---|
| prosumer_home_01 | house | 5 | residential, 0.4-3 kW |
| prosumer_apartment_01 | apartment block | 15 | residential, evening-heavy, 3-12 kW |
| prosumer_shop_01 | small shop | 10 | commercial, 9-21 h plateau, 2-8 kW |
| prosumer_school_01 | school | 30 | weekdays 8-16 h, 2-20 kW |
| community_bus (type `bus`, `community: true`) | - | - | capacity `COMMUNITY_BUS_CAPACITY_KW` (100), edge to `grid`; load = sum of abs(net_kw) (kW arithmetic, no power flow) |

Prosumer node fields: `type "prosumer"`, `generation_kw`, `consumption_kw`, `net_kw = gen - cons`, `role`
(`surplus | deficit | balanced`, deadband `PROSUMER_ROLE_DEADBAND_KW` = 0.1), `pv_kwp`, `profile`, `provenance`,
`provenance_detail`, `onchain` (`address`, registration `tx_hash`, `block_number`, `gas_used`, `status`).

**Data flow**
```
Open-Meteo (real GHI, temp) --poll 60 s--+
                                         v
 ingestion/prosumer_source  (tick PROSUMER_TICK_SECONDS: PV estimate + synthetic load -> NormalizedReading type="prosumer")
                                         v
 pipeline.ingest_reading -> _ingest_prosumer: normalize -> digital_twin.update_prosumer -> persist (readings) -> WS broadcast
        (NO fault detection, NO TA-GNN, NO self-healing; Module 1 graph untouched)
                                         v   market.observe(net_kw)
 market.MarketService clock  (every MARKET_INTERVAL_SECONDS, off-chain only, never waits on the chain)
   start: forecast = mean of the latest net_kw; surplus prosumers OFFER (qty = forecast kW x interval h, ask),
          deficit prosumers BID (qty = forecast deficit, max); engine.match_orders -> orders + matches in TimescaleDB;
          job "post"
   end:   METERED Wh = energy actually delivered, from the interval's readings (engine.allocate_metering); job "settle"
                                         v   asyncio queue
 chain worker (ONE task, sequential txs, retries with backoff, resumes per step; chain down => jobs wait, ingestion unaffected)
   post:   register (idempotent) -> postOffer / postBid (sender = the prosumer's own account) -> matchTrade (gateway)
   settle: submitMeter (gateway/oracle) -> settle -> mirror into EnergyLedger as P2P_TRADE -> advanceInterval
                                         v
 WS /ws/updates: market_* messages;  ledger worker: chain_record messages
```
Matching rule: offers sorted ascending by ask, bids descending by max; while `ask <= max`: `qty = min(remaining offer,
remaining bid)`, **price = the seller's ask** (the contract's rule). Unmatched deficit = "served by grid", unmatched surplus =
"exported to grid" (shown in the UI, not on-chain). Pay = `price * min(q_s, q_b)` with the METERED quantities, exactly as
`EnergyMarket.settle`. Units: Wh and milli-credits per kWh (demo credits; a rupee sign is only ever shown next to "demo credits").
Prices: `MARKET_PRICES` (JSON) / defaults in `app/config.py` (ask 5.0-6.0, max 7.0-8.0 per kWh, illustrative, not tariffs).

**Contract mapping** (EnergyMarket.sol, unchanged). `register(bytes32 nodeId)` is called by the prosumer itself, so each prosumer
has its own Hardhat dev account (#1..#4, public dev keys, local only; the market refuses to run on any other network);
account #0 (the backend's configured local key) is owner AND gateway/oracle for `matchTrade`, `submitMeter`, `advanceInterval`
(and sends `settle`). Every function the plan needs exists; nothing is faked. `expireOffer/expireBid` are not used (unmatched
quantity is simply not traded). Account #0 is shared with the ledger client, so both take `address_lock(address)`
(`app/blockchain/chain_client.py`) to avoid nonce races.
Deployment: `blockchain/deployments/localhost-market.json`, written by the backend's auto-deploy when the file is absent, the node
was restarted (no code / deployed in a block of another chain) or the contract's gateway is not account #0.
`scripts/deploy_market.js` is unchanged (writes `market.<network>.json`; its default gateway is the 2nd signer, set `MARKET_GATEWAY`).

**Schema additions.** `readings`: `ALTER TABLE ... ADD COLUMN IF NOT EXISTS consumption_kw, net_kw, irradiance_wm2 (DOUBLE),
provenance (TEXT)` (idempotent, `db.py`; NULL for wind/hydro). `NormalizedReading`: optional `consumption_kw`, `net_kw`,
`irradiance_wm2`, `provenance`; `type` gains `"prosumer"`, `source_type` gains `"simulated"`. New tables (`app/market/store.py`,
created at startup): `market_prosumers` (node_id, deployment_key, address, status, tx_hash, block_number, gas_used, events),
`market_intervals` (chain_interval, deployment_key, started/ends_at, status `open|closing|settled|skipped|failed`, forecast,
actuals, summary, solar_provenance, irradiance, advance tx/block/gas), `market_orders` (side offer|bid, node_id, qty_wh,
price_milli, remaining_wh, status `planned|pending|in_block|confirmed|failed`, chain_order_id, tx_hash, block_number, gas_used,
events), `market_trades` (seller, buyer, matched_wh, price_milli, status `matched_planned|matched|metered|settled|failed`,
chain_trade_id, match/meter/settle `tx_hash` + `block` + `gas`, meter_seller_wh/meter_buyer_wh, settled_wh, pay_milli,
ledger_record_id, events = the decoded contract events). TimescaleDB down: the interval is skipped and logged (like the ledger);
chain down: jobs wait (backlog capped at 3 intervals, then intervals are recorded as `skipped`); after a backend restart `closing`
intervals are re-settled and `open` ones abandoned.

**Ledger mirror.** Each settled trade becomes `P2P_TRADE` (`events.live_market_trade`): payload has `trade_source: "live_market"`,
seller, buyer, `kwh`, `price_per_kwh`, `pay`, `interval_id`, provenance + `provenance_detail`, and the EnergyMarket match/meter/settle
tx hashes, blocks and gas; dedupe key `live_market:<deployment_key>:<trade id>`. Verify, the integrity check and the tamper demo
work on it unchanged. `POST /chain/simulate-trade` records now carry `trade_source: "simulated_button"`.

**Routes** (all GET, protected, pinned in tests/test_auth.py): `/market/status`, `/market/prosumers`,
`/market/prosumers/{node_id}/series` (24 h, 5-minute averages), `/market/intervals?limit=`, `/market/intervals/{id}` (orders,
matches, settlements, tx hashes), `/market/trades?limit=`. `GET /twin/nodes` now also returns the 5 new nodes and their edges.
**WebSocket** (`/ws/updates`): `market_prosumer_update`, `market_registration`, `market_order`, `market_match`,
`market_settlement`, `market_interval`; each carries tx hash / block / status as it moves pending -> in_block -> confirmed.
**Isolation.** `predictor.score` filters nodes/edges to the original 9-node `NODE_ORDER` before building `edge_index`
(parity check max logit difference 4.77e-07, unchanged); `self_healing.maybe_trigger` returns immediately for prosumers and
`community_bus` ("prosumer self-healing: future work"). Frontend: Dashboard, Sources, AI Insights and Analytics ignore `type
"prosumer"`; Digital Twin map (`TwinNode`, `FlowEdge.TradeEdge`, `ProsumerPanel`, `MarketStrip`), Redistribution summary +
Blockchain "Prosumer market" section (`components/ProsumerMarket.jsx`, `hooks/useMarketSocket.js`); Vite proxies `/market`.


## Prosumer login + P2P dashboard - added 2026-10-23 (additive)

**Identity.** `users.role` gains `prosumer`; `users.prosumer_node_id` (nullable, FK to `prosumer_nodes(node_id)`, unique when set) links the user to
exactly one of the 4 market prosumers. `invites.role` / `invites.prosumer_node_id` carry the choice an admin makes on the Invite page
(`POST /auth/invites {prosumer_node_id?}`); `register_with_invite` copies them onto the new user in the same transaction. `deps.require_prosumer`
= valid session + role `prosumer` + a node (else 401 / 403); `require_admin` is unchanged, so a prosumer can never reach an admin route, and
`require_prosumer` rejects admins, so no prosumer API answers an admin. `GET /auth/me` uses `require_session` (any active user).

**Router `/p2p`** (`app/api/p2p_routes.py`, included with `dependencies=[Depends(require_prosumer)]`). The node always comes from the user row; an
optional `node_id` for another node is 403. Routes: `GET /me`, `GET /book`, `GET /trades`, `POST /offer`, `POST /bid`, `POST /auto`. State-changing
calls pass the existing Origin (CSRF) middleware.

**Manual order path.**
```
POST /p2p/offer|bid -> MarketService.place_manual   (role + qty vs forecast, price vs MARKET_PRICES bounds)
   -> market_manual_orders (queued)                  one per node, a newer one cancels the older
interval opens (_open_interval): per node
   queued manual order  -> replaces the node's auto order (qty capped at the forecast, lapses if the role flipped) -> market_orders.manual = true
   else auto_trade on   -> the usual forecast-based order       else auto_trade off -> no order
   -> engine.match_orders (price = seller's ask) -> "post" job -> chain worker (the node's own dev account) -> metering -> settle -> P2P_TRADE mirror
```
Nothing about matching, metering, settlement or the contract changed. `market_node_settings(node_id, auto_trade)` holds the switch (cached in
`MarketService.auto_trade`, loaded at start). Price bounds = `[min(ask), max(max)]` over `MARKET_PRICES`. Trade status shown to the prosumer:
`matched_planned -> pending`, `matched | metered -> matched`, `settled -> settled`, `failed -> failed`; `block_number` = settle, else meter, else match block.

**Live updates.** `ConnectionManager.connect(ws, market_only)`: prosumer sockets get only `market_*` messages (including the new
`market_manual_order`); admin sockets get everything as before. `useMarketSocket({ rest: false })` skips the admin-only `/market/*` fetches.
`/prosumer` re-reads `/p2p/*` (debounced) when the socket state changes - no timers other than the 1 s countdown clock.

**Frontend routing** (`App.jsx`): prosumer -> `/prosumer` after login; `/dashboard/*` redirects a prosumer to `/prosumer`; `/prosumer` redirects an admin to
`/dashboard/home`; anonymous -> `/login`. **Seeding**: `scripts/create_prosumers.py` (see PROGRESS.md); passwords are printed once and only hashes are stored.
