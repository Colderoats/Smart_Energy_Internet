"""Journal topologies A (radial), B (meshed), C (IEEE 33-bus) as pandapower networks.

Node kinds are only those the papers name (ALLOWED_KINDS). A *prosumer bus* is a bus that
has both generation and aggregated load (kind = its source, `load_kw > 0`). Storage is a
component attached to a bus (`storage_kwh > 0`). There are no households anywhere.

Switch model: every line has one breaker; `line.in_service` is the switch state, so
A(t) is derived from the switch states (journal Eq. 10 recomputes A_hat on every change).
Tie switches are the normally-open lines (topology C: lines 33-37 of Baran & Wu).

PROVENANCE: `simulated_testbed`. Ratings/lengths/loads are fixed in PREREGISTRATION.md B.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx
import numpy as np
import pandapower as pp
import pandapower.networks as pn

ALLOWED_KINDS = ("grid", "solar", "wind", "hydro", "load", "collector")  # storage is a component (storage_kwh>0) of a bus
PF = 0.95
TAN = float(np.tan(np.arccos(PF)))
MV_RX = (0.5, 0.3)  # ohm/km: weak 11 kV microgrid cable so that rerouting produces visible voltage drops (PREREGISTRATION B)
FLEX_SHARE = 0.20  # share of each bus load that is flexible (curtail/shift)


@dataclass
class Node:
    id: int
    kind: str
    bus: int
    load_kw: float = 0.0
    gen_cap_kw: float = 0.0
    storage_kwh: float = 0.0
    storage_kw: float = 0.0
    label: str = ""


@dataclass
class Line:
    id: int
    a: int
    b: int
    tie: bool = False  # normally open
    paper_no: int = 0  # 1-based numbering used by the papers (line 12-13 etc.)


@dataclass
class Topology:
    name: str
    title: str
    nodes: list[Node]
    lines: list[Line]
    net: pp.pandapowerNet
    rating_ka: dict[int, float] = field(default_factory=dict)

    # ---- structure ----
    @property
    def n(self) -> int:
        return len(self.nodes)

    def graph(self, status: np.ndarray | None = None) -> nx.Graph:
        g = nx.Graph()
        g.add_nodes_from(range(self.n))
        for ln in self.lines:
            on = (not ln.tie) if status is None else bool(status[ln.id])
            if on:
                g.add_edge(ln.a, ln.b, line=ln.id)
        return g

    def base_status(self) -> np.ndarray:
        return np.array([not ln.tie for ln in self.lines], dtype=bool)

    def adjacency(self, status: np.ndarray) -> np.ndarray:
        A = np.zeros((self.n, self.n), dtype=np.float32)
        for ln in self.lines:
            if status[ln.id]:
                A[ln.a, ln.b] = A[ln.b, ln.a] = 1.0
        return A

    def kinds(self) -> list[str]:
        return [nd.kind for nd in self.nodes]

    def counts(self) -> dict:
        k = self.kinds()
        return dict(nodes=self.n, lines=len(self.lines), solar=k.count("solar"), wind_hydro=k.count("wind") + k.count("hydro"),
                    ties=sum(l.tie for l in self.lines), storage=sum(nd.storage_kwh > 0 for nd in self.nodes))

    def line_between(self, a: int, b: int) -> Line:
        for ln in self.lines:
            if {ln.a, ln.b} == {a, b}:
                return ln
        raise KeyError((a, b))


def a_hat(A: np.ndarray) -> np.ndarray:
    """Eq. 10: D'^-1/2 (A + I) D'^-1/2, D' the degree matrix of A + I."""
    At = A + np.eye(len(A), dtype=A.dtype)
    d = At.sum(1)
    dinv = 1.0 / np.sqrt(d)
    return (At * dinv[:, None]) * dinv[None, :]


def _mk_net(vn_kv: float, n: int, nodes: list[Node], lines: list[Line], length_km: dict[int, float], rating_ka: float | dict, c_per_km=(0.19, 0.12), ) -> pp.pandapowerNet:
    net = pp.create_empty_network(sn_mva=1.0)
    for i in range(n):
        pp.create_bus(net, vn_kv=vn_kv, name=f"n{i}")
    for ln in lines:
        r = rating_ka[ln.id] if isinstance(rating_ka, dict) else rating_ka
        pp.create_line_from_parameters(net, ln.a, ln.b, length_km[ln.id], r_ohm_per_km=c_per_km[0], x_ohm_per_km=c_per_km[1], c_nf_per_km=0.0,
                                       max_i_ka=r, in_service=not ln.tie, name=f"L{ln.id + 1}")
    return net


def _populate(net: pp.pandapowerNet, nodes: list[Node]) -> None:
    pp.create_ext_grid(net, bus=next(nd.bus for nd in nodes if nd.kind == "grid"), vm_pu=1.0, name="grid")
    for nd in nodes:
        if nd.load_kw > 0:
            pp.create_load(net, nd.bus, p_mw=nd.load_kw / 1000, q_mvar=nd.load_kw / 1000 * TAN, name=f"load{nd.id}")
        if nd.gen_cap_kw > 0:
            pp.create_sgen(net, nd.bus, p_mw=0.0, q_mvar=0.0, name=f"gen{nd.id}")
        if nd.storage_kwh > 0:
            pp.create_storage(net, nd.bus, p_mw=0.0, max_e_mwh=nd.storage_kwh / 1000, name=f"stor{nd.id}")


