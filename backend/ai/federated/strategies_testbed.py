"""Flower strategy for the TESTBED federated runs: the two paper rules as new, separately named strategies next to the existing ones.

  fedavg                    mu = 0, clients weighted by n_k
  fedprox                   mu > 0 (client-side proximal term), weights n_k
  fedprox_journal_adaptive  journal Eq. 16   alpha_k = n_k exp(-eta v_k) / sum_j n_j exp(-eta v_j)
  fedprox_conf_adaptive     conference Eqs. 11-12   rho_k = 1/(1 + L_k/Lbar), omega_k ∝ n_k rho_k

The pre-existing strategies (strategies.py: fedavg / fedprox / fedprox_adaptive with the EMA + update-norm rule) and their Kelmarsh runs are untouched.
Only parameter arrays plus the allow-listed scalars n_k and v_k cross the wire (wire.py audits every message). The server holds no data; the global
validation loss each round is the size-weighted mean of the clients' evaluation of the aggregated model on their slice of the common validation windows.
PROVENANCE: simulated_testbed.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np
from flwr.common import ndarrays_to_parameters, parameters_to_ndarrays
from flwr.server.strategy import FedProx

from ai.federated import weighting, weighting_paper, wire

MODES = ("fedavg", "fedprox", "fedprox_journal_adaptive", "fedprox_conf_adaptive")


class TestbedStrategy(FedProx):
    __test__ = False  # not a pytest class

    def __init__(self, *, mode: str, mu: float, eta: float, n_clients: int, initial_weights, rounds: int, local_cfg: dict, out_dir: Path, target: float) -> None:
        assert mode in MODES, mode
        self.mode, self.eta, self.rounds, self.local_cfg, self.out_dir, self.target = mode, float(eta), rounds, local_cfg, Path(out_dir), target
        self.mu = 0.0 if mode == "fedavg" else float(mu)
        self.current = [w.copy() for w in initial_weights]
        self.n_params = int(sum(w.size for w in initial_weights))
        self.audit = wire.WireAudit([tuple(w.shape) for w in initial_weights])
        self.log: dict[int, dict] = {}
        self.t0 = time.time()
        super().__init__(fraction_fit=1.0, fraction_evaluate=1.0, min_fit_clients=n_clients, min_evaluate_clients=n_clients, min_available_clients=n_clients,
                         on_fit_config_fn=lambda r: {"server_round": r, **self.local_cfg}, initial_parameters=ndarrays_to_parameters(initial_weights),
                         accept_failures=False, proximal_mu=self.mu)
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def evaluate(self, server_round, parameters):
        return None

    def aggregate_fit(self, server_round, results, failures):
        if failures or not results:
            raise RuntimeError(f"round {server_round}: {len(failures)} client failures")
        arrs, n_k, v_k, node = {}, {}, {}, {}
        for proxy, res in results:
            a = parameters_to_ndarrays(res.parameters)
            self.audit.check(a, res.metrics)
            k = int(res.metrics["turbine"])  # the allow-listed 'turbine' key carries the client/node index in testbed runs
            arrs[k], n_k[k], v_k[k] = a, float(res.metrics["n_k"]), float(res.metrics["v_k"])
        if self.mode == "fedprox_journal_adaptive":
            w = weighting_paper.journal_weights(n_k, v_k, self.eta)
        elif self.mode == "fedprox_conf_adaptive":
            w = weighting_paper.conf_weights(n_k, v_k)
        else:
            w = weighting_paper.sample_weights(n_k)
        self.current = weighting.aggregate(arrs, w)
        self.log[server_round] = {"weights": {str(k): w[k] for k in sorted(w)}, "v_k": {str(k): v_k[k] for k in sorted(v_k)}, "n_k": {str(k): n_k[k] for k in sorted(n_k)}}
        return ndarrays_to_parameters(self.current), {}

    def aggregate_evaluate(self, server_round, results, failures):
        tot = sum(r.num_examples for _, r in results)
        loss = sum(r.loss * r.num_examples for _, r in results) / tot
        for _, r in results:
            self.audit.check_metrics(r.metrics)
        self.log.setdefault(server_round, {})["val_loss"] = float(loss)
        print(f"[server] round {server_round}: {self.mode} global val loss {loss:.5f}", flush=True)
        return float(loss), {}

    def finalize(self) -> dict:
        hit = next((r for r in sorted(self.log) if self.log[r].get("val_loss", 9) <= self.target), None)
        n_clients = len(next(iter(self.log.values()))["weights"])
        meta = dict(mode=self.mode, mu=self.mu, eta=self.eta, rounds=self.rounds, target=self.target, rounds_to_target=hit, n_params=self.n_params, clients=n_clients,
                    comm_bytes_at_hit=weighting_paper.comm_cost_bytes(hit, n_clients, self.n_params) if hit else None, local_cfg=self.local_cfg,
                    wall_seconds=round(time.time() - self.t0, 1), provenance="simulated_testbed (Flower gRPC server + one client process per node, localhost)")
        (self.out_dir / "run_meta.json").write_text(json.dumps(meta, indent=2))
        (self.out_dir / "round_log.json").write_text(json.dumps({str(r): v for r, v in self.log.items()}, indent=1, default=float))
        (self.out_dir / "wire_audit.json").write_text(json.dumps(self.audit.summary(), indent=2))
        return meta
