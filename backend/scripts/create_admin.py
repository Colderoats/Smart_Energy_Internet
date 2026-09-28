"""
Create the FIRST admin account (one-time bootstrap; every later admin joins via
an invite link).

    cd backend
    venv\\Scripts\\python scripts\\create_admin.py            # prompts for email + password
    SEI_ADMIN_EMAIL=... SEI_ADMIN_PASSWORD=... python scripts/create_admin.py

Refuses to run if any admin already exists, unless --force is passed. With
--force and an existing email, that account's password is reset (and it is
unlocked/re-activated); otherwise an additional admin is created.
Needs TimescaleDB running (same .env as the backend).
"""

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db  # noqa: E402
from app.api.auth_routes import EMAIL_RE  # noqa: E402
from app.auth import store  # noqa: E402
from app.auth.passwords import hash_password, password_problem  # noqa: E402


def read_credentials() -> tuple[str, str]:
    email = os.environ.get("SEI_ADMIN_EMAIL") or input("Admin email: ")
    password = os.environ.get("SEI_ADMIN_PASSWORD")
    if not password:
        password = getpass.getpass("Password (min 12 chars): ")
        if getpass.getpass("Repeat password: ") != password:
            sys.exit("Passwords do not match.")
    return email.strip().lower(), password


async def main(force: bool) -> None:
    await db.connect()
    try:
        await db.init_schema()
        await store.init_schema()
        if await store.count_admins() > 0 and not force:
            sys.exit("An admin already exists. Invite further admins from the dashboard, "
                     "or pass --force to create/reset one anyway.")
        email, password = read_credentials()
        if not EMAIL_RE.match(email):
            sys.exit("Invalid email address.")
        problem = password_problem(password)
        if problem:
            sys.exit(problem)
        password_hash = hash_password(password)
        existing = await store.get_user_by_email(email)
        if existing and force:
            await store.set_password(email, password_hash)
            await store.audit("admin_password_reset_cli", user_id=existing["id"], email=email, ip="cli")
            print(f"Password reset for existing admin {email}.")
        elif existing:
            sys.exit(f"{email} already exists.")
        else:
            user = await store.create_user(email, password_hash, "admin")
            await store.audit("admin_created_cli", user_id=user["id"], email=email, ip="cli")
            print(f"Admin {email} created. Log in at the dashboard.")
    finally:
        await db.disconnect()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    parser = argparse.ArgumentParser(description="Create the first Smart Energy Internet admin.")
    parser.add_argument("--force", action="store_true", help="run even if an admin already exists")
    asyncio.run(main(parser.parse_args().force))
