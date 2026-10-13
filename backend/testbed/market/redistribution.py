"""Topology-aware peer redistribution between prosumer buses / microgrid nodes (no households).

Per trading interval (12 samples x 5 s... see INTERVAL_STEPS):
  surplus S = G - C (kW, interval mean); the OFFER is capped by the FORECAST surplus (forecast demand from the TA-GNN, generation by persistence),
  bids come from forecast deficits; offers are sorted by ask price, bids by maximum price and matched (journal), or matched by the conference
  rule (Eqs 14-15: a single offer must cover the whole request at price <= the bid maximum);
  among compatible offers a bid prefers the one with the lowest ask + RHO * (electrical resistance of the least-loss path) - "least-loss paths";
  every candidate match is checked with pandapower on the ACTIVE topology (voltage 0.95-1.05, loading <= 100 %, same connected section); an
  infeasible quantity is bisected down (up to 3 times) and dropped if nothing fits (counted as "infeasible rejected");
  the metered quantities are q_s = what the seller delivered and q_b = what the buyer received after its share of line losses; settlement
  is Pay = p * min(q_s, q_b) on the EnergyMarket contract (when a chain is attached);
  nothing feasible left -> storage -> grid import (identical storage policy in the no-trading baseline, so the reduction is due to trading only).
PROVENANCE: simulated_testbed.
"""
from __future__ import annotations

import numpy as np
import networkx as nx

from testbed import powerflow as pf
from testbed.topologies import Topology

DT_S = 5
INTERVAL_STEPS = 60  # 5 min trading interval
TAU_H = INTERVAL_STEPS * DT_S / 3600.0
ASK = (60, 110)  # milli-currency / kWh
BID_MAX = (120, 140)
GRID_IMPORT_PRICE = 150
FEED_IN_PRICE = 40
RHO_LOSS = 0.5  # milli / kWh per ohm of path resistance (least-loss preference)
MIN_KW = 0.5
V_LIM = (0.95, 1.05)
LOAD_LIM = 100.0


def path_resistance(top: Topology, status: np.ndarray) -> np.ndarray:
    g = nx.Graph()
    g.add_nodes_from(range(top.n))
    net = top.net
    for ln in top.lines:
        if status[ln.id]:
            r = float(net.line.r_ohm_per_km.iat[ln.id] * net.line.length_km.iat[ln.id])
            g.add_edge(ln.a, ln.b, w=r)
    d = dict(nx.all_pairs_dijkstra_path_length(g, weight="w"))
    R = np.full((top.n, top.n), np.inf)
    for a, row in d.items():
        for b, v in row.items():
            R[a, b] = v
    return R


class Intervals:
    """One day of actual / forecast arrays on a fixed switch state."""

    def __init__(self, top: Topology, status: np.ndarray, demand: np.ndarray, gen: np.ndarray, yhat: np.ndarray | None, allow_island: bool = True):
        self.top, self.status, self.demand, self.gen, self.yhat, self.allow_island = top, status, demand, gen, yhat, allow_island
        self.R = path_resistance(top, status)
        self.ev = pf.Evaluator(top)
        g = top.graph(status)
        self.comp = {}
        for ci, c in enumerate(nx.connected_components(g)):
            for x in c:
                self.comp[x] = ci
        self.grid = next(nd.id for nd in top.nodes if nd.kind == "grid")
        self.stor_cap = np.array([nd.storage_kwh for nd in top.nodes])
        self.stor_pw = np.array([nd.storage_kw for nd in top.nodes])

    def _state(self, D, export):
        N = self.top.n
        return dict(status=self.status, demand_kw=D, served=np.ones(N), gen_kw=export, stor_kw=np.zeros(N), allow_island=self.allow_island)

    def _viol(self, D, export):
        r = self.ev.evaluate(self._state(D, export))
        if not r.converged:
            return None, r
        v = r.vm[r.energised]
        dv = np.maximum(V_LIM[0] - v, 0).sum() + np.maximum(v - V_LIM[1], 0).sum()
        ov = np.maximum(r.loading[self.status] - LOAD_LIM, 0).sum() / 100.0
        return float(dv + ov), r


