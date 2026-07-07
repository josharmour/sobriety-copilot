"""SQLite-backed user state + interaction history.

Per-user record of sobriety date, current step, and free-form notes,
plus an append-only interaction log. The path is configurable via
USER_MEMORY_DB_PATH (default ./user_memory.db), so the same module
works inside the container (volume-mounted persistent path) and on a
developer laptop without changing code.
"""

from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass


@dataclass
class UserState:
    user_id: str
    sobriety_date: str | None = None
    current_step: int = 1
    notes: str = ""
    last_interaction: float | None = None


DEFAULT_DB_PATH = os.environ.get("USER_MEMORY_DB_PATH", "user_memory.db")


class UserMemoryManager:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or DEFAULT_DB_PATH
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS user_state ("
                " user_id TEXT PRIMARY KEY,"
                " sobriety_date TEXT,"
                " current_step INTEGER,"
                " notes TEXT,"
                " last_interaction REAL"
                ")"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS interaction_history ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " user_id TEXT NOT NULL,"
                " message TEXT NOT NULL,"
                " response TEXT,"
                " timestamp REAL NOT NULL"
                ")"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_history_user_ts "
                "ON interaction_history (user_id, timestamp DESC)"
            )

    def get_user_state(self, user_id: str) -> UserState:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT user_id, sobriety_date, current_step, notes, last_interaction "
                "FROM user_state WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if not row:
            return UserState(user_id=user_id)
        return UserState(
            user_id=row[0],
            sobriety_date=row[1],
            current_step=row[2] if row[2] is not None else 1,
            notes=row[3] or "",
            last_interaction=row[4],
        )

    def update_user_state(self, state: UserState) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO user_state (user_id, sobriety_date, current_step, notes, last_interaction) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                "  sobriety_date    = excluded.sobriety_date,"
                "  current_step     = excluded.current_step,"
                "  notes            = excluded.notes,"
                "  last_interaction = excluded.last_interaction",
                (
                    state.user_id,
                    state.sobriety_date,
                    state.current_step,
                    state.notes,
                    state.last_interaction,
                ),
            )

    def save_interaction(self, user_id: str, message: str, response: str) -> None:
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO interaction_history (user_id, message, response, timestamp) "
                "VALUES (?, ?, ?, ?)",
                (user_id, message, response, now),
            )
            conn.execute(
                "INSERT INTO user_state (user_id, current_step, notes, last_interaction) "
                "VALUES (?, 1, '', ?) "
                "ON CONFLICT(user_id) DO UPDATE SET last_interaction = excluded.last_interaction",
                (user_id, now),
            )

    def touch(self, user_id: str) -> None:
        """Update last_interaction without storing any message content.

        Used when STORE_CHAT_HISTORY is off (the privacy-preserving default).
        """
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO user_state (user_id, current_step, notes, last_interaction) "
                "VALUES (?, 1, '', ?) "
                "ON CONFLICT(user_id) DO UPDATE SET last_interaction = excluded.last_interaction",
                (user_id, now),
            )

    def get_recent_history(self, user_id: str, limit: int = 5) -> list[dict]:
        with self._conn() as conn:
            cursor = conn.execute(
                "SELECT message, response, timestamp FROM interaction_history "
                "WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
                (user_id, limit),
            )
            return [
                {"message": r[0], "response": r[1], "timestamp": r[2]}
                for r in cursor.fetchall()
            ]


def format_state_note(state: UserState) -> str:
    """Render UserState as a short ambient-context note for the LLM.

    Returns empty string when the state has no actionable info — we don't
    want to inject `Current step: 1` into the system message for every
    anonymous visitor.
    """
    parts: list[str] = []
    if state.sobriety_date:
        parts.append(f"Sobriety date: {state.sobriety_date}")
    if state.current_step and state.current_step != 1:
        parts.append(f"Currently working step: {state.current_step}")
    if state.notes:
        parts.append(f"Personal notes: {state.notes}")
    if not parts:
        return ""
    return (
        "User context (private; reference if relevant, do not recite "
        "verbatim): " + " · ".join(parts)
    )
