"""Prosumer login + /p2p dashboard: role separation, own-node scoping, order validation,
auto-trade toggle and the create_prosumers.py seeding script (run as a real subprocess
against the test database)."""

import re
import subprocess
import sys
from collections import deque
from pathlib import Path

import pytest

from app.auth.passwords import hash_password
from app.market import store as market_store
from app.market.service import market
from conftest import ADMIN_EMAIL, ADMIN_PASSWORD, sql

NODE, OTHER = "prosumer_home_01", "prosumer_shop_01"
PW = "prosumer-test-passphrase-1"
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "create_prosumers.py"

P2P_GET = ["/p2p/me", "/p2p/book", "/p2p/trades"]
P2P_POST = [("/p2p/offer", {"kwh": 0.05, "ask": 5.5}), ("/p2p/bid", {"kwh": 0.05, "max": 7.0}), ("/p2p/auto", {"enabled": False})]
ADMIN_ONLY = [("GET", "/nodes"), ("GET", "/twin/nodes"), ("GET", "/market/status"), ("GET", "/chain/status"),
              ("GET", "/auth/invites"), ("POST", "/auth/invites")]


@pytest.fixture(autouse=True)
def market_state(client, monkeypatch):
    """Fresh market tables per test; market enabled; prosumer_home_01 in surplus at 3 kW (cap 0.1 kWh / 120 s)."""
    sql(market_store.SCHEMA_SQL)
    sql("TRUNCATE market_node_settings, market_manual_orders, market_orders, market_trades, market_intervals RESTART IDENTITY")
    monkeypatch.setattr(market, "enabled", True)
    monkeypatch.setattr(market, "db_ready", False)
    monkeypatch.setattr(market, "auto_trade", {})
    monkeypatch.setattr(market, "_recent", {NODE: deque([3.0]), OTHER: deque([-2.0])})


def make_prosumer(email="home01@sei.local", node=NODE, password=PW):
    return sql("INSERT INTO users (email, password_hash, role, prosumer_node_id) VALUES (%s, %s, 'prosumer', %s) RETURNING id",
               (email, hash_password(password), node))[0][0]


@pytest.fixture()
def prosumer(client, admin):
    make_prosumer()
    r = client.post("/auth/login", json={"email": "home01@sei.local", "password": PW})
    assert r.status_code == 200, r.text
    return client


def login_as(client, email, password):
    client.cookies.clear()
    return client.post("/auth/login", json={"email": email, "password": password})


# ---- role separation ----------------------------------------------------------

def test_prosumer_session_and_me(prosumer):
    user = prosumer.get("/auth/me").json()["user"]
    assert user["role"] == "prosumer" and user["prosumer_node_id"] == NODE
    me = prosumer.get("/p2p/me").json()
    assert me["node_id"] == NODE and me["auto_trade"] is True and me["role"] in ("surplus", "deficit", "balanced", None)
    assert "Amounts are demo credits" in me["provenance_note"]


def test_prosumer_cannot_reach_admin_routes(prosumer):
    for method, path in ADMIN_ONLY:
        assert prosumer.request(method, path).status_code == 403, f"{method} {path}"


def test_admin_cannot_use_p2p_and_anonymous_gets_401(logged_in):
    for path in P2P_GET:
        assert logged_in.get(path).status_code == 403, path
    for path, body in P2P_POST:
        assert logged_in.post(path, json=body).status_code == 403, path
    logged_in.cookies.clear()
    for path in P2P_GET:
        assert logged_in.get(path).status_code == 401, path


def test_user_with_prosumer_role_but_no_node_is_refused(client, admin):
    sql("INSERT INTO users (email, password_hash, role) VALUES ('orphan@sei.local', %s, 'prosumer')", (hash_password(PW),))
    assert login_as(client, "orphan@sei.local", PW).status_code == 200
    assert client.get("/p2p/me").status_code == 403


def test_prosumer_websocket_gets_market_messages_only(prosumer):
    import asyncio

    from app.api.ws_manager import ConnectionManager

    class Fake:
        def __init__(self):
            self.sent = []

        async def accept(self):
            pass

        async def send_json(self, m):
            self.sent.append(m["type"])

    async def go():
        m, p, a = ConnectionManager(), Fake(), Fake()
        await m.connect(p, market_only=True)
        await m.connect(a)
        for t in ("twin_update", "chain_record", "market_order", "market_settlement"):
            await m.broadcast({"type": t})
        return p.sent, a.sent

    prosumer_got, admin_got = asyncio.run(go())
    assert prosumer_got == ["market_order", "market_settlement"]
    assert admin_got == ["twin_update", "chain_record", "market_order", "market_settlement"]


# ---- invite -> registration ----------------------------------------------------

