"""Module 2 — the Digital Twin's own state layer.

This is a SEPARATE NetworkX graph from `app.twin.graph.twin` (Module 1's
graph, which backs the unchanged "Live Data" tab / `GET /nodes`). Module 1's
graph models the *raw* topology (each source wired straight to "grid") and
must stay untouched. This graph models the twin's richer view of the same
nodes: each source has a small set of alternate routes to the grid, plus the
capacity/routing state the self-healing layer (Stage 2) needs to reroute,
isolate, or curtail a node and reason about the result.

Both graphs are fed from the same Module 1 ingestion pipeline
(`app/ingestion/pipeline.py`) — this twin does not replace or duplicate
ingestion, it just maintains a second, richer state view of the same
normalized readings.

Topology: each source node's primary route goes to one of two collector
buses ("bus_a" / "bus_b"), which both feed "grid". The other bus is the
node's one alternate route — a deliberately small (2-option) choice set per
architecture.md's "even if only 2-3 options" scope. `capacity_kw` on each
bus and `rated_capacity_kw` on each source are illustrative demo figures
(not a real load-flow study — that's pandapower's job, later) sized so that
rerouting a node onto the other bus can plausibly push it over capacity,
giving Stage 2's optimizer something real to weigh.
"""

from datetime import datetime, timezone
from threading import Lock
from typing import Literal

import networkx as nx

from app.twin.graph import HealthStatus

BUS_A = "bus_a"
BUS_B = "bus_b"
GRID = "grid"

# rated_capacity_kw: wind_01 matches WIND_RATED_POWER_KW in live_source.py;
# the Kelmarsh turbines are real Senvion MM92s (2.05 MW rated) per the
# Stage 3 SCADA replay notes; hydro_01 has no real plant behind it (see
# live_source.py) so this is a small-hydro-scale illustrative figure, not a
# spec.
SOURCE_NODES = [
    {"node_id": "wind_01", "type": "wind", "source_type": "live", "rated_capacity_kw": 2000.0, "primary_via": BUS_A},
    {"node_id": "hydro_01", "type": "hydro", "source_type": "live", "rated_capacity_kw": 400.0, "primary_via": BUS_A},
    {"node_id": "wind_scada_kelmarsh_1", "type": "wind", "source_type": "historical", "rated_capacity_kw": 2050.0, "primary_via": BUS_A},
    {"node_id": "wind_scada_kelmarsh_2", "type": "wind", "source_type": "historical", "rated_capacity_kw": 2050.0, "primary_via": BUS_B},
    {"node_id": "wind_scada_kelmarsh_3", "type": "wind", "source_type": "historical", "rated_capacity_kw": 2050.0, "primary_via": BUS_B},
    {"node_id": "wind_scada_kelmarsh_4", "type": "wind", "source_type": "historical", "rated_capacity_kw": 2050.0, "primary_via": BUS_B},
]

# Sized just above each bus's normal (primary-routing) combined load —
# bus_a: 2000+400+2050=4450, bus_b: 2050*3=6150 — so a reroute onto the
# other bus is *plausible* but can tip it over capacity, which is exactly
# the tradeoff Stage 2's scoring function needs to weigh.
BUS_CAPACITY_KW = {BUS_A: 5000.0, BUS_B: 6500.0}


