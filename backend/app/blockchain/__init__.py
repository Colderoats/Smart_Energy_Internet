"""Module 5 — blockchain ledger (Solidity EnergyLedger + Web3.py).

Every important grid action is written to an append-only on-chain ledger:

    grid event ──> payload builder (events.py, provenance label inside the payload)
               ──> canonical JSON + keccak256 fingerprint (hashing.py)
               ──> chain_records row in TimescaleDB, status "queued" (store.py)
               ──> ledger worker (ledger.py): appendRecord tx -> receipt -> confirmations
               ──> WebSocket `chain_record` / `chain_status` messages on /ws/updates

The chain stores only the fingerprint (plus event type and actor); the full
payload lives off-chain in `chain_records`. Verification = re-hash the stored
payload and compare with the on-chain hash (ledger.verify_record).

Event types:
  ENERGY_REDISTRIBUTION  Module 2 self-healing reroute / isolate / curtail
  FAULT_ALERT            fault / fault_predicted verdict (rule_based and/or ta_gnn)
  P2P_TRADE              SIMULATED peer-to-peer trade between twin nodes
                         (no solar/EV hardware exists yet; always labelled "simulated")
  FL_ROUND               Module 4 federated round, REPLAYED from the offline run's round_log.json

Contract + Hardhat project: <repo>/blockchain (see PROGRESS.md "Module 5").
The chain being slow or down never blocks ingestion or the twin: hooks only
enqueue, the worker retries with backoff.
"""
