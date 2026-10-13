"""Flower client for the TESTBED: one process per grid node (journal: one client per node, K = 6 / 14 / 33).

Same local training function as the in-process simulation (ai.testbed_models.journal_core.local_train). The process loads the pre-exported
windowed tensors (ai/testbed_models/export_fl_data.py) - no pandapower needed in the Flower venv. It sends only the model arrays and the allow-listed
scalars n_k and v_k (wire.py is enforced before every send).

    ai\\federated\\venv\\Scripts\\python -m ai.federated.client_testbed --top A --it 0 --node 3 --server 127.0.0.1:8099
Normally launched for you by run_testbed.py. PROVENANCE: simulated_testbed.
"""
from __future__ import annotations

import argparse
import warnings

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import torch  # noqa: E402

torch.set_num_threads(1)

import flwr as fl  # noqa: E402
from flwr.compat.client.app import start_client  # noqa: E402

from ai.federated import wire  # noqa: E402
from ai.testbed_models import journal_core as JC  # noqa: E402
from ai.testbed_models.paths import ART  # noqa: E402

CFG = dict(H=128, K=2, M=3, lr=0.001)  # Option 3 (journal Sec. V-A)


def load_data(top: str, it: int) -> JC.Data:
    d = torch.load(ART / f"journal_{top}" / f"it{it}" / "fl_data.pt", weights_only=False)
    return JC.Data(**d)


def get_weights(m):
    return [p.detach().numpy().astype(np.float32) for p in m.parameters()]


def set_weights(m, arrs):
    with torch.no_grad():
        for p, a in zip(m.parameters(), arrs):
            p.copy_(torch.from_numpy(np.asarray(a, dtype=np.float32)))


class NodeClient(fl.client.NumPyClient):
    def __init__(self, top: str, it: int, node: int, seed: int, frac: float) -> None:
        self.node, self.seed, self.frac = node, seed, frac
        self.data = load_data(top, it)
        self.n_tr = self.data.split
        self.val = np.arange(self.n_tr, len(self.data.c))
        torch.manual_seed(seed)
        self.model = JC.JointGNN(self.data.x.shape[-1], CFG["H"], CFG["K"], CFG["M"], "tag")
        self.ref_shapes = [tuple(a.shape) for a in get_weights(self.model)]
        self.rng = np.random.default_rng(seed * 7919 + node)
        print(f"[client {node}] ready: {self.n_tr} train windows, {len(self.val)} val windows", flush=True)

    def get_properties(self, config):
        return {"turbine": self.node}

    def get_parameters(self, config):
        return get_weights(self.model)

    def fit(self, parameters, config):
        set_weights(self.model, parameters)
        w_ref = JC.flat(self.model).clone()
        loss = JC.local_train(self.model, self.data, self.node, w_ref, float(config["proximal_mu"]), int(config["local_epochs"]), self.frac, CFG["lr"], self.rng, self.n_tr)
        vsel = torch.from_numpy(self.rng.choice(self.val, min(len(self.val), 512), replace=False))
        v_k = JC.client_val(self.model, self.data, vsel, self.node)
        metrics = {"train_loss": float(loss), "turbine": self.node, "n_k": float(self.n_tr), "v_k": float(v_k)}
        out = get_weights(self.model)
        wire.check_payload(out, metrics, self.ref_shapes)
        return out, self.n_tr, metrics

    def evaluate(self, parameters, config):
        set_weights(self.model, parameters)
        K = int(config.get("n_clients", 1))
        idx = self.val[self.node::K]  # this client's slice of the common validation windows (slices partition it)
        self.model.eval()
        with torch.no_grad():
            tot = 0.0
            for i in range(0, len(idx), 2048):
                b = torch.from_numpy(idx[i:i + 2048])
                loss, *_ = JC.batch_loss(self.model, self.data, b)
                tot += float(loss) * len(b)
        metrics = {"turbine": self.node, "val_n": len(idx), "val_loss": tot / max(len(idx), 1)}
        wire.check_payload([], metrics, [])
        return tot / max(len(idx), 1), len(idx), metrics


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", required=True)
    ap.add_argument("--it", type=int, default=0)
    ap.add_argument("--node", type=int, required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--frac", type=float, default=0.05)
    ap.add_argument("--server", default="127.0.0.1:8099")
    a = ap.parse_args()
    c = NodeClient(a.top, a.it, a.node, a.seed, a.frac)
    start_client(server_address=a.server, client=c.to_client(), insecure=True)
    print(f"[client {a.node}] done", flush=True)


if __name__ == "__main__":
    main()
