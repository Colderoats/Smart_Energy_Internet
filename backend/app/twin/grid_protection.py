"""Live grid protection on the 9-node digital twin: overload relief, node isolation, line-fault sectionalising.

Three situations, each executed as an ordered list of switch operations (one every healing_events.SWITCH_OP_MS)
so the whole reroute can be watched live and timed (events: app/twin/healing_events.py, WS `healing_event`):

* Bus overload  - a collector bus carries more than its limit. The relief plan moves sources to the other bus by
  opening their feeder and closing their tie switch (partly curtailing where the other bus lacks headroom). The
  subset with the least unserved kW wins, ties go to fewer switch operations.
* Faulty node   - the node is isolated (switches opened at both ends of its feeder) and stays isolated until it is
  repaired (real faults: self_healing._handle_recovery when the health status clears; injected: `repair`).
* Faulty line   - a feeder (source -> bus) or an uplink (bus -> grid). The faulted section is isolated by opening the
  switch at BOTH of its ends, then the healthy sources that lost their path are re-fed by closing their tie switch
  to the other bus. What cannot be re-fed within the other bus's headroom is curtailed or left unserved.

Switch model (the twin has no switch hardware, so this is a SIMULATION of the switching): every source has a closed
feeder switch pair to its primary bus and a normally-open tie switch to the other bus; every bus has a switch pair
on its uplink to the grid. Bus loads are rated_capacity_kw * load_share (no power flow), as everywhere in the twin.
Faults are INJECTED through simulate() (POST /twin/healing/simulate); real node faults reach the same events through
self_healing.py. Prosumers / community_bus are not part of this (as in self_healing).
"""

import asyncio
import itertools
import logging
from time import perf_counter

from app.api.ws_manager import manager
from app.twin import healing_events as he
from app.twin.digital_twin import BUS_A, BUS_B, GRID, digital_twin

logger = logging.getLogger("sei")

BUSES = (BUS_A, BUS_B)
DEFAULT_OVERLOAD_PCT = 25.0  # injected overload: the bus limit is derated to load / (1 + pct/100)
MIN_SHARE = 0.10  # a source is only re-fed over a tie if at least 10 % of its output fits

KINDS = ("bus_overload", "node_fault", "line_fault")

_lock = asyncio.Lock()
_tasks: set[asyncio.Task] = set()
_overload_events: dict[str, dict] = {}  # bus -> its overload incident
_sim_overload: dict[str, float] = {}  # bus -> perf_counter() when the (injected) derate was applied


class ProtectionError(ValueError):
    pass


# -- small helpers -----------------------------------------------------------------------------------------------

def _other(bus: str) -> str:
    return BUS_B if bus == BUS_A else BUS_A


def _sources() -> list[dict]:
    return [n for n in digital_twin.get_all_nodes() if "possible_connections" in n and not n.get("community")]


def _contrib(n: dict) -> float:
    return n["rated_capacity_kw"] * n["load_share"]


def _uplink_closed(bus: str) -> bool:
    return bool(digital_twin.get_node(bus).get("uplink_closed", True))


def _room(bus: str) -> float:
    """kW the bus can still take (0 when its uplink is open)."""
    if not _uplink_closed(bus):
        return 0.0
    return max(0.0, digital_twin.bus_capacity_kw(bus) - digital_twin.bus_load_kw(bus))


def _bus_state() -> dict:
    return {b: {"load_kw": round(digital_twin.bus_load_kw(b), 1), "capacity_kw": round(digital_twin.bus_capacity_kw(b), 1), "uplink_closed": _uplink_closed(b)} for b in BUSES}


def _primary(n: dict) -> str:
    return n["possible_connections"][0]


async def _push_nodes(*node_ids: str) -> None:
    for nid in dict.fromkeys([*node_ids, *BUSES]):
        await manager.broadcast({"type": "twin_node_update", "node": digital_twin.get_node(nid)})


