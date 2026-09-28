import re
import time
from datetime import timedelta
from pathlib import Path

import jwt
import pytest
from fastapi.routing import APIRoute
from starlette.websockets import WebSocketDisconnect

from app.auth import store
from app.auth.passwords import COMMON_WORDS, password_problem
from app.auth.tokens import ACCESS_COOKIE, REFRESH_COOKIE
from app.config import settings
from app.main import app
from conftest import ADMIN_EMAIL, ADMIN_PASSWORD, ORIGIN, create_admin_row, sql

PUBLIC_ROUTES = {"/health", "/auth/login", "/auth/register", "/auth/refresh", "/auth/logout"}
NEW_PASSWORD = "a-perfectly-fine-passphrase"


def login(client, email=ADMIN_EMAIL, password=ADMIN_PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def audit_events():
    return [r[0] for r in sql("SELECT event_type FROM auth_audit_log ORDER BY id")]


# ---- login -----------------------------------------------------------------

def test_login_success_sets_httponly_strict_cookies(client, admin):
    r = login(client, email="  Admin@Example.COM ")  # email is case/space-insensitive
    assert r.status_code == 200
    assert r.json()["user"]["email"] == ADMIN_EMAIL
    set_cookies = r.headers.get_list("set-cookie")
    for name in (ACCESS_COOKIE, REFRESH_COOKIE):
        assert client.cookies.get(name) not in r.text  # tokens never appear in the body
    access = next(c for c in set_cookies if c.startswith(f"{ACCESS_COOKIE}="))
    refresh = next(c for c in set_cookies if c.startswith(f"{REFRESH_COOKIE}="))
    for c in (access, refresh):
        assert "HttpOnly" in c and "SameSite=strict" in c
    assert "Path=/auth" in refresh
    assert client.get("/auth/me").json()["user"]["email"] == ADMIN_EMAIL
    assert "login_success" in audit_events()
    assert sql("SELECT last_login_at IS NOT NULL FROM users")[0][0]


def test_login_failure_is_generic(client, admin):
    wrong_pw = login(client, password="wrong-password-123")
    wrong_email = login(client, email="nobody@example.com")
    assert wrong_pw.status_code == wrong_email.status_code == 401
    assert wrong_pw.json() == wrong_email.json() == {"detail": "Invalid credentials"}
    assert audit_events().count("login_failure") == 2


def test_lockout_after_five_failures(client, admin):
    for _ in range(5):
        assert login(client, password="wrong-password-123").status_code == 401
    # Locked: even the correct password fails, with the same generic message.
    r = login(client)
    assert r.status_code == 401 and r.json()["detail"] == "Invalid credentials"
    locked_until = sql("SELECT locked_until FROM users")[0][0]
    assert locked_until is not None
    events = audit_events()
    assert "account_locked" in events and "login_failure_locked" in events
    # Lock expires -> correct password works and the counter resets.
    sql("UPDATE users SET locked_until = now() - interval '1 second'")
    assert login(client).status_code == 200
    assert sql("SELECT failed_login_count, locked_until FROM users")[0] == (0, None)


def test_login_rate_limited_per_ip(client, admin):
    limit = int(settings.login_rate_limit.split("/")[0])
    for _ in range(limit):
        login(client, email="nobody@example.com")
    r = login(client, email="nobody@example.com")
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_inactive_user_cannot_log_in(client, admin):
    sql("UPDATE users SET is_active = FALSE")
    assert login(client).status_code == 401


def test_post_without_allowed_origin_is_rejected(client, admin):
    r = client.post("/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                    headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    r = client.post("/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                    headers={"origin": ""})
    assert r.status_code == 403


# ---- refresh / logout ------------------------------------------------------

def test_refresh_rotates_and_detects_reuse(client, admin, monkeypatch):
    assert login(client).status_code == 200
    first = client.cookies.get(REFRESH_COOKIE)
    r = client.post("/auth/refresh")
    assert r.status_code == 200
    second = client.cookies.get(REFRESH_COOKIE)
    assert second and second != first
    assert client.get("/auth/me").status_code == 200

    # Replaying the rotated token within the grace window: benign race, no revocation.
    client.cookies.clear()
    r = client.post("/auth/refresh", headers={"cookie": f"{REFRESH_COOKIE}={first}"})
    assert r.status_code == 401
    assert sql("SELECT count(*) FROM refresh_tokens WHERE revoked_at IS NULL")[0][0] == 1

    # Outside the grace window it is reuse: the whole family is revoked.
    monkeypatch.setattr(store, "ROTATION_GRACE", timedelta(0))
    r = client.post("/auth/refresh", headers={"cookie": f"{REFRESH_COOKIE}={first}"})
    assert r.status_code == 401
    assert "refresh_token_reuse" in audit_events()
    r = client.post("/auth/refresh", headers={"cookie": f"{REFRESH_COOKIE}={second}"})
    assert r.status_code == 401


def test_refresh_without_cookie_or_expired(client, admin):
    assert client.post("/auth/refresh").status_code == 401
    login(client)
    sql("UPDATE refresh_tokens SET expires_at = now() - interval '1 second'")
    r = client.post("/auth/refresh")
    assert r.status_code == 401
    assert any(c.startswith(f"{REFRESH_COOKIE}=") and "Max-Age=0" in c for c in r.headers.get_list("set-cookie"))


def test_logout_revokes_refresh_and_clears_cookies(logged_in):
    token = logged_in.cookies.get(REFRESH_COOKIE)
    r = logged_in.post("/auth/logout")
    assert r.status_code == 200
    assert logged_in.cookies.get(ACCESS_COOKIE) is None
    logged_in.cookies.clear()
    r = logged_in.post("/auth/refresh", headers={"cookie": f"{REFRESH_COOKIE}={token}"})
    assert r.status_code == 401
    assert "logout" in audit_events()


def test_expired_or_forged_access_token_rejected(client, admin):
    now = int(time.time())
    base = {"sub": str(admin), "email": ADMIN_EMAIL, "role": "admin", "type": "access"}
    expired = jwt.encode({**base, "iat": now - 1000, "exp": now - 10}, settings.jwt_secret, "HS256")
    forged = jwt.encode({**base, "iat": now, "exp": now + 600}, "some-other-secret-that-is-long-enough!!", "HS256")
    for token in (expired, forged, "garbage"):
        assert client.get("/nodes", headers={"cookie": f"{ACCESS_COOKIE}={token}"}).status_code == 401


# ---- invites / register ----------------------------------------------------

def make_invite(client):
    r = client.post("/auth/invites")
    assert r.status_code == 201, r.text
    return r.json()


def register(client, token, email="second@example.com", password=NEW_PASSWORD):
    return client.post("/auth/register", json={"token": token, "email": email, "password": password})


def test_invite_is_hashed_and_single_use(logged_in):
    invite = make_invite(logged_in)
    assert invite["invite_url"] == f"{ORIGIN}/register?token={invite['token']}"
    stored = sql("SELECT token_hash FROM invites")[0][0]
    assert stored != invite["token"] and len(stored) == 64
    assert "invite_created" in audit_events()

    logged_in.cookies.clear()
    r = register(logged_in, invite["token"], email="Second@Example.com")
    assert r.status_code == 201, r.text
    assert r.json()["user"]["email"] == "second@example.com"
    used_at, used_by = sql("SELECT used_at, used_by FROM invites")[0]
    assert used_at is not None and used_by == r.json()["user"]["id"]
    assert "invite_used" in audit_events()
    assert login(logged_in, "second@example.com", NEW_PASSWORD).status_code == 200

    r = register(logged_in, invite["token"], email="third@example.com")
    assert r.status_code == 400 and "already been used" in r.json()["detail"]


def test_expired_invite_rejected(logged_in):
    invite = make_invite(logged_in)
    sql("UPDATE invites SET expires_at = now() - interval '1 second'")
    r = register(logged_in, invite["token"])
    assert r.status_code == 400 and "expired" in r.json()["detail"]
    assert sql("SELECT count(*) FROM users")[0][0] == 1


def test_invalid_invite_rejected(client, admin):
    r = register(client, "not-a-real-token")
    assert r.status_code == 400 and "invalid" in r.json()["detail"]
    assert register(client, "").status_code == 400


def test_register_validates_input_and_keeps_invite_on_failure(logged_in):
    invite = make_invite(logged_in)
    assert register(logged_in, invite["token"], password="short").status_code == 422
    assert register(logged_in, invite["token"], password="Password123456!").status_code == 422
    assert register(logged_in, invite["token"], email="not-an-email").status_code == 422
    r = register(logged_in, invite["token"], email=ADMIN_EMAIL)
    assert r.status_code == 409
    # Failed attempts did not consume the invite (same transaction).
    assert sql("SELECT used_at FROM invites")[0][0] is None
    assert register(logged_in, invite["token"]).status_code == 201


def test_list_invites(logged_in):
    make_invite(logged_in)
    invites = logged_in.get("/auth/invites").json()["invites"]
    assert len(invites) == 1 and invites[0]["status"] == "pending"
    assert "token" not in invites[0] and "token_hash" not in invites[0]


def test_invite_endpoints_require_admin(client, admin):
    assert client.post("/auth/invites").status_code == 401
    assert client.get("/auth/invites").status_code == 401


def test_register_rate_limited(client, admin):
    limit = int(settings.register_rate_limit.split("/")[0])
    for _ in range(limit):
        register(client, "nope")
    assert register(client, "nope").status_code == 429


# ---- route protection ------------------------------------------------------

def protected_routes():
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path not in PUBLIC_ROUTES:
            path = re.sub(r"\{[^}]+\}", "1", route.path)
            for method in route.methods:
                yield method, path


def test_every_non_public_route_requires_auth(client, admin):
    routes = sorted(protected_routes())
    # Must match the protected-route list in ARCHITECTURE.md.
    assert routes == sorted([
        ("GET", "/nodes"), ("GET", "/nodes/1/history"),
        ("GET", "/twin/nodes"), ("GET", "/twin/nodes/1/history"), ("GET", "/twin/decisions"),
        ("GET", "/ai/predictions"),
        ("GET", "/chain/status"), ("GET", "/chain/records"), ("GET", "/chain/records/1"),
        ("POST", "/chain/verify/1"), ("POST", "/chain/simulate-trade"), ("POST", "/chain/replay-fl-rounds"),
        ("POST", "/chain/dev/tamper/1"),
        ("GET", "/auth/me"), ("POST", "/auth/invites"), ("GET", "/auth/invites"),
    ])
    for method, path in routes:
        r = client.request(method, path)
        assert r.status_code == 401, f"{method} {path} -> {r.status_code}"


def test_protected_route_works_with_session(logged_in):
    assert logged_in.get("/nodes").status_code == 200
    assert logged_in.get("/twin/nodes").status_code == 200


def test_health_is_public(client):
    assert client.get("/health").status_code == 200


def test_api_docs_disabled_by_default(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


# ---- WebSocket -------------------------------------------------------------

def ws_close_code(client, headers):
    with client.websocket_connect("/ws/updates", headers=headers) as ws:
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
    return exc.value.code


def test_websocket_rejects_unauthenticated(client, admin):
    assert ws_close_code(client, {"origin": ORIGIN}) == 4401
    assert ws_close_code(client, {"origin": ORIGIN, "cookie": f"{ACCESS_COOKIE}=garbage"}) == 4401


def test_websocket_rejects_foreign_origin(logged_in):
    assert ws_close_code(logged_in, {"origin": "https://evil.example"}) == 4403


def test_websocket_accepts_session_and_closes_at_token_expiry(client, admin):
    now = int(time.time())
    token = jwt.encode(
        {"sub": str(admin), "email": ADMIN_EMAIL, "role": "admin", "type": "access", "iat": now, "exp": now + 2},
        settings.jwt_secret, "HS256",
    )
    started = time.monotonic()
    code = ws_close_code(client, {"origin": ORIGIN, "cookie": f"{ACCESS_COOKIE}={token}"})
    # It was accepted and stayed open until the token expired, then closed with 4401.
    assert code == 4401
    assert time.monotonic() - started >= 0.9


# ---- password policy -------------------------------------------------------

@pytest.mark.parametrize("pw", ["short", "password1234", "Password123!", "qwerty123456", "aaaaaaaaaaaaaaa",
                                "123456789012", "iloveyou!!!!"])
def test_weak_passwords_rejected(pw):
    assert password_problem(pw) is not None


@pytest.mark.parametrize("pw", [NEW_PASSWORD, "Tr0ub4dor&3-horse", "grid-twin-ledger-42"])
def test_reasonable_passwords_accepted(pw):
    assert password_problem(pw) is None


def test_frontend_policy_mirrors_backend():
    js = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "auth" / "passwordPolicy.js").read_text()
    block = js[js.index("COMMON_WORDS = [") : js.index("]", js.index("COMMON_WORDS = ["))]
    assert re.findall(r"'([^']+)'", block) == COMMON_WORDS
    assert "MIN_LENGTH = 12" in js and "MAX_LENGTH = 128" in js


def test_create_admin_row_helper_matches_store(client):
    # Sanity check for the fixture: email stored lowercase, role admin.
    create_admin_row("x@example.com")
    assert sql("SELECT email, role, is_active FROM users")[0] == ("x@example.com", "admin", True)
