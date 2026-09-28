"""
Admin authentication endpoints (/auth/*). Design notes in ARCHITECTURE.md
"Admin authentication".

Public (no access token): POST /auth/login, /auth/register, /auth/refresh,
/auth/logout. Admin only: GET /auth/me, POST /auth/invites, GET /auth/invites.
"""

import re
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth import store
from app.auth.deps import client_ip, require_admin
from app.auth.passwords import hash_password, password_problem, verify_password
from app.auth.rate_limit import limiter
from app.auth.tokens import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    REFRESH_COOKIE_PATH,
    create_access_token,
    hash_token,
    new_opaque_token,
    now,
)
from app.config import settings

router = APIRouter(prefix="/auth")

INVALID_CREDENTIALS = "Invalid credentials"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    token: str
    email: str
    password: str


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "role": user["role"],
        "created_at": user["created_at"],
        "last_login_at": user.get("last_login_at"),
    }


def _meta(request: Request) -> dict:
    return {"ip": client_ip(request), "user_agent": request.headers.get("user-agent")}


def _set_cookie(response: Response, name: str, value: str, max_age: int, path: str) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        path=path,
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def _clear_cookies(response: Response) -> None:
    for name, path in ((ACCESS_COOKIE, "/"), (REFRESH_COOKIE, REFRESH_COOKIE_PATH)):
        response.delete_cookie(
            name, path=path, domain=settings.cookie_domain, secure=settings.cookie_secure,
            httponly=True, samesite="strict",
        )


async def _issue_session(response: Response, user: dict, family_id: str | None = None,
                         refresh_raw: str | None = None) -> dict:
    """Set a fresh access cookie, plus a refresh cookie (new family on login)."""
    access, access_exp = create_access_token(user)
    _set_cookie(response, ACCESS_COOKIE, access, settings.access_token_minutes * 60, "/")
    if refresh_raw is None:
        refresh_raw = new_opaque_token()
        await store.insert_refresh_token(
            user["id"], hash_token(refresh_raw), family_id or uuid.uuid4().hex,
            now() + timedelta(days=settings.refresh_token_days),
        )
    _set_cookie(response, REFRESH_COOKIE, refresh_raw, settings.refresh_token_days * 86400, REFRESH_COOKIE_PATH)
    return {"user": _public_user(user), "access_expires_at": access_exp}


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response):
    meta = _meta(request)
    limiter.check(f"login:{meta['ip']}", settings.login_rate_limit)
    email = _normalize_email(body.email)
    user = await store.get_user_by_email(email) if email else None

    if user is not None and user["locked_until"] is not None and user["locked_until"] > now():
        verify_password(None, body.password)  # same cost as a real check
        await store.audit("login_failure_locked", user_id=user["id"], email=email, **meta)
        raise HTTPException(status_code=401, detail=INVALID_CREDENTIALS)

    ok = verify_password(user["password_hash"] if user else None, body.password)
    if not ok or not user["is_active"]:
        if user is not None and not ok:
            if await store.record_failed_login(user["id"], settings.lockout_threshold, settings.lockout_minutes):
                await store.audit("account_locked", user_id=user["id"], email=email, **meta)
        await store.audit("login_failure", user_id=user["id"] if user else None, email=email, **meta)
        raise HTTPException(status_code=401, detail=INVALID_CREDENTIALS)

    # Second factor hook: when TOTP is added, a user with mfa_enabled gets a
    # short-lived "mfa_pending" token here instead of a session, and a new
    # POST /auth/login/totp completes the login via _issue_session().
    # Nothing can set mfa_enabled yet, so this branch is unreachable today.
    if user["mfa_enabled"]:
        raise HTTPException(status_code=501, detail="Second factor required but not implemented yet")

    await store.record_successful_login(user["id"])
    user = await store.get_user_by_id(user["id"])
    result = await _issue_session(response, user)
    await store.audit("login_success", user_id=user["id"], email=email, **meta)
    return {**result, "mfa_required": False}


@router.post("/refresh")
async def refresh(request: Request, response: Response):
    meta = _meta(request)
    limiter.check(f"refresh:{meta['ip']}", settings.refresh_rate_limit)
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise HTTPException(status_code=401, detail="Not authenticated")
    new_raw = new_opaque_token()
    status, user = await store.rotate_refresh_token(
        hash_token(raw), hash_token(new_raw), now() + timedelta(days=settings.refresh_token_days)
    )
    if status == "ok":
        return await _issue_session(response, user, refresh_raw=new_raw)
    if status == "stale":
        # Another tab rotated this token a moment ago; the browser already has
        # the new cookies, so leave them alone.
        raise HTTPException(status_code=401, detail="Refresh token already rotated")
    if status == "reused":
        await store.audit("refresh_token_reuse", user_id=user["id"], **meta)
    fail = JSONResponse(status_code=401, content={"detail": "Session expired"})
    _clear_cookies(fail)
    return fail


@router.post("/logout")
async def logout(request: Request, response: Response):
    raw = request.cookies.get(REFRESH_COOKIE)
    user_id = await store.revoke_refresh_family(hash_token(raw)) if raw else None
    _clear_cookies(response)
    if user_id is not None:
        await store.audit("logout", user_id=user_id, **_meta(request))
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(require_admin)):
    return {"user": _public_user(user)}


@router.post("/register", status_code=201)
async def register(body: RegisterRequest, request: Request):
    meta = _meta(request)
    limiter.check(f"register:{meta['ip']}", settings.register_rate_limit)
    email = _normalize_email(body.email)
    if len(email) > 254 or not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    problem = password_problem(body.password)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    if not body.token:
        raise HTTPException(status_code=400, detail="This invite link is invalid.")
    try:
        user, invite_id = await store.register_with_invite(hash_token(body.token), email, hash_password(body.password))
    except store.InviteError as exc:
        await store.audit("register_failure_invite", email=email, **meta)
        raise HTTPException(status_code=400, detail=str(exc))
    except store.EmailTaken:
        await store.audit("register_failure_email_taken", email=email, **meta)
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    await store.audit("invite_used", user_id=user["id"], email=email, **meta)
    return {"user": _public_user(user)}


@router.post("/invites", status_code=201)
async def create_invite(request: Request, user: dict = Depends(require_admin)):
    raw = new_opaque_token()
    invite = await store.create_invite(
        hash_token(raw), user["id"], now() + timedelta(hours=settings.invite_ttl_hours)
    )
    await store.audit("invite_created", user_id=user["id"], email=user["email"], **_meta(request))
    # The raw token is returned exactly once and never stored.
    return {
        "id": invite["id"],
        "token": raw,
        "invite_url": f"{settings.frontend_origin.rstrip('/')}/register?token={raw}",
        "created_at": invite["created_at"],
        "expires_at": invite["expires_at"],
    }


@router.get("/invites")
async def list_invites(_: dict = Depends(require_admin)):
    current = now()
    rows = await store.list_invites()
    for row in rows:
        row["status"] = "used" if row["used_at"] else ("expired" if row["expires_at"] <= current else "pending")
    return {"invites": rows}