def test_prosumer_invite_registers_a_linked_prosumer(logged_in):
    r = logged_in.post("/auth/invites", json={"prosumer_node_id": OTHER})
    assert r.status_code == 201 and r.json()["role"] == "prosumer" and r.json()["prosumer_node_id"] == OTHER
    assert logged_in.post("/auth/invites", json={"prosumer_node_id": "wind_01"}).status_code == 422
    token = r.json()["token"]
    logged_in.cookies.clear()
    reg = logged_in.post("/auth/register", json={"token": token, "email": "shop@sei.local", "password": PW})
    assert reg.status_code == 201
    assert reg.json()["user"]["role"] == "prosumer" and reg.json()["user"]["prosumer_node_id"] == OTHER
    assert login_as(logged_in, "shop@sei.local", PW).status_code == 200
    assert logged_in.get("/p2p/me").json()["node_id"] == OTHER
    # a plain invite (no body) still creates an admin
    assert login_as(logged_in, ADMIN_EMAIL, ADMIN_PASSWORD).status_code == 200
    inv = logged_in.post("/auth/invites").json()
    assert inv["role"] == "admin" and inv["prosumer_node_id"] is None
    # the node now has an account: no second invite for it
    assert logged_in.post("/auth/invites", json={"prosumer_node_id": OTHER}).status_code == 409


# ---- own node only ---------------------------------------------------------------

def test_another_nodes_data_is_403(prosumer):
    for path in P2P_GET:
        assert prosumer.get(path, params={"node_id": OTHER}).status_code == 403, path
        assert prosumer.get(path, params={"node_id": NODE}).status_code == 200, path
    assert prosumer.post("/p2p/offer", json={"kwh": 0.05, "ask": 5.5, "node_id": OTHER}).status_code == 403
    assert prosumer.post("/p2p/bid", json={"kwh": 0.05, "max": 7.0, "node_id": OTHER}).status_code == 403
    assert prosumer.post("/p2p/auto", json={"enabled": False, "node_id": OTHER}).status_code == 403
    assert sql("SELECT count(*) FROM market_manual_orders")[0][0] == 0
    assert market.is_auto(OTHER) is True


def test_trades_only_lists_my_trades(prosumer):
    now = "now()"
    for seller, buyer in ((NODE, OTHER), (OTHER, "prosumer_school_01"), ("prosumer_school_01", NODE)):
        sql(f"INSERT INTO market_trades (interval_id, seller, buyer, matched_wh, price_milli, status, created_at, settle_block) "
            f"VALUES (1, %s, %s, 50, 5000, 'settled', {now}, 7)", (seller, buyer))
    trades = prosumer.get("/p2p/trades").json()["trades"]
    assert sorted(t["side"] for t in trades) == ["buy", "sell"]
    assert all(t["status"] == "settled" and t["block_number"] == 7 for t in trades)


# ---- validation ----------------------------------------------------------------

def test_offer_requires_surplus_and_bid_requires_deficit(prosumer):
    assert prosumer.post("/p2p/bid", json={"kwh": 0.05, "max": 7.0}).status_code == 422  # surplus: cannot buy
    assert prosumer.post("/p2p/offer", json={"kwh": 0.05, "ask": 5.5}).status_code == 201
    market._recent[NODE] = deque([-2.0])
    r = prosumer.post("/p2p/offer", json={"kwh": 0.05, "ask": 5.5})
    assert r.status_code == 422 and "surplus" in r.json()["detail"]
    assert prosumer.post("/p2p/bid", json={"kwh": 0.05, "max": 7.0}).status_code == 201


@pytest.mark.parametrize("kwh", [0, -1, 0.5])  # none, negative, above the 0.1 kWh forecast surplus
def test_quantity_is_validated_against_the_forecast(prosumer, kwh):
    assert prosumer.post("/p2p/offer", json={"kwh": kwh, "ask": 5.5}).status_code == 422
    assert sql("SELECT count(*) FROM market_manual_orders")[0][0] == 0


@pytest.mark.parametrize("ask", [0, 1.0, 4.99, 8.01, 100])  # MARKET_PRICES bounds: 5.0 .. 8.0
def test_price_is_validated_against_market_prices_bounds(prosumer, ask):
    r = prosumer.post("/p2p/offer", json={"kwh": 0.05, "ask": ask})
    assert r.status_code == 422 and "between 5" in r.json()["detail"]


def test_malformed_body_is_422(prosumer):
    assert prosumer.post("/p2p/offer", json={"kwh": "lots", "ask": 5}).status_code == 422
    assert prosumer.post("/p2p/offer", json={}).status_code == 422


