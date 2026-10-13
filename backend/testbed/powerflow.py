"""Power-flow evaluation of one operating state of a testbed topology (pandapower), including
islanded sections that have local generation/storage.

A *state* is the full description needed to evaluate a candidate or the real network:
  status      bool[E]   switch (line) states
  demand_kw   float[N]  requested bus demand (aggregated load)
  served      float[N]  fraction of the demand that is NOT shed (1 = fully allowed; flexible-load curtailment lowers it)
  gen_kw      float[N]  available generation at each generator bus (already 0 when tripped)
  stor_kw     float[N]  storage set-point, + = charging (only used in the grid-connected component)
  fault_shunt dict      {bus: (p_kw, q_kvar)} short-circuit shunt (high-impedance feeder fault)

Islands (components without the grid connection) are solved with a temporary slack at the
grid-forming bus (storage bus if any, else the largest generator). If the island's slack must
import more than its storage can deliver (deficit) the island's loads are shed in proportion;
if it must export more than storage can absorb the generation is curtailed. Components with no
source at all are de-energised (all their load unserved).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx
import numpy as np
import pandapower as pp

from testbed.topologies import Topology, TAN

V_MIN, V_MAX = 0.95, 1.05


@dataclass
class Result:
    vm: np.ndarray  # pu, 0 where de-energised
    line_i_ka: np.ndarray
    loading: np.ndarray  # percent
    served_kw: np.ndarray  # delivered to each bus load
    unserved_kw: np.ndarray  # demand - served (shed + de-energised)
    gen_out_kw: np.ndarray
    stor_kw: np.ndarray
    slack_kw: float
    losses_kw: float
    energised: np.ndarray  # bool[N]
    converged: bool = True
    islands: list = field(default_factory=list)  # [(buses, shed_kw, curtailed_kw)]
    line_p_kw: np.ndarray | None = None  # active power at the 'from' end (kW), + = a -> b
    line_loss_kw: np.ndarray | None = None


class Evaluator:
    def __init__(self, top: Topology):
        self.top = top
        self.net = top.net
        n = self.net
        self.load_idx = {nd.id: int(n.load.index[n.load.name == f"load{nd.id}"][0]) for nd in top.nodes if nd.load_kw > 0}
        self.gen_idx = {nd.id: int(n.sgen.index[n.sgen.name == f"gen{nd.id}"][0]) for nd in top.nodes if nd.gen_cap_kw > 0}
        self.stor_idx = {nd.id: int(n.storage.index[n.storage.name == f"stor{nd.id}"][0]) for nd in top.nodes if nd.storage_kwh > 0}
        self.former_idx = {}
        for nd in top.nodes:
            if nd.id in self.gen_idx or nd.id in self.stor_idx:
                self.former_idx[nd.id] = int(pp.create_ext_grid(n, bus=nd.bus, vm_pu=1.0, in_service=False, name=f"former{nd.id}"))
        self.grid_node = next(nd.id for nd in top.nodes if nd.kind == "grid")
        self.grid_ext = int(n.ext_grid.index[n.ext_grid.name == "grid"][0])
        self._fault_load = None
        self.retries = 0
        self.stor_pmax = np.array([nd.storage_kw for nd in top.nodes])

    # -------------------------------------------------------------
    def _set(self, st: dict, load_scale: np.ndarray, gen_scale: np.ndarray):
        n, top = self.net, self.top
        n.line.in_service = np.asarray(st["status"], dtype=bool)
        for nid, i in self.load_idx.items():
            p = st["demand_kw"][nid] * st["served"][nid] * load_scale[nid] / 1000
            n.load.at[i, "p_mw"] = p
            n.load.at[i, "q_mvar"] = p * TAN
        for nid, i in self.gen_idx.items():
            n.sgen.at[i, "p_mw"] = st["gen_kw"][nid] * gen_scale[nid] / 1000
        # fault shunt: temporary load rows
        if self._fault_load is not None:
            n.load.drop(self._fault_load, inplace=True)
            self._fault_load = None
        fs = st.get("fault_shunt") or {}
        if fs:
            idx = [int(pp.create_load(n, bus=b, p_mw=p / 1000, q_mvar=q / 1000, name="fault")) for b, (p, q) in fs.items()]
            self._fault_load = idx

    def evaluate(self, st: dict) -> Result:
        top, n = self.top, self.net
        N, E = top.n, len(top.lines)
        status = np.asarray(st["status"], dtype=bool)
        g = top.graph(status)
        comps = [sorted(c) for c in nx.connected_components(g)]
        load_scale = np.ones(N)
        gen_scale = np.ones(N)
        stor_kw = np.zeros(N)
        for nid, i in self.stor_idx.items():
            n.storage.at[i, "in_service"] = False
        for i in self.former_idx.values():
            n.ext_grid.at[i, "in_service"] = False
        n.ext_grid.at[self.grid_ext, "in_service"] = True
        main = next(c for c in comps if self.grid_node in c)
        islands, dead = [], []
        for c in comps:
            if c is main:
                continue
            has_gen = [x for x in c if x in self.gen_idx and st["gen_kw"][x] > 0]
            stores = [x for x in c if x in self.stor_idx]
            if (not has_gen and not stores) or not st.get("allow_island", True):
                dead.append(c)
                continue
            former = max(stores, key=lambda x: self.top.nodes[x].storage_kw) if stores else max(has_gen, key=lambda x: st["gen_kw"][x])
            islands.append((c, former))
        # grid-connected storage dispatch
        for nid, i in self.stor_idx.items():
            if nid in main:
                n.storage.at[i, "in_service"] = True
                n.storage.at[i, "p_mw"] = st["stor_kw"][nid] / 1000
                stor_kw[nid] = st["stor_kw"][nid]
        for c, former in islands:
            n.ext_grid.at[self.former_idx[former], "in_service"] = True
        dead_nodes = set(x for c in dead for x in c)
        for x in dead_nodes:  # de-energised: nothing may inject/draw
            if x in self.load_idx:
                load_scale[x] = 0.0
            if x in self.gen_idx:
                gen_scale[x] = 0.0
        island_info = []
        res_ok = True
        shunt_scales = [1.0, 0.6, 0.35] if st.get("fault_shunt") else [1.0]
        si = 0
        st_run = st
        for it in range(8):
            self._set(st_run, load_scale, gen_scale)
            try:
                pp.runpp(n, numba=False, max_iteration=40, init="dc" if it else "auto")
            except pp.LoadflowNotConverged:
                # numerical fallback for a short-circuit shunt that collapses the feeder voltage: retry with a weaker shunt
                if si + 1 < len(shunt_scales):
                    si += 1
                    fs = {b: (p * shunt_scales[si], q * shunt_scales[si]) for b, (p, q) in st["fault_shunt"].items()}
                    st_run = dict(st, fault_shunt=fs)
                    self.retries += 1
                    continue
                res_ok = False
                break
            changed = False
            island_info = []
            for c, former in islands:
                p_s = float(n.res_ext_grid.p_mw.at[self.former_idx[former]]) * 1000  # kW the island must import (+) / export (-)
                cap = self.top.nodes[former].storage_kw if former in self.stor_idx else 0.0
                # other storages in the island are not in service; storage budget = sum of island storage power limits
                cap = sum(self.top.nodes[x].storage_kw for x in c if x in self.stor_idx)
                shed = curt = 0.0
                if p_s > cap + 1e-6:
                    deficit = p_s - cap
                    ld = sum(st["demand_kw"][x] * st["served"][x] * load_scale[x] for x in c if x in self.load_idx)
                    if ld > 1e-9:
                        f = max(0.0, 1 - deficit / ld * 1.02)
                        for x in c:
                            if x in self.load_idx:
                                load_scale[x] *= f
                        changed = True
                        shed = deficit
                elif -p_s > cap + 1e-6:
                    surplus = -p_s - cap
                    gg = sum(st["gen_kw"][x] * gen_scale[x] for x in c if x in self.gen_idx)
                    if gg > 1e-9:
                        f = max(0.0, 1 - surplus / gg * 1.02)
                        for x in c:
                            if x in self.gen_idx:
                                gen_scale[x] *= f
                        changed = True
                        curt = surplus
                island_info.append((c, shed, curt, p_s))
            if not changed:
                break
        if not res_ok:
            # voltage collapse / non-convergence: treat the whole state as infeasible
            return Result(np.zeros(N), np.zeros(E), np.full(E, 999.0), np.zeros(N), np.array([st["demand_kw"][i] for i in range(N)], float), np.zeros(N),
                          np.zeros(N), 0.0, 0.0, np.zeros(N, bool), converged=False)
        vm = np.zeros(N)
        vm_all = n.res_bus.vm_pu.values
        vm[:] = np.nan_to_num(vm_all, nan=0.0)
        energised = vm > 0
        i_ka = np.nan_to_num(n.res_line.i_ka.values, nan=0.0)
        i_ka = np.where(status, i_ka, 0.0)
        loading = np.where(status, np.nan_to_num(n.res_line.loading_percent.values, nan=0.0), 0.0)
        served = np.zeros(N)
        demand = np.array(st["demand_kw"], float)
        for nid in self.load_idx:
            served[nid] = st["demand_kw"][nid] * st["served"][nid] * load_scale[nid] * (1.0 if energised[nid] else 0.0)
        gen_out = np.array([st["gen_kw"][i] * gen_scale[i] if i in self.gen_idx and energised[i] else 0.0 for i in range(N)])
        for c, former in islands:
            for x in c:
                if x in self.stor_idx:
                    pass
        slack = float(n.res_ext_grid.p_mw.at[self.grid_ext]) * 1000
        losses = float(n.res_line.pl_mw.sum()) * 1000
        # islands: storage dispatch = slack (discharge +)
        for c, shed, curt, p_s in island_info:
            cap = sum(self.top.nodes[x].storage_kw for x in c if x in self.stor_idx)
            tot = cap if cap else 1.0
            for x in c:
                if x in self.stor_idx:
                    stor_kw[x] = -float(np.clip(p_s, -cap, cap)) * self.top.nodes[x].storage_kw / tot  # + charging
        lp = np.where(status, np.nan_to_num(n.res_line.p_from_mw.values, nan=0.0) * 1000, 0.0)
        ll = np.where(status, np.nan_to_num(n.res_line.pl_mw.values, nan=0.0) * 1000, 0.0)
        return Result(vm, i_ka, loading, served, np.maximum(demand - served, 0.0), gen_out, stor_kw, slack, losses, energised, True,
                      [(c, shed, curt) for c, shed, curt, _ in island_info], lp, ll)

    # -------------------------------------------------------------
    def violation(self, r: Result, status: np.ndarray) -> float:
        """V_viol (Eq. 7): sum over energised buses of voltage excursions beyond [0.95, 1.05] pu plus line overload (fraction over 100 %)."""
        if not r.converged:
            return 10.0
        v = r.vm[r.energised]
        dv = np.maximum(V_MIN - v, 0).sum() + np.maximum(v - V_MAX, 0).sum()
        ov = np.maximum(r.loading[status] - 100.0, 0).sum() / 100.0
        return float(dv + ov)
