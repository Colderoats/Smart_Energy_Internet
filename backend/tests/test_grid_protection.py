"""Live grid protection (app/twin/grid_protection.py): overload relief, node isolation until repair, line-fault
sectionalising with tie closing. Runs on the real `digital_twin` singleton with the switch time patched to ~0 and
repairs every incident it opens, so the singleton ends as it started."""

import asyncio

import pytest

from app.twin import grid_protection as gp
from app.twin import healing_events as he
from app.twin.digital_twin import BUS_A, BUS_C, BUS_D, digital_twin as twin


@pytest.fixture(autouse=True)
def fast_switches(monkeypatch):
    monkeypatch.setattr(he, "SWITCH_OP_MS", 1.0)


def _routing():
    return {n["node_id"]: (n["active_connection"], n["load_share"], n["isolated"]) for n in twin.get_all_nodes() if "possible_connections" in n}


async def _settle():
    while gp._tasks:
        await asyncio.sleep(0.005)


async def _incident(kind, target, **kw):
    n = len(he.list_events())
    await gp.simulate(kind, target, **kw)
    await _settle()
    return he.list_events()[n]


async def _repair(event):
    await gp.repair(event["id"])
    await _settle()


def test_overload_reroutes_to_other_bus_and_clears():
    async def run():
        before = _routing()
        ev = await _incident("bus_overload", BUS_A)
        assert ev["kind"] == "bus_overload" and ev["status"] == "restored" and ev["action"] == "reroute"
        assert twin.bus_load_kw(BUS_A) <= twin.bus_capacity_kw(BUS_A) + 1e-6
        moved = [n for n in twin.get_all_nodes() if "possible_connections" in n and n["active_connection"] not in (BUS_A, None) and n["possible_connections"][0] == BUS_A]
        assert moved and moved[0]["active_connection"] in (BUS_C, BUS_D)  # moved over its tie to a spare bus (most headroom)
        ops = [s["op"] for s in ev["steps"]]
        assert ops[:2] == ["OPEN", "CLOSE"] and all(s["state"] == "done" for s in ev["steps"])
        assert ev["detect_ms"] >= 0 and ev["compute_ms"] >= 0 and ev["est_complete_ms"] > 0
        await _repair(ev)
        assert ev["incident"] == "repaired" and _routing() == before
        assert twin.bus_capacity_kw(BUS_A) == 5000.0

    asyncio.run(run())


def test_faulty_node_stays_isolated_until_repaired():
    async def run():
        before = _routing()
        ev = await _incident("node_fault", "wind_01")
        node = twin.get_node("wind_01")
        assert node["isolated"] and node["active_connection"] is None
        assert [s["op"] for s in ev["steps"]] == ["OPEN", "OPEN"]  # both ends of its feeder
        assert ev["impact"]["unserved_kw"] == 2000.0
        with pytest.raises(gp.ProtectionError):
            await gp.simulate("node_fault", "wind_01")  # already isolated
        await _repair(ev)
        assert _routing() == before

    asyncio.run(run())


def test_feeder_fault_opens_both_ends_then_closes_tie():
    async def run():
        before = _routing()
        ev = await _incident("line_fault", "hydro_01>bus_a")
        assert [s["op"] for s in ev["steps"]] == ["OPEN", "OPEN", "CLOSE"]
        assert "end of" in ev["steps"][0]["text"] and "end of" in ev["steps"][1]["text"]
        assert twin.get_node("hydro_01")["active_connection"] in (BUS_C, BUS_D)  # re-fed from the bus with most headroom
        await _repair(ev)
        assert _routing() == before

    asyncio.run(run())


def test_uplink_fault_isolates_bus_and_refeeds_what_fits():
    async def run():
        before = _routing()
        ev = await _incident("line_fault", "bus_a>grid")
        assert twin.get_node(BUS_A)["uplink_closed"] is False
        assert ("bus_a", "grid") not in [(e["source"], e["target"]) for e in twin.get_edges()]
        assert ev["steps"][0]["op"] == "OPEN" and ev["steps"][1]["op"] == "OPEN"
        assert any(s["op"] == "CLOSE" for s in ev["steps"])  # something was re-fed over a tie
        assert all(twin.bus_load_kw(b) <= twin.bus_capacity_kw(b) + 1e-6 for b in twin.bus_ids())
        await _repair(ev)
        assert twin.get_node(BUS_A)["uplink_closed"] is True and _routing() == before

    asyncio.run(run())


def test_bad_requests_rejected():
    async def run():
        for kind, target in [("bus_overload", "wind_01"), ("node_fault", "bus_a"), ("line_fault", "wind_01>bus_b"), ("line_fault", "nope"), ("bogus", "x")]:
            with pytest.raises(gp.ProtectionError):
                await gp.simulate(kind, target)
        with pytest.raises(gp.ProtectionError):
            await gp.simulate("bus_overload", BUS_A, overload_pct=500)
        assert twin.bus_capacity_kw(BUS_A) == 5000.0  # a rejected request changes nothing

    asyncio.run(run())


def test_extra_buses_exist_on_live_twin_only():
    from app.twin.digital_twin import DigitalTwin

    assert twin.bus_ids() == ["bus_a", "bus_b", "bus_c", "bus_d"]
    assert DigitalTwin().bus_ids() == ["bus_a", "bus_b"]  # AI training / parity topology unchanged
    assert twin.get_node("wind_01")["possible_connections"][:2] == ["bus_a", "bus_b"]
    assert {"bus_c", "bus_d"} <= set(twin.get_node("wind_01")["possible_connections"])
