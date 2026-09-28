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
and experiment log in aiprogress.md. Module 4 (adaptive federated learning,
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

## Auth quick reference
- Needs `JWT_SECRET` (>= 32 chars) in the repo-root .env, or the backend will not start (see .env.example).
- First admin (once): `cd backend && venv\Scripts\python scripts\create_admin.py` (prompts; or set
  SEI_ADMIN_EMAIL / SEI_ADMIN_PASSWORD). Refuses if an admin exists unless `--force`. Further admins:
  dashboard -> "Invite admin" -> send the one-time link.
- Backend tests: `cd backend && venv\Scripts\python -m pytest tests -q` (needs TimescaleDB running;
  uses its own `sei_auth_test` database, created automatically).
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
  backend/data/scada/extra_years/ (training/eval only; Module 1's replay does
  not read them).

## See also
- ARCHITECTURE.md — module details, data schemas, twin state model and why each stack choice was made (avoid re-litigating)
- PROGRESS.MD - to check what's been done so far and keep adding the updates to the file