"""Prosumer market unit tests: pure logic only (no chain, no DB needed except for the
shared conftest bootstrap). End-to-end behaviour is exercised against a live Hardhat node
separately (PROGRESS.md "Prosumer market (live)")."""

import asyncio
from datetime import datetime, timezone

import pytest

from app.blockchain import events
from app.market import engine
from app.market import prosumers as P
from app.market.chain import MarketChainUnavailable
from app.market.engine import Match, Order
from app.market.service import MarketService
from app.twin import self_healing
from app.twin.digital_twin import DigitalTwin, digital_twin


# ---- PV formula --------------------------------------------------------------

def test_pv_formula_reference_point():
    # 5 kWp, GHI 1000, air 25 C -> cell 55 C: 5 * 1 * 0.8 * (1 - 0.004 * 30) = 3.52
    assert P.pv_generation_kw(5.0, 1000.0, 25.0) == pytest.approx(3.52)


def test_pv_formula_no_temperature_penalty_when_cell_is_cool():
    # air 0 C, GHI 100 -> cell 3 C <= 25: no penalty, 10 * 0.1 * 0.8
    assert P.pv_generation_kw(10.0, 100.0, 0.0) == pytest.approx(0.8)


def test_pv_is_zero_at_night_and_scales_with_size():
    assert P.pv_generation_kw(30.0, 0.0, 28.0) == 0.0
    assert P.pv_generation_kw(30.0, -5.0, 28.0) == 0.0
    assert P.pv_generation_kw(30.0, 600.0, 30.0) == pytest.approx(6 * P.pv_generation_kw(5.0, 600.0, 30.0))


# ---- load profiles --------------------------------------------------------------

def at_local(day: int, hour: int, minute: int = 0) -> datetime:
    """UTC instant whose local (UTC+5.5) wall time is 2026-10-<day> hour:minute."""
    local = datetime(2026, 10, day, hour, minute, tzinfo=timezone.utc)
    from datetime import timedelta
    return local - timedelta(hours=5.5)


@pytest.mark.parametrize("profile", ["house", "apartment", "shop", "school"])
def test_load_is_deterministic_and_in_range(profile):
    lo, hi = P.LOAD_PROFILES[profile][2:]
    for day in (20, 25):  # Tuesday, Sunday
        for hour in range(24):
            t = at_local(day, hour, 17)
            a = P.load_kw("n1", profile, t, 5.5)
            assert a == P.load_kw("n1", profile, t, 5.5)
            assert lo * 0.95 - 1e-9 <= a <= hi * 1.05 + 1e-9


def test_load_noise_is_seeded_per_node_and_within_five_percent():
    t = at_local(20, 19)
    base = P.base_load_kw("apartment", P.local_time(t, 5.5))
    a, b = P.load_kw("a", "apartment", t, 5.5), P.load_kw("b", "apartment", t, 5.5)
    assert a != b
    assert abs(a / base - 1) <= 0.05 + 1e-9 and abs(b / base - 1) <= 0.05 + 1e-9


def test_load_profile_shapes():
    house = lambda h: P.base_load_kw("house", datetime(2026, 10, 20, h))  # noqa: E731  (Tuesday)
    assert house(19) > house(3) and house(7) > house(13)  # morning + evening peaks above midday and night
    shop = lambda h: P.base_load_kw("shop", datetime(2026, 10, 20, h))  # noqa: E731
    assert shop(12) > 6 and shop(3) == 2.0  # 9-21 plateau, quiet at night
    school_wk = lambda h: P.base_load_kw("school", datetime(2026, 10, 20, h))  # noqa: E731
    school_we = lambda h: P.base_load_kw("school", datetime(2026, 10, 25, h))  # noqa: E731  (Sunday)
    assert school_wk(10) == 20.0 and school_wk(22) == 2.0 and school_we(10) == 2.0
    apt = lambda h: P.base_load_kw("apartment", datetime(2026, 10, 20, h))  # noqa: E731
    assert apt(19) == 12.0 and apt(19) > apt(10)  # evening-heavy


