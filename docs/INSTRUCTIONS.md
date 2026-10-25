# Smart Energy Internet — Project Memory

## What this is
AI/IoT/blockchain smart grid platform. 5 modules — see docs/architecture.md 
for full module breakdowns and data schemas. This file is the source of 
truth for stack and working conventions; keep it short.

## Stack — LOCKED, do not suggest alternatives
- Firmware: Arduino/C++ on ESP32
- Messaging: MQTT via Mosquitto
- Storage: TimescaleDB
- Backend: Python + FastAPI
- Twin graph logic: NetworkX
- Power-flow simulation: pandapower
- GNN: PyTorch + PyTorch Geometric
- Federated learning: Flower (FedProx-style aggregation, adaptive weighting)
- Blockchain: Solidity + Hardhat + Ethers.js/Web3.py, deployed to Sepolia testnet
- Frontend: React + React Flow + Tailwind CSS + WebSockets

If you think a different tool would genuinely be better, ask me first — 
don't just switch or introduce a new dependency.

## Current focus
Modules 1 (ingestion) and 2 (digital twin) are done. Module 3 (TA-GNN fault
prediction) is built — code in backend/ai + backend/app/ai_service, results
and experiment log in aiprogress.md. Module 3 now trains/evaluates on 2016–2022 with split `exp013`
(test 2021–2022); Module 4 is partly re-run on it (aiprogress.md EXP-016). Module 4 (adaptive federated learning,
Flower: FedAvg / FedProx / FedProx + adaptive weighting) is built and evaluated —
code, artifacts and run instructions in backend/ai/federated (own venv there:
Flower's pins conflict with backend/venv), measured results in aiprogress.md.
Module 5 (blockchain ledger) is built: Solidity EnergyLedger + Hardhat in blockchain/
(local Hardhat node by default, Sepolia config ready but not exercised), Web3.py service in
backend/app/blockchain, Blockchain tab in the frontend. It records self-healing redistributions,
fault alerts, SIMULATED P2P trades and Module 4 federated rounds (replayed from round_log.json).
Run instructions, measured results and limitations: PROGRESS.md "Module 5".
Admin authentication is built (ARCHITECTURE.md "Admin authentication"). The whole dashboard, every
REST route except /health + /auth/{login,register,refresh,logout}, and the /ws/updates WebSocket
require an admin session. New routers MUST be included with `dependencies=protected` in
app/main.py; tests/test_auth.py pins the protected-route list and fails if a route is added unprotected.
A live PROSUMER MARKET is built (4 simulated buildings on a `community_bus`: solar estimated from live weather, load synthetic;
automatic surplus->deficit trading; registration + every exchange step on the EnergyMarket contract, settled trades mirrored to
the ledger as P2P_TRADE): PROGRESS.md "Prosumer market (live)", ARCHITECTURE.md "Prosumer market (live)".
The frontend UI was redesigned (presentation layer only): sidebar shell, design tokens and the view map
are in ARCHITECTURE.md "Frontend structure (UI redesign)"; what is mocked is in PROGRESS.md "UI redesign".

Live protection on the 9-node twin (bus overload -> reroute over tie switches, faulty node -> isolated until repaired, faulty line -> open both ends + close a tie, all timed and shown live in the
Self-Healing tab with a fault simulator): `backend/app/twin/grid_protection.py`, PROGRESS.md / ARCHITECTURE.md "Live protection". Faulty nodes are now always isolated (not rerouted) by `self_healing`.

A real hardware node `solar_hardware` (ESP32 + INA219 mini panel, USB serial JSON lines) exists: firmware/solar_hardware, ARCHITECTURE.md "solar_hardware node".

## Auth quick reference
- Needs `JWT_SECRET` (>= 32 chars) in the repo-root .env, or the backend will not start (see .env.example).
- First admin (once): `cd backend && venv\Scripts\python scripts\create_admin.py` (prompts; or set
  SEI_ADMIN_EMAIL / SEI_ADMIN_PASSWORD). Refuses if an admin exists unless `--force`. Further admins:
  dashboard -> "Invite admin" -> send the one-time link.
- Backend tests: `cd backend && venv\Scripts\python -m pytest tests -q` (needs TimescaleDB running;
  uses its own `sei_auth_test` database, created automatically).
- Prosumer logins (one per simulated building; role `prosumer`, page `/prosumer`, API `/p2p/*` via `require_prosumer`): an admin invites from
  Settings -> Admins ("Invite as" a building), or seed with `cd backend && venv\Scripts\python scripts\create_prosumers.py [--all|--node ..|--reset]`
  (random passwords printed once, never stored). See PROGRESS.md / ARCHITECTURE.md "Prosumer login + P2P dashboard". New /p2p routes are pinned in tests/test_auth.py.
- Auth libraries: argon2-cffi (password hashing) and PyJWT (access tokens), plus pytest for tests.
  The frontend has no new dependency.

## Data sourcing (important — don't get this wrong)
- Solar + EV: real sensor data via ESP32 (INA219/ACS712) → MQTT → TimescaleDB
- Wind/hydro: LIVE data (power output, wind speed) comes from an external 
  API — not physically instrumented
- Fault-prediction training uses a separate public SCADA dataset (Kaggle/
  EDP-style, with vibration/temperature/labeled faults) — replayed, not live
- Never conflate these three sources or present simulated/API data as 
  physically sensed without saying so in code comments

## Git / GitHub
- Do NOT run any git commands (no add, commit, push, branch, etc.) and do 
  not touch GitHub in any way. I manage version control manually myself.
- You can still read git history/diffs read-only if it helps you understand 
  context, but never write or stage anything.

## Working style
- Keep changes scoped to what I ask — don't refactor unrelated files
- Flag any deviation from the locked stack before making it
- When a design decision isn't obvious, ask rather than assume
- [add your code style / naming preferences here as you notice them]
- Module 3 conventions: training/evaluation code and model artifacts live only
  in backend/ai/; live serving lives in backend/app/ai_service/. Every model,
  dataset and metric states its data provenance (real replayed SCADA vs
  estimated vs synthetic). Synthetic data (e.g. topology variants) is labelled
  synthetic and kept out of headline metrics. Report measured numbers only,
  never tuned toward the targets. Extra Kelmarsh years live in
  backend/data/scada/extra_years/ (2017-2022; training/eval only; Module 1's replay does
  not read them).
- Frontend conventions (UI redesign): reuse `src/ui/` (theme colours, Card/StatCard/Pill, icons)
  instead of ad-hoc styles; colour = meaning (Solar amber, Wind teal, Hydro blue, Grid slate,
  blockchain violet; green/amber/red only for status). Data no endpoint exposes goes ONLY in
  `src/mocks/uiMocks.js`, tagged MOCK or SNAPSHOT, shown with a "Mock data" tag, and listed in PROGRESS.md.

## Tests (TC01-TC05 and Set-2 TC01-TC10)
Software-only test cases and how to run them: `tests/README.md`; results: PROGRESS.md "Software-only test cases TC01-TC05" and "...second sheet Set-2 TC01-TC10" (Set-2: 9 PASS, TC07 FAIL left unaltered; new unused module app/ingestion/buffered_publisher.py for TC02) (TC01 passes since `app/ingestion/validation.py` was added: live wind/hydro samples outside physical limits (no upper power limit for hydro) are replaced by the last valid value).

## See also
- ARCHITECTURE.md — module details, data schemas, twin state model and why each stack choice was made (avoid re-litigating)
- PROGRESS.MD - to check what's been done so far and keep adding the updates to the file