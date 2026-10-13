"""Journal simulator: 24 h per scenario at 5 s sampling (17,280 samples), 3 seeded iterations,
topologies A/B/C, 4 fault types x 5 per iteration at random instants.

Node features X(t) per node (journal Sec. III): [generation kW, consumption kW, voltage pu,
current kA (largest in-service incident line), SOC (0-1; 0 where there is no storage)].
Targets: Y(t+1) = requested demand of every node at t+1 (kW), c(t) = fault class from the
injection log (0 normal, 1 line outage, 2 feeder short-circuit, 3 loss of generation,
4 load surge). Line currents/loading and switch states are saved for the twin and for A(t).

Physical response only: faults persist until the (random) repair time; restoration actions
are evaluated separately by twin_eval (they do not alter the saved training data).

PROVENANCE: `simulated_testbed`. Wind/hydro/solar/load profiles are synthetic here
(PREREGISTRATION B/D); the ESP32/Open-Meteo/Kelmarsh data are not used.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.signal import lfilter

from testbed import powerflow as pf
from testbed.topologies import Topology, build

DT_S = 5
STEPS = 24 * 3600 // DT_S  # 17,280
CLASSES = ["normal", "line_outage", "feeder_short_circuit", "loss_of_generation", "load_surge"]
N_PER_TYPE = 5
DUR_STEPS = (60, 180)  # 5-15 min until repaired
MIN_GAP_STEPS = 240  # 20 min between fault starts
START_MARGIN = (720, 400)  # no fault in the first hour / last 33 min
SURGE_FACTOR = (1.8, 2.5)
SC_RATIO = (1.6, 2.6)  # short-circuit current as a multiple of the line rating
SC_PF = 0.3
LOAD_OU = (60.0, 0.03)  # tau s, relative sigma
LOAD_WHITE = 0.005
METER_NOISE = dict(power=0.01, voltage=0.002, current=0.005)
SOLAR_CLOUD_OU = (300.0, 0.20)
WIND_OU = (600.0, 2.0)
WIND_MEAN = 7.0
HYDRO_OU = (3600.0, 0.05)
STORAGE_SOC0 = 0.5
SOC_BOUNDS = (0.1, 0.9)
DATA_ROOT = Path(__file__).resolve().parent / "data"


def _ou(rng, n, tau, sigma):
    rho = np.exp(-DT_S / tau)
    e = rng.normal(0, sigma * np.sqrt(1 - rho ** 2), n)
    e[0] = rng.normal(0, sigma)
    return lfilter([1.0], [1.0, -rho], e)


def daily_profile(h: np.ndarray) -> np.ndarray:
    """Aggregated bus-load daily shape (mean ~0.75): morning and evening peaks."""
    return 0.55 + 0.22 * np.exp(-0.5 * ((h - 8.0) / 2.2) ** 2) + 0.42 * np.exp(-0.5 * ((h - 19.0) / 2.5) ** 2)


def profiles(top: Topology, seed: int):
    rng = np.random.default_rng(seed)
    t = np.arange(STEPS)
    h = t * DT_S / 3600.0
    N = top.n
    demand = np.zeros((STEPS, N))
    gen = np.zeros((STEPS, N))
    base = daily_profile(h)
    for nd in top.nodes:
        if nd.load_kw > 0:
            demand[:, nd.id] = nd.load_kw / 0.75 * base * (1 + _ou(rng, STEPS, *LOAD_OU) + rng.normal(0, LOAD_WHITE, STEPS))
        if nd.gen_cap_kw > 0:
            if nd.kind == "solar":
                cs = np.clip(np.sin(np.pi * (h - 6.0) / 12.0), 0, None) ** 1.2
                cloud = np.clip(0.25 + _ou(rng, STEPS, *SOLAR_CLOUD_OU) * 1.0 + 0.15, 0, 0.8)  # cloud cover in [0, 0.8]
                gen[:, nd.id] = nd.gen_cap_kw * 0.9 * cs * (1 - 0.75 * cloud ** 3.4) * (1 + rng.normal(0, 0.01, STEPS))
            elif nd.kind == "wind":
                w = np.clip(WIND_MEAN + _ou(rng, STEPS, *WIND_OU), 0, 30)
                frac = np.where(w < 3, 0, np.where(w < 12, ((w - 3) / 9.0) ** 3, np.where(w < 25, 1.0, 0)))
                gen[:, nd.id] = nd.gen_cap_kw * frac
            else:  # hydro
                gen[:, nd.id] = nd.gen_cap_kw * np.clip(0.7 + _ou(rng, STEPS, *HYDRO_OU), 0.2, 1.0)
    return np.clip(demand, 0, None), np.clip(gen, 0, None), rng


def schedule_faults(top: Topology, rng, force_line: int | None = None) -> list[dict]:
    """4 types x 5 at random instants. With `force_line` (Table VIII scenario) every event is a line outage on that line (20 events)."""
    types = [1] * N_PER_TYPE + [2] * N_PER_TYPE + [3] * N_PER_TYPE + [4] * N_PER_TYPE
    if force_line is not None:
        types = [1] * (4 * N_PER_TYPE)
    rng.shuffle(types)
    n = len(types)
    lo, hi = START_MARGIN[0], STEPS - START_MARGIN[1]
    # uniform random instants with a minimum gap: sample in a shortened span, then add i * gap (always feasible)
    base = np.sort(rng.integers(0, hi - lo - (n - 1) * MIN_GAP_STEPS, n))
    starts = lo + base + np.arange(n) * MIN_GAP_STEPS
    gens = [nd.id for nd in top.nodes if nd.gen_cap_kw > 0]
    loads = [nd.id for nd in top.nodes if nd.load_kw > 0 and nd.kind != "grid"]
    cand_lines = [ln.id for ln in top.lines if not ln.tie]
    out = []
    for k, (s, ty) in enumerate(zip(starts, types)):
        ev = dict(id=k, type=int(ty), class_name=CLASSES[ty], start=int(s), duration=int(rng.integers(DUR_STEPS[0], DUR_STEPS[1] + 1)))
        if ty in (1, 2):
            ev["line"] = int(rng.choice(cand_lines)) if force_line is None else int(force_line)
            if ty == 2:
                ev["sc_ratio"] = float(rng.uniform(*SC_RATIO))
        elif ty == 3:
            ev["node"] = int(rng.choice(gens))
        else:
            ev["node"] = int(rng.choice(loads))
            ev["factor"] = float(rng.uniform(*SURGE_FACTOR))
        ev["end"] = ev["start"] + ev["duration"]
        out.append(ev)
    return out


def fault_state_at(top: Topology, ev: dict | None, state: dict) -> dict:
    """Apply one fault event's physical effect to a state (returns a modified copy)."""
    st = dict(state)
    if ev is None:
        return st
    st["status"] = state["status"].copy()
    st["demand_kw"] = state["demand_kw"].copy()
    st["gen_kw"] = state["gen_kw"].copy()
    ty = ev["type"]
    if ty == 1:
        st["status"][ev["line"]] = False
    elif ty == 2:
        ln = top.lines[ev["line"]]
        vn = float(top.net.bus.vn_kv.iloc[ln.b])
        s_kva = ev["sc_ratio"] * 1.7320508 * vn * top.rating_ka[ev["line"]] * 1000  # kVA
        st["fault_shunt"] = {top.nodes[ln.b].bus: (s_kva * SC_PF, s_kva * (1 - SC_PF ** 2) ** 0.5)}
        st["sc_line"] = ev["line"]
    elif ty == 3:
        st["gen_kw"][ev["node"]] = 0.0
    else:
        st["demand_kw"][ev["node"]] *= ev["factor"]
    return st