def test_load_is_interpolated_per_minute():
    mid = P.base_load_kw("house", datetime(2026, 10, 20, 6, 30))
    assert mid == pytest.approx((1.4 + 2.4) / 2)  # halfway between the 06:00 and 07:00 anchors


# ---- role deadband ------------------------------------------------------------------

def test_role_deadband():
    db = 0.1
    assert P.role_of(0.11, db) == "surplus"
    assert P.role_of(-0.11, db) == "deficit"
    assert P.role_of(0.1, db) == "balanced" and P.role_of(-0.1, db) == "balanced" and P.role_of(0.0, db) == "balanced"
    assert P.role_of(None, db) == "balanced"


# ---- matching -------------------------------------------------------------------------

def test_matching_price_order_and_partial_fills():
    offers = [Order("s_dear", 1000, 6000), Order("s_cheap", 1500, 5000)]
    bids = [Order("b_low", 1000, 6500), Order("b_high", 2000, 8000)]
    matches, off_rem, bid_rem = engine.match_orders(offers, bids)
    # cheapest ask meets the highest max first
    assert (matches[0].seller, matches[0].buyer, matches[0].qty_wh, matches[0].price_milli) == ("s_cheap", "b_high", 1500, 5000)
    # b_high has 500 left and takes the next ask; the price is each SELLER'S ask
    assert (matches[1].seller, matches[1].buyer, matches[1].qty_wh, matches[1].price_milli) == ("s_dear", "b_high", 500, 6000)
    assert (matches[2].seller, matches[2].buyer, matches[2].qty_wh, matches[2].price_milli) == ("s_dear", "b_low", 500, 6000)
    assert off_rem == [0, 0] and bid_rem == [500, 0]  # b_low only partly served


def test_no_match_when_ask_above_max():
    matches, off_rem, bid_rem = engine.match_orders([Order("s", 1000, 7000)], [Order("b", 1000, 6999)])
    assert matches == [] and off_rem == [1000] and bid_rem == [1000]


def test_matching_conserves_quantities():
    offers = [Order(f"s{i}", 700 + 130 * i, 5000 + 250 * i) for i in range(5)]
    bids = [Order(f"b{i}", 400 + 220 * i, 8000 - 400 * i) for i in range(5)]
    matches, off_rem, bid_rem = engine.match_orders(offers, bids)
    matched = sum(m.qty_wh for m in matches)
    assert sum(o.qty_wh for o in offers) == matched + sum(off_rem)
    assert sum(b.qty_wh for b in bids) == matched + sum(bid_rem)
    assert all(m.qty_wh > 0 for m in matches)
    for m in matches:  # every executed match satisfies ask <= max
        assert m.price_milli <= bids[m.bid_idx].price_milli and m.price_milli == offers[m.offer_idx].price_milli


def test_energy_is_mean_kw_times_interval_hours():
    assert engine.energy_wh(3.0, 120 / 3600) == 100  # 3 kW * 2 min = 0.1 kWh
    assert engine.energy_wh(-1.0, 1.0) == 0


# ---- metering + settlement ---------------------------------------------------------------

def test_metering_hands_out_actual_energy_in_match_order():
    ms = [Match(0, 0, "s", "b1", 600, 5000), Match(0, 1, "s", "b2", 400, 5000)]
    # seller actually only had 700 Wh surplus; b1 took 500 of the 600 matched, b2 took its 400
    assert engine.allocate_metering(ms, {"s": 700}, {"b1": 500, "b2": 400}) == [(600, 500), (100, 400)]


