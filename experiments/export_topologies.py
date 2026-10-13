"""Export topology descriptions (nodes, lines, layout, N-1 connectivity) to experiments/results/topologies.json for the Topologies view."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import networkx as nx  # noqa: E402
import numpy as np  # noqa: E402

from testbed.topologies import build  # noqa: E402

FIXED = {
    "A": {0: (0, 150), 1: (220, 150), 2: (440, 60), 3: (440, 260), 4: (660, 0), 5: (660, 130)},
}


def layout(name, top):
    if name in FIXED:
        return FIXED[name]
    g = top.graph(np.ones(len(top.lines), dtype=bool))  # all lines incl. ties, for a stable embedding
    pos = nx.kamada_kawai_layout(g, scale=1.0)
    xs = np.array([p[0] for p in pos.values()])
    ys = np.array([p[1] for p in pos.values()])
    w, h = (1500, 900) if name == "C" else (1000, 650)
    return {i: (float((pos[i][0] - xs.min()) / (xs.max() - xs.min()) * w), float((pos[i][1] - ys.min()) / (ys.max() - ys.min()) * h)) for i in pos}


def n1(top):
    base = top.base_status()
    full = np.ones(len(top.lines), dtype=bool)
    kept_no, kept_ties, tested = 0, 0, 0
    for ln in top.lines:
        if ln.tie:
            continue
        tested += 1
        s = base.copy()
        s[ln.id] = False
        kept_no += nx.is_connected(top.graph(s))
        f = full.copy()
        f[ln.id] = False
        kept_ties += nx.is_connected(top.graph(f))
    return dict(lines_tested=tested, keeps_connected_no_ties=int(kept_no), keeps_connected=int(kept_ties))


def main():
    out = {}
    for name in "ABC":
        top = build(name)
        pos = layout(name, top)
        out[name] = dict(
            name=name, title=top.title, counts=top.counts(), n1=n1(top),
            nodes=[dict(id=nd.id, label=("S" if nd.kind == "solar" else "W" if nd.kind == "wind" else "H" if nd.kind == "hydro" else "G" if nd.kind == "grid" else "Cb" if nd.kind == "collector" else "L") + str(nd.id + 1),
                        kind=nd.kind, load_kw=nd.load_kw, gen_cap_kw=nd.gen_cap_kw, storage_kwh=nd.storage_kwh, storage_kw=nd.storage_kw, prosumer=bool(nd.load_kw > 0 and nd.gen_cap_kw > 0),
                        x=pos[nd.id][0], y=pos[nd.id][1]) for nd in top.nodes],
            lines=[dict(id=ln.id, a=ln.a, b=ln.b, tie=ln.tie, paper_no=ln.paper_no, rating_ka=top.rating_ka[ln.id], length_km=float(top.net.line.length_km.iat[ln.id])) for ln in top.lines])
    d = ROOT / "experiments" / "results"
    d.mkdir(parents=True, exist_ok=True)
    (d / "topologies.json").write_text(json.dumps(out))
    print({k: v["n1"] for k, v in out.items()})


if __name__ == "__main__":
    main()
