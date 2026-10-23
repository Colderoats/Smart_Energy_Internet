"""TC05 helper: create the isolated sei_tc05 database and its admin (backend venv). Prints nothing secret."""
import asyncio, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ["POSTGRES_DB"] = "sei_tc05"
import psycopg
from app.config import settings
c = f"host={settings.postgres_host} port={settings.postgres_port} user={settings.postgres_user} password={settings.postgres_password} dbname=postgres"
with psycopg.connect(c, autocommit=True) as conn:
    if not conn.execute("SELECT 1 FROM pg_database WHERE datname='sei_tc05'").fetchone():
        conn.execute('CREATE DATABASE "sei_tc05"')
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from app import db
from app.auth import store
from app.auth.passwords import hash_password
async def main():
    await db.connect(); await db.init_schema(); await store.init_schema()
    if not await store.get_user_by_email("tc05@example.com"):
        await store.create_user("tc05@example.com", hash_password("Tc05-test-password-1"), "admin")
    await db.disconnect()
asyncio.run(main())
