#!/usr/bin/env python3
"""FT-B2 Verify: check finetune/retriever/triplets.jsonl.

Checks:
  - Every row has exactly 4 neg_blocks
  - No positive leaked into negatives (doc-scoped identity check)
  - Adjacency respected: no negative from same doc within |block_num| <= 2
  - All doc_id, block_id pairs exist in search.db
  - Print 5-row sample
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from scripts.ft_checks import register, open_corpus  # noqa: E402

TRIPLETS_PATH = _REPO_ROOT / "finetune" / "retriever" / "triplets.jsonl"

_BLOCK_NUM_RE = re.compile(r"^b(\d+)$")


def _block_num(block_id: str) -> int | None:
    m = _BLOCK_NUM_RE.match(block_id)
    return int(m.group(1)) if m else None


@register("b2")
def check_b2(args: list[str]) -> int:
    errors: list[str] = []

    if not TRIPLETS_PATH.is_file():
        print(f"FAIL: {TRIPLETS_PATH} not found", file=sys.stderr)
        return 1

    # Load triplets
    rows: list[dict] = []
    with open(TRIPLETS_PATH) as f:
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
    print(f"  Total rows: {n}")
    n_pairs = sum(1 for l in open(_REPO_ROOT / "finetune" / "retriever" / "pairs.jsonl") if l.strip())
    print(f"  Expected:   {n_pairs} (live count of pairs.jsonl)")
    if n != n_pairs:
        errors.append(f"expected {n_pairs} rows (pairs.jsonl), got {n}")

    # Schema and neg count check
    required_keys = {"query", "pos_block", "neg_blocks"}
    pos_keys = {"doc_id", "block_id", "text"}
    neg_keys = {"doc_id", "block_id", "text"}

    leak_errors = 0
    adj_errors = 0
    missing_block_errors = 0
    neg_count_errors = 0

    # Load all corpus block_ids for existence check
    conn = open_corpus()
    all_corpus_pairs: set[tuple[str, str]] = set()
    for r in conn.execute("SELECT doc_id, block_id FROM blocks").fetchall():
        all_corpus_pairs.add((r["doc_id"], r["block_id"]))
    conn.close()
    print(f"  Corpus pairs loaded: {len(all_corpus_pairs)}")

    for i, row in enumerate(rows):
        missing = required_keys - set(row.keys())
        if missing:
            errors.append(f"row {i}: missing keys {missing}")
            continue

        query = row.get("query", "")
        pos = row.get("pos_block", {})
        negs = row.get("neg_blocks", [])

        # Check query
        if not isinstance(query, str) or len(query) < 5:
            errors.append(f"row {i}: query too short or missing")

        # Check pos_block schema
        pos_missing = pos_keys - set(pos.keys())
        if pos_missing:
            errors.append(f"row {i}: pos_block missing keys {pos_missing}")

        pos_doc = pos.get("doc_id", "")
        pos_bid = pos.get("block_id", "")

        # Check neg_blocks count
        if len(negs) != 4:
            neg_count_errors += 1
            if neg_count_errors <= 3:
                errors.append(
                    f"row {i}: {len(negs)} negatives (need 4)"
                )

        # Check each negative
        pos_key = (pos_doc, pos_bid)
        for j, neg in enumerate(negs):
            neg_missing = neg_keys - set(neg.keys())
            if neg_missing:
                errors.append(f"row {i}: neg[{j}] missing keys {neg_missing}")
                continue

            neg_doc = neg.get("doc_id", "")
            neg_bid = neg.get("block_id", "")
            neg_key = (neg_doc, neg_bid)

            # Leak check (doc-scoped)
            if neg_key == pos_key:
                leak_errors += 1
                if leak_errors <= 3:
                    errors.append(
                        f"row {i}: neg[{j}] == positive ({neg_key}) — LEAK"
                    )

            # Adjacency check (same doc, |block_num diff| <= 2)
            if neg_doc == pos_doc:
                pos_n = _block_num(pos_bid)
                neg_n = _block_num(neg_bid)
                if pos_n is not None and neg_n is not None:
                    if abs(neg_n - pos_n) <= 2:
                        adj_errors += 1
                        if adj_errors <= 3:
                            errors.append(
                                f"row {i}: neg[{j}] [{neg_doc}:{neg_bid}] "
                                f"adjacent to positive [{pos_doc}:{pos_bid}] "
                                f"(|{neg_n} - {pos_n}| = {abs(neg_n - pos_n)})"
                            )

            # Existence check
            if neg_key not in all_corpus_pairs:
                missing_block_errors += 1
                if missing_block_errors <= 3:
                    errors.append(
                        f"row {i}: neg[{j}] [{neg_doc}:{neg_bid}] "
                        f"not found in corpus"
                    )

        # Also check pos_block existence
        if pos_key not in all_corpus_pairs:
            missing_block_errors += 1
            if missing_block_errors <= 3:
                errors.append(
                    f"row {i}: pos_block [{pos_doc}:{pos_bid}] "
                    f"not found in corpus"
                )

    # Summary stats
    print(f"  Wrong neg count: {neg_count_errors}")
    print(f"  Leak errors:     {leak_errors}")
    print(f"  Adjacency errors: {adj_errors}")
    print(f"  Missing blocks:   {missing_block_errors}")

    # Report errors
    if errors:
        for e in errors:
            print(f"  FAIL: {e}", file=sys.stderr)
        return 1

    # Print 5-row sample
    print(f"\nB2 OK — {n} triplets in {TRIPLETS_PATH}")
    print("\nSample (first 5 rows):")
    for i, r in enumerate(rows[:5], 1):
        query_short = r["query"][:70] + ("…" if len(r["query"]) > 70 else "")
        pos = r["pos_block"]
        print(f"  {i}. Q: {query_short}")
        print(f"     POS: [{pos['doc_id']}:{pos['block_id']}] "
              f"\"{pos['text'][:50]}…\"")
        for j, neg in enumerate(r["neg_blocks"]):
            print(f"     NEG[{j}]: [{neg['doc_id']}:{neg['block_id']}] "
                  f"\"{neg['text'][:40]}…\"")
        print()

    return 0
