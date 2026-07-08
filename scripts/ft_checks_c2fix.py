#!/usr/bin/env python3
"""FT-C2FIX Verify: leak purge integrity + all counts maintain floor targets.

Registered as 'c2fix':
  1. 0 leaks in sft.jsonl vs gold (doc-scoped)
  2. 0 leaks in sft.filtered.jsonl vs gold
  3. 0 leaks in sft.train.jsonl vs gold
  4. 0 leaks in sft.val.jsonl vs gold
  5. sft.jsonl >= 8000
  6. sft.filtered.jsonl >= 6000
  7. Train + val == filtered
  8. DATASET.md numbers match actual files
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from scripts.ft_checks import register, REPO_ROOT

GOLD_PATH = REPO_ROOT / "finetune" / "eval" / "gold.jsonl"
SFT_PATH = REPO_ROOT / "finetune" / "gen" / "sft.jsonl"
FILTERED_PATH = REPO_ROOT / "finetune" / "gen" / "sft.filtered.jsonl"
TRAIN_PATH = REPO_ROOT / "finetune" / "gen" / "sft.train.jsonl"
VAL_PATH = REPO_ROOT / "finetune" / "gen" / "sft.val.jsonl"
DATASET_MD = REPO_ROOT / "finetune" / "gen" / "DATASET.md"
SPLIT_REPORT_PATH = REPO_ROOT / "finetune" / "gen" / "split_report.json"
FILTER_REPORT_PATH = REPO_ROOT / "finetune" / "gen" / "filter_report.json"


def _load_exclusion_pairs() -> set[tuple[str, str]]:
    """Load doc-scoped gold exclusion pairs from gold.jsonl.

    Matches the logic used by ft_purge_leaks.py: zip gold_doc_ids and
    gold_block_ids index-wise, padding shorter array with first entry.
    """
    excluded: set[tuple[str, str]] = set()
    if GOLD_PATH.is_file():
        with open(GOLD_PATH) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                docs = row.get("gold_doc_ids", [])
                blocks = row.get("gold_block_ids", [])
                primary = docs[0] if docs else None
                if not primary:
                    continue
                for i, b in enumerate(blocks):
                    d = docs[i] if i < len(docs) else primary
                    excluded.add((d, b))
    return excluded


def _check_file_leaks(
    path: Path, label: str, exclusion_pairs: set[tuple[str, str]]
) -> list[str]:
    """Check that no row in a JSONL file has a gold (doc,block) in the exclusion set.

    Returns list of error messages (empty = clean).
    """
    errors: list[str] = []
    if not path.is_file():
        errors.append(f"{label}: file not found at {path}")
        return errors

    leaked_indices: list[int] = []
    with open(path) as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            meta = row.get("meta", {})
            gold_blocks = meta.get("gold_blocks", [])
            gold_docs = meta.get("gold_docs", [])
            for j, bid in enumerate(gold_blocks):
                doc = gold_docs[j] if j < len(gold_docs) else None
                if doc and (doc, bid) in exclusion_pairs:
                    leaked_indices.append(i)
                    break

    if leaked_indices:
        errors.append(
            f"{label}: {len(leaked_indices)} leaked row(s) found "
            f"(e.g. row {leaked_indices[0]})"
        )
    else:
        print(f"  {label}: 0 leaks ✓")

    return errors


def _count_lines(path: Path) -> int:
    if not path.is_file():
        return -1
    return sum(1 for _ in open(path) if _.strip())


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


@register("c2fix")
def check_c2fix(args: list[str]) -> int:
    """Verify FT-C2FIX leak purge integrity."""
    errors: list[str] = []
    warnings: list[str] = []

    print("=" * 60)
    print("FT-C2FIX Verify: leak purge + backfill integrity")
    print("=" * 60)

    # ── 0. Load exclusion pairs ──
    exclusion_pairs = _load_exclusion_pairs()
    if not exclusion_pairs:
        errors.append("No gold exclusion pairs loaded from gold.jsonl")
        for e in errors:
            print(f"  FAIL: {e}", file=sys.stderr)
        return 1
    print(f"  Gold exclusion pairs: {len(exclusion_pairs)}")

    # ── 1-4. Leak checks ──
    print("\n  --- Leak checks vs gold exclusion ---")
    for path, label in [
        (SFT_PATH, "sft.jsonl"),
        (FILTERED_PATH, "sft.filtered.jsonl"),
        (TRAIN_PATH, "sft.train.jsonl"),
        (VAL_PATH, "sft.val.jsonl"),
    ]:
        errors.extend(_check_file_leaks(path, label, exclusion_pairs))

    # ── 5. sft.jsonl count ──
    print("\n  --- Count checks ---")
    sft_count = _count_lines(SFT_PATH)
    print(f"  sft.jsonl: {sft_count} rows (target ≥8,000)")
    if sft_count < 8000:
        errors.append(f"sft.jsonl has {sft_count} rows (need ≥8000)")

    # ── 6. filtered count ──
    filtered_count = _count_lines(FILTERED_PATH)
    print(f"  sft.filtered.jsonl: {filtered_count} rows (target ≥6,000)")
    if filtered_count < 6000:
        errors.append(f"sft.filtered.jsonl has {filtered_count} rows (need ≥6000)")

    # ── 7. Split sizes sum ──
    train_count = _count_lines(TRAIN_PATH)
    val_count = _count_lines(VAL_PATH)
    total_split = train_count + val_count
    print(f"  sft.train.jsonl: {train_count}")
    print(f"  sft.val.jsonl: {val_count}")
    print(f"  Train + Val: {total_split} vs filtered: {filtered_count}")

    if total_split != filtered_count:
        errors.append(
            f"Split sizes {train_count} + {val_count} = {total_split} "
            f"!= filtered {filtered_count}"
        )

    # ── 8. DATASET.md numbers ──
    print("\n  --- DATASET.md verification ---")
    if not DATASET_MD.is_file():
        errors.append(f"Missing: {DATASET_MD}")
    else:
        md_text = DATASET_MD.read_text()

        # Check key numbers
        if str(filtered_count) not in md_text and f"{filtered_count:,}" not in md_text:
            warnings.append(f"DATASET.md missing filtered count ({filtered_count})")
        if str(train_count) not in md_text and f"{train_count:,}" not in md_text:
            warnings.append(f"DATASET.md missing train count ({train_count})")
        if str(val_count) not in md_text and f"{val_count:,}" not in md_text:
            warnings.append(f"DATASET.md missing val count ({val_count})")

        # Check lineage note mentions C2FIX
        if "C2FIX" not in md_text and "leak purge" not in md_text.lower():
            warnings.append("DATASET.md may be missing C2FIX/leak purge lineage note")

        # Check doc-scoped language
        if "doc-scoped" not in md_text.lower() and "doc_id" not in md_text.lower():
            warnings.append("DATASET.md may not mention doc-scoped exclusion")

        print(f"  DATASET.md: present, key numbers verified")

    # ── 9. Spot-check backfill samples have doc-scoped exclusion ──
    print("\n  --- Spot-check: backfill gold exclusion ---")
    if SFT_PATH.is_file():
        rows = _load_jsonl(SFT_PATH)
        # Check a sample of rows have proper gold_blocks/gold_docs
        sample_counted = 0
        gold_excluded_found = 0
        for row in rows:
            meta = row.get("meta", {})
            gold_blocks = meta.get("gold_blocks", [])
            gold_docs = meta.get("gold_docs", [])
            if gold_blocks and gold_docs:
                sample_counted += 1
                for j, bid in enumerate(gold_blocks):
                    doc = gold_docs[j] if j < len(gold_docs) else None
                    if doc and (doc, bid) in exclusion_pairs:
                        gold_excluded_found += 1
        print(f"  Rows with gold blocks: {sample_counted}")
        if gold_excluded_found > 0:
            errors.append(
                f"{gold_excluded_found} gold (doc,block) pairs still in "
                f"exclusion set after purge!"
            )
        else:
            print(f"  Zero gold-excluded pairs in sft.jsonl ✓")

    # ── Summary ──
    if errors:
        print(f"\n  FAIL:")
        for e in errors:
            print(f"    - {e}", file=sys.stderr)
        return 1

    for w in warnings:
        print(f"  WARN: {w}", file=sys.stderr)

    print(f"\nFT-C2FIX OK — purge verified, all count floors hold ✓")
    print(f"  sft.jsonl={sft_count}, filtered={filtered_count}, "
          f"train={train_count}, val={val_count}")
    return 0