def _kw(x: float) -> str:
    return f"{x:,.0f} kW" if x >= 1 else f"{x:.2f} kW"


def _share_for(n: dict, room: float) -> float | None:
    """Fraction of the source's rated output that fits in `room`, or None if less than MIN_SHARE."""
    if n["rated_capacity_kw"] <= 0:
        return None
    share = min(1.0, room / n["rated_capacity_kw"])
    return share if share >= MIN_SHARE else None


def _validate_line(target: str) -> tuple[str, str]:
    a, _, b = target.partition(">")
    nodes = {n["node_id"]: n for n in _sources()}
    if a in nodes and b in BUSES:
        if nodes[a]["active_connection"] != b:
            raise ProtectionError(f"{target} is not an energised feeder right now")
        return a, b
    if a in BUSES and b == GRID:
        if not _uplink_closed(a):
            raise ProtectionError(f"{target} is already open")
        return a, b
    raise ProtectionError(f"unknown line {target!r} (use source>bus or bus>grid)")


# -- public API ---------------------------------------------------------------------------------------------------

async def simulate(kind: str, target: str, overload_pct: float = 25.0) -> None:
    """Inject a fault now. Validated here; the detection / isolation / restoration then run as a background task and
    are reported through `healing_event` messages (watch them live in the Self-Healing tab)."""
    t0 = perf_counter()
    if kind not in KINDS:
        raise ProtectionError(f"kind must be one of {KINDS}")
    if kind == "bus_overload":
        if target not in BUSES:
            raise ProtectionError("target must be bus_a or bus_b")
        if target in _overload_events and _overload_events[target]["incident"] == "active":
            raise ProtectionError(f"{target} already has an active overload incident - repair it first")
        if not _uplink_closed(target):
            raise ProtectionError(f"{target} is cut off from the grid")
        load = digital_twin.bus_load_kw(target)
        if load <= 0:
            raise ProtectionError(f"{target} carries no load")
        if not 5 <= overload_pct <= 80:
            raise ProtectionError("overload_pct must be between 5 and 80")
        digital_twin.set_bus_capacity(target, load / (1 + overload_pct / 100))  # the fault condition appears now
        _sim_overload[target] = t0
    elif kind == "node_fault":
        node = next((n for n in _sources() if n["node_id"] == target), None)
        if node is None:
            raise ProtectionError(f"{target!r} is not a source node of the live twin")
        if node.get("isolated") or he.find_open(target):
            raise ProtectionError(f"{target} is already isolated / has an open incident")
    else:
        _validate_line(target)
        if he.find_open(target):
            raise ProtectionError(f"{target} already has an open incident")
    task = asyncio.create_task(_run(kind, target, t0))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def repair(event_id: str) -> None:
    event = he.get_event(event_id)
    if event is None or event.get("incident") != "active" or "_ctx" not in event:
        raise ProtectionError("only an active, injected incident can be repaired here")
    event["incident"] = "repairing"  # blocks a second repair while the task is queued
    task = asyncio.create_task(_repair_run(event))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def check_overloads() -> None:
    """Called after every ingested reading (self_healing.maybe_trigger): relieve any bus over its limit that has no
    incident yet. Skips quietly while another protection run is busy."""
    if _lock.locked():
        return
    over = [b for b in BUSES if _uplink_closed(b) and digital_twin.bus_load_kw(b) > digital_twin.bus_capacity_kw(b) + 1e-6
            and not (b in _overload_events and _overload_events[b]["incident"] != "repaired")]
    if not over:
        return
    async with _lock:
        for bus in over:
            if bus in _overload_events and _overload_events[bus]["incident"] != "repaired":
                continue
            if digital_twin.bus_load_kw(bus) > digital_twin.bus_capacity_kw(bus) + 1e-6:
                await _handle_overload(bus, _sim_overload.get(bus, perf_counter()), simulated=bus in _sim_overload)


# -- runs ---------------------------------------------------------------------------------------------------------