def test_settlement_pay_is_price_times_min_of_metered_quantities():
    assert engine.settle_amount(5000, 600, 500) == (500, 2500)  # 5.0 credits/kWh * 0.5 kWh = 2.5 credits = 2500 milli
    assert engine.settle_amount(6400, 300, 900) == (300, 1920)
    assert engine.settle_amount(5000, 0, 800) == (0, 0)
    q, pay = engine.settle_amount(7777, 123, 456)
    assert pay == 7777 * q // 1000  # integer division exactly as EnergyMarket.settle


def test_ledger_mirror_payload_is_a_p2p_trade_with_the_market_hashes():
    trade = {"id": 7, "seller": "prosumer_school_01", "buyer": "prosumer_shop_01", "matched_wh": 900, "settled_wh": 800, "price_milli": 6000,
             "pay_milli": 4800, "meter_seller_wh": 800, "meter_buyer_wh": 850, "chain_trade_id": 3,
             "match_tx_hash": "0xaa", "match_block": 10, "match_gas": 1, "meter_tx_hash": "0xbb", "meter_block": 11, "meter_gas": 2,
             "settle_tx_hash": "0xcc", "settle_block": 12, "settle_gas": 3}
    entry = events.live_market_trade(trade, {"id": 5, "chain_interval": 4, "solar_provenance": "simulated"}, {"contract_address": "0xC", "deployment_key": "0xC@0xB"})
    p = entry["payload"]
    assert entry["event_type"] == "P2P_TRADE" and p["trade_source"] == "live_market"
    assert (p["seller"], p["buyer"], p["kwh"], p["price_per_kwh"], p["pay"], p["interval_id"]) == ("prosumer_school_01", "prosumer_shop_01", 0.8, 6.0, 4.8, 5)
    assert p["energymarket"]["settle"]["tx_hash"] == "0xcc" and p["provenance_detail"]["solar"] == "simulated"
    assert entry["dedupe_key"] == "live_market:0xC@0xB:7"


# ---- twin / isolation ------------------------------------------------------------------------

def test_fresh_twin_is_the_original_nine_nodes_and_live_twin_adds_five_plus_solar():
    fresh = DigitalTwin()
    assert len(fresh.get_all_nodes()) == 9 and len(fresh.get_edges()) == 8
    live_ids = {n["node_id"] for n in digital_twin.get_all_nodes()}
    assert {n["node_id"] for n in fresh.get_all_nodes()} < live_ids
    assert live_ids - {n["node_id"] for n in fresh.get_all_nodes()} == {
        "community_bus", "prosumer_home_01", "prosumer_apartment_01", "prosumer_shop_01", "prosumer_school_01", "solar_01"}
    assert digital_twin.get_node("community_bus")["capacity_kw"] == 100.0


def test_self_healing_ignores_prosumers_and_community_bus():
    async def go():
        for nid in ("prosumer_home_01", "community_bus"):
            assert await self_healing.maybe_trigger(nid) is None
        assert "prosumer_home_01" not in self_healing._last_health_status
    asyncio.run(go())


# ---- worker must not block when the chain is down ------------------------------------------------

class DeadChain:
    deployment_key = None
    contract_address = None

    def ensure(self):
        raise MarketChainUnavailable("node unreachable (test)")


def test_worker_does_not_block_when_chain_is_down():
    async def go():
        svc = MarketService()
        svc.enabled = True
        svc.chain = DeadChain()
        await svc._check_connection()
        assert svc.state == "unreachable" and not svc._connected.is_set()
        worker = asyncio.create_task(svc._worker())
        svc._jobs.put_nowait(("post", 1))
        svc._jobs.put_nowait(("settle", 1))
        ticks = 0
        for _ in range(20):  # the event loop (ingestion stand-in) keeps running while jobs wait for the chain
            svc.observe("prosumer_home_01", 1.0 + ticks)
            ticks += 1
            await asyncio.sleep(0.01)
        assert ticks == 20 and svc._samples["prosumer_home_01"][-1] == 20.0
        assert svc._jobs.qsize() == 1  # first job taken by the worker and parked, second still queued; nothing sent
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker
    asyncio.run(go())
