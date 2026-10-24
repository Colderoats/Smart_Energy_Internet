"""solar_hardware node for topologies A (radial), B (meshed) and C (IEEE 33-bus).

ONE data source: the ESP32 + INA219 mini panel (firmware/solar_hardware, app/ingestion/solar_hardware.py). Its readings are
normalised per-unit of the panel's rating and scaled to the node's `gen_cap_kw`, so a few-watt panel can drive a kW-scale
feeder. That scaling is an ASSUMPTION of this testbed: the measured SHAPE is real, the magnitude on the feeder is not.

`build()` in topologies.py is unchanged (its node/line counts are the paper's Table III, pinned by tests), so the node is
added by `build_with_hardware(name)`, which returns a COPY with one extra solar leaf bus + one line.
PROVENANCE: topology `simulated_testbed`; the per-unit series is `sensed` (hardware) when it comes from a capture file.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pandapower as pp

from testbed.topologies import Line, Node, Topology, build

NODE_NAME = "solar_hardware"
# Attach point per topology (0-based node index): A feeder bus (node 2, 1-based), B collector hub (node 4), C mid-feeder bus 10.
ATTACH = {"A": 1, "B": 3, "C": 9}
GEN_CAP_KW = 50.0  # feeder-scale rating the per-unit hardware series is multiplied by (assumption, see module docstring)
RATED_MW = 526.0  # panel rating in mW (0.526 W) the INA219 power is divided by; keep equal to SOLAR_HARDWARE_RATED_KW (x1e6) in app/twin/digital_twin.py


def build_with_hardware(name: str, gen_cap_kw: float = GEN_CAP_KW) -> Topology:
    """Copy of topology `name` plus the solar_hardware leaf (last node id, last line id). Line electrical data is copied from the
    first existing line at the attach bus, so no new network parameters are invented."""
    top = copy.deepcopy(build(name))
    at = ATTACH[name]
    new = top.n
    ref = next(ln for ln in top.lines if at in (ln.a, ln.b) and not ln.tie)
    ref_row = top.net.line.iloc[ref.id]
    top.nodes.append(Node(new, "solar", new, gen_cap_kw=gen_cap_kw, label=NODE_NAME))
    line = Line(len(top.lines), at, new, paper_no=len(top.lines) + 1)
    top.lines.append(line)
    pp.create_bus(top.net, vn_kv=float(top.net.bus.vn_kv.iloc[at]), name=f"n{new}")
    pp.create_line_from_parameters(top.net, at, new, float(ref_row.length_km), r_ohm_per_km=float(ref_row.r_ohm_per_km),
                                   x_ohm_per_km=float(ref_row.x_ohm_per_km), c_nf_per_km=0.0, max_i_ka=float(ref_row.max_i_ka), name=f"L{line.id + 1}")
    pp.create_sgen(top.net, new, p_mw=0.0, q_mvar=0.0, name=f"gen{new}")
    top.rating_ka[line.id] = float(ref_row.max_i_ka)
    return top


def hardware_node(top: Topology) -> Node:
    return next(nd for nd in top.nodes if nd.label == NODE_NAME)


def load_pu_series(path: str | Path, rated_mw: float = RATED_MW) -> np.ndarray:
    """Per-unit power series (clipped to [0, 1]) from a capture file written by scripts/capture_solar_hardware.py (JSON lines
    with p_mw)."""
    vals = []
    for line in Path(path).read_text().splitlines():
        try:
            d = json.loads(line)
            vals.append(float(d["p_mw"]))
        except (ValueError, KeyError, TypeError):
            continue
    return np.clip(np.array(vals) / rated_mw, 0.0, 1.0)


def apply_pu(top: Topology, pu: float) -> float:
    """Set the hardware node's generation for one power-flow run; returns the injected kW."""
    nd = hardware_node(top)
    kw = float(np.clip(pu, 0.0, 1.0)) * nd.gen_cap_kw
    idx = top.net.sgen.index[top.net.sgen.name == f"gen{nd.id}"][0]
    top.net.sgen.at[idx, "p_mw"] = kw / 1000
    return kw