async def _run(kind: str, target: str, t0: float) -> None:
    try:
        async with _lock:
            if kind == "bus_overload":
                if target in _overload_events and _overload_events[target]["incident"] != "repaired":
                    return  # the reading-driven check got there first
                await _handle_overload(target, t0, simulated=True)
            elif kind == "node_fault":
                await _handle_node_fault(target, t0)
            elif target.split(">")[0] in BUSES:
                await _handle_uplink_fault(target, t0)
            else:
                await _handle_feeder_fault(target, t0)
    except Exception:
        logger.exception("grid protection run failed (%s %s)", kind, target)


async def _execute(event: dict, ops: list) -> None:
    """ops = [(op, text, fn_or_None)]; one simulated switch time each, the twin changes when the step completes."""
    for i, (_, _, fn) in enumerate(ops):
        await asyncio.sleep(he.SWITCH_OP_MS / 1000)
        if fn:
            touched = fn()
            await _push_nodes(*(touched or []))
        await he.step_done(event, i)


# -- bus overload -------------------------------------------------------------------------------------------------

def _cut(group: list[dict], amount: float) -> dict[str, float]:
    """Remove `amount` kW from the group, biggest source first (fewest sources touched). Returns {node: new load_share}."""
    shares = {}
    for s in sorted(group, key=_contrib, reverse=True):
        if amount <= 1e-6:
            break
        cut = min(amount, _contrib(s))
        shares[s["node_id"]] = (_contrib(s) - cut) / s["rated_capacity_kw"]
        amount -= cut
    return shares


def _plan_relief(bus: str) -> dict:
    other = _other(bus)
    cap, load = digital_twin.bus_capacity_kw(bus), digital_twin.bus_load_kw(bus)
    room = _room(other)
    srcs = [n for n in _sources() if n["active_connection"] == bus and not n.get("isolated") and n["load_share"] > 0]
    best = None
    for r in range(len(srcs) + 1):
        for moved in itertools.combinations(srcs, r):
            if moved and room <= 0:
                continue
            moved_kw = sum(_contrib(s) for s in moved)
            short_other, short_stay = max(0.0, moved_kw - room), max(0.0, load - moved_kw - cap)
            key = (round(short_other + short_stay, 3), len(moved), moved_kw)
            if best is None or key < best[0]:
                best = (key, moved, short_other, short_stay)
    _, moved, short_other, short_stay = best
    moved = list(moved)
    stay = [s for s in srcs if s not in moved]
    moved_kw, stay_kw = sum(_contrib(s) for s in moved), sum(_contrib(s) for s in stay)
    shares = {**_cut(moved, short_other), **_cut(stay, short_stay)}
    return {"other": other, "room": room, "moved": moved, "stay": stay, "shares": shares, "unserved": short_other + short_stay, "moved_kw": moved_kw - short_other}


