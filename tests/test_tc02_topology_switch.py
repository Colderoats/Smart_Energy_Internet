"""TC02 - switch state changed in topology C (IEEE 33-bus): A(t) and A_hat are recomputed and the SAME trained
TA-GNN (journal_C/it0/model_3_LRS.pt, weights untouched) predicts on the new topology without retraining.
Needs the TESTBED venv (torch + pandapower):  backend\testbed\venv\Scripts\python -m pytest tests\test_tc02_topology_switch.py -s"""
import hashlib

import networkx as nx
import numpy as np
import pytest
import torch

pytest.importorskip("pandapower")
from ai.testbed_models import journal_model as JM  # noqa: E402
from ai.testbed_models.predict import load_model  # noqa: E402
from testbed.topologies import a_hat, build  # noqa: E402
from testbed.twin_eval.journal_twin import Action, apply_action  # noqa: E402


def _digest(m):
    h = hashlib.sha256()
    for k, v in m.state_dict().items():
        h.update(k.encode()); h.update(v.numpy().tobytes())
    return h.hexdigest()[:16]


def _changed(A0, A1):
    iu = np.triu_indices(A0.shape[0])
    d = np.argwhere(np.triu(A0 != A1))
    return [(int(i) + 1, int(j) + 1, float(A0[i, j]), float(A1[i, j])) for i, j in d]  # paper (1-based) bus numbers


def test_tc02_switch_change_recomputes_adjacency_and_same_model_predicts():
    top = build("C")
    model, stats = load_model("C", 0, "3_LRS")
    w_before = _digest(model)

    d, _ = JM.load_data("C", 0, kind="eval")
    data, _ = JM.make_data("C", d, stats=dict(stats))
    x = data.x[:1]  # one 12-step window [1, 33, 60]

    st0 = {"status": top.base_status(), "served": np.ones(top.n)}
    ts34 = next(l for l in top.lines if l.paper_no == 34)
    print(f"\n[TC02] TS34 = line {ts34.paper_no}, buses {ts34.a + 1}-{ts34.b + 1}, tie={ts34.tie}")
    assert ts34.tie and {ts34.a + 1, ts34.b + 1} == {9, 15}

    # twin switching primitive: (1) close tie TS34 ; (2) close TS34 and open sectionalising line 9-10 (radial again)
    open_line = top.line_between(8, 9)  # 0-based -> paper buses 9-10
    scenarios = {
        "close TS34": Action([("close", ts34.id)], False, False, "close TS34"),
        "close TS34 + open 9-10": Action([("close", ts34.id), ("open", open_line.id)], False, False, "reconfigure"),
    }
    A0 = top.adjacency(st0["status"]); Ah0 = a_hat(A0)
    out0 = model(x, torch.from_numpy(Ah0)[None])
    for name, act in scenarios.items():
        st1 = apply_action(top, st0, act, [])
        A1 = top.adjacency(st1["status"]); Ah1 = a_hat(A1)
        ch = _changed(A0, A1)
        dh = int((np.abs(Ah1 - Ah0) > 1e-9).sum())
        print(f"[TC02] {name}: edges {int(A0.sum() // 2)} -> {int(A1.sum() // 2)}; A changed entries (bus,bus,old,new)={ch}; "
              f"A_hat entries changed={dh}; connected={nx.is_connected(nx.from_numpy_array(A1))}")
        assert ch and dh > 0, "adjacency / normalised adjacency did not change"
        np.testing.assert_allclose(Ah1, a_hat(A1))  # normalisation recomputed from the new A
        out1 = model(x, torch.from_numpy(Ah1)[None])
        assert all(torch.isfinite(o).all() for o in out1) and out1[0].shape == (1, 33) and out1[1].shape == (1, JM.N_CLASSES)
        print(f"[TC02] {name}: prediction ok; demand head shape {tuple(out1[0].shape)}, fault-class argmax {int(out1[1].argmax())} "
              f"(before: {int(out0[1].argmax())}); max |demand delta| = {float((out1[0] - out0[0]).abs().max()):.4f} (normalised)")
    assert _digest(model) == w_before, "model weights changed -> would mean retraining"
    print(f"[TC02] weights sha256[:16] before/after: {w_before} / {_digest(model)}")
