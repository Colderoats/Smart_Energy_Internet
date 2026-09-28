"""
Auth test fixtures. Tests run against a SEPARATE database (sei_auth_test) in
the same TimescaleDB container as the backend (created on first run), with the
app's background tasks (ingestion, AI model, ledger) switched off.

    cd backend
    venv\\Scripts\\python -m pytest tests -q
"""

import os
import sys
from pathlib import Path

TEST_DB = "sei_auth_test"
ORIGIN = "http://localhost:5173"

os.environ["POSTGRES_DB"] = TEST_DB
os.environ["RUN_BACKGROUND_TASKS"] = "false"
os.environ["JWT_SECRET"] = "test-secret-" + "x" * 40
os.environ["COOKIE_SECURE"] = "false"
os.environ["FRONTEND_ORIGIN"] = ORIGIN
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402


def _conninfo(dbname: str) -> str:
    return (
        f"host={settings.postgres_host} port={settings.postgres_port} user={settings.postgres_user} "
        f"password={settings.postgres_password} dbname={dbname}"
    )


def _ensure_test_db() -> None:
    with psycopg.connect(_conninfo("postgres"), autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{TEST_DB}"')


_ensure_test_db()

from app.auth.passwords import hash_password  # noqa: E402
from app.auth.rate_limit import limiter  # noqa: E402
from app.main import app  # noqa: E402

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "correct-horse-battery-staple"


def sql(query: str, params: tuple = ()):
    """Run SQL against the test DB from the test thread (sync connection)."""
    with psycopg.connect(_conninfo(TEST_DB), autocommit=True) as conn:
        cur = conn.execute(query, params)
        return cur.fetchall() if cur.description else None


@pytest.fixture(scope="session")
def app_client():
    with TestClient(app, headers={"origin": ORIGIN}) as c:
        yield c


@pytest.fixture()
def client(app_client):
    sql("TRUNCATE users, invites, auth_audit_log, refresh_tokens RESTART IDENTITY CASCADE")
    limiter.reset()
    app_client.cookies.clear()
    yield app_client
    app_client.cookies.clear()


def create_admin_row(email: str = ADMIN_EMAIL, password: str = ADMIN_PASSWORD) -> int:
    return sql(
        "INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id",
        (email, hash_password(password)),
    )[0][0]


@pytest.fixture()
def admin(client):
    return create_admin_row()


@pytest.fixture()
def logged_in(client, admin):
    r = client.post("/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return client
