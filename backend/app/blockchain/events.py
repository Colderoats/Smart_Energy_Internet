"""Payload builders for the four ledger event types.

Every payload states its data provenance, in the payload itself (so it is
covered by the on-chain hash) and in the record's `provenance` column:

  live_api               Open-Meteo wind/hydro values (external API, not physically sensed)
  replayed_scada         Kelmarsh SCADA dataset replayed at a fixed interval (not live)
  simulated              generated for demos (P2P trades: no solar/EV hardware exists yet)
  offline_federated_run  Module 4 Flower run, recorded after the fact from its round_log.json

Each builder returns an "entry" dict consumed by ledger.record():
  event_type, actor, provenance, summary, source_ref, dedupe_key, payload
"""

import csv
import json
import random
import uuid
from datetime import datetime, timezone

from app.config import REPO_ROOT
from app.twin.digital_twin import digital_twin

SCHEMA_VERSION = 1

FEDERATED_ARTIFACTS = REPO_ROOT / "backend" / "ai" / "federated" / "artifacts"
# The run whose model is exported to model_federated/ (see aiprogress.md EXP-012).
DEFAULT_FL_RUN = "fedprox_adaptive_mu1_clean_s3"

PROVENANCE_NOTES = {
    "live_api": "Live values from the Open-Meteo API (external source, not physically instrumented).",
    "replayed_scada": "Kelmarsh wind-farm SCADA dataset REPLAYED at a fixed interval to simulate a live feed; not live.",
    "simulated": "SIMULATED for demos. No solar/EV hardware exists yet; no real energy or money moved.",
    "offline_federated_run": "Recorded from an OFFLINE Module 4 federated training run (round_log.json), replayed onto the ledger after the fact.",
}

STRATEGY_LABELS = {"fedavg": "FedAvg", "fedprox": "FedProx", "fedprox_adaptive": "FedProx + adaptive weighting"}


def _node_provenance(node: dict) -> str:
    return "replayed_scada" if node.get("source_type") == "historical" else "live_api"


def _r(value, digits=4):
    return round(value, digits) if isinstance(value, float) else value


def twin_decision_id(decision: dict) -> str:
    """Module 2 decisions have no numeric id; node + decision time identifies
    one uniquely (it matches GET /twin/decisions rows)."""
    return f"{decision['node_id']}@{decision['time'].isoformat()}"


# -- FAULT_ALERT ---------------------------------------------------------------


def fault_alert(node: dict, trigger_summary: str, detected_at: datetime) -> dict:
    detectors = node.get("detectors") or {}
    rule = detectors.get("rule_based") or {}
    ta = detectors.get("ta_gnn") or {}
    flagged_by = list(node.get("flagged_by") or [])
    reading = node.get("latest_reading") or {}
    provenance = _node_provenance(node)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "event_type": "FAULT_ALERT",
        "provenance": provenance,
        "provenance_note": PROVENANCE_NOTES[provenance],
        "node_id": node["node_id"],
        "node_type": node.get("type"),
        "health_status": node.get("health_status"),
        "flagged_by": flagged_by,
        "detectors": {
            "rule_based": {k: rule.get(k) for k in ("status", "flagged", "basis") if k in rule} or None,
            "ta_gnn": (
                {
                    "flagged": ta.get("flagged"),
                    "probability": _r(ta.get("probability")),
                    "horizon_min": ta.get("horizon_min"),
                    "model": ta.get("model"),
                    "model_source": ta.get("model_source"),
                    "as_of": ta.get("as_of"),
                    "note": "forecast on replayed SCADA data",
                }
                if ta
                else None
            ),
        },
        "trigger_summary": trigger_summary,
        "reading_timestamp": reading.get("timestamp"),
        "detected_at": detected_at.isoformat(),
    }

    node_id = node["node_id"]
    status_word = "a predicted fault" if node.get("health_status") == "fault_predicted" else "a fault"
    if "ta_gnn" in flagged_by and "rule_based" not in flagged_by and ta:
        summary = (f"TA-GNN predicted a fault on {node_id} within {ta.get('horizon_min')} min "
                   f"(probability {ta.get('probability') or 0:.2f})")
    elif "rule_based" in flagged_by and "ta_gnn" in flagged_by:
        summary = f"Rule-based detector and TA-GNN both flagged {status_word} on {node_id}"
    else:
        summary = f"Rule-based detector flagged {status_word} on {node_id}"

    return {
        "event_type": "FAULT_ALERT",
        "actor": node["node_id"],
        "provenance": provenance,
        "summary": summary,
        "source_ref": f"{node['node_id']}@{detected_at.isoformat()}",
        "dedupe_key": None,
        "payload": payload,
    }


# -- ENERGY_REDISTRIBUTION ------------------------------------------------------