def run(iv: Intervals, seed: int, rule: str = "journal", chain=None, accounts: dict | None = None, k_range: range | None = None, trade: bool = True) -> dict:
    top, N = iv.top, iv.top.n
    rng = np.random.default_rng(seed)
    T = len(iv.demand)
    K = T // INTERVAL_STEPS
    ks = k_range if k_range is not None else range(K)
    soc = np.where(iv.stor_cap > 0, 0.5 * iv.stor_cap, 0.0)
    prev_G = None
    tot = dict(consumption_kwh=0.0, import_kwh=0.0, import_notrade_kwh=0.0, traded_kwh=0.0, received_kwh=0.0, losses_kwh=0.0, losses_notrade_kwh=0.0, trades=0,
               infeasible_rejected=0, reduced=0, offers=0, bids=0, expired=0, paid_milli=0.0, curtailed_kwh=0.0)
    trade_log = []
    series = []
    frames = []
    node_ok = np.array([True] * N)
    for k in ks:
        sl = slice(k * INTERVAL_STEPS, (k + 1) * INTERVAL_STEPS)
        C = iv.demand[sl].mean(0)
        G = iv.gen[sl].mean(0)
        Ch = iv.yhat[sl].mean(0) if iv.yhat is not None else C
        Gh = prev_G if prev_G is not None else G
        prev_G = G.copy()
        # energised participants only (dead sections cannot trade)
        base_state = iv._state(np.maximum(C - G, 0), np.zeros(N))
        r0 = iv.ev.evaluate(base_state)
        alive = r0.energised.copy() if r0.converged else np.ones(N, bool)
        is_grid = np.arange(N) == iv.grid
        S = np.where(alive & ~is_grid, G - C, 0.0)
        Sh = np.where(alive & ~is_grid, Gh - Ch, 0.0)
        D_act = np.maximum(-S, 0)
        # ----- storage policy shared by baseline and trading: applied AFTER trading to leftovers -----
        offers = [(i, float(Sh[i]), int(rng.integers(ASK[0], ASK[1] + 1))) for i in range(N) if Sh[i] > MIN_KW and S[i] > 0]
        bids = [(j, float(-Sh[j]), int(rng.integers(BID_MAX[0], BID_MAX[1] + 1))) for j in range(N) if -Sh[j] > MIN_KW and S[j] < 0]
        tot["offers"] += len(offers)
        tot["bids"] += len(bids)
        export = np.zeros(N)
        accepted = []
        rem_off = {i: q for i, q, _ in offers}
        ask = {i: p for i, _, p in offers}
        order_bids = sorted(bids, key=lambda b: -b[2])  # highest willingness to pay first (price priority)
        if trade and offers and bids:
            v_base, _ = iv._viol(D_act, export)
            v_base = v_base if v_base is not None else 0.0
            for j, qb, pmax in order_bids:
                need = min(qb, D_act[j])
                cands = [i for i in rem_off if rem_off[i] > MIN_KW and ask[i] <= pmax and iv.comp.get(i) == iv.comp.get(j)]
                cands.sort(key=lambda i: ask[i] + RHO_LOSS * (iv.R[i, j] if np.isfinite(iv.R[i, j]) else 1e6))
                for i in cands:
                    if need <= MIN_KW:
                        break
                    q = min(rem_off[i], need, S[i] - export[i])
                    if rule == "conference" and rem_off[i] < need:  # Eq. 15: Qoffer >= Qrequest
                        continue
                    if q <= MIN_KW:
                        continue
                    ok, scale = False, 1.0
                    for _ in range(4):
                        e2 = export.copy()
                        e2[i] += q * scale
                        v, res = iv._viol(D_act, e2)
                        if v is not None and v <= v_base + 1e-6:
                            ok = True
                            break
                        scale *= 0.5
                    if not ok:
                        tot["infeasible_rejected"] += 1
                        continue
                    if scale < 1.0:
                        tot["reduced"] += 1
                    q *= scale
                    export[i] += q
                    rem_off[i] -= q
                    need -= q
                    accepted.append(dict(seller=i, buyer=j, q_kw=q, price=ask[i]))
        # ----- physical result with the accepted exports -----
        v, res = iv._viol(D_act, export)
        losses_kw = float(res.losses_kw) if (v is not None and res is not None) else 0.0
        _, res0 = iv._viol(D_act, np.zeros(N))
        losses0_kw = float(res0.losses_kw) if res0 is not None and res0.converged else 0.0
        sum_q = sum(a["q_kw"] for a in accepted)
        delivered_scale = {}
        for a in accepted:
            delivered_scale.setdefault(a["seller"], 0.0)
            delivered_scale[a["seller"]] += a["q_kw"]
        received = np.zeros(N)
        for a in accepted:
            f_s = min(1.0, S[a["seller"]] / max(delivered_scale[a["seller"]], 1e-9))
            qs = a["q_kw"] * f_s
            qb = qs - (losses_kw * (a["q_kw"] / sum_q) if sum_q > 0 else 0.0)
            qb = max(min(qb, D_act[a["buyer"]] - received[a["buyer"]]), 0.0)
            received[a["buyer"]] += qb
            a.update(qs_kwh=qs * TAU_H, qb_kwh=qb * TAU_H)
        # leftovers: surplus -> storage charge (else curtailed); deficit -> storage discharge -> grid
        left_surplus = np.maximum(S - export, 0)
        left_deficit = np.maximum(D_act - received, 0)
        imp_trade = 0.0
        imp_notrade = 0.0
        soc_nt = soc.copy()
        for i in range(N):
            if iv.stor_cap[i] > 0:
                ch = min(left_surplus[i], iv.stor_pw[i], (0.9 * iv.stor_cap[i] - soc[i]) / TAU_H)
                ch = max(ch, 0)
                soc[i] += ch * TAU_H * 0.95
                dis = min(left_deficit[i], iv.stor_pw[i], max(soc[i] - 0.1 * iv.stor_cap[i], 0) / TAU_H)
                soc[i] -= dis * TAU_H
                left_deficit[i] -= dis
                tot["curtailed_kwh"] += (left_surplus[i] - ch) * TAU_H
                # same policy without trading
                ch0 = max(min(np.maximum(S[i], 0), iv.stor_pw[i], (0.9 * iv.stor_cap[i] - soc_nt[i]) / TAU_H), 0)
                soc_nt[i] += ch0 * TAU_H * 0.95
                dis0 = min(D_act[i], iv.stor_pw[i], max(soc_nt[i] - 0.1 * iv.stor_cap[i], 0) / TAU_H)
                soc_nt[i] -= dis0 * TAU_H
                imp_notrade += (D_act[i] - dis0) * TAU_H
            else:
                tot["curtailed_kwh"] += left_surplus[i] * TAU_H
                imp_notrade += D_act[i] * TAU_H
        imp_trade = float(left_deficit.sum()) * TAU_H
        tot["consumption_kwh"] += float(C[alive & ~is_grid].sum()) * TAU_H
        tot["import_kwh"] += imp_trade
        tot["import_notrade_kwh"] += imp_notrade
        tot["traded_kwh"] += sum(a["qs_kwh"] for a in accepted)
        tot["received_kwh"] += sum(a["qb_kwh"] for a in accepted)
        tot["losses_kwh"] += losses_kw * TAU_H
        tot["losses_notrade_kwh"] += losses0_kw * TAU_H
        tot["trades"] += len(accepted)
        # ----- on-chain -----
        if chain is not None and accepted:
            oid, bid_ids = {}, {}
            for i, q, p in offers:
                if export[i] > 0 or rem_off.get(i, 0) > 0:
                    oid[i] = chain.post_offer(accounts[i], int(q * TAU_H * 1000), p)
            for j, q, p in bids:
                bid_ids[j] = chain.post_bid(accounts[j], int(q * TAU_H * 1000), p)
            for a in accepted:
                try:
                    tr = chain.match(oid[a["seller"]], bid_ids[a["buyer"]])
                except Exception:  # contract refused (e.g. NothingToMatch: its remaining quantities were already used by an earlier match)
                    tot["chain_skipped"] = tot.get("chain_skipped", 0) + 1
                    continue
                tid = tr["id"]
                chain.meter(tid, int(a["qs_kwh"] * 1000), int(a["qb_kwh"] * 1000))
                ev = chain.settle(tid)
                tot["paid_milli"] += ev["payMilli"]
                a.update(trade_id=int(tid), pay_milli=int(ev["payMilli"]), settled_wh=int(ev["settledWh"]))
            for i in oid:
                pass
            chain.advance()
            for i, oi in oid.items():
                if rem_off.get(i, 0) > MIN_KW:
                    chain.expire_offer(oi, accounts[i])
                    tot["expired"] += 1
        elif chain is not None:
            chain.advance()
        trade_log.extend([dict(k=k, **a) for a in accepted])
        if res is not None and res.converged and res.line_p_kw is not None:
            frames.append(dict(k=k, hour=round(k * INTERVAL_STEPS * DT_S / 3600.0, 3), line_p_kw=np.round(res.line_p_kw, 1).tolist(), line_loss_kw=np.round(res.line_loss_kw, 2).tolist(),
                               inj_kw=np.round(export - D_act, 1).tolist(), vm=np.round(res.vm, 4).tolist(), soc=np.round(np.where(iv.stor_cap > 0, soc / np.maximum(iv.stor_cap, 1e-9), 0), 3).tolist(),
                               trades=[dict(s=a["seller"], b=a["buyer"], q_kw=round(a["q_kw"], 1), price=a["price"]) for a in accepted]))
        series.append(dict(k=k, hour=k * INTERVAL_STEPS * DT_S / 3600.0, consumption_kw=float(C[alive & ~is_grid].sum()), generation_kw=float(G[alive & ~is_grid].sum()),
                           traded_kw=float(sum_q), losses_kw=losses_kw, import_kw=imp_trade / TAU_H, import_notrade_kw=imp_notrade / TAU_H, trades=len(accepted)))
    cons = max(tot["consumption_kwh"], 1e-9)
    kpi = dict(energy_redistributed_kwh=tot["received_kwh"], energy_sent_kwh=tot["traded_kwh"], network_losses_kwh=tot["losses_kwh"],
               network_losses_without_trading_kwh=tot["losses_notrade_kwh"], local_self_sufficiency=1.0 - tot["import_kwh"] / cons,
               local_self_sufficiency_without_trading=1.0 - tot["import_notrade_kwh"] / cons,
               grid_import_reduction=(tot["import_notrade_kwh"] - tot["import_kwh"]) / max(tot["import_notrade_kwh"], 1e-9), trades=tot["trades"],
               infeasible_rejected=tot["infeasible_rejected"], matches_reduced=tot["reduced"], offers=tot["offers"], bids=tot["bids"], expired_offers=tot["expired"],
               paid_milli=tot["paid_milli"], chain_matches_refused=tot.get("chain_skipped", 0), consumption_kwh=tot["consumption_kwh"], grid_import_kwh=tot["import_kwh"], curtailed_kwh=tot["curtailed_kwh"])
    return dict(kpi=kpi, series=series, trades=trade_log, rule=rule, intervals=len(list(ks)), frames=frames)
