"""
Server-side enforcement.

- require_admin: FastAPI dependency applied to every protected REST router
  (see app/main.py). 401 without a valid access cookie, 403 for a non-admin.
- authenticate_websocket: the same check for the /ws/updates handshake.
- origin_check_middleware: CSRF defence. Cookies are SameSite=Strict AND every
  state-changing request (POST/PUT/PATCH/DELETE) must carry an Origin (or
  Referer) equal to FRONTEND_ORIGIN, otherwise 403.
"""

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.requests import HTTPConnection

from app.auth import store
from app.auth.tokens import ACCESS_COOKIE, decode_access_token
from app.config import settings

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def client_ip(conn: HTTPConnection) -> str:
    peer = conn.client.host if conn.client else "unknown"
    trusted = {p.strip() for p in settings.trusted_proxies.split(",") if p.strip()}
    forwarded = conn.headers.get("x-forwarded-for")
    if forwarded and peer in trusted:
        return forwarded.split(",")[0].strip()
    return peer


def origin_allowed(conn: HTTPConnection) -> bool:
    origin = conn.headers.get("origin")
    if origin is None:
        referer = conn.headers.get("referer")
        if referer is None:
            return False
        parts = referer.split("/")
        origin = "/".join(parts[:3]) if len(parts) >= 3 else referer
    return origin.rstrip("/") == settings.frontend_origin.rstrip("/")


async def user_from_connection(conn: HTTPConnection) -> tuple[dict, dict] | None:
    """(user, claims) for a valid access cookie belonging to an active user, else None."""
    token = conn.cookies.get(ACCESS_COOKIE)
    if not token:
        return None
    claims = decode_access_token(token)
    if claims is None:
        return None
    try:
        user = await store.get_user_by_id(int(claims["sub"]))
    except (ValueError, RuntimeError):
        return None
    if user is None or not user["is_active"]:
        return None
    return user, claims


async def require_admin(request: Request) -> dict:
    found = await user_from_connection(request)
    if found is None:
        raise HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Cookie"})
    user, _ = found
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def authenticate_websocket(conn: HTTPConnection) -> tuple[dict, dict] | None:
    found = await user_from_connection(conn)
    if found is None or found[0]["role"] != "admin":
        return None
    return found


async def origin_check_middleware(request: Request, call_next):
    if request.method in UNSAFE_METHODS and not origin_allowed(request):
        return JSONResponse(status_code=403, content={"detail": "Origin not allowed"})
    return await call_next(request)