def storage_dispatch(top: Topology, demand_t, gen_t, soc, h) -> np.ndarray:
    """Rule-based storage: charge on net generation surplus, discharge half of the deficit; SOC limits respected. Returns kW (+ charging)."""
    net_surplus = gen_t.sum() - demand_t.sum()
    p = np.zeros(top.n)
    stor = [nd for nd in top.nodes if nd.storage_kwh > 0]
    if not stor:
        return p
    tot_pw = sum(nd.storage_kw for nd in stor)
    for nd in stor:
        share = nd.storage_kw / tot_pw
        want = np.clip(net_surplus * share, -nd.storage_kw, nd.storage_kw) if net_surplus > 0 else np.clip(0.5 * net_surplus * share, -nd.storage_kw, 0)
        if want > 0 and soc[nd.id] >= SOC_BOUNDS[1]:
            want = 0.0
        if want < 0 and soc[nd.id] <= SOC_BOUNDS[0]:
            want = 0.0
        p[nd.id] = want
    return p


SCENARIO_KINDS = {"train": ("journal_{t}", 0), "eval": ("journal_{t}_eval", 50000), "c1213": ("journal_C_1213", 90000)}


def run(top_name: str, iteration: int, kind: str = "train") -> dict:
    """kind: train = the 3 training/validation iterations; eval = fresh held-out self-healing scenarios (other seeds, same generator);
    c1213 = topology C with 20 line outages between buses 12 and 13 (Table VIII)."""
    top = build(top_name)
    seed = SCENARIO_KINDS[kind][1] + 1000 * (iteration + 1) + {"A": 1, "B": 2, "C": 3}[top_name]
    demand, gen, rng = profiles(top, seed)
    force = None
    if kind == "c1213":
        force = top.line_between(11, 12).id  # paper buses 12-13
    faults = schedule_faults(top, rng, force)
    ev_at = {}
    for ev in faults:
        for t in range(ev["start"], ev["end"]):
            ev_at[t] = ev
    E, N = len(top.lines), top.n
    ev_ = pf.Evaluator(top)
    X = np.zeros((STEPS, N, 5), np.float32)
    status_log = np.zeros((STEPS, E), bool)
    line_i = np.zeros((STEPS, E), np.float32)
    line_load = np.zeros((STEPS, E), np.float32)
    label = np.zeros(STEPS, np.int8)
    unserved = np.zeros((STEPS, N), np.float32)
    losses = np.zeros(STEPS, np.float32)
    slack = np.zeros(STEPS, np.float32)
    flow_ok = np.ones(STEPS, bool)
    soc = np.zeros(N)
    cap_kwh = np.array([nd.storage_kwh for nd in top.nodes])
    soc[cap_kwh > 0] = STORAGE_SOC0
    base_status = top.base_status()
    meter = np.random.default_rng(seed + 7)
    for t in range(STEPS):
        h = t * DT_S / 3600.0
        ev = ev_at.get(t)
        stor_kw = storage_dispatch(top, demand[t], gen[t], soc, h)
        st = dict(status=base_status.copy(), demand_kw=demand[t], served=np.ones(N), gen_kw=gen[t].copy(), stor_kw=stor_kw, allow_island=False)
        st = fault_state_at(top, ev, st)
        r = ev_.evaluate(st)
        flow_ok[t] = r.converged
        label[t] = ev["type"] if ev else 0
        status_log[t] = st["status"]
        line_i[t] = r.line_i_ka
        line_load[t] = r.loading
        unserved[t] = r.unserved_kw
        losses[t] = r.losses_kw
        slack[t] = r.slack_kw
        # SOC update (+ charging)
        soc += stor_kw * DT_S / 3600.0 * 0.95 / np.where(cap_kwh > 0, cap_kwh, 1.0) * (cap_kwh > 0)
        soc = np.clip(soc, 0, 1)
        # node currents: largest in-service incident line
        inc = np.zeros(N)
        for ln in top.lines:
            if st["status"][ln.id]:
                inc[ln.a] = max(inc[ln.a], r.line_i_ka[ln.id])
                inc[ln.b] = max(inc[ln.b], r.line_i_ka[ln.id])
        X[t, :, 0] = r.gen_out_kw * (1 + meter.normal(0, METER_NOISE["power"], N))
        X[t, :, 1] = r.served_kw * (1 + meter.normal(0, METER_NOISE["power"], N))
        X[t, :, 2] = r.vm * (1 + meter.normal(0, METER_NOISE["voltage"], N)) * (r.vm > 0)
        X[t, :, 3] = inc * (1 + meter.normal(0, METER_NOISE["current"], N))
        X[t, :, 4] = soc
    Y = np.vstack([demand[1:], demand[-1:]]).astype(np.float32)  # Y(t+1)
    return dict(X=X, Y=Y, label=label, status=status_log, line_i_ka=line_i, line_loading=line_load, unserved_kw=unserved, losses_kw=losses,
                slack_kw=slack, converged=flow_ok, faults=faults, demand_kw=demand.astype(np.float32), gen_kw=gen.astype(np.float32), seed=seed,
                topology=top_name, iteration=iteration, kind=kind, retries=ev_.retries)


