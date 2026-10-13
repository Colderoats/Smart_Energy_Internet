"""Journal self-healing evaluation: twin-based scheme vs the default scheme, on pandapower.

Default scheme  : threshold protection (persistent over-current / under-voltage / under-power
                  alarm) + a FIXED rule-based restoration sequence: isolate the faulted section,
                  then try the tie switches in their fixed list order, keeping the first one whose
                  closing is feasible (every operation is followed by a verification interval);
                  no islanding, no curtailment, no cost evaluation.
Twin scheme     : the TA-GNN fault head raises the alarm; the twin localises the fault from
                  measurements, enumerates the action set Omega, simulates every candidate with
                  pandapower on a copy of the state, rejects infeasible ones and applies
                  a* = argmin J (Eq. 5/7), J = w1*E_uns + w2*V_viol + w3*N_sw.
Both schemes sit behind the same protection backstop (an over-current feeder trips after
PROT_STEPS samples). Timing constants are fixed in PREREGISTRATION.md section E.

T_rec (Eq. 22) = t_restored - t_fault, evaluated only for faults that interrupted supply.
E_uns          = integral of unserved power from t_fault to the repair instant.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from testbed import journal_sim as JS
from testbed import powerflow as pf
from testbed.topologies import FLEX_SHARE, Topology

DT = JS.DT_S
# ---- fixed a priori (PREREGISTRATION E) ----
W_E, W_V, W_SW = 0.6, 0.3, 0.1  # w1 > w2, w3 (paper: unserved energy carries the largest weight)
N_SW_NORM = 4.0
HORIZON_S = 600.0  # planning horizon of E_uns inside J (a typical repair time)
T_SWITCH_S = 2.0  # one remote switching operation
VERIFY_STEPS = 1  # one sampling interval to confirm the state after an operation
PROT_STEPS = 3  # backup-protection persistence / default detection persistence (samples)
TWIN_PERSIST = 2  # TA-GNN alarm persistence (samples)
DECISION_STEPS = 1  # twin evaluates Omega within one prediction interval
TRIP_LOADING = 125.0  # feeder over-current trip level (% of rating)
DET_I = 1.2  # protection pick-up: line current / rating
DET_V = 0.90
DET_GEN_DROP = 0.5
HARD_V = (0.90, 1.10)
HARD_LOADING = 120.0
LOOKBACK = 12


@dataclass
class Scenario:
    top: Topology
    X: np.ndarray
    label: np.ndarray
    status: np.ndarray
    line_i: np.ndarray
    demand: np.ndarray
    gen: np.ndarray
    faults: list


def load_scenario(top: Topology, root, name: str) -> Scenario:
    import json
    from pathlib import Path
    p = Path(root) / name
    d = np.load(p / "data.npz")
    return Scenario(top, d["X"], d["label"], d["status"], d["line_i_ka"], d["demand_kw"], d["gen_kw"], json.loads((p / "faults.json").read_text()))


# ---------------------------------------------------------------- detection --------
def default_alarm(sc: Scenario) -> np.ndarray:
    """Threshold protection alarm per sample (persisted PROT_STEPS)."""
    top, X = sc.top, sc.X
    T = len(X)
    rating = np.array([top.rating_ka[ln.id] for ln in top.lines])
    over = (sc.line_i / rating[None, :] > DET_I).any(1)
    volt = X[:, :, 2]
    under = ((volt < DET_V) & (volt > 0) | ((volt == 0) & (np.arange(top.n)[None, :] > 0))).any(1)
    gens = [nd.id for nd in top.nodes if nd.gen_cap_kw > 0]
    g = X[:, gens, 0]
    pre = np.zeros_like(g)
    pre[LOOKBACK:] = g[:-LOOKBACK]
    cap = np.array([top.nodes[i].gen_cap_kw for i in gens])
    drop = ((pre - g) > DET_GEN_DROP * np.maximum(pre, 1e-9)) & (pre > 0.1 * cap[None, :])
    inst = over | under | drop.any(1)
    inst[:LOOKBACK] = False
    return _persist(inst, PROT_STEPS)


def _persist(a: np.ndarray, k: int) -> np.ndarray:
    out = np.zeros_like(a)
    run = 0
    for t, v in enumerate(a):
        run = run + 1 if v else 0
        out[t] = run >= k
    return out


def twin_alarm(pred_class: np.ndarray) -> np.ndarray:
    return _persist(pred_class != 0, TWIN_PERSIST)


def detection_f1(alarm: np.ndarray, label: np.ndarray) -> dict:
    y = label > 0
    tp = int((alarm & y).sum())
    fp = int((alarm & ~y).sum())
    fn = int((~alarm & y).sum())
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return dict(precision=p, recall=r, f1=2 * p * r / (p + r) if p + r else 0.0, tp=tp, fp=fp, fn=fn)


# --------------------------------------------------------------- localisation ------
def localize(sc: Scenario, t: int, cls: int) -> dict | None:
    """Fault location from MEASUREMENTS only (switch states, line currents, bus power) - never from the injection log."""
    top = sc.top
    base = top.base_status()
    pre = slice(max(t - 2 * LOOKBACK, 0), max(t - LOOKBACK, 1))
    if cls == 1:
        opened = [ln.id for ln in top.lines if base[ln.id] and not sc.status[t, ln.id]]
        return dict(type=1, line=opened[0]) if opened else None
    if cls == 2:
        rating = np.array([top.rating_ka[ln.id] for ln in top.lines])
        r = np.where(sc.status[t], sc.line_i[t] / rating, 0)
        over = [int(i) for i in np.nonzero(r > 1.0)[0]]
        if not over:
            return None
        # fault current flows from the source up to the fault, so every upstream line is also overloaded: the faulted line is the overloaded one farthest from the grid
        import networkx as nx
        g = top.graph(sc.status[t])
        grid = next(nd.id for nd in top.nodes if nd.kind == "grid")
        dist = nx.single_source_shortest_path_length(g, grid)
        far = lambda i: max(dist.get(top.lines[i].a, -1), dist.get(top.lines[i].b, -1))
        return dict(type=2, line=max(over, key=lambda i: (far(i), r[i])))
    if cls == 3:
        gens = [nd.id for nd in top.nodes if nd.gen_cap_kw > 0]
        d = sc.X[pre][:, gens, 0].mean(0) - sc.X[t, gens, 0]
        return dict(type=3, node=gens[int(np.argmax(d))]) if d.max() > 0 else None
    if cls == 4:
        loads = [nd.id for nd in top.nodes if nd.load_kw > 0 and nd.kind != "grid"]
        d = sc.X[t, loads, 1] - sc.X[pre][:, loads, 1].mean(0)
        return dict(type=4, node=loads[int(np.argmax(d))], factor=float(1 + d.max() / max(sc.X[pre][:, loads[int(np.argmax(d))], 1].mean(), 1e-6))) if d.max() > 0 else None
    return None


# ------------------------------------------------------------------ candidates -----
@dataclass
class Action:
    ops: list  # [("open", line), ("close", line)]
    curtail: bool
    island: bool
    label: str
    storage: bool = False

    @property
    def n_sw(self) -> int:
        """Switching operations: breaker moves + 1 if a section is islanded (grid-forming set-point) + 1 if flexible load is curtailed."""
        return len(self.ops) + (1 if self.island else 0) + (1 if self.curtail else 0)


def apply_action(top: Topology, st: dict, act: Action, affected: list) -> dict:
    s = dict(st)
    s["status"] = st["status"].copy()
    for op in act.ops:
        s["status"][op[1]] = op[0] == "close"
    s["served"] = st["served"].copy()
    if act.curtail:
        for i in affected:
            if top.nodes[i].load_kw > 0:
                s["served"][i] *= 1 - FLEX_SHARE
    s["allow_island"] = act.island
    if s.get("fault_shunt") and any(o[0] == "open" and o[1] == s.get("sc_line", -1) for o in act.ops):
        s.pop("fault_shunt")  # isolating the short-circuited line removes the fault current
    if act.storage:
        stor = np.zeros(top.n)
        for nd in top.nodes:
            if nd.storage_kwh > 0:
                stor[nd.id] = -nd.storage_kw  # full discharge (- = discharging)
        s["stor_kw"] = stor
    return s


def believed_state(sc: Scenario, belief: dict | None, t: int) -> dict:
    """The twin's picture of the faulted network at detection time t: measured status, pre-fault demand/availability estimate."""
    top = sc.top
    pre = slice(max(t - 2 * LOOKBACK, 0), max(t - LOOKBACK, 1))
    dem = np.maximum(sc.X[pre][:, :, 1].mean(0), 0)
    gen = np.maximum(sc.X[pre][:, :, 0].mean(0), 0)
    for i in range(top.n):  # buses that were not yet fully fed pre-fault keep their demand estimate from the plan
        if top.nodes[i].load_kw > 0 and dem[i] <= 0:
            dem[i] = top.nodes[i].load_kw * 0.75
    st = dict(status=sc.status[t].copy(), demand_kw=dem, served=np.ones(top.n), gen_kw=gen, stor_kw=np.zeros(top.n), allow_island=True)
    if belief:
        ty = belief["type"]
        if ty == 3:
            st["gen_kw"] = gen.copy()
            st["gen_kw"][belief["node"]] = 0.0
        elif ty == 4:
            st["demand_kw"] = dem.copy()
            st["demand_kw"][belief["node"]] *= belief.get("factor", 2.0)
        elif ty == 2:
            ln = top.lines[belief["line"]]
            vn = float(top.net.bus.vn_kv.iloc[ln.b])
            s_kva = 2.0 * 1.7320508 * vn * top.rating_ka[belief["line"]] * 1000
            st["fault_shunt"] = {top.nodes[ln.b].bus: (s_kva * JS.SC_PF, s_kva * (1 - JS.SC_PF ** 2) ** 0.5)}
            st["sc_line"] = belief["line"]
    return st


