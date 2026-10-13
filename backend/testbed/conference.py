"""Conference testbed (experiment config): 12 nodes (4 solar, 4 wind, 4 hydro) in a ring
with chords, 365 days at 15-minute sampling = 35,040 samples/node, 420,480 in total.

PROVENANCE: every number produced from this module is `simulated_testbed`. Nothing here
reads Kelmarsh data. Settings are fixed in PREREGISTRATION.md section C before any run.

Generation models (conference Sec. III-A): clear-sky irradiance with cloud cover (solar),
cubic power curve of wind speed (wind), seasonal flow profile (hydro). Faults: on average
one per node every 8 days, lasting 1-8 h, output -> 0-70 % of normal, voltage dip 3-8 %;
the live neighbour with the most spare capacity picks up part of the lost power. The
twin's expected state carries a 5 % forecast error. Labels come from the injection log.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np

DAYS = 365
STEP_MIN = 15
STEPS = DAYS * 24 * 60 // STEP_MIN  # 35,040
N_NODES = 12
TYPES = ["solar", "wind", "hydro"] * 4  # node i -> TYPES[i]; 4 of each
CAP_KW = 50.0  # nameplate of every node (PREREGISTRATION C1)
V_NOM = 400.0
PF = 0.95
RING = [(i, (i + 1) % N_NODES) for i in range(N_NODES)]
CHORDS = [(0, 6), (1, 7), (3, 9), (4, 10)]
EDGES = RING + CHORDS

FAULT_MEAN_GAP_DAYS = 8.0
FAULT_DUR_H = (1.0, 8.0)
FAULT_OUT_FRAC = (0.0, 0.70)
FAULT_V_DIP = (0.03, 0.08)
DOWN_FRAC = 0.02  # a node producing < 2 % of nameplate counts as tripped for the adjacency
PICKUP_FRACTION = 0.5  # share of lost power the best neighbour takes over
TWIN_ERR_P = 0.05  # twin forecast error (conference text)
TWIN_ERR_V = 0.01  # voltage is measured more accurately than power (PREREGISTRATION C2)
TWIN_ERR_RHO = 0.5  # AR(1) correlation of the twin error

N_FEATURES = 7  # [P/cap, V/Vnom, I/Inom, driver (irradiance|wind speed|flow), sin hour, cos hour, sin day-of-year]
FEATURE_NAMES = ["power_pu", "voltage_pu", "current_pu", "resource_driver", "sin_hour", "cos_hour", "sin_doy"]
WINDOW = 8

SPLIT = (0.70, 0.15, 0.15)


def season_of(day: np.ndarray) -> np.ndarray:
    """0 summer (Mar-May), 1 monsoon (Jun-Sep), 2 winter (rest). `day` is day-of-year 0..364 of a non-leap year."""
    month_start = np.cumsum([0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])
    month = np.searchsorted(month_start, day, side="right") - 1  # 0=Jan
    out = np.full(day.shape, 2)
    out[(month >= 2) & (month <= 4)] = 0
    out[(month >= 5) & (month <= 8)] = 1
    return out


def _ar1(rng, n, rho, sigma):
    from scipy.signal import lfilter
    e = rng.normal(0, sigma * np.sqrt(1 - rho ** 2), n)
    x0 = rng.normal(0, sigma)
    e[0] = x0
    return lfilter([1.0], [1.0, -rho], e)


def config_hash() -> str:
    cfg = dict(DAYS=DAYS, STEP_MIN=STEP_MIN, N=N_NODES, TYPES=TYPES, CAP=CAP_KW, EDGES=EDGES, GAP=FAULT_MEAN_GAP_DAYS, DUR=FAULT_DUR_H,
               OUT=FAULT_OUT_FRAC, DIP=FAULT_V_DIP, PICK=PICKUP_FRACTION, EP=TWIN_ERR_P, EV=TWIN_ERR_V, SPLIT=SPLIT, W=WINDOW)
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:12]


def simulate(seed: int) -> dict:
    """One independent 365-day dataset. Returns arrays (float32) + the fault log."""
    rng = np.random.default_rng(seed)
    t = np.arange(STEPS)
    hour = (t * STEP_MIN / 60.0) % 24
    day = (t * STEP_MIN // (24 * 60)).astype(int)
    season = season_of(day)
    sin_h, cos_h = np.sin(2 * np.pi * hour / 24), np.cos(2 * np.pi * hour / 24)
    sin_d = np.sin(2 * np.pi * day / 365)

    # seasonal means (PREREGISTRATION C1)
    cloud_mean = np.array([0.20, 0.60, 0.25])[season]
    wind_mean = np.array([5.5, 7.5, 4.5])[season]
    flow_base = np.array([0.35, 1.00, 0.50])[season]

    P = np.zeros((N_NODES, STEPS))  # healthy (no-fault) power, kW
    drv = np.zeros((N_NODES, STEPS))
    elev = np.clip(np.sin(np.pi * (hour - 6.0) / 12.0), 0, None)
    season_gain = 1.0 + 0.15 * np.cos(2 * np.pi * (day - 172) / 365.0)
    for i, ty in enumerate(TYPES):
        if ty == "solar":
            cloud = np.clip(cloud_mean + _ar1(rng, STEPS, 0.97, 0.18), 0, 1)
            g = 1000.0 * elev ** 1.2 * season_gain * (1 - 0.75 * cloud ** 3.4)
            P[i] = CAP_KW * 0.85 * g / 1000.0
            drv[i] = g / 1000.0
        elif ty == "wind":
            w = np.clip(wind_mean + 1.2 * np.sin(2 * np.pi * (hour - 15) / 24) + _ar1(rng, STEPS, 0.985, 2.0), 0, 30)
            frac = np.where(w < 3, 0, np.where(w < 12, ((w - 3) / 9.0) ** 3, np.where(w < 25, 1.0, 0)))
            P[i] = CAP_KW * frac
            drv[i] = w / 25.0
        else:
            q = np.clip(flow_base * (1 + _ar1(rng, STEPS, 0.9995, 0.10)), 0.05, 1.2)
            P[i] = CAP_KW * np.clip(0.9 * q, 0, 1)
            drv[i] = q / 1.2
    V = V_NOM * (1 + 0.02 * (P / CAP_KW - 0.5)) + rng.normal(0, 0.002 * V_NOM, P.shape)
    # --- fault injection (labels from this log only) ---
    label = np.zeros((N_NODES, STEPS), dtype=np.int8)
    factor = np.ones((N_NODES, STEPS))
    dip = np.zeros((N_NODES, STEPS))
    log = []
    for i in range(N_NODES):
        s = 0
        p_start = 1.0 / (FAULT_MEAN_GAP_DAYS * 24 * 60 / STEP_MIN)
        while s < STEPS:
            s += int(rng.geometric(p_start))
            if s >= STEPS:
                break
            dur = int(rng.uniform(*FAULT_DUR_H) * 60 / STEP_MIN)
            e = min(STEPS, s + dur)
            f, d = rng.uniform(*FAULT_OUT_FRAC), rng.uniform(*FAULT_V_DIP)
            label[i, s:e] = 1
            factor[i, s:e] = f
            dip[i, s:e] = d
            log.append(dict(node=i, start=int(s), end=int(e), out_frac=float(f), v_dip=float(d)))
            s = e
    P_ph = P * factor
    V_ph = V * (1 - dip)
    # neighbour pick-up (Sec. III-A): live neighbour with the most spare capacity takes PICKUP_FRACTION of the lost power
    nbrs = [[] for _ in range(N_NODES)]
    for a, b in EDGES:
        nbrs[a].append(b)
        nbrs[b].append(a)
    down_mask = np.zeros((N_NODES, STEPS), dtype=bool)
    for ev in log:
        i, s, e = ev["node"], ev["start"], ev["end"]
        lost = P[i, s:e] - P_ph[i, s:e]
        live = [j for j in nbrs[i] if not label[j, s:e].any()]
        if live:
            spare = np.stack([CAP_KW - P_ph[j, s:e] for j in live])
            best = np.argmax(spare, axis=0)
            for k, j in enumerate(live):
                m = best == k
                add = np.minimum(PICKUP_FRACTION * lost, spare[k])
                P_ph[j, s:e][m] += add[m]
        down_mask[i, s:e] = P_ph[i, s:e] < DOWN_FRAC * CAP_KW  # output ~0: node effectively tripped, its links drop out of A(t)
    I_ph = P_ph / (np.sqrt(3) * V_ph * PF) * 1000.0  # A
    I_nom = CAP_KW / (np.sqrt(3) * V_NOM * PF) * 1000.0
    # --- twin expected state: healthy value with a 5 % AR(1) forecast error ---
    e_p = np.stack([_ar1(rng, STEPS, TWIN_ERR_RHO, TWIN_ERR_P) for _ in range(N_NODES)])
    e_v = np.stack([_ar1(rng, STEPS, TWIN_ERR_RHO, TWIN_ERR_V) for _ in range(N_NODES)])
    P_tw = P * (1 + e_p)
    V_tw = V * (1 + e_v)
    I_tw = P_tw / (np.sqrt(3) * V_tw * PF) * 1000.0

    feats = np.stack([P_ph / CAP_KW, V_ph / V_NOM, I_ph / I_nom, drv,
                      np.broadcast_to(sin_h, P.shape), np.broadcast_to(cos_h, P.shape), np.broadcast_to(sin_d, P.shape)], axis=-1)  # [N,T,7]
    twin = np.stack([P_tw / CAP_KW, V_tw / V_NOM, I_tw / I_nom], axis=-1)
    return dict(features=feats.astype(np.float32), twin=twin.astype(np.float32), power_kw=P_ph.astype(np.float32), healthy_kw=P.astype(np.float32),
                label=label, down=down_mask, season=season.astype(np.int8), day=day.astype(np.int16), faults=log, seed=seed)


def splits() -> dict:
    a = int(STEPS * SPLIT[0])
    b = a + int(STEPS * SPLIT[1])
    return dict(train=(0, a), val=(a, b), test=(b, STEPS))
