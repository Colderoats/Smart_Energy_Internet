"""Flower strategy for all three federated modes, built on Flower's own
`flwr.server.strategy.FedProx` (which sends the proximal factor mu to clients).

  mode="fedavg"           mu = 0, all participating clients weighted EQUALLY
  mode="fedprox"          mu > 0 (client-side proximal term), equal weights
  mode="fedprox_adaptive" mu >= 0, weights from weighting.AdaptiveWeighter
                          (history of client validation loss + server-measured
                          update norm, with a floor)

The strategy is the only server-side component. It never sees data: only
parameter arrays and the allow-listed scalar metrics (wire.py audits every
message). Each round it records — for later plotting and for Module 5, which
may want to log per-node contribution scores — the participants, the SIMULATED
dropouts, every client's adaptive factors and final aggregation weight, update
norms and reported validation scalars: round_log.json.

Validation for model selection / convergence comes from the clients'
distributed evaluation of the aggregated global model on their OWN validation
rows (mean of client validation PR-AUC). The held-out TEST set is never
touched here (it is scored offline by evaluate.py).
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np
from flwr.common import (
    EvaluateIns,
    GetPropertiesIns,
    ndarrays_to_parameters,
    parameters_to_ndarrays,
)
from flwr.server.strategy import FedProx

from ai.federated import simulated, weighting, wire

MODES = ("fedavg", "fedprox", "fedprox_adaptive")
N_CLIENTS = 4
CONVERGENCE_FRACTION = 0.95  # "converged" = first round reaching 95% of the run's best validation metric


def save_weights(path: Path, weights: list[np.ndarray]) -> None:
    np.savez(path, *weights)


def load_weights(path: Path) -> list[np.ndarray]:
    blob = np.load(path)
    return [blob[f"arr_{i}"] for i in range(len(blob.files))]


class FederatedStrategy(FedProx):
    def __init__(self, *, mode: str, mu: float, initial_weights: list[np.ndarray], rounds: int, seed: int,
                 scenario: str, out_dir: Path, local_cfg: dict) -> None:
        assert mode in MODES, mode
        self.mode = mode
        self.mu = 0.0 if mode == "fedavg" else float(mu)
        self.rounds, self.seed, self.scenario, self.out_dir = rounds, seed, scenario, Path(out_dir)
        self.local_cfg = local_cfg
        self.current = [w.copy() for w in initial_weights]
        self.n_params = int(sum(w.size for w in initial_weights))
        self.audit = wire.WireAudit([tuple(w.shape) for w in initial_weights])
        self.weighter = weighting.AdaptiveWeighter() if mode == "fedprox_adaptive" else None
        self.cid2turbine: dict[str, int] = {}
        self.dropout = simulated.dropout_schedule(seed, rounds) if scenario == "dropout" else {}
        self.rounds_log: dict[int, dict] = {}
        self.best = {"round": 0, "val_pr_auc": -1.0}
        self.t_start = time.time()
        super().__init__(
            fraction_fit=1.0, fraction_evaluate=1.0, min_fit_clients=N_CLIENTS, min_evaluate_clients=N_CLIENTS,
            min_available_clients=N_CLIENTS, on_fit_config_fn=self._fit_config,
            initial_parameters=ndarrays_to_parameters(initial_weights), accept_failures=True, proximal_mu=self.mu,
        )
        self.out_dir.mkdir(parents=True, exist_ok=True)
        save_weights(self.out_dir / "weights_init.npz", initial_weights)

    # -- configuration -----------------------------------------------------
    def _fit_config(self, server_round: int) -> dict:
        return {"server_round": server_round, "seed": self.seed, **self.local_cfg}

    def _identify(self, pairs, server_round: int) -> None:
        for proxy, _ in pairs:
            if proxy.cid not in self.cid2turbine:
                res = proxy.get_properties(GetPropertiesIns(config={}), timeout=120, group_id=server_round)
                self.cid2turbine[proxy.cid] = int(res.properties["turbine"])

    def configure_fit(self, server_round, parameters, client_manager):
        pairs = super().configure_fit(server_round, parameters, client_manager)  # FedProx adds proximal_mu
        self._identify(pairs, server_round)
        absent = sorted(self.dropout.get(server_round, []))
        kept = [(p, ins) for p, ins in pairs if self.cid2turbine[p.cid] not in absent]
        self.rounds_log[server_round] = {
            "participants": sorted(self.cid2turbine[p.cid] for p, _ in kept),
            "simulated_dropped_clients": absent,
        }
        if absent:
            print(f"[server] round {server_round}: {simulated.LABEL} dropout - client(s) T{absent} unavailable", flush=True)
        return kept

    def configure_evaluate(self, server_round, parameters, client_manager):
        pairs = super().configure_evaluate(server_round, parameters, client_manager)
        part = set(self.rounds_log[server_round]["participants"])
        return [(p, ins) for p, ins in pairs if self.cid2turbine[p.cid] in part]

    def evaluate(self, server_round, parameters):
        return None  # the server holds no data; evaluation is client-side (validation) or offline (test)

    # -- aggregation ---------------------------------------------------------
    def aggregate_fit(self, server_round, results, failures):
        log = self.rounds_log[server_round]
        log["failures"] = len(failures)
        if not results:
            print(f"[server] round {server_round}: no results, keeping the previous global model", flush=True)
            return None, {}
        by_turbine, cmetrics, norms = {}, {}, {}
        for proxy, res in results:
            t = self.cid2turbine[proxy.cid]
            arrs = parameters_to_ndarrays(res.parameters)
            self.audit.check(arrs, res.metrics)
            by_turbine[t], cmetrics[t] = arrs, dict(res.metrics)
            norms[t] = float(math.sqrt(sum(((a.astype(np.float64) - g.astype(np.float64)) ** 2).sum() for a, g in zip(arrs, self.current))))
        participants = sorted(by_turbine)
        if self.weighter is not None:
            # ONLY the reported val_norm_loss and the server-measured update norm are inputs; sim_scenario labels are ignored.
            w, diag = self.weighter.weights({t: cmetrics[t].get("val_norm_loss") for t in participants}, norms)
        else:
            w, diag = weighting.equal_weights(participants), {"update_norm": {t: norms[t] for t in participants}}
        self.current = weighting.aggregate(by_turbine, w)
        log.update(
            weights={t: w[t] for t in participants},
            diagnostics=diag,
            client_fit_metrics={t: {k: v for k, v in cmetrics[t].items()} for t in participants},
        )
        wtxt = " ".join(f"T{t}={w[t]:.3f}" for t in participants)
        print(f"[server] round {server_round}: {self.mode} mu={self.mu} weights {wtxt}", flush=True)
        return ndarrays_to_parameters(self.current), {"n_participants": len(participants)}

    def aggregate_evaluate(self, server_round, results, failures):
        log = self.rounds_log[server_round]
        per = {}
        for proxy, res in results:
            self.audit.check_metrics(res.metrics)
            per[self.cid2turbine[proxy.cid]] = dict(res.metrics)
        pr = [m["val_pr_auc"] for m in per.values() if m.get("val_pr_auc") == m.get("val_pr_auc")]
        nl = [m["val_norm_loss"] for m in per.values() if m.get("val_norm_loss") == m.get("val_norm_loss")]
        mean_pr = float(np.mean(pr)) if pr else float("nan")
        log["client_val_metrics"] = per
        log["mean_val_pr_auc"] = mean_pr
        log["mean_val_norm_loss"] = float(np.mean(nl)) if nl else float("nan")
        if mean_pr == mean_pr and mean_pr > self.best["val_pr_auc"]:
            self.best = {"round": server_round, "val_pr_auc": mean_pr}
            save_weights(self.out_dir / "weights_best.npz", self.current)
        if server_round == self.rounds:
            save_weights(self.out_dir / "weights_final.npz", self.current)
        print(f"[server] round {server_round}: mean client val PR-AUC {mean_pr:.4f} (best so far {self.best['val_pr_auc']:.4f} @ round {self.best['round']})", flush=True)
        return float(np.mean([m["val_loss"] for m in per.values()])) if per else float("nan"), {"val_pr_auc": mean_pr}

    # -- wrap up -------------------------------------------------------------
    def finalize(self) -> dict:
        series = {r: v.get("mean_val_pr_auc", float("nan")) for r, v in sorted(self.rounds_log.items())}
        best_r, best_v = self.best["round"], self.best["val_pr_auc"]
        conv = next((r for r, v in series.items() if v == v and v >= CONVERGENCE_FRACTION * best_v), None) if best_v > 0 else None
        floats = sum(len(v["participants"]) * 2 * self.n_params for v in self.rounds_log.values())  # weights down + up per participating client
        meta = {
            "mode": self.mode, "mu": self.mu, "seed": self.seed, "rounds": self.rounds, "n_params": self.n_params,
            "local_cfg": self.local_cfg, "scenario": simulated.describe(self.scenario),
            "best_round_by_client_val": best_r, "best_mean_client_val_pr_auc": best_v,
            "rounds_to_convergence": conv,
            "convergence_definition": f"first round whose mean client validation PR-AUC >= {CONVERGENCE_FRACTION:.0%} of the run's best",
            "communication": {
                "rounds_x_params": self.rounds * self.n_params,
                "convergence_rounds_x_params": (conv * self.n_params) if conv else None,
                "total_floats_transferred_both_directions": floats,
                "total_megabytes_float32": floats * 4 / 1e6,
            },
            "wall_seconds": round(time.time() - self.t_start, 1),
            "provenance": "Real Kelmarsh SCADA, REPLAYED; clients are partitions of it. "
            + ("SIMULATED degradation injected (see scenario)." if self.scenario != "clean" else "No simulated degradation."),
        }
        (self.out_dir / "run_meta.json").write_text(json.dumps(meta, indent=2))
        (self.out_dir / "round_log.json").write_text(json.dumps({str(r): v for r, v in self.rounds_log.items()}, indent=1, default=float))
        (self.out_dir / "wire_audit.json").write_text(json.dumps(self.audit.summary(), indent=2))
        return meta