def energy_redistribution(node_before: dict, decision: dict) -> dict:
    """`node_before` is the twin node snapshot taken before the action was applied."""
    provenance = _node_provenance(node_before)
    kw = node_before["rated_capacity_kw"] * node_before["load_share"]
    params = decision.get("chosen_params") or {}
    action = decision["chosen_action"]
    target = params.get("via") if action == "reroute" else None
    chosen = next(
        (c for c in decision["candidates"] if c["action"] == action and c["params"] == params),
        {},
    )
    decision_id = twin_decision_id(decision)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "event_type": "ENERGY_REDISTRIBUTION",
        "provenance": provenance,
        "provenance_note": PROVENANCE_NOTES[provenance]
        + " The redistribution itself happened in the DIGITAL TWIN only (no physical switching, no human-approval gate yet).",
        "twin_decision_id": decision_id,
        "source_node": node_before["node_id"],
        "previous_connection": node_before.get("active_connection"),
        "target_node": target,
        "action": action,
        "action_params": params,
        "kw_affected": _r(kw, 1),
        "kw_basis": "rated_capacity_kw x load_share (twin approximation; no power-flow model yet)",
        "unserved_kw": chosen.get("unserved_kw"),
        "overload_kw": chosen.get("overload_kw"),
        "score": decision.get("chosen_score"),
        "reason": decision["reason"],
        "trigger_health_status": decision["trigger_health_status"],
        "trigger_summary": decision.get("trigger_summary"),
        "decided_at": decision["time"].isoformat(),
    }

    if action == "reroute":
        what = f"rerouted {node_before['node_id']} ({kw:.0f} kW) from {node_before.get('active_connection')} to {target}"
    elif action == "isolate":
        what = f"isolated {node_before['node_id']} ({kw:.0f} kW taken off the grid)"
    else:
        what = f"cut {node_before['node_id']} to {params.get('fraction', 0) * 100:.0f}% output ({kw:.0f} kW before)"
    summary = f"Self-healing twin {what} after a {decision['trigger_health_status'].replace('_', ' ')}"

    return {
        "event_type": "ENERGY_REDISTRIBUTION",
        "actor": node_before["node_id"],
        "provenance": provenance,
        "summary": summary,
        "source_ref": decision_id,
        "dedupe_key": f"decision:{decision_id}",
        "payload": payload,
    }


# -- P2P_TRADE (SIMULATED) --------------------------------------------------------


DEMO_PRICE_PER_KWH = 6.5  # illustrative demo tariff, in "demo credits" — not a market price


def _source_nodes() -> list[dict]:
    return [n for n in digital_twin.get_all_nodes() if n.get("type") in ("wind", "hydro", "solar")]


def simulated_trade(seller: str | None = None, buyer: str | None = None, kwh: float | None = None,
                    price_per_kwh: float | None = None) -> dict:
    """A SIMULATED P2P trade between two twin nodes, for demos. Raises
    ValueError on unknown/identical nodes. Nothing physical happens."""
    sources = _source_nodes()
    ids = [n["node_id"] for n in sources]
    by_id = {n["node_id"]: n for n in sources}
    buyer_pool = ids + ["grid"]

    if seller is not None and seller not in by_id:
        raise ValueError(f"unknown seller node {seller!r}; choose one of {ids}")
    if buyer is not None and buyer not in buyer_pool:
        raise ValueError(f"unknown buyer node {buyer!r}; choose one of {buyer_pool}")
    if seller is None:
        producing = [n for n in sources if ((n.get("latest_reading") or {}).get("power_output") or 0) > 0
                     and not n.get("isolated")]
        seller = random.choice(producing or sources)["node_id"]
    if buyer is None:
        buyer = random.choice([b for b in buyer_pool if b != seller])
    if buyer == seller:
        raise ValueError("seller and buyer must differ")

    seller_node = by_id[seller]
    seller_power = (seller_node.get("latest_reading") or {}).get("power_output")
    if kwh is None:
        if seller_power and seller_power > 0:
            # 5-20 % of what the seller would produce in 15 min at its latest
            # reading, capped at rated capacity (the live hydro value is a
            # river-discharge-derived figure that can exceed the 400 kW rating).
            rated = seller_node.get("rated_capacity_kw") or seller_power
            basis_kw = min(seller_power, rated)
            kwh = round(basis_kw * 0.25 * random.uniform(0.05, 0.20), 2)
            capped = " capped at rated capacity" if basis_kw < seller_power else ""
            kwh_basis = (f"5-20% of 15 min at the seller's latest power_output ({seller_power:.1f} kW{capped}"
                         f" = {basis_kw:.1f} kW, {_node_provenance(seller_node)})")
        else:
            kwh = round(random.uniform(5, 50), 2)
            kwh_basis = "random 5-50 kWh (seller had no positive power reading)"
    else:
        kwh_basis = "entered by the demo user"
    if kwh <= 0:
        raise ValueError("kwh must be positive")
    price = round(price_per_kwh if price_per_kwh is not None else DEMO_PRICE_PER_KWH * random.uniform(0.9, 1.1), 3)
    if price <= 0:
        raise ValueError("price_per_kwh must be positive")

    trade_id = f"sim-trade-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "event_type": "P2P_TRADE",
        "provenance": "simulated",
        "provenance_note": PROVENANCE_NOTES["simulated"],
        "trade_id": trade_id,
        "seller": seller,
        "buyer": buyer,
        "kwh": kwh,
        "kwh_basis": kwh_basis,
        "price_per_kwh": price,
        "price_unit": "demo credits per kWh (illustrative)",
        "settlement": {
            "amount": round(kwh * price, 2),
            "unit": "demo credits",
            "status": "settled (simulated: no real energy or money moved)",
            "method": "instant ledger settlement on record confirmation",
        },
        "created_at": now.isoformat(),
    }
    return {
        "event_type": "P2P_TRADE",
        "actor": seller,
        "provenance": "simulated",
        "summary": f"Simulated trade: {seller} sold {kwh:g} kWh to {buyer} at {price:.2f} credits/kWh",
        "source_ref": trade_id,
        "dedupe_key": f"trade:{trade_id}",
        "payload": payload,
    }