def config_hash() -> str:
    cfg = {k: (v if not isinstance(v, np.ndarray) else v.tolist()) for k, v in dict(
        DT=DT_S, DUR=DUR_STEPS, GAP=MIN_GAP_STEPS, MARGIN=START_MARGIN, SURGE=SURGE_FACTOR, SC=SC_RATIO, SCPF=SC_PF, LOAD=LOAD_OU, WHITE=LOAD_WHITE,
        METER=METER_NOISE, CLOUD=SOLAR_CLOUD_OU, WIND=WIND_OU, WM=WIND_MEAN, HYDRO=HYDRO_OU, SOC0=STORAGE_SOC0, SOCB=SOC_BOUNDS, NT=N_PER_TYPE).items()}
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:12]


def save(d: dict, root: Path = DATA_ROOT) -> Path:
    out = root / SCENARIO_KINDS[d["kind"]][0].format(t=d["topology"]) / f"it{d['iteration']}"
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out / "data.npz", X=d["X"], Y=d["Y"], label=d["label"], status=d["status"], line_i_ka=d["line_i_ka"], line_loading=d["line_loading"],
                        unserved_kw=d["unserved_kw"], losses_kw=d["losses_kw"], slack_kw=d["slack_kw"], demand_kw=d["demand_kw"], gen_kw=d["gen_kw"])
    (out / "faults.json").write_text(json.dumps(d["faults"], indent=1))
    n = len(d["label"])
    split = int(0.8 * n)
    manifest = dict(provenance="simulated_testbed", kind=d["kind"], topology=d["topology"], iteration=d["iteration"], seed=d["seed"], config_hash=config_hash(), samples=n,
                    dt_s=DT_S, split=dict(train=[0, split], val=[split, n], rule="first 80 % chronological / rest validation"),
                    counts=build(d["topology"]).counts(), faults=len(d["faults"]), faults_per_type={CLASSES[t]: sum(f["type"] == t for f in d["faults"]) for t in range(1, 5)},
                    nonconverged_steps=int((~d["converged"]).sum()), shunt_retries=int(d["retries"]), feature_names=["gen_kw", "cons_kw", "voltage_pu", "current_ka", "soc"], classes=CLASSES)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    assert n == STEPS  # 17,280 for the real runs (24 h at 5 s)
    return out


if __name__ == "__main__":
    import sys
    import time

    top_name, it = sys.argv[1], int(sys.argv[2])
    kind = sys.argv[3] if len(sys.argv) > 3 else "train"
    t0 = time.time()
    d = run(top_name, it, kind)
    p = save(d)
    print(top_name, it, kind, "saved", p, f"{time.time() - t0:.0f}s", "nonconv", int((~d["converged"]).sum()), flush=True)
