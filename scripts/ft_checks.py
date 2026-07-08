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
import json
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

KINDS = ["doctrine", "practical", "phrase", "crosswork", "personal", "negative"]


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
# FT-A1  —  eval questions
# ═══════════════════════════════════════════════════════════════════════════

@register("a1")
def check_a1(args: list[str]) -> int:
    """Verify finetune/eval/questions.jsonl — schema, counts, source ids."""
    q_path = REPO_ROOT / "finetune" / "eval" / "questions.jsonl"

    if not q_path.is_file():
        print(f"FAIL: {q_path} not found", file=sys.stderr)
        return 1

    errors: list[str] = []
    rows: list[dict] = []
    with open(q_path) as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                errors.append(f"line {i}: invalid JSON — {e}")
                continue
            rows.append(row)

    if len(rows) < 240:
        errors.append(f"only {len(rows)} rows (need ≥240)")

    # Schema check
    required_keys = {"id", "question", "kind", "source_doc_id", "source_block_ids"}
    kind_counts: dict[str, int] = {}
    for i, row in enumerate(rows, 1):
        missing = required_keys - set(row.keys())
        if missing:
            errors.append(f"row {i} (id={row.get('id','?')}): missing keys {missing}")
            continue
        kind = row["kind"]
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        if kind not in KINDS:
            errors.append(f"row {i}: unknown kind '{kind}'")
        if not isinstance(row["source_block_ids"], list):
            errors.append(f"row {i}: source_block_ids must be a list")
        if kind in ("doctrine", "practical", "phrase", "personal"):
            if not row["source_doc_id"]:
                errors.append(f"row {i}: missing source_doc_id for kind '{kind}'")
        if kind == "negative":
            if row["source_doc_id"] is not None:
                errors.append(f"row {i}: negative kind should have null source_doc_id")
            if row.get("source_block_ids"):
                errors.append(f"row {i}: negative kind should have empty source_block_ids")
        if kind == "crosswork":
            # crosswork can have null source_doc_id
            if len(row.get("source_block_ids", [])) < 2:
                errors.append(f"row {i}: crosswork needs ≥2 source_block_ids")

    # Check per-kind counts
    for k in KINDS:
        count = kind_counts.get(k, 0)
        if count < 40:
            errors.append(f"kind '{k}' has {count} rows (need ≥40)")

    # Verify all source ids exist in corpus DB
    try:
        conn = open_corpus()
        for row in rows:
            for bid in row.get("source_block_ids", []):
                exists = conn.execute(
                    "SELECT 1 FROM blocks WHERE block_id = ?", (bid,)
                ).fetchone()
                if not exists:
                    errors.append(
                        f"row {row['id']}: block_id '{bid}' not found in corpus"
                    )
        conn.close()
    except Exception as e:
        errors.append(f"corpus DB check failed: {e}")

    if errors:
        for e in errors:
            print(f"  FAIL: {e}", file=sys.stderr)
        return 1

    # Print summary
    print(f"A1 OK — {len(rows)} questions")
    for k in KINDS:
        print(f"  {k}: {kind_counts[k]}")
    return 0


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

def _load_task_modules() -> None:
    """Auto-import scripts/ft_checks_*.py so parallel workers register their
    checks in per-task modules instead of editing this shared file (swarm
    mode: no two agents may write the same path).

    After importing, sync any checks that ended up in a secondary
    ``scripts.ft_checks`` module (which happens when this file is run
    as ``__main__`` and task modules ``import scripts.ft_checks`` —
    they get a separate module instance).
    """
    import importlib
    for mod in sorted(Path(__file__).parent.glob("ft_checks_*.py")):
        try:
            importlib.import_module(f"scripts.{mod.stem}")
        except Exception as e:
            print(f"WARN: failed to load {mod.name}: {e}", file=sys.stderr)

    # Sync: copy checks from scripts.ft_checks if it's a different module
    # (the ``python -m scripts.ft_checks`` case described above).
    _sync_imported_checks()


def _sync_imported_checks() -> None:
    """Copy any checks that were registered into a secondary
    ``scripts.ft_checks`` module back into the current module's
    ``_CHECKS`` dict.

    This is a no-op when ``scripts.ft_checks`` is the same module
    as the currently executing one.
    """
    import importlib
    try:
        ftc = importlib.import_module("scripts.ft_checks")
    except ImportError:
        return
    # If ftc IS the current module, nothing to do
    if ftc is sys.modules.get("__main__"):
        return
    for k, v in ftc._CHECKS.items():
        if k not in _CHECKS:
            _CHECKS[k] = v


def main() -> int:
    _load_task_modules()
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
