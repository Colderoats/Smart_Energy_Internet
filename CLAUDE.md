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
Only Module 1 (hardware/ingestion) and Module 2 (digital twin) right now.
Do not scaffold Module 3 (GNN), Module 4 (federated learning), or Module 5 
(blockchain) code yet unless I explicitly ask.

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

## See also
- docs/architecture.md — module details, data schemas, twin state model
- docs/decisions.md — why each stack choice was made (avoid re-litigating)