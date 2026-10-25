"""Live grid protection (app/twin/grid_protection.py): overload relief, node isolation until repair, line-fault
sectionalising with tie closing. Runs on the real `digital_twin` singleton with the switch time patched to ~0 and
repairs every incident it opens, so the singleton ends as it started."""

import asyncio

import pytest

from app.twin import grid_protection as gp
from app.twin import healing_events as he
from app.twin.digital_twin import BUS_A, BUS_B, digital_twin as twin


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
        assert twin.get_node("hydro_01")["active_connection"] == BUS_B  # moved over its tie
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
        assert twin.get_node("hydro_01")["active_connection"] == BUS_B  # re-fed from the other bus
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
        assert twin.bus_load_kw(BUS_B) <= twin.bus_capacity_kw(BUS_B) + 1e-6
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


def test_simulate_and_repair_routes(logged_in, monkeypatch):
    import time

    r = logged_in.post("/twin/healing/simulate", json={"kind": "node_fault", "target": "hydro_01"})
    assert r.status_code == 202
    for _ in range(100):  # the run is a background task on the app's loop
        ev = next((e for e in he.list_events() if e["fixture"] == "hydro_01" and e["incident"] == "active" and e["status"] == "restored"), None)
        if ev:
            break
        time.sleep(0.1)
    assert ev, "node fault was never isolated"
    assert logged_in.post("/twin/healing/simulate", json={"kind": "node_fault", "target": "hydro_01"}).status_code == 400
    assert logged_in.post("/twin/healing/simulate", json={"kind": "nope", "target": "x"}).status_code == 422
    assert logged_in.post("/twin/healing/repair", json={"event_id": ev["id"]}).status_code == 202
    for _ in range(100):
        if ev["incident"] == "repaired":
            break
        time.sleep(0.1)
    assert ev["incident"] == "repaired" and not twin.get_node("hydro_01")["isolated"]
