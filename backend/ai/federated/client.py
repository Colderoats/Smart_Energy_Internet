"""Flower client: one process per grid node (Kelmarsh turbine).

Wraps the Module 3 TA-GNN for federated training. The process opens ONLY its
own shard (ai/federated/artifacts/shards/client_<n>.npz); the only things it
sends to the server are the model weights and scalar metrics (see wire.py,
which is enforced before every send).

Run (from backend/, in the Module 4 venv; the server must already be listening):
    ai\\federated\\venv\\Scripts\\python -m ai.federated.client --turbine 1 --server 127.0.0.1:8098
Normally launched for you by run_experiment.py (server + 4 clients).

`--scenario degraded_data|corrupted_update` makes THIS client behave as the
SIMULATED faulty client (only honoured for turbine simulated.SIM_TURBINE); see
simulated.py. Real runs use the default `clean`. Provenance of the data: real
Kelmarsh SCADA, replayed; a client is a partition, not a separate site.
"""

from __future__ import annotations

import argparse
import time
import warnings

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import torch  # noqa: E402

torch.set_num_threads(1)  # 4 clients run in parallel on one machine

import flwr as fl  # noqa: E402
from flwr.compat.client.app import start_client  # noqa: E402

from ai.federated import local, partition, simulated, wire  # noqa: E402
from ai.models import get_weights, set_weights  # noqa: E402


class TurbineClient(fl.client.NumPyClient):
    def __init__(self, turbine: int, scenario: str = "clean", seed: int = 0) -> None:
        self.turbine, self.scenario, self.seed = turbine, scenario, seed
        shard = partition.load_shard(turbine)
        self.is_sim_client = turbine == simulated.SIM_TURBINE and scenario in ("degraded_data", "corrupted_update")
        tx, ty, vx, vy = shard.train_x, shard.train_y, shard.val_x, shard.val_y
        if scenario == "degraded_data" and self.is_sim_client:
            print(f"[client T{turbine}] {simulated.LABEL} degraded client: noise sigma={simulated.NOISE_SIGMA}, "
                  f"{simulated.LABEL_DROP_FRAC:.0%} of positive labels dropped (NOT real data)", flush=True)
            tx, ty, vx, vy = simulated.degrade_shard_arrays(tx, ty, vx, vy, seed)
        self.data = local.local_data_from_shard(shard, tx, ty, vx, vy)
        self.model = local.make_model(0)
        self.ref_shapes = [tuple(w.shape) for w in get_weights(self.model)]
        print(f"[client T{turbine}] shard loaded: {len(ty)} train rows ({int((ty == 1).sum())} positive), "
              f"{len(vy)} val rows; pos_weight {self.data.pos_weight:.1f}; scenario={scenario}", flush=True)

    def _label(self) -> str:
        return f"{simulated.LABEL}:{self.scenario}" if self.is_sim_client else "none"

    # -- Flower NumPyClient interface --------------------------------------
    def get_properties(self, config):
        return {"turbine": self.turbine}

    def get_parameters(self, config):
        return get_weights(self.model)

    def fit(self, parameters, config):
        mu, rnd = float(config["proximal_mu"]), int(config["server_round"])
        t0 = time.time()
        local_seed = int(config["seed"]) * 1_000_003 + rnd * 101 + self.turbine
        new_w, st = local.local_train(
            parameters, self.data, mu=mu, epochs=int(config["local_epochs"]), seed=local_seed,
            lr=float(config["lr"]), weight_decay=float(config["weight_decay"]),
            batch_size=int(config["batch_size"]), neg_keep_frac=float(config["neg_keep_frac"]),
        )
        set_weights(self.model, new_w)
        ev = local.evaluate_local(self.model, self.data)  # honest, pre-corruption local validation scalars
        sent = new_w
        if self.scenario == "corrupted_update" and self.is_sim_client:
            sent = simulated.corrupt_update(parameters, new_w)
            print(f"[client T{self.turbine}] round {rnd}: {simulated.LABEL} corrupted update transmitted "
                  f"(sign-flipped x{simulated.UPDATE_SCALE})", flush=True)
        metrics = {
            "train_loss": float(st["train_loss"]), "prox_sq_dist": float(st["prox_sq_dist"]), "n_batches": int(st["n_batches"]),
            "train_seconds": round(time.time() - t0, 2), "turbine": self.turbine, "sim_scenario": self._label(),
            **{k: (int(v) if k in ("val_n", "val_pos") else float(v)) for k, v in ev.items()},
        }
        sent = [np.asarray(a, dtype=np.float32) for a in sent]
        wire.check_payload(sent, metrics, self.ref_shapes)  # enforced BEFORE anything leaves the process
        return sent, int(len(self.data.train_y)), metrics

    def evaluate(self, parameters, config):
        set_weights(self.model, parameters)
        ev = self.eval_local()
        metrics = {k: (int(v) if k in ("val_n", "val_pos") else float(v)) for k, v in ev.items()}
        metrics["turbine"] = self.turbine
        wire.check_payload([], metrics, [])
        return float(ev["val_loss"]), int(ev["val_n"]), metrics

    def eval_local(self):
        return local.evaluate_local(self.model, self.data)


def main() -> None:
    ap = argparse.ArgumentParser(description="Federated client for one Kelmarsh turbine (REPLAYED data)")
    ap.add_argument("--turbine", type=int, required=True, choices=partition.TURBINES)
    ap.add_argument("--server", default="127.0.0.1:8098")
    ap.add_argument("--scenario", default="clean", choices=simulated.SCENARIOS)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    client = TurbineClient(args.turbine, args.scenario, args.seed)
    # localhost, unencrypted: single-machine simulation. A real deployment would use TLS.
    start_client(server_address=args.server, client=client.to_client(), insecure=True)
    print(f"[client T{args.turbine}] done", flush=True)


if __name__ == "__main__":
    main()
