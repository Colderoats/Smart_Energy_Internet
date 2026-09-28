"""Node-level fault classifiers on the twin graph.

kind="tag"   TA-GNN — PyG TAGConv (Topology Adaptive Graph Convolution,
             K-hop polynomial filter over the normalised adjacency). The main model.
kind="gcn"   Baseline 1 — plain GCN, same depth/width/features/split.
kind="sage"  Alternative plain baseline (GraphSAGE), available but not the headline.
kind="mlp"   Ablation only — same network with NO message passing, to show
             honestly how much the graph itself contributes.

All share one interface: forward(x [N,F], edge_index [2,E]) -> logits [N].
The edge_index is an INPUT, not baked into the module, so the same weights run
on any topology (rerouted / isolated twin states) with no code change.

Federated-ready (Module 4 will wrap this in Flower; no Flower code here):
get_weights()/set_weights() exchange plain lists of numpy arrays.
"""

from __future__ import annotations

import numpy as np
import torch
from torch import nn
from torch_geometric.nn import GCNConv, SAGEConv, TAGConv

from ai import features as F

MODEL_KINDS = ("tag", "gcn", "sage", "mlp")
DISPLAY_NAME = {
    "tag": "TA-GNN (TAGConv)",
    "gcn": "Plain GNN (GCN)",
    "sage": "Plain GNN (GraphSAGE)",
    "mlp": "MLP (no graph, ablation)",
}


class NodeClassifier(nn.Module):
    def __init__(
        self,
        kind: str = "tag",
        in_dim: int = F.NODE_FEATURES,
        hidden: int = 64,
        n_layers: int = 2,
        K: int = 3,
        dropout: float = 0.2,
    ) -> None:
        super().__init__()
        if kind not in MODEL_KINDS:
            raise ValueError(f"unknown model kind {kind!r}")
        self.kind = kind
        self.config = {"kind": kind, "in_dim": in_dim, "hidden": hidden, "n_layers": n_layers, "K": K, "dropout": dropout}
        dims = [in_dim] + [hidden] * n_layers
        layers = []
        for a, b in zip(dims[:-1], dims[1:]):
            if kind == "tag":
                layers.append(TAGConv(a, b, K=K))
            elif kind == "gcn":
                layers.append(GCNConv(a, b))
            elif kind == "sage":
                layers.append(SAGEConv(a, b))
            else:
                layers.append(nn.Linear(a, b))
        self.layers = nn.ModuleList(layers)
        self.dropout = nn.Dropout(dropout)
        self.head = nn.Linear(hidden, 1)

    def forward(self, x: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        for layer in self.layers:
            x = layer(x) if self.kind == "mlp" else layer(x, edge_index)
            x = self.dropout(torch.relu(x))
        return self.head(x).squeeze(-1)

    def n_params(self) -> int:
        return sum(p.numel() for p in self.parameters())


def get_weights(model: nn.Module) -> list[np.ndarray]:
    """Model parameters as a list of numpy arrays (Flower NDArrays convention)."""
    return [v.detach().cpu().numpy() for v in model.state_dict().values()]


def set_weights(model: nn.Module, weights: list[np.ndarray]) -> None:
    keys = list(model.state_dict().keys())
    if len(keys) != len(weights):
        raise ValueError(f"expected {len(keys)} weight arrays, got {len(weights)}")
    model.load_state_dict({k: torch.as_tensor(w) for k, w in zip(keys, weights)}, strict=True)
