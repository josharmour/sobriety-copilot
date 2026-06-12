"""SQLite-backed bug report store.

Durable replacement for the old Redis list (Redis here runs with weak
persistence, so reports submitted from the PWA's "Report a Bug" button were
being lost across restarts). The path is configurable via BUG_REPORT_DB_PATH
so the same module works inside the container (volume-mounted persistent
path) and on a developer laptop. Reads are gated by an admin token at the
API layer — this module just stores, lists, and tracks seen/unseen state.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from uuid import uuid4

DEFAULT_DB_PATH = os.environ.get("BUG_REPORT_DB_PATH", "bug_reports.db")


class BugReportStore:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or DEFAULT_DB_PATH
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS bug_reports ("
                " id TEXT PRIMARY KEY,"
                " description TEXT NOT NULL,"
                " conversation TEXT,"
                " url TEXT,"
                " timestamp REAL NOT NULL,"
                " seen INTEGER NOT NULL DEFAULT 0,"
                " screenshot BLOB"
                ")"
            )
            # Lightweight migrations for DBs created before these columns existed.
            cols = {row[1] for row in conn.execute("PRAGMA table_info(bug_reports)")}
            if "seen" not in cols:
                conn.execute(
                    "ALTER TABLE bug_reports ADD COLUMN seen INTEGER NOT NULL DEFAULT 0"
                )
            if "screenshot" not in cols:
                conn.execute("ALTER TABLE bug_reports ADD COLUMN screenshot BLOB")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_bug_reports_ts "
                "ON bug_reports (timestamp DESC)"
            )

    def add(
        self,
        description: str,
        conversation: list[dict],
        url: str,
        screenshot: bytes | None = None,
    ) -> str:
        bug_id = str(uuid4())
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO bug_reports "
                "(id, description, conversation, url, timestamp, screenshot) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    bug_id,
                    description,
                    json.dumps(conversation),
                    url,
                    time.time(),
                    screenshot,
                ),
            )
        return bug_id

    def list(self, limit: int = 200) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, description, conversation, url, timestamp, seen, "
                "(screenshot IS NOT NULL) AS has_screenshot "
                "FROM bug_reports ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "id": row[0],
                "description": row[1],
                "conversation": json.loads(row[2]) if row[2] else [],
                "url": row[3] or "",
                "timestamp": row[4],
                "seen": bool(row[5]),
                "has_screenshot": bool(row[6]),
            }
            for row in rows
        ]

    def get_screenshot(self, bug_id: str) -> bytes | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT screenshot FROM bug_reports WHERE id = ?",
                (bug_id,),
            ).fetchone()
        if not row or row[0] is None:
            return None
        return bytes(row[0])

    def count_unseen(self) -> int:
        with self._conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM bug_reports WHERE seen = 0"
            ).fetchone()[0]

    def mark_all_seen(self) -> int:
        with self._conn() as conn:
            return conn.execute(
                "UPDATE bug_reports SET seen = 1 WHERE seen = 0"
            ).rowcount

    def clear_seen(self) -> int:
        with self._conn() as conn:
            return conn.execute("DELETE FROM bug_reports WHERE seen = 1").rowcount
