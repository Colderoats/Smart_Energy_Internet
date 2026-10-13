# SEI baseline (Phase 0, before any paper-alignment change)

Recorded 2026-10-12. No code was changed to produce this.

## Environment
- Windows 11; `backend/venv` = Python 3.14.6 (torch 2.14.0, torch_geometric 2.8.0.post1, networkx 3.4.2, web3 8.0.0; **no pandas, no pandapower, no python-docx**).
- Flower venv: `backend/ai/federated/venv` = Python 3.14.6.
- Frontend: React 19, @xyflow/react 12, recharts 3, vite 8, oxlint.

## Results
| Check | Result |
|---|---|
| `npm run build` (frontend) | PASS (916 kB main chunk; size warning only) |
| `npm run lint` (oxlint) | PASS (no findings printed) |
| Hardhat tests (`blockchain`, EnergyLedger) | PASS, 10 passing |
| Backend `pytest tests -q` | **NOT RUN** - needs TimescaleDB on :5432; nothing is listening and Docker Desktop is not running. Must be started by the user before Phase 9 regression. |
| Dashboard views / endpoints | **NOT OPENED** - backend cannot start without TimescaleDB. |

## Existing structure confirmed
- Routers in `app/main.py`: auth (public), api, twin, ai, chain (all `dependencies=protected`), ws.
- Twin: `app/twin/{digital_twin,self_healing,fault_detection,graph}.py` (9 nodes, reroute/isolate/curtail by unserved + overload kW).
- AI: `backend/ai/` (Module 3 TA-GNN), `backend/ai/federated/` (Flower, own venv, `strategies.py`, `weighting.py`, `wire.py`).
- Chain: `blockchain/contracts/EnergyLedger.sol` only.
- Frontend: tabs Dashboard/GridMap/Sources/Redistribution/AIInsights/Analytics/Settings, `src/ui/nav.js`, `vite.config.js` proxies `/nodes /twin /chain /ai /auth /health /ws`.
- `tests/test_auth.py::test_every_non_public_route_requires_auth` pins the protected route list.

## Regression re-check (2026-10-13, TimescaleDB up via Docker Desktop)
| Check | Result |
|---|---|
| Backend `pytest tests -q` (venv) | PASS, 46 passed (all pre-existing tests + `test_testbed_routes.py` + the extended protected-route list in `test_auth.py`) |
| Hardhat tests | PASS, 22 passing (10 EnergyLedger, unchanged + 12 EnergyMarket) |
| `npm run build` / `npm run lint` | PASS / clean |
| Testbed tests (`backend/testbed/tests`) | PASS, 18 |
Fixed on the way (my own code): `/testbed/results` returned NaN (std of a single-iteration metric) which is not valid JSON; NaN/inf are now served as null.
