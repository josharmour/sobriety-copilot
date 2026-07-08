#!/usr/bin/env python3
"""FT-B1 Verify: check finetune/retriever/pairs.jsonl.

Checks:
  - ≥60k rows
  - Schema: {query, doc_id, block_id}
  - All block_ids exist in corpus
  - No gold leakage (if gold.jsonl present)
  - Print 10-row sample
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from scripts.ft_checks import register, open_corpus  # noqa: E402

PAIRS_PATH = _REPO_ROOT / "finetune" / "retriever" / "pairs.jsonl"
GOLD_PATH = _REPO_ROOT / "finetune" / "eval" / "gold.jsonl"


@register("b1")
def check_b1(args: list[str]) -> int:
    errors: list[str] = []

    if not PAIRS_PATH.is_file():
        print(f"FAIL: {PAIRS_PATH} not found", file=sys.stderr)
        return 1

    # Load pairs
    rows: list[dict] = []
    with open(PAIRS_PATH) as f:
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

    n = len(rows)

    # Count check
    if n < 60000:
        errors.append(f"only {n} rows (need ≥60k)")

    # Schema check
    required_keys = {"query", "doc_id", "block_id"}
    for i, row in enumerate(rows, 1):
        missing = required_keys - set(row.keys())
        if missing:
            errors.append(f"row {i}: missing keys {missing}")
        if not isinstance(row.get("query"), str) or len(row["query"]) < 5:
            errors.append(f"row {i}: query too short or missing")
        if not isinstance(row.get("doc_id"), str) or not row["doc_id"]:
            errors.append(f"row {i}: invalid doc_id")
        if not isinstance(row.get("block_id"), str) or not row["block_id"]:
            errors.append(f"row {i}: invalid block_id")

    # Block ID existence check
    try:
        conn = open_corpus()
        # Batch check for speed
        all_block_ids = list({r["block_id"] for r in rows if isinstance(r.get("block_id"), str)})
        existing_ids = set()
        # Check in chunks to avoid too-large IN clauses
        chunk_size = 500
        for i in range(0, len(all_block_ids), chunk_size):
            chunk = all_block_ids[i : i + chunk_size]
            placeholders = ",".join("?" for _ in chunk)
            found = conn.execute(
                f"SELECT block_id FROM blocks WHERE block_id IN ({placeholders})",
                chunk,
            ).fetchall()
            existing_ids.update(r["block_id"] for r in found)

        missing_ids = set(all_block_ids) - existing_ids
        if missing_ids:
            sample = list(missing_ids)[:5]
            errors.append(f"{len(missing_ids)} block_ids not in corpus (sample: {sample})")
        conn.close()
    except Exception as e:
        errors.append(f"corpus DB check failed: {e}")

    # Gold leakage check — keyed by (doc_id, block_id): bare block ids
    # collide across docs (b00406 exists in 66 docs).
    if GOLD_PATH.is_file():
        gold_pairs = set()
        with open(GOLD_PATH) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                docs = row.get("gold_doc_ids", [])
                blocks = row.get("gold_block_ids", [])
                primary = docs[0] if docs else None
                for i, bid in enumerate(blocks):
                    d = docs[i] if i < len(docs) else primary
                    if d:
                        gold_pairs.add((d, bid))

        leaked = [
            r for r in rows
            if (r.get("doc_id"), r.get("block_id")) in gold_pairs
        ]
        if leaked:
            sample = leaked[:3]
            errors.append(
                f"{len(leaked)} rows use gold blocks (leakage)! Sample: {sample}"
            )
        else:
            print(f"  Gold leakage check: PASS (0 leaked of {len(gold_pairs)} gold blocks)")
    else:
        print(
            "  Gold leakage check: SKIPPED (gold.jsonl not yet available — "
            "run `--re-exclude` after A2 lands)",
        )

    # Report
    if errors:
        for e in errors:
            print(f"  FAIL: {e}", file=sys.stderr)
        return 1

    print(f"B1 OK — {n} pairs in {PAIRS_PATH}")
    print(f"  Unique docs: {len(set(r['doc_id'] for r in rows))}")
    print(
        "  Unique (doc, block) pairs: "
        f"{len(set((r['doc_id'], r['block_id']) for r in rows))}"
    )

    # Print 10-row sample
    print("\nSample (first 10 rows):")
    for i, r in enumerate(rows[:10], 1):
        query_short = r["query"][:80] + ("…" if len(r["query"]) > 80 else "")
        print(f"  {i}. [{r['doc_id']}:{r['block_id']}] {query_short}")

    return 0
