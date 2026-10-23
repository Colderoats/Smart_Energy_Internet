r"""Set-2 TC04-TC07 on the SIMULATED testbed, topology C (IEEE 33-bus). Needs the TESTBED venv (torch + pandapower):
  cd backend && testbed\venv\Scripts\python -m pytest ..\tests\test_set2_testbed.py -q -s
TC04/TC05/TC06 re-run the saved models / the real evaluation code live (nothing is written under experiments/).
TC07 (federated training with 33 clients) is NOT re-run - 100-round x 3-method x 33-client training takes hours - it reads the
stored result experiments/results/j_table10/metrics.json (same code path that produced the published numbers)."""
import json

import numpy as np
import pytest

pytest.importorskip("pandapower")
from ai.testbed_models import predict  # noqa: E402
from testbed import journal_sim as JS  # noqa: E402
from testbed.topologies import build  # noqa: E402
from testbed.twin_eval import journal_twin as JT  # noqa: E402
from tests_paths import REPO  # noqa: E402


@pytest.fixture(scope="module")
def c1213():
    """The 20 injected line outages between buses 12-13 of topology C (journal Table VIII scenario), evaluated live."""
    top = build("C")
    sc = JT.load_scenario(top, JS.DATA_ROOT, f"{JS.SCENARIO_KINDS['c1213'][0].format(t='C')}/it0")
    pr = predict.predict_scenario("C", 0, kind="c1213", model_it=0, eval_it=0)
    return top, sc, JT.evaluate_scenario(sc, pr["pred"])


def _load_mae(top, name):
    pr = predict.predict_scenario("C", 0, kind="eval", name=name, model_it=0, eval_it=0)
    loads = [n.id for n in top.nodes if n.load_kw > 0 and n.kind != "grid"]
    return float(np.abs(pr["yhat_kw"][:, loads] - pr["y_kw"][:, loads]).mean())


def test_tc04_demand_forecast_topology_c_tagnn_vs_gcn():
    top = build("C")
    tag, gcn = _load_mae(top, "3_LRS"), _load_mae(top, "gcn_o3_LRS")
    print(f"\n[TC04] topology C held-out forecast MAE: TA-GNN {tag:.2f} kW vs GCN {gcn:.2f} kW")
    assert tag < gcn


def test_tc05_line_outage_12_13_lowest_cost_action(c1213):
    top, sc, res = c1213
    ln = top.line_between(11, 12)  # paper buses 12-13
    twin = res["results"]["twin"]
    assert len(twin) == 20 and all(r["line"] == ln.id for r in twin)
    r = twin[0]
    a = r["action"]
    feas = [c for c in a["costs"] if c["feasible"]]
    ties = {l.id: l.paper_no for l in top.lines if l.tie}
    closed = [ties[o[1]] for o in a["ops"] if o[0] == "close"]
    print(f"\n[TC05] outage {ln.a + 1}-{ln.b + 1}: chosen '{a['label']}' ops={[(o[0], top.lines[o[1]].a + 1, top.lines[o[1]].b + 1) for o in a['ops']]} "
          f"(closes tie switch TS{closed}) J={a['J']:.3f} among {a['n_candidates']} candidates ({a['n_rejected']} infeasible)")
    assert a["any_feasible"] and abs(a["J"] - min(c["J"] for c in feas)) < 1e-12   # lowest-cost feasible candidate
    assert [o for o in a["ops"] if o[0] == "open"] == [["open", ln.id]]            # isolates the faulted line
    assert closed, "no tie switch closed"
    print("[TC05] chosen action over all 20 outages:", sorted({(x["action"]["label"], tuple(ties[o[1]] for o in x["action"]["ops"] if o[0] == "close")) for x in twin}))


def test_tc06_twin_recovers_faster_than_rule_based(c1213):
    _, _, res = c1213
    s = {k: JT.summarise(res["results"][k]) for k in ("twin", "default")}
    print(f"\n[TC06] 20 faults, topology C: mean T_rec twin {s['twin']['t_rec_mean_s']:.1f} s vs rule-based {s['default']['t_rec_mean_s']:.1f} s "
          f"(n={s['twin']['t_rec_n']}/{s['default']['t_rec_n']}; E_uns {s['twin']['e_uns_total_kwh']:.1f} vs {s['default']['e_uns_total_kwh']:.1f} kWh)")
    assert s["twin"]["faults"] == s["default"]["faults"] == 20
    assert s["twin"]["t_rec_mean_s"] < s["default"]["t_rec_mean_s"]


def test_tc07_federated_33_clients_fewer_rounds_than_fedavg_and_fedprox():
    m = json.loads((REPO / "experiments/results/j_table10/metrics.json").read_text())["metrics"]
    k33 = [x for x in m if "K=33" in (x["conditions"] or "") and x["name"] == "rounds_to_target"]
    common = {x["conditions"]: x["value"] for x in m if x["name"] == "rounds_to_common_target"}
    # the three 'common target' rows of the K=33 block are the last three in the file
    fa, fp, ad = [x["value"] for x in m if x["name"] == "rounds_to_common_target"][-3:]
    print(f"\n[TC07] 33 clients (stored result): rounds to the validation-loss target = {[x['value'] for x in k33]} (FedAvg, FedProx, adaptive; "
          f"degenerate); rounds to the common target: FedAvg {fa}, FedProx {fp}, adaptive FedProx {ad}")
    assert ad is not None and (fa is None or ad < fa) and ad < fp
