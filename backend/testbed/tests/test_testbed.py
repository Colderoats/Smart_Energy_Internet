"""Tests for the simulated testbed (paper reproduction). Run with the testbed venv (pandapower + torch):

    cd backend
    testbed\\venv\\Scripts\\python -m pytest testbed\\tests -q

Kept outside backend/tests so they need neither TimescaleDB nor the auth fixtures.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pytest

from testbed import journal_sim as JS
from testbed import powerflow as pf
from testbed.topologies import ALLOWED_KINDS, a_hat, build

TABLE_III = {"A": (6, 5, 2, 1), "B": (14, 20, 4, 2), "C": (33, 37, 6, 3)}


@pytest.mark.parametrize("name", "ABC")
def test_topology_matches_table_iii(name):
    top = build(name)
    c = top.counts()
    n, l, s, w = TABLE_III[name]
    assert (c["nodes"], c["lines"], c["solar"], c["wind_hydro"]) == (n, l, s, w)
    assert len(top.net.bus) == n and len(top.net.line) == l


def test_ieee33_ties_and_numbering():
    top = build("C")
    ties = [ln for ln in top.lines if ln.tie]
    assert [ln.paper_no for ln in ties] == [33, 34, 35, 36, 37]
    assert not top.net.line.in_service.iloc[32:].any() and top.net.line.in_service.iloc[:32].all()
    assert top.line_between(11, 12).paper_no == 12  # "line 12-13" of Table VIII (buses 12 and 13, 1-based)


@pytest.mark.parametrize("name", "ABC")
def test_only_allowed_node_kinds_and_no_households(name):
    top = build(name)
    assert set(top.kinds()) <= set(ALLOWED_KINDS)
    text = " ".join(nd.label.lower() for nd in top.nodes) + top.title.lower()
    assert "house" not in text and "household" not in text
    for nd in top.nodes:  # a prosumer bus is a bus with generation AND load
        if nd.kind in ("solar", "wind", "hydro"):
            assert nd.gen_cap_kw > 0


def test_a_hat_recomputed_on_switch_change():
    top = build("C")
    s0 = top.base_status()
    A0 = a_hat(top.adjacency(s0))
    s1 = s0.copy()
    s1[11] = False  # open line 12
    s1[32] = True  # close tie 33
    A1 = a_hat(top.adjacency(s1))
    assert not np.allclose(A0, A1)
    # symmetric normalisation of A + I
    At = top.adjacency(s1) + np.eye(33)
    d = At.sum(1)
    assert np.allclose(A1, At / np.sqrt(np.outer(d, d)))
    assert np.allclose(A1, A1.T)


@pytest.mark.parametrize("name", "ABC")
def test_fault_schedule_counts(name):
    top = build(name)
    rng = np.random.default_rng(1)
    f = JS.schedule_faults(top, rng)
    assert len(f) == 20
    assert [sum(e["type"] == t for e in f) for t in (1, 2, 3, 4)] == [5, 5, 5, 5]
    starts = np.array([e["start"] for e in f])
    assert np.all(np.diff(starts) >= JS.MIN_GAP_STEPS)
    assert starts.min() >= JS.START_MARGIN[0] and (starts + [e["duration"] for e in f]).max() < JS.STEPS
    assert JS.STEPS == 17280


def test_table_viii_schedule_is_20_outages_of_line_12_13():
    top = build("C")
    line = top.line_between(11, 12).id
    f = JS.schedule_faults(top, np.random.default_rng(2), force_line=line)
    assert len(f) == 20 and all(e["type"] == 1 and e["line"] == line for e in f)


def _base_state(top, t=12000, seed=5):
    demand, gen, _ = JS.profiles(top, seed)
    return dict(status=top.base_status(), demand_kw=demand[t], served=np.ones(top.n), gen_kw=gen[t].copy(), stor_kw=np.zeros(top.n), allow_island=False)


def test_cost_choice_prefers_lowest_J_and_rejects_infeasible():
    from testbed.twin_eval import journal_twin as jt
    top = build("C")
    ev = pf.Evaluator(top)
    base = _base_state(top)
    line = top.line_between(11, 12).id
    assert jt.W_E > jt.W_V and jt.W_E > jt.W_SW  # unserved energy carries the largest weight (paper)
    st = JS.fault_state_at(top, dict(type=1, line=line), base)
    ch = jt.choose(top, ev, dict(type=1, line=line), st)
    feas = [s for s in ch["scored"] if s["feasible"]]
    assert ch["n_candidates"] > 5 and feas
    assert ch["best"]["J"] == min(s["J"] for s in feas)
    assert ch["best"]["feasible"]
    # an action that leaves part of the network de-energised must cost more than one that restores it
    dead = next(s for s in ch["scored"] if s["action"].label == "open")
    assert dead["J"] > ch["best"]["J"]
    # infeasible: a 20x load surge makes every candidate violate the hard limits -> flagged, none feasible
    st2 = dict(st)
    st2["demand_kw"] = st["demand_kw"] * 20
    ch2 = jt.choose(top, ev, dict(type=1, line=line), st2)
    assert not ch2["any_feasible"] and ch2["n_rejected"] == ch2["n_candidates"]


def test_islanding_serves_load_only_when_allowed():
    top = build("A")
    ev = pf.Evaluator(top)
    base = _base_state(top)
    st = JS.fault_state_at(top, dict(type=1, line=1), base)  # section 2,4,5 cut off from the grid
    dead = ev.evaluate(dict(st, allow_island=False))
    isl = ev.evaluate(dict(st, allow_island=True))
    assert dead.unserved_kw.sum() > isl.unserved_kw.sum() > -1e-9
    assert not dead.energised[[2, 4, 5]].any()


def test_redistribution_invariants():
    from testbed.market import redistribution as RD
    top = build("C")
    demand, gen, _ = JS.profiles(top, 9)
    k0 = 140  # around noon
    sl = slice(k0 * RD.INTERVAL_STEPS, (k0 + 3) * RD.INTERVAL_STEPS)
    iv = RD.Intervals(top, top.base_status(), demand[sl], gen[sl], None, True)
    res = RD.run(iv, seed=3, k_range=range(0, 3))
    kpi = res["kpi"]
    assert kpi["trades"] > 0
    for t in res["trades"]:
        assert t["q_kw"] > 0 and t["qs_kwh"] >= 0 and t["qb_kwh"] >= -1e-9  # no negative flows
        assert t["qb_kwh"] <= t["qs_kwh"] + 1e-9  # the buyer cannot receive more than the seller sent (losses >= 0)
        assert top.nodes[t["seller"]].kind != "grid" and top.nodes[t["buyer"]].kind != "grid"  # trades are between buses, not with the slack
        assert t["seller"] != t["buyer"]
    assert kpi["energy_redistributed_kwh"] <= kpi["energy_sent_kwh"] + 1e-6  # energy conserved up to losses
    assert kpi["network_losses_kwh"] >= 0
    for fr in res["frames"]:  # line limits respected (never worse than loaded without trading is not required; absolute limit on accepted flows)
        assert max(abs(np.array(fr["line_p_kw"]))) < 0.25 * 1.732 * 12.66 * 1000 * 1.01  # kW at the line rating (0.25 kA, 12.66 kV)
    # price sorted / compatible: every match respects ask <= bid cap range
    assert all(60 <= t["price"] <= 110 for t in res["trades"])


def test_weights_sum_to_one_and_behave():
    from ai.federated import weighting_paper as WP
    n = {0: 100.0, 1: 100.0, 2: 300.0}
    v = {0: 0.01, 1: 0.05, 2: 0.02}
    for eta in (0, 1, 5, 10):
        w = WP.journal_weights(n, v, eta)
        assert abs(sum(w.values()) - 1) < 1e-12
    assert WP.journal_weights(n, v, 0) == pytest.approx(WP.sample_weights(n))  # eta = 0 reduces to n_k weighting (FedProx)
    w5 = WP.journal_weights({0: 1.0, 1: 1.0}, {0: 0.01, 1: 0.05}, 5)
    assert w5[0] > w5[1]  # lower validation loss -> larger weight
    wc = WP.conf_weights(n, v)
    assert abs(sum(wc.values()) - 1) < 1e-12
    assert WP.conf_weights({0: 1.0, 1: 1.0}, {0: 0.01, 1: 0.05})[0] > 0.5


def test_comm_cost_formula():
    from ai.federated import weighting_paper as WP
    assert WP.comm_cost_bytes(rounds=10, clients=6, n_params=1000) == 2 * 10 * 6 * 1000 * 4


def test_dense_ta_layer_equals_pyg_tagconv():
    import torch
    from torch_geometric.nn import TAGConv
    from ai.testbed_models.journal_core import TALayer
    torch.manual_seed(0)
    top = build("B")
    A = torch.from_numpy(a_hat(top.adjacency(top.base_status())))
    K, d_in, d_out = 2, 7, 5
    dense = TALayer(d_in, d_out, K)
    x = torch.randn(1, top.n, d_in)
    ref = TAGConv(d_in, d_out, K=K, normalize=False, bias=True)
    # copy weights: PyG stacks hop-k linear maps; bias lives on the output linear
    with torch.no_grad():
        for k in range(K + 1):  # PyG keeps one weight matrix per hop; the dense layer stores them side by side
            dense.lin.weight[:, k * d_in:(k + 1) * d_in].copy_(ref.lins[k].weight)
        dense.lin.bias.copy_(ref.bias)
    ei = A.nonzero().t().contiguous()
    ew = A[ei[0], ei[1]]
    out_ref = ref(x[0], ei, ew)
    out = dense(x, A.unsqueeze(0))[0]
    assert torch.allclose(out, out_ref, atol=1e-5)
