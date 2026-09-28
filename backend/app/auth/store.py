"""
Auth tables and queries. Same migration approach as app/db.py and the Module 5
ledger: idempotent CREATE ... IF NOT EXISTS, run at startup (init_schema).

All opaque tokens (refresh tokens, invites) are stored as SHA-256 hashes only.
"""

import logging
from datetime import datetime, timedelta

from psycopg import errors
from psycopg.rows import dict_row

from app import db
from app.auth.tokens import now

logger = logging.getLogger("sei.auth")

AUTH_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE CHECK (email = lower(email)),
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'admin',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ,
    -- Reserved for a later TOTP second factor (not implemented yet): the login
    -- flow already branches on mfa_enabled, see app/api/auth_routes.py.
    mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    mfa_secret TEXT
);

CREATE TABLE IF NOT EXISTS invites (
    id BIGSERIAL PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    created_by BIGINT NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    used_by BIGINT REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS auth_audit_log (
    id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    email_attempted TEXT,
    ip TEXT,
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS auth_audit_log_time_idx ON auth_audit_log (created_at DESC);

-- Server-side refresh tokens (hashed) so they can be rotated and revoked.
-- All tokens descended from one login share a family_id; re-use of a rotated
-- token revokes the whole family.
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    family_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    replaced_by BIGINT REFERENCES refresh_tokens(id)
);
CREATE INDEX IF NOT EXISTS refresh_tokens_family_idx ON refresh_tokens (family_id);
"""

# A rotated token presented again within this window is treated as a benign
# race (two tabs refreshing at once), not as theft.
ROTATION_GRACE = timedelta(seconds=10)


class InviteError(Exception):
    """Invite token is invalid, used or expired (message is user-facing)."""


class EmailTaken(Exception):
    pass


async def init_schema() -> None:
    async with db.get_pool().connection() as conn:
        await conn.execute(AUTH_SCHEMA_SQL)


async def _fetchone(sql: str, params: tuple) -> dict | None:
    async with db.get_pool().connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return await cur.fetchone()


async def get_user_by_email(email: str) -> dict | None:
    return await _fetchone("SELECT * FROM users WHERE email = %s", (email,))


async def get_user_by_id(user_id: int) -> dict | None:
    return await _fetchone("SELECT * FROM users WHERE id = %s", (user_id,))


async def count_admins() -> int:
    row = await _fetchone("SELECT count(*) AS n FROM users WHERE role = 'admin'", ())
    return row["n"]


async def create_user(email: str, password_hash: str, role: str = "admin") -> dict:
    try:
        return await _fetchone(
            "INSERT INTO users (email, password_hash, role) VALUES (%s, %s, %s) RETURNING *",
            (email, password_hash, role),
        )
    except errors.UniqueViolation as exc:
        raise EmailTaken() from exc


async def set_password(email: str, password_hash: str) -> dict | None:
    return await _fetchone(
        "UPDATE users SET password_hash = %s, failed_login_count = 0, locked_until = NULL, is_active = TRUE "
        "WHERE email = %s RETURNING *",
        (password_hash, email),
    )


async def record_failed_login(user_id: int, threshold: int, lock_minutes: int) -> bool:
    """Count a failure; lock the account at the threshold. Returns True if it just got locked."""
    row = await _fetchone(
        """
        UPDATE users SET
            failed_login_count = CASE WHEN failed_login_count + 1 >= %(t)s THEN 0
                                      ELSE failed_login_count + 1 END,
            locked_until = CASE WHEN failed_login_count + 1 >= %(t)s
                                THEN now() + make_interval(mins => %(m)s) ELSE locked_until END
        WHERE id = %(id)s
        RETURNING failed_login_count, locked_until
        """,
        {"t": threshold, "m": lock_minutes, "id": user_id},
    )
    return bool(row and row["failed_login_count"] == 0 and row["locked_until"] and row["locked_until"] > now())


async def record_successful_login(user_id: int) -> None:
    async with db.get_pool().connection() as conn:
        await conn.execute(
            "UPDATE users SET failed_login_count = 0, locked_until = NULL, last_login_at = now() WHERE id = %s",
            (user_id,),
        )


async def audit(event_type: str, *, user_id=None, email=None, ip=None, user_agent=None) -> None:
    """Append to auth_audit_log. Never raises: auditing must not break a login."""
    try:
        async with db.get_pool().connection() as conn:
            await conn.execute(
                "INSERT INTO auth_audit_log (event_type, user_id, email_attempted, ip, user_agent) "
                "VALUES (%s, %s, %s, %s, %s)",
                (event_type, user_id, (email or "")[:254] or None, ip, (user_agent or "")[:512] or None),
            )
    except Exception as exc:
        logger.warning("audit log write failed (%s): %s", event_type, exc)


# ---- refresh tokens -------------------------------------------------------

async def insert_refresh_token(user_id: int, token_hash: str, family_id: str, expires_at: datetime) -> None:
    async with db.get_pool().connection() as conn:
        await conn.execute(
            "INSERT INTO refresh_tokens (user_id, token_hash, family_id, expires_at) VALUES (%s, %s, %s, %s)",
            (user_id, token_hash, family_id, expires_at),
        )


async def rotate_refresh_token(old_hash: str, new_hash: str, expires_at: datetime) -> tuple[str, dict | None]:
    """
    Swap a refresh token for a new one in the same family, atomically.
    Returns (status, user): status is "ok", "invalid", "expired", "stale"
    (benign concurrent rotation; the browser already holds the newer cookie)
    or "reused" (a rotated/revoked token was replayed: the family is revoked).
    """
    async with db.get_pool().connection() as conn:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SELECT * FROM refresh_tokens WHERE token_hash = %s FOR UPDATE", (old_hash,))
                old = await cur.fetchone()
                if old is None:
                    return "invalid", None
                current = now()
                if old["revoked_at"] is not None:
                    if old["replaced_by"] is not None and current - old["revoked_at"] < ROTATION_GRACE:
                        return "stale", None
                    await cur.execute(
                        "UPDATE refresh_tokens SET revoked_at = now() WHERE family_id = %s AND revoked_at IS NULL",
                        (old["family_id"],),
                    )
                    return "reused", {"id": old["user_id"]}
                if old["expires_at"] <= current:
                    return "expired", None
                await cur.execute("SELECT * FROM users WHERE id = %s", (old["user_id"],))
                user = await cur.fetchone()
                if user is None or not user["is_active"]:
                    await cur.execute("UPDATE refresh_tokens SET revoked_at = now() WHERE id = %s", (old["id"],))
                    return "invalid", None
                await cur.execute(
                    "INSERT INTO refresh_tokens (user_id, token_hash, family_id, expires_at) "
                    "VALUES (%s, %s, %s, %s) RETURNING id",
                    (old["user_id"], new_hash, old["family_id"], expires_at),
                )
                new_id = (await cur.fetchone())["id"]
                await cur.execute(
                    "UPDATE refresh_tokens SET revoked_at = now(), replaced_by = %s WHERE id = %s",
                    (new_id, old["id"]),
                )
                return "ok", user


async def revoke_refresh_family(token_hash: str) -> int | None:
    """Revoke every token in this token's family (logout). Returns the user id, if known."""
    async with db.get_pool().connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT user_id, family_id FROM refresh_tokens WHERE token_hash = %s", (token_hash,))
            row = await cur.fetchone()
            if row is None:
                return None
            await cur.execute(
                "UPDATE refresh_tokens SET revoked_at = now() WHERE family_id = %s AND revoked_at IS NULL",
                (row["family_id"],),
            )
            return row["user_id"]


# ---- invites --------------------------------------------------------------

async def create_invite(token_hash: str, created_by: int, expires_at: datetime) -> dict:
    return await _fetchone(
        "INSERT INTO invites (token_hash, created_by, expires_at) VALUES (%s, %s, %s) "
        "RETURNING id, created_by, created_at, expires_at",
        (token_hash, created_by, expires_at),
    )


async def list_invites(limit: int = 100) -> list[dict]:
    async with db.get_pool().connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT i.id, i.created_at, i.expires_at, i.used_at,
                       c.email AS created_by_email, u.email AS used_by_email
                FROM invites i
                JOIN users c ON c.id = i.created_by
                LEFT JOIN users u ON u.id = i.used_by
                ORDER BY i.created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return await cur.fetchall()


async def register_with_invite(token_hash: str, email: str, password_hash: str) -> tuple[dict, int]:
    """
    Validate the invite, create the user and mark the invite used in ONE
    transaction. The invite row is locked (FOR UPDATE) so two concurrent
    registrations cannot both consume it. Returns (user, invite_id).
    """
    async with db.get_pool().connection() as conn:
        try:
            async with conn.transaction():
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute("SELECT * FROM invites WHERE token_hash = %s FOR UPDATE", (token_hash,))
                    invite = await cur.fetchone()
                    if invite is None:
                        raise InviteError("This invite link is invalid.")
                    if invite["used_at"] is not None:
                        raise InviteError("This invite link has already been used.")
                    if invite["expires_at"] <= now():
                        raise InviteError("This invite link has expired. Ask an admin for a new one.")
                    await cur.execute(
                        "INSERT INTO users (email, password_hash, role) VALUES (%s, %s, 'admin') RETURNING *",
                        (email, password_hash),
                    )
                    user = await cur.fetchone()
                    await cur.execute(
                        "UPDATE invites SET used_at = now(), used_by = %s WHERE id = %s",
                        (user["id"], invite["id"]),
                    )
                    return user, invite["id"]
        except errors.UniqueViolation as exc:
            raise EmailTaken() from exc