class DigitalTwin:
    def __init__(self) -> None:
        self._graph = nx.DiGraph()
        self._lock = Lock()

        for bus_id, capacity in BUS_CAPACITY_KW.items():
            self._graph.add_node(bus_id, type="bus", capacity_kw=capacity)
        self._graph.add_node(GRID, type="grid")
        self._graph.add_edge(BUS_A, GRID)
        self._graph.add_edge(BUS_B, GRID)

        for node in SOURCE_NODES:
            other_bus = BUS_B if node["primary_via"] == BUS_A else BUS_A
            self._graph.add_node(
                node["node_id"],
                type=node["type"],
                source_type=node["source_type"],
                rated_capacity_kw=node["rated_capacity_kw"],
                latest_reading=None,
                health_status="normal",
                last_updated=None,
                possible_connections=[node["primary_via"], other_bus],
                active_connection=node["primary_via"],
                load_share=1.0,
                isolated=False,
            )
            self._graph.add_edge(node["node_id"], node["primary_via"])

    # -- state update (every ingested reading flows through here) --------

    def update_node(self, node_id: str, reading: dict, health_status: HealthStatus) -> dict:
        """Formalizes architecture.md's prediction-layer rule: every new
        reading updates the node's state AND re-evaluates health_status, in
        one place. Routing/isolation/load_share are untouched here — those
        only change via the mutation methods below, driven by Stage 2's
        self-healing decision layer."""
        with self._lock:
            if node_id not in self._graph:
                raise KeyError(f"unknown twin node: {node_id}")
            attrs = self._graph.nodes[node_id]
            attrs["latest_reading"] = reading
            attrs["health_status"] = health_status
            attrs["last_updated"] = datetime.now(timezone.utc).isoformat()
            return self.get_node(node_id)

    # -- reconfiguration primitives (called by the Stage 2 decision layer) --

    def reroute_node(self, node_id: str, via: str) -> dict:
        """Switch node_id's active route to `via` (must be one of its
        possible_connections). Human-override hook: before this is ever
        wired to real actuation hardware, a human-approval gate must sit in
        front of this call — this basic pass applies automatically."""
        with self._lock:
            attrs = self._graph.nodes[node_id]
            if via not in attrs["possible_connections"]:
                raise ValueError(f"{via} is not a valid connection for {node_id}")
            current = attrs["active_connection"]
            if current is not None and self._graph.has_edge(node_id, current):
                self._graph.remove_edge(node_id, current)
            self._graph.add_edge(node_id, via)
            attrs["active_connection"] = via
            attrs["isolated"] = False
            return self.get_node(node_id)

    def isolate_node(self, node_id: str) -> dict:
        """Cut node_id off from the grid entirely (its load becomes fully
        unserved). Same human-override note as reroute_node."""
        with self._lock:
            attrs = self._graph.nodes[node_id]
            current = attrs["active_connection"]
            if current is not None and self._graph.has_edge(node_id, current):
                self._graph.remove_edge(node_id, current)
            attrs["active_connection"] = None
            attrs["isolated"] = True
            return self.get_node(node_id)

    def set_load_share(self, node_id: str, fraction: float) -> dict:
        """Curtail node_id to `fraction` of its rated_capacity_kw (0-1)
        instead of rerouting/isolating it. Same human-override note."""
        with self._lock:
            attrs = self._graph.nodes[node_id]
            attrs["load_share"] = max(0.0, min(1.0, fraction))
            return self.get_node(node_id)

    # -- reads --------------------------------------------------------

    def get_node(self, node_id: str) -> dict:
        attrs = self._graph.nodes[node_id]
        node = {"node_id": node_id, **attrs}
        # Derived, read-only field for the frontend — not stored state, just
        # computed fresh from current routing on every read.
        if attrs.get("type") == "bus":
            node["current_load_kw"] = self.bus_load_kw(node_id)
        return node

    def get_all_nodes(self) -> list[dict]:
        return [self.get_node(n) for n in self._graph.nodes]

    def get_edges(self) -> list[dict]:
        return [{"source": u, "target": v} for u, v in self._graph.edges]

    def get_possible_connections(self, node_id: str) -> list[str]:
        return list(self._graph.nodes[node_id]["possible_connections"])

    def bus_load_kw(self, bus_id: str) -> float:
        """Sum of currently-routed load (rated_capacity_kw * load_share,
        approximating current output by rated capacity since this pass has
        no power-flow model yet) for every source node actively connected
        to bus_id right now."""
        total = 0.0
        for node_id in self._graph.predecessors(bus_id):
            attrs = self._graph.nodes[node_id]
            if attrs.get("active_connection") == bus_id:
                total += attrs["rated_capacity_kw"] * attrs["load_share"]
        return total


digital_twin = DigitalTwin()