def enumerate_actions(top: Topology, belief: dict | None, st: dict) -> list[Action]:
    ties = [ln.id for ln in top.lines if ln.tie and not st["status"][ln.id]]
    acts: list[Action] = []
    isolate = []
    if belief and belief["type"] in (1, 2):
        isolate = [("open", belief["line"])]
    stor = bool(belief and belief["type"] in (3, 4))
    acts.append(Action(list(isolate), False, False, "open" if isolate else "none", stor))
    acts.append(Action(list(isolate), False, True, "open+island" if isolate else "island", stor))
    acts.append(Action(list(isolate), True, False, "open+curtail" if isolate else "curtail", stor))
    closed = [ln.id for ln in top.lines if st["status"][ln.id] and not ln.tie and (not isolate or ln.id != isolate[0][1])]
    for tie in ties:
        ops = isolate + [("close", tie)]
        base = "open+close_tie" if isolate else "close_tie"
        acts.append(Action(ops, False, False, base, stor))
        acts.append(Action(ops, True, False, base + "+curtail", stor))
        acts.append(Action(ops, False, True, base + "+island", stor))
        for m in closed:  # additionally split the network at switch m to island a DG-rich segment
            acts.append(Action(ops + [("open", m)], False, True, base + "+island", stor))
    # a plain curtail of the whole feasible set is already covered; deduplicate identical ops/flags
    seen, out = set(), []
    for a in acts:
        key = (tuple(sorted(a.ops)), a.curtail, a.island, a.storage)
        if key not in seen:
            seen.add(key)
            out.append(a)
    return out


