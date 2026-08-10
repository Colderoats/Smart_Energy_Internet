"""In-memory digital twin state — a NetworkX graph holding each node's
latest reading and health status. Topology is static for this phase (see
docs/architecture.md); no switching/reconfiguration logic yet."""

from datetime import datetime, timezone
from threading import Lock
from typing import Literal

import networkx as nx

HealthStatus = Literal["normal", "warning", "fault_predicted", "fault"]

# Live nodes (Open-Meteo-fed) + historical nodes (Kelmarsh wind farm SCADA
# replay, one per turbine used from the dataset — see
# app/ingestion/scada_replay.py). "grid" is a twin-only structural node
# with no readings of its own — just gives the frontend graph somewhere to
# route edges to.
NODES = [
    {"node_id": "wind_01", "type": "wind", "source_type": "live"},
    {"node_id": "hydro_01", "type": "hydro", "source_type": "live"},
    {"node_id": "wind_scada_kelmarsh_1", "type": "wind", "source_type": "historical"},
    {"node_id": "wind_scada_kelmarsh_2", "type": "wind", "source_type": "historical"},
    {"node_id": "wind_scada_kelmarsh_3", "type": "wind", "source_type": "historical"},
    {"node_id": "wind_scada_kelmarsh_4", "type": "wind", "source_type": "historical"},
    {"node_id": "grid", "type": "grid", "source_type": None},
]

EDGES = [
    ("wind_01", "grid"),
    ("hydro_01", "grid"),
    ("wind_scada_kelmarsh_1", "grid"),
    ("wind_scada_kelmarsh_2", "grid"),
    ("wind_scada_kelmarsh_3", "grid"),
    ("wind_scada_kelmarsh_4", "grid"),
]


class TwinGraph:
    def __init__(self) -> None:
        self._graph = nx.DiGraph()
        self._lock = Lock()
        for node in NODES:
            self._graph.add_node(
                node["node_id"],
                type=node["type"],
                source_type=node["source_type"],
                latest_reading=None,
                health_status="normal",
                last_updated=None,
            )
        self._graph.add_edges_from(EDGES)

    def update_node(self, node_id: str, reading: dict, health_status: HealthStatus) -> dict:
        with self._lock:
            if node_id not in self._graph:
                raise KeyError(f"unknown twin node: {node_id}")
            attrs = self._graph.nodes[node_id]
            attrs["latest_reading"] = reading
            attrs["health_status"] = health_status
            attrs["last_updated"] = datetime.now(timezone.utc).isoformat()
            return self.get_node(node_id)

    def get_node(self, node_id: str) -> dict:
        attrs = self._graph.nodes[node_id]
        return {"node_id": node_id, **attrs}

    def get_all_nodes(self) -> list[dict]:
        return [self.get_node(n) for n in self._graph.nodes]

    def get_edges(self) -> list[dict]:
        return [{"source": u, "target": v} for u, v in self._graph.edges]


twin = TwinGraph()
