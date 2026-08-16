"""
Shared registry across bot instances.
Prevents a user from joining more than one bot in the same family.
Uses a SQLite DB mounted as a shared volume between all containers.
"""

import os
import sqlite3
from datetime import datetime

SHARED_DB = os.getenv("SHARED_REGISTRY_PATH", "shared/registry.db")


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(SHARED_DB)), exist_ok=True)
    c = sqlite3.connect(SHARED_DB, timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_bot (
            user_id      INTEGER PRIMARY KEY,
            bot_instance TEXT    NOT NULL,
            registered_at TEXT   NOT NULL
        )
    """)
    c.commit()
    return c


def registry_check(user_id: int, current_bot: str) -> str | None:
    """Return bot_instance name if user is already in a DIFFERENT bot, else None."""
    c = _conn()
    try:
        row = c.execute(
            "SELECT bot_instance FROM user_bot WHERE user_id = ?", (user_id,)
        ).fetchone()
    finally:
        c.close()
    if row and row[0] != current_bot:
        return row[0]
    return None


def registry_register(user_id: int, bot_instance: str) -> None:
    """Register (or move) user to this bot instance."""
    c = _conn()
    try:
        c.execute(
            "INSERT OR REPLACE INTO user_bot (user_id, bot_instance, registered_at) VALUES (?, ?, ?)",
            (user_id, bot_instance, datetime.now().isoformat()),
        )
        c.commit()
    finally:
        c.close()


def registry_unregister(user_id: int) -> None:
    """Remove user from registry (on ban / removal / inactivity)."""
    try:
        c = _conn()
        try:
            c.execute("DELETE FROM user_bot WHERE user_id = ?", (user_id,))
            c.commit()
        finally:
            c.close()
    except Exception:
        pass