def affected_buses(top: Topology, ev_: pf.Evaluator, st: dict) -> list:
    r = ev_.evaluate(st)
    aff = set(i for i in range(top.n) if (not r.energised[i]) or abs(r.vm[i] - 1) > 0.03)
    for ln in top.lines:
        if st["status"][ln.id] and r.loading[ln.id] > 90:
            aff.update([ln.a, ln.b])
    for c, shed, curt in r.islands:
        aff.update(c)
    return sorted(aff)


def cost(top: Topology, ev_: pf.Evaluator, st: dict, dem_ref: float) -> dict:
    r = ev_.evaluate(st)
    feas = r.converged
    if feas:
        v = r.vm[r.energised]
        if len(v) and (v.min() < HARD_V[0] or v.max() > HARD_V[1]):
            feas = False
        if (r.loading[st["status"]] > HARD_LOADING).any():
            feas = False
    e_uns = float(r.unserved_kw.sum()) * HORIZON_S / 3600.0
    e_norm = e_uns / max(dem_ref * HORIZON_S / 3600.0, 1e-9)
    v_viol = ev_.violation(r, st["status"]) / top.n
    return dict(feasible=feas, e_uns_kwh=e_uns, e_norm=e_norm, v_viol=v_viol, unserved_kw=float(r.unserved_kw.sum()), result=r)