# -- FL_ROUND (replayed from the offline federated run) ------------------------------


def fl_round_entries(run: str = DEFAULT_FL_RUN) -> list[dict]:
    """One entry per round of an offline Module 4 run. Weights come from the
    run's round_log.json and are cross-checked against the aggregate
    adaptive_weights_by_round.csv."""
    run_dir = FEDERATED_ARTIFACTS / "runs" / run
    if not run.replace("_", "").replace(".", "").isalnum() or not run_dir.is_dir():
        raise ValueError(f"unknown federated run {run!r}")
    round_log = json.loads((run_dir / "round_log.json").read_text(encoding="utf-8"))
    meta_path = run_dir / "run_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    mode = meta.get("mode", "unknown")
    scenario = (meta.get("scenario") or {}).get("scenario", "unknown")
    simulated = bool((meta.get("scenario") or {}).get("simulated", False))

    csv_weights: dict[int, dict[str, float]] = {}
    csv_path = FEDERATED_ARTIFACTS / "adaptive_weights_by_round.csv"
    if csv_path.exists():
        with csv_path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if (row["strategy"] == mode and row["scenario"] == scenario and int(row["seed"]) == meta.get("seed")
                        and abs(float(row["mu"]) - float(meta.get("mu", 0))) < 1e-12):
                    csv_weights.setdefault(int(row["round"]), {})[row["turbine"]] = float(row["weight"])

    entries = []
    for round_key in sorted(round_log, key=int):
        rnd = round_log[round_key]
        n = int(round_key)
        weights = {str(k): round(v, 6) for k, v in rnd["weights"].items()}
        csv_match = None
        if n in csv_weights:
            csv_match = all(abs(csv_weights[n].get(k, -1) - v) < 1e-6 for k, v in weights.items())
        diag = rnd.get("diagnostics") or {}
        payload = {
            "schema_version": SCHEMA_VERSION,
            "event_type": "FL_ROUND",
            "provenance": "offline_federated_run",
            "provenance_note": PROVENANCE_NOTES["offline_federated_run"]
            + " Clients are partitions of the REPLAYED Kelmarsh SCADA data, not separate physical sites."
            + (" This run includes SIMULATED client degradation." if simulated else ""),
            "run": run,
            "strategy": mode,
            "strategy_label": STRATEGY_LABELS.get(mode, mode),
            "mu": meta.get("mu"),
            "seed": meta.get("seed"),
            "scenario": scenario,
            "round": n,
            "total_rounds": meta.get("rounds", len(round_log)),
            "participants": [f"T{p}" for p in rnd.get("participants", [])],
            "simulated_dropped_clients": [f"T{p}" for p in rnd.get("simulated_dropped_clients", [])],
            "failures": rnd.get("failures", 0),
            "client_weights": {f"T{k}": v for k, v in weights.items()},
            "weight_factors": {
                name: {f"T{k}": _r(v, 6) for k, v in (diag.get(name) or {}).items()}
                for name in ("ema_norm_loss", "f_loss", "update_norm", "f_norm")
                if diag.get(name)
            },
            "mean_val_pr_auc": _r(rnd.get("mean_val_pr_auc"), 6),
            "mean_val_norm_loss": _r(rnd.get("mean_val_norm_loss"), 6),
            "source_files": [
                f"backend/ai/federated/artifacts/runs/{run}/round_log.json",
                "backend/ai/federated/artifacts/adaptive_weights_by_round.csv",
            ],
            "csv_weights_match": csv_match,
        }
        pct = ", ".join(f"T{k} {v * 100:.0f}%" for k, v in sorted(weights.items()))
        entries.append({
            "event_type": "FL_ROUND",
            "actor": "federated_server",
            "provenance": "offline_federated_run",
            "summary": f"Federated round {n} ({STRATEGY_LABELS.get(mode, mode)}): client weights {pct}",
            "source_ref": f"{run}#round{n}",
            "dedupe_key": f"fl:{run}:{n}",
            "payload": payload,
        })
    return entries
