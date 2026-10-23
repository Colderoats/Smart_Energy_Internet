"""
Create the seeded PROSUMER accounts (one login per simulated building of the live market).

    cd backend
    venv\\Scripts\\python scripts\\create_prosumers.py                   # prosumer_home_01 + prosumer_shop_01
    venv\\Scripts\\python scripts\\create_prosumers.py --all             # all 4 buildings
    venv\\Scripts\\python scripts\\create_prosumers.py --node prosumer_school_01 [--node ...]
    venv\\Scripts\\python scripts\\create_prosumers.py --reset           # rotate the password of existing accounts

A random password (passing the password policy) is generated per account and printed ONCE to the
console. It is never written to a file, a log or .env; only the argon2 hash is stored. A node that
already has a prosumer account is skipped unless --reset is given. Emails are <profile><nn>@sei.local
(home01, apartment01, shop01, school01). Audit events: prosumer_created_cli / prosumer_password_reset_cli.
Needs TimescaleDB running (same .env as the backend).
"""

import argparse
import asyncio
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db  # noqa: E402
from app.auth import store  # noqa: E402
from app.auth.passwords import hash_password, password_problem  # noqa: E402
from app.twin.digital_twin import PROSUMER_NODES  # noqa: E402

DEFAULT_NODES = ["prosumer_home_01", "prosumer_shop_01"]
ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no look-alikes (l, 1, I, O, 0)


def email_for(node_id: str) -> str:
    """prosumer_home_01 -> home01@sei.local"""
    _, profile, num = node_id.split("_")
    return f"{profile}{num}@sei.local"


def new_password() -> str:
    while True:
        pw = "".join(secrets.choice(ALPHABET) for _ in range(16))
        if password_problem(pw) is None:
            return pw


async def provision(nodes: list[str], reset: bool) -> list[dict]:
    """Create / skip / reset one prosumer account per node (the DB pool must already be connected)."""
    rows = []
    for node in nodes:
        email = email_for(node)
        existing = await store.get_prosumer_user(node)
        if existing and not reset:
            rows.append({"node": node, "email": existing["email"], "password": None, "status": "skipped (account exists, use --reset)"})
            continue
        password = new_password()
        pw_hash = hash_password(password)
        if existing:
            await store.set_password(existing["email"], pw_hash)
            await store.audit("prosumer_password_reset_cli", user_id=existing["id"], email=existing["email"], ip="cli")
            rows.append({"node": node, "email": existing["email"], "password": password, "status": "password reset"})
            continue
        try:
            user = await store.create_user(email, pw_hash, "prosumer", node)
        except store.EmailTaken:
            rows.append({"node": node, "email": email, "password": None, "status": "skipped (email belongs to another account)"})
            continue
        await store.audit("prosumer_created_cli", user_id=user["id"], email=email, ip="cli")
        rows.append({"node": node, "email": email, "password": password, "status": "created"})
    return rows


def print_table(rows: list[dict]) -> None:
    cols = [("Node", "node"), ("Email", "email"), ("Password", "password"), ("Status", "status")]
    cells = [[c for c, _ in cols]] + [[r[k] or "-" for _, k in cols] for r in rows]
    widths = [max(len(row[i]) for row in cells) for i in range(len(cols))]
    for n, row in enumerate(cells):
        print("  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip())
        if n == 0:
            print("  ".join("-" * w for w in widths))
    if any(r["password"] for r in rows):
        print("\nThese passwords are shown ONCE and are not stored anywhere (only their hash is). Log in at the dashboard login page.")


async def main(nodes: list[str], reset: bool) -> None:
    await db.connect()
    try:
        await db.init_schema()
        await store.init_schema()
        print_table(await provision(nodes, reset))
    finally:
        await db.disconnect()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    known = [p["node_id"] for p in PROSUMER_NODES]
    parser = argparse.ArgumentParser(description="Create seeded Smart Energy Internet prosumer accounts.")
    parser.add_argument("--all", action="store_true", help="all 4 buildings")
    parser.add_argument("--node", action="append", choices=known, help="a specific building (repeatable)")
    parser.add_argument("--reset", action="store_true", help="rotate the password of nodes that already have an account")
    args = parser.parse_args()
    selected = known if args.all else (args.node or DEFAULT_NODES)
    asyncio.run(main(list(dict.fromkeys(selected)), args.reset))