def choose(top, ev_, belief, st, t_note="") -> dict:
    """a* = argmin J over feasible candidates of Omega (journal Eq. 5/7). All candidates are simulated on `st` (a copy)."""
    acts = enumerate_actions(top, belief, st)
    aff = affected_buses(top, ev_, st)
    dem_ref = float(np.sum(st["demand_kw"]))
    scored = []
    for a in acts:
        s2 = apply_action(top, st, a, aff)
        c = cost(top, ev_, s2, dem_ref)
        n_sw = a.n_sw
        J = W_E * c["e_norm"] + W_V * c["v_viol"] + W_SW * n_sw / N_SW_NORM
        scored.append(dict(action=a, J=J, n_sw=n_sw, feasible=c["feasible"], e_uns_kwh=c["e_uns_kwh"], v_viol=c["v_viol"]))
    feas = [s for s in scored if s["feasible"]]
    pool = feas if feas else scored  # nothing feasible: least-bad (flagged)
    best = min(pool, key=lambda s: (s["J"], s["n_sw"]))
    return dict(best=best, scored=scored, affected=aff, any_feasible=bool(feas), n_candidates=len(acts), n_rejected=len(scored) - len(feas))


# ------------------------------------------------------------- response timeline ---
def physical_state(sc: Scenario, ev: dict, t: int) -> dict:
    """Actual state at step t under the fault. Anti-islanding: a section without the grid connection stays de-energised
    unless an action explicitly enables islanded operation (allow_island)."""
    top = sc.top
    st = dict(status=top.base_status().copy(), demand_kw=sc.demand[t].astype(float), served=np.ones(top.n), gen_kw=sc.gen[t].astype(float),
              stor_kw=np.zeros(top.n), allow_island=False)
    return JS.fault_state_at(top, ev, st)


def _build(top, base_phys, applied, trips):
    s = {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in base_phys.items()}
    if applied:
        for kind, line in applied["ops"]:
            s["status"][line] = kind == "close"
        for i in applied["curtail"]:
            s["served"][i] *= 1 - FLEX_SHARE
        s["allow_island"] = applied["island"]
        if applied["storage"]:
            for nd in top.nodes:
                if nd.storage_kwh > 0:
                    s["stor_kw"][nd.id] = -nd.storage_kw
        if any(o[0] == "open" and o[1] == s.get("sc_line", -1) for o in applied["ops"]):
            s.pop("fault_shunt", None)
    for l in trips:
        s["status"][l] = False
        if s.get("sc_line") == l:
            s.pop("fault_shunt", None)
    return s


def _trip_line(top, ev_, st):
    """Backstop over-current protection: the SC line, or the most overloaded in-service line above TRIP_LOADING."""
    if st.get("fault_shunt") and "sc_line" in st and st["status"][st["sc_line"]]:
        return st["sc_line"]
    r = ev_.evaluate(st)
    if not r.converged:
        return None
    cand = [(r.loading[ln.id], ln.id) for ln in top.lines if st["status"][ln.id] and r.loading[ln.id] > TRIP_LOADING]
    return max(cand)[1] if cand else None


