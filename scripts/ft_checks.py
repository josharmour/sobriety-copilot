#!/usr/bin/env python3
"""Subcommand-based verification checks for the fine-tuning pipeline.

Usage:
    python -m scripts.ft_checks <task-id> [args...]

Each task in finetuning-the-rag.md registers a check function via the
@register decorator.  The dispatch loop looks up the task ID, calls the
function, and exits with its return code (0 = pass, nonzero = fail).

Shared helpers:
    ensure_corpus_db()  — extract search.db from packs/library-v1.scpack
                           into finetune/cache/search.db (idempotent).
                           Never touches packs/ directly.
"""

from __future__ import annotations

import argparse
import collections.abc
import shutil
import sqlite3
import sys
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths  (all relative to the repo root)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_PACK = REPO_ROOT / "packs" / "library-v1.scpack"
CACHE_DB = REPO_ROOT / "finetune" / "cache" / "search.db"

FINETUNE_DIRS = [
    REPO_ROOT / "finetune" / "eval",
    REPO_ROOT / "finetune" / "retriever",
    REPO_ROOT / "finetune" / "gen",
    REPO_ROOT / "finetune" / "infra",
    REPO_ROOT / "finetune" / "runs",
    REPO_ROOT / "finetune" / "cache",
]


# ---------------------------------------------------------------------------
# Corpus DB helper  (shared by all tasks)
# ---------------------------------------------------------------------------

def ensure_corpus_db() -> Path:
    """Extract search.db from the v1 pack into finetune/cache if not present.

    Returns the path to the extracted SQLite database.  The extraction is
    idempotent — subsequent calls are a no-op when the file already exists.

    All tasks MUST use this helper to access the corpus.  Never read
    directly from ``packs/``.
    """
    if CACHE_DB.exists():
        return CACHE_DB

    CACHE_DB.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(CORPUS_PACK, "r") as zf:
        # The pack stores search.db at the top level
        with zf.open("search.db") as src, open(CACHE_DB, "wb") as dst:
            shutil.copyfileobj(src, dst)

    # Verify it's a valid SQLite database
    conn = sqlite3.connect(str(CACHE_DB))
    try:
        row = conn.execute("SELECT COUNT(*) FROM blocks").fetchone()
        print(f"[corpus] {row[0]} blocks in {CACHE_DB}", flush=True)
    finally:
        conn.close()

    return CACHE_DB


def open_corpus() -> sqlite3.Connection:
    """Open the corpus DB read-only (convenience wrapper)."""
    db_path = ensure_corpus_db()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Check registry
# ---------------------------------------------------------------------------

_CHECKS: dict[str, collections.abc.Callable] = {}


def register(id: str):
    """Decorator that registers a check function for *id*."""
    def wrapper(fn: collections.abc.Callable) -> collections.abc.Callable:
        _CHECKS[id] = fn
        return fn
    return wrapper


# ═══════════════════════════════════════════════════════════════════════════
# FT-A0  —  scaffolding + ft_checks skeleton
# ═══════════════════════════════════════════════════════════════════════════

@register("a0")
def check_a0(args: list[str]) -> int:
    """Verify FT-A0 scaffolding."""
    errors = []

    # All finetune subdirectories exist
    for d in FINETUNE_DIRS:
        if not d.is_dir():
            errors.append(f"missing directory: {d}")

    # ft_checks.py itself is executable and importable
    this_file = REPO_ROOT / "scripts" / "ft_checks.py"
    if not this_file.is_file():
        errors.append(f"missing: {this_file}")

    # Corpus DB helper works
    try:
        db = ensure_corpus_db()
        conn = open_corpus()
        count = conn.execute("SELECT COUNT(*) FROM blocks").fetchone()[0]
        conn.close()
        print(f"  corpus DB: {db} ({count} blocks)")
    except Exception as e:
        errors.append(f"corpus DB helper failed: {e}")

    # Registered checks exist
    expected_ids = {"a0"}
    missing = expected_ids - set(_CHECKS)
    if missing:
        errors.append(f"unregistered task IDs: {missing}")

    if errors:
        for e in errors:
            print(f"  FAIL: {e}", file=sys.stderr)
        return 1

    print("FT-A0 scaffolding OK")
    return 0


# ═══════════════════════════════════════════════════════════════════════════
# Dispatch
# ═══════════════════════════════════════════════════════════════════════════

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Fine-tuning pipeline verification checks",
    )
    ap.add_argument("task_id", help="Task identifier (e.g., a1, b1, c1)")
    ap.add_argument(
        "extra", nargs=argparse.REMAINDER,
        help="Additional arguments forwarded to the check function",
    )
    args = ap.parse_args()

    task_id = args.task_id.lower()

    if task_id not in _CHECKS:
        registered = ", ".join(sorted(_CHECKS))
        print(
            f"ERROR: no check registered for '{task_id}'.\n"
            f"Registered checks: {registered}",
            file=sys.stderr,
        )
        return 1

    return _CHECKS[task_id](args.extra)


if __name__ == "__main__":
    raise SystemExit(main())
