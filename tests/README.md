# Software-only test cases TC01-TC05 (run 2026-10-23)

TC01 first FAILED (real gap: no validation step); the user then asked for a fix: `backend/app/ingestion/validation.py` + 3 lines in `pipeline.py`. Nothing else outside `tests/` and docs was changed.

| ID | How to run |
|---|---|
| TC01, TC03 | `backend\venv\Scripts\python -m pytest tests\test_tc01_tc03.py -q -s` (real ingestion pipeline in-process; DB + ledger hook stubbed) |
| TC02 | `cd backend && testbed\venv\Scripts\python -m pytest ..\tests\test_tc02_topology_switch.py -q -s` (needs the testbed venv: torch + pandapower) |
| TC04 | `cd blockchain && set NODE_PATH=%CD%\node_modules && npx hardhat run ..\tests\tc04_blockchain_immutability.js` (in-process Hardhat network) |
| TC05 | isolated stack, see below; screenshots + timings in `tests/screenshots/` |

## TC05 stack (isolated: own DB `sei_tc05`, own Hardhat node on 8546, backend on 8100, Vite on 5190; the normal dev ports are not touched)
1. `backend\venv\Scripts\python tests\tc05_setup_db.py` (creates `sei_tc05` + admin `tc05@example.com`)
2. `cd blockchain && npx hardhat node --port 8546`
3. `backend\venv\Scripts\python tests\tc05_server.py` (the real app + a TEST-ONLY `/_test/inject-fault` route + a synthetic healthy 2 s feed in place of the SCADA replay, whose first rows are already inside a logged fault)
4. `cd frontend && node node_modules\vite\bin\vite.js --config ..\tests\vite.tc05.config.mjs`
5. `python tests\tc05_dashboard_fault.py wind_scada_kelmarsh_1` (needs `pip install playwright`; uses the Chromium already in `%LOCALAPPDATA%\ms-playwright\chromium-1243`)

Restart step 3 (and drop/recreate `sei_tc05`) before each run: self-healing is edge-triggered, a node already faulted cannot be injected again.
The server auto-deploys the contracts and rewrites `blockchain/deployments/localhost*.json`; back them up and restore them afterwards.

# Set 2 (TC01-TC10 of the second test sheet, run 2026-10-23) - on top of the tests above
Same IDs as the first sheet but different cases; in docs they are written "Set-2 TCnn". Files:

| Set-2 ID | How to run |
|---|---|
| TC01, TC03 | the existing `tests\test_tc01_tc03.py` (same scenarios as the first sheet's TC01/TC03) |
| TC02 | `backend\venv\Scripts\python -m pytest tests\test_set2_tc02_broker.py -q -s` (new module `backend/app/ingestion/buffered_publisher.py`, fake broker; the product has no MQTT path yet) |
| TC04-TC07 | `cd backend && testbed\venv\Scripts\python -m pytest ..\tests\test_set2_testbed.py -q -s` (~20 min: TC05/TC06 re-evaluate the 20 outages 12-13 live; TC07 reads the stored FL result, not re-trained) |
| TC08, TC09 | `cd blockchain && set NODE_PATH=%CD%\node_modules && npx hardhat run ..\tests\tc_set2_market_events.js` |
| TC10 | same test as the first sheet's TC05 (`tests/tc05_dashboard_fault.py`, stack above); the result of the run made earlier the same day is reused, not re-run |