def default_plan(sc, ev_, ev, base_phys, t_alarm):
    """Fixed sequence: isolate (open the faulted line), then close tie switches in list order; first feasible improving tie wins."""
    top, t0 = sc.top, ev["start"]
    t = (t_alarm - t0) * DT
    ops, plan = [], []
    dem_ref = float(np.sum(base_phys["demand_kw"]))
    if ev["type"] == 2:
        t += T_SWITCH_S + VERIFY_STEPS * DT
        ops = [("open", ev["line"])]
        plan.append(dict(time=t, ops=list(ops), curtail=[], island=False, storage=False, label="open"))
    elif ev["type"] == 1:
        t += VERIFY_STEPS * DT
    cur = _build(top, base_phys, plan[-1] if plan else None, [])
    c0 = cost(top, ev_, cur, dem_ref)
    label = "open" if ev["type"] in (1, 2) else "none"
    if c0["unserved_kw"] > 1e-6:
        for tie in [ln.id for ln in top.lines if ln.tie]:
            t += T_SWITCH_S
            trial = dict(time=t + VERIFY_STEPS * DT, ops=ops + [("close", tie)], curtail=[], island=False, storage=False, label="open+close_tie")
            c = cost(top, ev_, _build(top, base_phys, trial, []), dem_ref)
            t += VERIFY_STEPS * DT
            if c["feasible"] and c["unserved_kw"] < c0["unserved_kw"] - 1e-6:
                trial["time"] = t
                plan.append(trial)
                label = "open+close_tie"
                break
            t += T_SWITCH_S + VERIFY_STEPS * DT  # open the failed tie again and verify
    n_sw = len(plan[-1]["ops"]) if plan else 0
    return plan, dict(label=label, n_sw=n_sw, ops=[list(o) for o in (plan[-1]["ops"] if plan else [])], island=False, curtail=False)


def twin_plan(sc, ev_, ev, t_alarm, belief):
    top, t0 = sc.top, ev["start"]
    st_b = believed_state(sc, belief, min(t_alarm, sc.X.shape[0] - 1))
    ch = choose(top, ev_, belief, st_b)
    best = ch["best"]
    a = best["action"]
    t = (t_alarm + DECISION_STEPS - t0) * DT + a.n_sw * T_SWITCH_S + VERIFY_STEPS * DT
    cur_nodes = [i for i in ch["affected"] if top.nodes[i].load_kw > 0] if a.curtail else []
    plan = [dict(time=t, ops=list(a.ops), curtail=cur_nodes, island=a.island, storage=a.storage, label=a.label)]
    chosen = dict(label=a.label, ops=[list(o) for o in a.ops], island=a.island, curtail=a.curtail, storage=a.storage, affected=ch["affected"], n_sw=best["n_sw"], J=best["J"], n_candidates=ch["n_candidates"], n_rejected=ch["n_rejected"], any_feasible=ch["any_feasible"],
                  belief=belief, costs=[dict(label=s["action"].label, ops=s["action"].ops, J=s["J"], feasible=s["feasible"], n_sw=s["n_sw"], e_uns_kwh=s["e_uns_kwh"],
                                            v_viol=s["v_viol"]) for s in sorted(ch["scored"], key=lambda s: s["J"])[:12]])
    return plan, chosen


def respond(sc: Scenario, ev_: pf.Evaluator, ev: dict, scheme: str, t_alarm: int | None, belief: dict | None, floor: float = 0.0) -> dict:
    """Timeline of one fault under `scheme` ('default' | 'twin' | 'none'). Returns T_rec, E_uns and the action sequence."""
    top = sc.top
    t0, t_end = ev["start"], ev["end"]
    dur_s = (t_end - t0) * DT
    base_phys = physical_state(sc, ev, t0)
    plan, chosen = [], None
    if t_alarm is not None and t_alarm < t_end:
        if scheme == "default":
            plan, chosen = default_plan(sc, ev_, ev, base_phys, t_alarm)
        elif scheme == "twin":
            plan, chosen = twin_plan(sc, ev_, ev, t_alarm, belief)
    plan = [p for p in plan if p["time"] < dur_s]
    trip_due = PROT_STEPS * DT
    bps = sorted(set([0.0, trip_due] + [p["time"] for p in plan] + [p["time"] + trip_due for p in plan]))
    bps = [b for b in bps if b < dur_s] + [dur_s]
    trips: list[int] = []
    series = []
    for k, bt in enumerate(bps[:-1]):
        applied = None
        for p in plan:
            if p["time"] <= bt + 1e-9:
                applied = p
        if bt + 1e-9 >= trip_due:
            for _ in range(3):
                l = _trip_line(top, ev_, _build(top, base_phys, applied, trips))
                if l is None or l in trips:
                    break
                trips = trips + [l]
        r = ev_.evaluate(_build(top, base_phys, applied, trips))
        series.append((bt, bps[k + 1], float(r.unserved_kw.sum()), float(r.losses_kw), r.converged, float(r.vm[r.energised].min()) if r.energised.any() else 0.0,
                       float(r.loading.max())))
    e_uns = sum((b - a) / 3600.0 * u for a, b, u, *_ in series)
    eps = 1e-6 + 0.005 * max(floor, 1.0)
    bad = [k for k, (_, _, u, *_) in enumerate(series) if u > floor + eps]
    interrupted = bool(bad)  # restorable load was cut: more load unserved than the best feasible reconfiguration (the oracle floor) would leave
    t_rec = None
    if interrupted:
        last = bad[-1]
        t_rec = series[last][1]  # restorable load is back when unserved power first stays at the floor; never before repair -> the repair instant
    return dict(fault=ev["id"], type=ev["type"], line=ev.get("line"), node=ev.get("node"), scheme=scheme, t_alarm_step=t_alarm,
                detect_delay_s=None if t_alarm is None else (t_alarm - t0) * DT, restorable_floor_kw=floor, e_uns_kwh=e_uns, t_rec_s=t_rec, interrupted=interrupted, action=chosen, trips=trips, plan=plan, start=t0, duration_s=dur_s,
                timeline=[dict(t0=a, t1=b, unserved_kw=u, losses_kw=l, ok=c, vmin=vm, max_loading=ml) for a, b, u, l, c, vm, ml in series],
                peak_unserved_kw=max(u for _, _, u, *_ in series))