def topology_a() -> Topology:
    """Radial 6-node, 5-line feeder: grid, collector, load bus (+storage), 2 solar prosumer buses, 1 wind prosumer bus."""
    nodes = [
        Node(0, "grid", 0, label="Grid (slack)"),
        Node(1, "collector", 1, label="Feeder bus"),
        Node(2, "load", 2, load_kw=350, storage_kwh=400, storage_kw=150, label="Load bus + storage"),
        Node(3, "solar", 3, load_kw=80, gen_cap_kw=400, label="Solar prosumer 1"),
        Node(4, "solar", 4, load_kw=60, gen_cap_kw=300, label="Solar prosumer 2"),
        Node(5, "wind", 5, load_kw=100, gen_cap_kw=350, label="Wind prosumer"),
    ]
    pairs = [(0, 1), (1, 2), (1, 3), (2, 4), (2, 5)]
    lines = [Line(i, a, b, paper_no=i + 1) for i, (a, b) in enumerate(pairs)]
    net = _mk_net(11.0, 6, nodes, lines, {i: 4.0 for i in range(5)}, 0.05, MV_RX)
    _populate(net, nodes)
    return Topology("A", "A - radial microgrid", nodes, lines, net, {i: 0.05 for i in range(5)})


def topology_b() -> Topology:
    """Meshed 14-node, 20-line microgrid. Graph = IEEE 14-bus branch list (0-based), rescaled to an 11 kV microgrid."""
    pairs = [(0, 1), (0, 4), (1, 2), (1, 3), (1, 4), (2, 3), (3, 4), (3, 6), (3, 8), (4, 5), (5, 10), (5, 11), (5, 12), (6, 7), (6, 8), (8, 9), (8, 13),
             (9, 10), (11, 12), (12, 13)]
    assert len(pairs) == 20
    kinds = {0: "grid", 2: "solar", 7: "solar", 11: "solar", 13: "solar", 5: "wind", 9: "hydro", 3: "collector", 8: "collector",
             1: "load", 4: "load", 6: "load", 10: "load", 12: "load"}
    cap = {2: 300, 7: 300, 11: 250, 13: 250, 5: 400, 9: 350}
    load = {1: 220, 4: 260, 6: 180, 10: 200, 12: 150, 2: 70, 7: 60, 11: 50, 13: 60, 5: 90, 9: 80}
    stor = {4: (500, 200), 10: (400, 150)}
    nodes = []
    for i in range(14):
        nodes.append(Node(i, kinds[i], i, load_kw=load.get(i, 0), gen_cap_kw=cap.get(i, 0), storage_kwh=stor.get(i, (0, 0))[0], storage_kw=stor.get(i, (0, 0))[1],
                          label=f"{kinds[i]} {i + 1}"))
    lines = [Line(i, a, b, paper_no=i + 1) for i, (a, b) in enumerate(pairs)]
    net = _mk_net(11.0, 14, nodes, lines, {i: 4.0 for i in range(20)}, 0.05, MV_RX)
    _populate(net, nodes)
    return Topology("B", "B - meshed microgrid", nodes, lines, net, {i: 0.05 for i in range(20)})


# Topology C source placement (paper bus numbers, 1-based): 6 solar, 3 wind/hydro. Spread over the four laterals.
C_SOLAR = [6, 13, 18, 25, 29, 33]
C_WIND_HYDRO = {11: "wind", 22: "hydro", 31: "wind"}
C_STORAGE = {8: (600, 250), 15: (500, 200), 24: (600, 250), 30: (500, 200)}
C_GEN_KW = 450.0


def topology_c() -> Topology:
    """IEEE 33-bus (Baran & Wu) from pandapower case33bw: 33 buses, 32 lines + 5 normally-open tie lines (33-37)."""
    net = pn.case33bw()
    assert len(net.bus) == 33 and len(net.line) == 37
    # case33bw loads are the aggregated bus loads (kW scale) - kept as is.
    load_kw = {int(r.bus): float(r.p_mw) * 1000 for r in net.load.itertuples()}
    nodes = []
    for b in range(33):
        pn_ = b + 1  # paper numbering
        kind = "grid" if b == 0 else "load"
        gen = 0.0
        if pn_ in C_SOLAR:
            kind, gen = "solar", C_GEN_KW
        elif pn_ in C_WIND_HYDRO:
            kind, gen = C_WIND_HYDRO[pn_], C_GEN_KW
        st = C_STORAGE.get(pn_, (0, 0))
        nodes.append(Node(b, kind, b, load_kw=load_kw.get(b, 0.0), gen_cap_kw=gen, storage_kwh=st[0], storage_kw=st[1], label=f"bus {pn_}"))
    lines = []
    for i, r in enumerate(net.line.itertuples()):
        lines.append(Line(i, int(r.from_bus), int(r.to_bus), tie=bool(i >= 32), paper_no=i + 1))
    # network element data comes from the case; ratings are set uniformly (PREREGISTRATION B)
    net.line["max_i_ka"] = 0.25
    net.line["in_service"] = [not ln.tie for ln in lines]
    for t in ("load", "sgen", "storage", "gen", "ext_grid", "shunt"):
        getattr(net, t).drop(getattr(net, t).index, inplace=True)
    _populate(net, nodes)
    return Topology("C", "C - IEEE 33-bus", nodes, lines, net, {i: 0.25 for i in range(37)})


BUILDERS = {"A": topology_a, "B": topology_b, "C": topology_c}


def build(name: str) -> Topology:
    return BUILDERS[name]()
