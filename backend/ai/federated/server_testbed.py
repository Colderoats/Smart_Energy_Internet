"""Flower server for one TESTBED federated run (see strategies_testbed.py).

    ai\\federated\\venv\\Scripts\\python -m ai.federated.server_testbed --mode fedprox_journal_adaptive --mu 0.01 --eta 5 --epochs 3 --clients 6 \
        --top A --it 0 --target 0.0132 --rounds 150 --out <dir>
Clients: ai.federated.client_testbed (one per node). Normally launched by run_testbed.py. PROVENANCE: simulated_testbed.
"""
from __future__ import annotations

import argparse
import warnings

warnings.filterwarnings("ignore")

import torch  # noqa: E402

torch.set_num_threads(1)

from flwr.compat.server.app import start_server  # noqa: E402
from flwr.server import ServerConfig  # noqa: E402

from ai.federated.client_testbed import CFG, get_weights  # noqa: E402
from ai.federated.strategies_testbed import MODES, TestbedStrategy  # noqa: E402
from ai.testbed_models import journal_core as JC  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=MODES, required=True)
    ap.add_argument("--mu", type=float, default=0.0)
    ap.add_argument("--eta", type=float, default=0.0)
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--clients", type=int, required=True)
    ap.add_argument("--in-dim", type=int, default=JC.L_WIN * JC.F_NODE)
    ap.add_argument("--target", type=float, required=True)
    ap.add_argument("--rounds", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    torch.manual_seed(a.seed)
    init = get_weights(JC.JointGNN(a.in_dim, CFG["H"], CFG["K"], CFG["M"], "tag"))
    strat = TestbedStrategy(mode=a.mode, mu=a.mu, eta=a.eta, n_clients=a.clients, initial_weights=init, rounds=a.rounds,
                            local_cfg={"local_epochs": a.epochs, "n_clients": a.clients}, out_dir=a.out, target=a.target)
    start_server(server_address=f"127.0.0.1:{a.port}", config=ServerConfig(num_rounds=a.rounds), strategy=strat)
    meta = strat.finalize()
    print(f"[server] finished: rounds to target {meta['rounds_to_target']}, {meta['wall_seconds']}s", flush=True)


if __name__ == "__main__":
    main()