async def _handle_overload(bus: str, t0: float, simulated: bool) -> None:
    cap, load = digital_twin.bus_capacity_kw(bus), digital_twin.bus_load_kw(bus)
    over = load - cap
    event = await he.open_event(
        "bus_overload", bus, "Bus overload",
        f"{bus} carries {_kw(load)} but its limit is {_kw(cap)}: {_kw(over)} over (+{over / cap * 100:.0f} %)" + (" [injected: limit derated]" if simulated else ""),
        t0=t0, simulated=simulated, impact_before=_bus_state(),
    )
    _overload_events[bus] = event
    plan = _plan_relief(bus)
    other, moved, shares = plan["other"], plan["moved"], plan["shares"]
    ops, path_lines, iso_lines = [], [], []
    orig = {s["node_id"]: s["load_share"] for s in plan["moved"] + plan["stay"]}
    for s in moved:
        nid = s["node_id"]
        ops.append(("OPEN", f"Open feeder switch {nid}–{bus}", lambda nid=nid: [digital_twin.isolate_node(nid) and nid]))
        def close(nid=nid, share=shares.get(nid)):
            digital_twin.reroute_node(nid, other)
            if share is not None:
                digital_twin.set_load_share(nid, share)
            return [nid]
        ops.append(("CLOSE", f"Close tie switch {nid}–{other}" + (f" (curtailed to {shares[nid] * 100:.0f} % to fit {other})" if nid in shares else ""), close))
        path_lines += [[nid, other]]
        iso_lines += [[nid, bus]]
    for s in plan["stay"]:
        nid = s["node_id"]
        if nid in shares:
            ops.append(("CURTAIL", f"Curtail {nid} to {shares[nid] * 100:.0f} % (no bus can take it)", lambda nid=nid: [digital_twin.set_load_share(nid, shares[nid]) and nid]))
            path_lines += [[nid, bus]]
    if moved:
        path_lines += [[other, GRID]]
    decision = (f"move {', '.join(s['node_id'] for s in moved)} to {other} ({_kw(plan['room'])} headroom there)" if moved else f"no source fits on {other} ({_kw(plan['room'])} headroom)") \
        + (f"; curtail {_kw(plan['unserved'])}" if plan["unserved"] > 0.5 else "; nothing curtailed")
    path = {"from": bus, "to": GRID, "via": other if moved else bus, "lines": path_lines, "isolated_lines": iso_lines}
    await he.set_plan(event, [(o, t) for o, t, _ in ops], path, "reroute" if moved else "reduce_load_share")
    event["decision"] = decision
    event["_ctx"] = {"kind": "bus_overload", "bus": bus, "moved": [s["node_id"] for s in moved], "orig": orig, "curtailed": [k for k in shares]}
    await _execute(event, ops)
    await he.complete(event, _bus_state(), plan["moved_kw"], plan["unserved"])
    logger.info("Grid protection: %s overload -> %s", bus, decision)


# -- faulty node --------------------------------------------------------------------------------------------------

async def _handle_node_fault(nid: str, t0: float) -> None:
    node = digital_twin.get_node(nid)
    bus = node["active_connection"]
    event = await he.open_event(
        "node_fault", nid, "Equipment fault / node outage", f"{nid} reported an equipment fault [injected] -> the faulty node is isolated until it is fixed",
        t0=t0, simulated=True, impact_before=_bus_state(),
    )
    ops = [("OPEN", f"Open switch at {nid} end of {nid}–{bus}", None), ("OPEN", f"Open switch at {bus} end of {nid}–{bus}", lambda: [digital_twin.isolate_node(nid) and nid])]
    await he.set_plan(event, [(o, t) for o, t, _ in ops], {"from": nid, "to": None, "via": None, "lines": [], "isolated_lines": [[nid, bus]]}, "isolate")
    event["decision"] = f"isolate {nid} ({_kw(_contrib(node))} stays unserved) until it is repaired"
    event["_ctx"] = {"kind": "node_fault", "node": nid, "bus": bus}
    await _execute(event, ops)
    await he.complete(event, _bus_state(), 0.0, _contrib(node))


# -- faulty line --------------------------------------------------------------------------------------------------

