"""Flower server for one federated run.

Run (from backend/, in the Module 4 venv). Start the server first, then the
four clients (or just use run_experiment.py, which does all of it):

    ai\\federated\\venv\\Scripts\\python -m ai.federated.server --strategy fedprox_adaptive --mu 0.01 --seed 0 --out ai\\federated\\artifacts\\runs\\demo
    ai\\federated\\venv\\Scripts\\python -m ai.federated.client --turbine 1   # ...and 2, 3, 4, each in its own terminal

Strategies: fedavg | fedprox | fedprox_adaptive (see strategies.py / weighting.py).
`--scenario dropout` injects SIMULATED client dropout on the server side; the
other simulated scenarios (degraded_data, corrupted_update) are client-side
flags (see client.py / simulated.py).

Transport: Flower's gRPC server on localhost, insecure (single-machine
simulation). Ray-based Flower simulation is not installable on Windows +
Python 3.14, so each client is a separate OS process instead.
"""

from __future__ import annotations

import argparse
import warnings

warnings.filterwarnings("ignore")

import torch  # noqa: E402

torch.set_num_threads(1)

from flwr.compat.server.app import start_server  # noqa: E402
from flwr.server import ServerConfig  # noqa: E402

from ai.federated import local, simulated  # noqa: E402
from ai.federated.strategies import MODES, FederatedStrategy  # noqa: E402
from ai.models import get_weights  # noqa: E402

LOCAL_CFG = {
    "local_epochs": 1,
    "lr": 3e-3,
    "weight_decay": 1e-4,
    "batch_size": 256,
    "neg_keep_frac": 0.3,
}  # Module 3's optimiser settings; one local epoch per round. Fixed a priori.
DEFAULT_ROUNDS = 30


def main() -> None:
    ap = argparse.ArgumentParser(description="Federated server (REPLAYED Kelmarsh data, one client per turbine)")
    ap.add_argument("--strategy", choices=MODES, required=True)
    ap.add_argument("--mu", type=float, default=0.0, help="FedProx proximal factor (ignored for fedavg)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    ap.add_argument("--scenario", choices=simulated.SCENARIOS, default="clean")
    ap.add_argument("--port", type=int, default=8098)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.scenario != "clean":
        print(f"[server] scenario={args.scenario}: {simulated.LABEL} degradation - results are labelled simulated", flush=True)
    strategy = FederatedStrategy(
        mode=args.strategy, mu=args.mu, initial_weights=get_weights(local.make_model(args.seed)), rounds=args.rounds,
        seed=args.seed, scenario=args.scenario, out_dir=args.out, local_cfg=LOCAL_CFG,
    )
    start_server(server_address=f"127.0.0.1:{args.port}", config=ServerConfig(num_rounds=args.rounds), strategy=strategy)
    meta = strategy.finalize()
    print(f"[server] finished: best client-val round {meta['best_round_by_client_val']}, "
          f"rounds to convergence {meta['rounds_to_convergence']}, {meta['wall_seconds']}s", flush=True)


if __name__ == "__main__":
    main()