def restorable_floor(sc: Scenario, ev_: pf.Evaluator, ev: dict) -> float:
    """Evaluation reference (never used by either scheme): the least unserved power any feasible, non-curtailing action of Omega leaves on the TRUE faulted
    state. Load below this floor is 'restorable'; T_rec is the time until all of it is re-energised (journal: 'all the restorable load')."""
    top, t0 = sc.top, ev["start"]
    st = physical_state(sc, ev, t0)
    st["allow_island"] = True
    belief = {k: ev[k] for k in ("type", "line", "node", "factor") if k in ev}
    dem_ref = float(np.sum(st["demand_kw"]))
    best = None
    for a in enumerate_actions(top, belief, st):
        if a.curtail:
            continue
        c = cost(top, ev_, apply_action(top, st, a, []), dem_ref)
        if c["feasible"] and (best is None or c["unserved_kw"] < best):
            best = c["unserved_kw"]
    return float(best if best is not None else 0.0)


def first_alarm_after(alarm: np.ndarray, t0: int, t_end: int) -> int | None:
    seg = np.nonzero(alarm[t0:t_end])[0]
    return int(t0 + seg[0]) if len(seg) else None


def evaluate_scenario(sc: Scenario, pred_class: np.ndarray) -> dict:
    """Run every fault of the scenario under both schemes (and 'none' = protection only). `pred_class[t]` is the TA-GNN fault-head class per step."""
    top = sc.top
    ev_ = pf.Evaluator(top)
    a_def = default_alarm(sc)
    a_tw = twin_alarm(pred_class)
    out = dict(default=[], twin=[], none=[])
    for ev in sc.faults:
        t0, t_end = ev["start"], ev["end"]
        td = first_alarm_after(a_def, t0, t_end)
        tt = first_alarm_after(a_tw, t0, t_end)
        belief = localize(sc, tt, int(pred_class[tt])) if tt is not None else None
        floor = restorable_floor(sc, ev_, ev)
        out["default"].append(respond(sc, ev_, ev, "default", td, None, floor))
        out["twin"].append(respond(sc, ev_, ev, "twin", tt, belief, floor))
        out["none"].append(respond(sc, ev_, ev, "none", None, None, floor))
    return dict(results=out, detection=dict(default=detection_f1(a_def, sc.label), twin=detection_f1(a_tw, sc.label)))


def summarise(res: list[dict]) -> dict:
    tr = [r["t_rec_s"] for r in res if r["t_rec_s"] is not None]
    return dict(t_rec_mean_s=float(np.mean(tr)) if tr else float("nan"), t_rec_n=len(tr), e_uns_total_kwh=float(sum(r["e_uns_kwh"] for r in res)),
                faults=len(res), interrupted=sum(r["interrupted"] for r in res), undetected=sum(r["t_alarm_step"] is None for r in res))