async def _handle_feeder_fault(target: str, t0: float) -> None:
    nid, bus = _validate_line(target)
    node = digital_twin.get_node(nid)
    alt = _other(bus)
    event = await he.open_event(
        "line_fault", target, "Line fault (feeder)", f"Fault on feeder {nid}–{bus} [injected]: the section is isolated by opening the switches at both ends, then {nid} is re-fed over its tie to {alt}",
        t0=t0, simulated=True, impact_before=_bus_state(),
    )
    share = _share_for(node, _room(alt)) if _uplink_closed(alt) else None
    ops = [("OPEN", f"Open switch at {nid} end of {nid}–{bus}", None), ("OPEN", f"Open switch at {bus} end of {nid}–{bus}", lambda: [digital_twin.isolate_node(nid) and nid])]
    if share is not None:
        def close():
            digital_twin.reroute_node(nid, alt)
            digital_twin.set_load_share(nid, share)
            return [nid]
        ops.append(("CLOSE", f"Close tie switch {nid}–{alt}" + (f" (curtailed to {share * 100:.0f} % to fit {alt})" if share < 1 else ""), close))
        path = {"from": nid, "to": GRID, "via": alt, "lines": [[nid, alt], [alt, GRID]], "isolated_lines": [[nid, bus]]}
        decision = f"isolate {nid}–{bus}, feed {nid} from {alt} via its tie ({_kw(_room(alt))} headroom)"
    else:
        path = {"from": nid, "to": None, "via": None, "lines": [], "isolated_lines": [[nid, bus]]}
        decision = f"isolate {nid}–{bus}; no tie can take {nid} ({alt} has {_kw(_room(alt))} headroom) -> unserved"
    await he.set_plan(event, [(o, t) for o, t, _ in ops], path, "open+close_tie" if share is not None else "open")
    event["decision"] = decision
    event["_ctx"] = {"kind": "feeder", "node": nid, "bus": bus, "alt": alt, "on_alt": share is not None}
    contrib = node["rated_capacity_kw"]
    await _execute(event, ops)
    await he.complete(event, _bus_state(), contrib * (share or 0), contrib * (1 - (share or 0)))


async def _handle_uplink_fault(target: str, t0: float) -> None:
    bus, _ = _validate_line(target)
    alt = _other(bus)
    event = await he.open_event(
        "line_fault", target, "Line fault (bus uplink)",
        f"Fault on the uplink {bus}–{GRID} [injected]: every source on {bus} lost its path to the grid. The section is isolated by opening both ends, then the healthy sources are re-fed over their ties to {alt}",
        t0=t0, simulated=True, impact_before=_bus_state(),
    )
    srcs = sorted([n for n in _sources() if n["active_connection"] == bus and not n.get("isolated")], key=_contrib, reverse=True)
    ops = [("OPEN", f"Open switch at {bus} end of {bus}–{GRID}", None), ("OPEN", f"Open switch at {GRID} end of {bus}–{GRID}", lambda: [digital_twin.set_uplink(bus, False) and bus])]
    room = _room(alt) if _uplink_closed(alt) else 0.0
    path_lines, iso_lines, moved, stranded, delivered, shares = [], [[bus, GRID]], [], [], 0.0, {}
    for s in srcs:
        nid = s["node_id"]
        c = _contrib(s)
        share = _share_for(s, room) if room > 0 else None
        if share is None:
            stranded.append(nid)
            continue
        share = min(share, s["load_share"])
        room -= share * s["rated_capacity_kw"]
        delivered += share * s["rated_capacity_kw"]
        shares[nid] = share
        moved.append(nid)
        ops.append(("OPEN", f"Open feeder switch {nid}–{bus}", lambda nid=nid: [digital_twin.isolate_node(nid) and nid]))
        def close(nid=nid, share=share):
            digital_twin.reroute_node(nid, alt)
            digital_twin.set_load_share(nid, share)
            return [nid]
        ops.append(("CLOSE", f"Close tie switch {nid}–{alt}" + (f" (curtailed to {share * 100:.0f} % to fit {alt})" if share < s["load_share"] - 1e-9 else ""), close))
        path_lines.append([nid, alt])
        iso_lines.append([nid, bus])
    if moved:
        path_lines.append([alt, GRID])
    for nid in stranded:  # nothing can feed these: they stay on the dead bus, cut off from the grid
        iso_lines.append([nid, bus])
    total = sum(_contrib(s) for s in srcs)
    path = {"from": bus, "to": GRID if moved else None, "via": alt if moved else None, "lines": path_lines, "isolated_lines": iso_lines}
    await he.set_plan(event, [(o, t) for o, t, _ in ops], path, "open+close_tie" if moved else "open")
    event["decision"] = (f"isolate {bus}–{GRID}; re-feed {', '.join(moved)} from {alt} ({_kw(delivered)} of {_kw(total)})" if moved else f"isolate {bus}–{GRID}; {alt} has no headroom -> all unserved") \
        + (f"; {', '.join(stranded)} cannot be re-fed (unserved)" if stranded and moved else "")
    event["_ctx"] = {"kind": "uplink", "bus": bus, "alt": alt, "moved": moved, "stranded": stranded}
    await _execute(event, ops)
    await he.complete(event, _bus_state(), delivered, total - delivered)