def test_new_manual_order_replaces_the_queued_one_and_shows_in_the_book(prosumer):
    first = prosumer.post("/p2p/offer", json={"kwh": 0.05, "ask": 5.5}).json()["order"]
    second = prosumer.post("/p2p/offer", json={"kwh": 0.08, "ask": 6.0}).json()["order"]
    status = dict(sql("SELECT id, status FROM market_manual_orders"))
    assert status[first["id"]] == "cancelled" and status[second["id"]] == "queued"
    assert second["qty_wh"] == 80 and second["price_milli"] == 6000
    book = prosumer.get("/p2p/book").json()
    assert [q["qty_wh"] for q in book["queued"]] == [80]


# ---- auto-trade toggle -------------------------------------------------------------

def test_auto_trade_toggle(prosumer):
    assert prosumer.get("/p2p/me").json()["auto_trade"] is True and market.is_auto(NODE)
    assert prosumer.post("/p2p/auto", json={"enabled": False}).json() == {"node_id": NODE, "auto_trade": False}
    assert market.is_auto(NODE) is False and market.is_auto(OTHER) is True
    assert prosumer.get("/p2p/me").json()["auto_trade"] is False
    assert sql("SELECT auto_trade FROM market_node_settings WHERE node_id = %s", (NODE,))[0][0] is False
    assert prosumer.post("/p2p/auto", json={"enabled": True}).json()["auto_trade"] is True
    assert market.is_auto(NODE)


# ---- create_prosumers.py -------------------------------------------------------------

def run_script(*args):
    out = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    rows = {}
    for line in out.stdout.splitlines():
        cells = re.split(r"\s{2,}", line.strip())
        if len(cells) == 4 and cells[0].startswith("prosumer_"):
            rows[cells[0]] = {"email": cells[1], "password": None if cells[2] == "-" else cells[2], "status": cells[3]}
    return rows, out


def test_script_seeds_two_accounts_that_can_log_in(client, admin):
    rows, out = run_script()
    assert set(rows) == {"prosumer_home_01", "prosumer_shop_01"}
    assert rows["prosumer_home_01"]["email"] == "home01@sei.local" and rows["prosumer_shop_01"]["email"] == "shop01@sei.local"
    assert all(r["status"] == "created" and len(r["password"]) >= 12 for r in rows.values())
    assert rows["prosumer_home_01"]["password"] != rows["prosumer_shop_01"]["password"]
    # only the argon2 hash is stored
    hashes = [h for (h,) in sql("SELECT password_hash FROM users WHERE role = 'prosumer'")]
    assert len(hashes) == 2 and all(h.startswith("$argon2") for h in hashes)
    assert all(r["password"] not in "".join(hashes) for r in rows.values())
    events = [e for (e,) in sql("SELECT event_type FROM auth_audit_log")]
    assert events.count("prosumer_created_cli") == 2
    assert all(r["password"] not in str(sql("SELECT * FROM auth_audit_log")) for r in rows.values())

    home = rows["prosumer_home_01"]
    assert login_as(client, home["email"], home["password"]).status_code == 200
    me = client.get("/p2p/me")
    assert me.status_code == 200 and me.json()["node_id"] == "prosumer_home_01"
    for method, path in ADMIN_ONLY:
        assert client.request(method, path).status_code in (401, 403), path
    client.cookies.clear()
    for method, path in ADMIN_ONLY:
        assert client.request(method, path).status_code == 401, path


def test_script_refuses_duplicates_and_reset_rotates_the_password(client, admin):
    first, _ = run_script("--node", "prosumer_home_01")
    old = first["prosumer_home_01"]["password"]
    again, out = run_script("--node", "prosumer_home_01")
    assert again["prosumer_home_01"]["status"].startswith("skipped") and again["prosumer_home_01"]["password"] is None
    assert old not in out.stdout
    assert sql("SELECT count(*) FROM users WHERE role = 'prosumer'")[0][0] == 1
    assert login_as(client, "home01@sei.local", old).status_code == 200  # untouched by the skipped run

    reset, _ = run_script("--node", "prosumer_home_01", "--reset")
    new = reset["prosumer_home_01"]["password"]
    assert reset["prosumer_home_01"]["status"] == "password reset" and new and new != old
    assert login_as(client, "home01@sei.local", old).status_code == 401
    assert login_as(client, "home01@sei.local", new).status_code == 200
    events = [e for (e,) in sql("SELECT event_type FROM auth_audit_log")]
    assert "prosumer_created_cli" in events and "prosumer_password_reset_cli" in events


def test_script_all_creates_four(client, admin):
    rows, _ = run_script("--all")
    assert sorted(rows) == ["prosumer_apartment_01", "prosumer_home_01", "prosumer_school_01", "prosumer_shop_01"]
    assert {r["email"] for r in rows.values()} == {"home01@sei.local", "apartment01@sei.local", "shop01@sei.local", "school01@sei.local"}
