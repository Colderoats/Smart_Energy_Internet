import json

import numpy as np
import pytest

from testbed import hardware_node as hw
from testbed.topologies import ALLOWED_KINDS, build


@pytest.mark.parametrize("name", "ABC")
def test_hardware_added_as_extra_solar_leaf_default_build_unchanged(name):
    base, top = build(name), hw.build_with_hardware(name)
    assert base.n == top.n - 1 and len(base.lines) == len(top.lines) - 1
    nd = hw.hardware_node(top)
    assert nd.kind == "solar" and nd.kind in ALLOWED_KINDS and nd.gen_cap_kw > 0 and nd.storage_kwh == 0
    ln = top.lines[-1]
    assert {ln.a, ln.b} == {hw.ATTACH[name], nd.id} and not ln.tie
    assert len(top.net.bus) == top.n and len(top.net.line) == len(top.lines)
    assert [d for d in top.graph().degree if d[0] == nd.id][0][1] == 1  # leaf: radial A stays a tree, mesh/IEEE-33 unchanged


@pytest.mark.parametrize("name", "ABC")
def test_power_flow_runs_with_hardware_injection(name):
    import pandapower as pp
    top = hw.build_with_hardware(name)
    assert hw.apply_pu(top, 0.5) == pytest.approx(0.5 * hw.GEN_CAP_KW)
    pp.runpp(top.net)
    assert top.net.res_bus.vm_pu.notna().all()


def test_load_pu_series(tmp_path):
    p = tmp_path / "c.jsonl"
    p.write_text("\n".join(json.dumps({"p_mw": v}) for v in (0.0, 263.0, 900.0)) + "\nnot json\n")
    assert np.allclose(hw.load_pu_series(p), [0.0, 0.5, 1.0])