# -- repair -------------------------------------------------------------------------------------------------------

async def _repair_run(event: dict) -> None:
    try:
        async with _lock:
            ctx, ops = event["_ctx"], []
            kind = ctx["kind"]
            if kind == "node_fault":
                nid, bus = ctx["node"], ctx["bus"]
                ops = [("CLOSE", f"Close switch at {nid} end of {nid}–{bus}", None), ("CLOSE", f"Close switch at {bus} end of {nid}–{bus}", lambda: _restore(nid))]
            elif kind == "feeder":
                nid, bus, alt = ctx["node"], ctx["bus"], ctx["alt"]
                if ctx["on_alt"]:
                    ops.append(("OPEN", f"Open tie switch {nid}–{alt}", None))
                ops += [("CLOSE", f"Close switch at {nid} end of {nid}–{bus}", None), ("CLOSE", f"Close switch at {bus} end of {nid}–{bus}", lambda: _restore(nid))]
            elif kind == "uplink":
                bus = ctx["bus"]
                ops = [("CLOSE", f"Close switch at {GRID} end of {bus}–{GRID}", None), ("CLOSE", f"Close switch at {bus} end of {bus}–{GRID}", lambda: [digital_twin.set_uplink(bus, True) and bus])]
                for nid in ctx["moved"]:
                    ops.append(("OPEN", f"Open tie switch {nid}–{ctx['alt']}", None))
                    ops.append(("CLOSE", f"Close feeder switch {nid}–{bus}", lambda nid=nid: _restore(nid)))
                for nid in ctx["stranded"]:
                    ops.append(("CLOSE", f"Re-energise feeder {nid}–{bus}", lambda nid=nid: _restore(nid)))
            else:  # bus_overload: the limit comes back, moved sources go home, curtailed ones go back to their share
                bus = ctx["bus"]
                digital_twin.set_bus_capacity(bus, None)
                _sim_overload.pop(bus, None)
                await _push_nodes(bus)
                for nid in ctx["moved"]:
                    ops.append(("OPEN", f"Open tie switch {nid}–{_other(bus)}", None))
                    ops.append(("CLOSE", f"Close feeder switch {nid}–{bus}", lambda nid=nid: _restore(nid, ctx["orig"].get(nid, 1.0))))
                for nid in ctx["curtailed"]:
                    if nid not in ctx["moved"]:
                        ops.append(("CURTAIL", f"Restore {nid} to {ctx['orig'].get(nid, 1.0) * 100:.0f} %", lambda nid=nid: _restore(nid, ctx["orig"].get(nid, 1.0))))
            steps = [(o, t) for o, t, _ in ops]
            await he.repair(event, steps, lambda i: _apply_repair(ops[i][2]))
            if kind == "bus_overload":
                _overload_events.pop(ctx["bus"], None)
    except Exception:
        logger.exception("grid protection repair failed (%s)", event.get("id"))
        event["incident"] = "active"


_pending_touch: list[str] = []


def _apply_repair(fn) -> None:
    if fn:
        _pending_touch.extend(fn() or [])
    # twin_node_update pushes for repaired nodes are scheduled right after the (sync) apply
    ids, _pending_touch[:] = list(_pending_touch), []
    if ids:
        asyncio.get_running_loop().create_task(_push_nodes(*ids))


def _restore(nid: str, share: float = 1.0) -> list[str]:
    node = digital_twin.get_node(nid)
    digital_twin.reroute_node(nid, _primary(node))
    digital_twin.set_load_share(nid, share)
    return [nid]
