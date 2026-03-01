import json
import random
import time

import aiosqlite

from app.config import DB_PATH, PIN_TTL_SECONDS

_db: aiosqlite.Connection | None = None


async def init() -> None:
    global _db
    _db = await aiosqlite.connect(DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            alice_user_id TEXT PRIMARY KEY,
            hb_email      TEXT NOT NULL,
            hb_refresh_token TEXT NOT NULL,
            selected_child_uid TEXT,
            child_name    TEXT,
            children_json TEXT DEFAULT '[]',
            timezone      TEXT NOT NULL DEFAULT 'Europe/Moscow'
        );
        CREATE TABLE IF NOT EXISTS pending_links (
            pin       TEXT PRIMARY KEY,
            hb_data   TEXT NOT NULL,
            created_at REAL NOT NULL
        );
    """)
    await _db.commit()


async def close() -> None:
    global _db
    if _db:
        await _db.close()
        _db = None


def _conn() -> aiosqlite.Connection:
    assert _db is not None, "DB not initialized"
    return _db


async def get_user(alice_user_id: str) -> dict | None:
    cur = await _conn().execute(
        "SELECT * FROM users WHERE alice_user_id = ?", (alice_user_id,)
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def upsert_user(
    alice_user_id: str,
    hb_email: str,
    hb_refresh_token: str,
    timezone: str = "Europe/Moscow",
    selected_child_uid: str | None = None,
    child_name: str | None = None,
    children: list[dict] | None = None,
) -> None:
    children_json = json.dumps(children or [])
    await _conn().execute(
        """INSERT INTO users (alice_user_id, hb_email, hb_refresh_token, timezone, selected_child_uid, child_name, children_json)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(alice_user_id) DO UPDATE SET
               hb_email=excluded.hb_email,
               hb_refresh_token=excluded.hb_refresh_token,
               timezone=excluded.timezone,
               selected_child_uid=excluded.selected_child_uid,
               child_name=excluded.child_name,
               children_json=excluded.children_json""",
        (alice_user_id, hb_email, hb_refresh_token, timezone, selected_child_uid, child_name, children_json),
    )
    await _conn().commit()


async def update_user_child(alice_user_id: str, child_uid: str, child_name: str) -> None:
    await _conn().execute(
        "UPDATE users SET selected_child_uid=?, child_name=? WHERE alice_user_id=?",
        (child_uid, child_name, alice_user_id),
    )
    await _conn().commit()


async def update_refresh_token(alice_user_id: str, token: str) -> None:
    await _conn().execute(
        "UPDATE users SET hb_refresh_token=? WHERE alice_user_id=?",
        (token, alice_user_id),
    )
    await _conn().commit()


async def create_pending_link(hb_email: str, hb_refresh_token: str, children: list[dict], timezone: str = "Europe/Moscow") -> str:
    pin = f"{random.randint(0, 999999):06d}"
    data = json.dumps({"email": hb_email, "refresh_token": hb_refresh_token, "children": children, "timezone": timezone})
    await _conn().execute(
        "INSERT OR REPLACE INTO pending_links (pin, hb_data, created_at) VALUES (?, ?, ?)",
        (pin, data, time.time()),
    )
    await _conn().commit()
    return pin


async def consume_pending_link(pin: str) -> dict | None:
    cur = await _conn().execute("SELECT * FROM pending_links WHERE pin = ?", (pin,))
    row = await cur.fetchone()
    if not row:
        return None
    row = dict(row)
    if time.time() - row["created_at"] > PIN_TTL_SECONDS:
        await _conn().execute("DELETE FROM pending_links WHERE pin = ?", (pin,))
        await _conn().commit()
        return None
    await _conn().execute("DELETE FROM pending_links WHERE pin = ?", (pin,))
    await _conn().commit()
    return json.loads(row["hb_data"])


async def cleanup_expired_links() -> None:
    cutoff = time.time() - PIN_TTL_SECONDS
    await _conn().execute("DELETE FROM pending_links WHERE created_at < ?", (cutoff,))
    await _conn().commit()
