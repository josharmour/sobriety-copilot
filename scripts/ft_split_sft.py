#!/usr/bin/env python3
"""
FT-C5 — Stratified 98/2 train/val split of the filtered SFT dataset.

Reads:  finetune/gen/sft.filtered.jsonl  (6,446 rows, unmodified)
Writes: finetune/gen/sft.train.jsonl     (~6,315 rows)
        finetune/gen/sft.val.jsonl       (~131 rows)
        finetune/gen/split_report.json   (per-intent + aggregate stats)

Split strategy:
  - Stratified by meta.intent_id.
  - Every intent with ≥50 rows is represented in the validation set.
  - Per-intent allocation = max(1, round(count * 0.02)) for intents ≥50.
  - Deterministic: Python's random.Random(42) with shuffle + take-first.
  - All intents present in both splits (minimum val size = 1 for intents ≥50).

Usage:
    python -m scripts.ft_split_sft    # produces the three output files
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter, OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INPUT_PATH = REPO_ROOT / "finetune" / "gen" / "sft.filtered.jsonl"
TRAIN_OUT = REPO_ROOT / "finetune" / "gen" / "sft.train.jsonl"
VAL_OUT = REPO_ROOT / "finetune" / "gen" / "sft.val.jsonl"
REPORT_OUT = REPO_ROOT / "finetune" / "gen" / "split_report.json"

SPLIT_SEED = 42
VAL_FRACTION = 0.02
MIN_VAL_THRESHOLD = 50  # intents with this many rows get at least 1 val row


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _write_jsonl(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _stratified_split(
    indexed_rows: list[tuple[int, dict]],
) -> tuple[list[tuple[int, dict]], list[tuple[int, dict]]]:
    """Stratified 98/2 split by meta.intent_id.

    Returns (train, val) where each element is (input_index, row_dict).
    Using (index, row) tuples enables reliable identity checks even when
    multiple input rows have identical content.
    """
    # Group by intent
    by_intent: dict[str, list[tuple[int, dict]]] = OrderedDict()
    intent_counts: Counter[str] = Counter()

    for idx, row in indexed_rows:
        iid = row["meta"]["intent_id"]
        if iid not in by_intent:
            by_intent[iid] = []
        by_intent[iid].append((idx, row))
        intent_counts[iid] += 1

    rng = random.Random(SPLIT_SEED)
    train: list[tuple[int, dict]] = []
    val: list[tuple[int, dict]] = []

    stats: dict[str, dict] = {}

    for iid, group in by_intent.items():
        count = len(group)
        if count >= MIN_VAL_THRESHOLD:
            n_val = max(1, round(count * VAL_FRACTION))
        else:
            n_val = 0

        n_train = count - n_val

        # Shuffle deterministically, take first n_val for val
        rng.shuffle(group)
        val_group = group[:n_val]
        train_group = group[n_val:]

        train.extend(train_group)
        val.extend(val_group)

        stats[iid] = {
            "total": count,
            "train": n_train,
            "val": n_val,
            "val_pct": round(n_val / count * 100, 2) if count else 0.0,
        }

    # Re-shuffle each split so rows aren't clumped by intent
    rng.shuffle(train)
    rng.shuffle(val)

    # Store stats
    _stratified_split._stats = stats
    _stratified_split._intent_counts = dict(intent_counts)

    return train, val


def _verify(train: list[tuple[int, dict]], val: list[tuple[int, dict]]) -> list[str]:
    """Verify split integrity — uses input indices for identity (not JSON)."""
    errors: list[str] = []

    # 1. Sizes sum to input
    input_count = _stratified_split._input_count
    total_split = len(train) + len(val)
    if total_split != input_count:
        errors.append(
            f"Split sizes {len(train)} + {len(val)} = {total_split} "
            f"!= input {input_count}"
        )

    # 2. No row in both splits (by input index)
    train_indices = {idx for idx, _ in train}
    val_indices = {idx for idx, _ in val}
    overlap = train_indices & val_indices
    if overlap:
        errors.append(f"{len(overlap)} row(s) (by input index) appear in both splits")

    # 3. Every intent with ≥50 rows represented in val
    for iid, count in _stratified_split._intent_counts.items():
        val_iid = sum(1 for _, r in val if r["meta"]["intent_id"] == iid)
        if count >= MIN_VAL_THRESHOLD and val_iid == 0:
            errors.append(
                f"Intent '{iid}' has {count} rows (≥{MIN_VAL_THRESHOLD}) "
                f"but 0 in val"
            )

    # 4. Stratification check — count matches expected per intent
    for iid, count in _stratified_split._intent_counts.items():
        if count < MIN_VAL_THRESHOLD:
            continue
        val_iid = sum(1 for _, r in val if r["meta"]["intent_id"] == iid)
        expected = max(1, round(count * VAL_FRACTION))
        if val_iid != expected:
            errors.append(
                f"Intent '{iid}': expected {expected} val rows, got {val_iid} "
                f"(total {count}, {val_iid/count*100:.1f}%)"
            )

    return errors


def main() -> int:
    print("Loading filtered SFT dataset...", flush=True)
    rows = _load_jsonl(INPUT_PATH)
    _stratified_split._input_count = len(rows)
    print(f"  Loaded {len(rows)} rows", flush=True)

    print("Performing stratified split...", flush=True)
    indexed_rows = list(enumerate(rows))
    train_idx, val_idx = _stratified_split(indexed_rows)
    # Unwrap (index, row) → row for output
    train = [r for _, r in train_idx]
    val = [r for _, r in val_idx]
    print(f"  Train: {len(train)} rows", flush=True)
    print(f"  Val:   {len(val)} rows ({len(val)/len(rows)*100:.2f}%)", flush=True)

    print("Verifying split integrity...", flush=True)
    errors = _verify(train_idx, val_idx)
    if errors:
        for e in errors:
            print(f"  ERROR: {e}", file=sys.stderr)
        return 1

    print("Writing output files...", flush=True)
    _write_jsonl(train, TRAIN_OUT)
    _write_jsonl(val, VAL_OUT)
    print(f"  Wrote {TRAIN_OUT}", flush=True)
    print(f"  Wrote {VAL_OUT}", flush=True)

    # Write report
    stats = _stratified_split._stats
    report = {
        "seed": SPLIT_SEED,
        "val_fraction": VAL_FRACTION,
        "input_count": _stratified_split._input_count,
        "train_count": len(train),
        "val_count": len(val),
        "val_pct": round(len(val) / len(rows) * 100, 2),
        "intents": stats,
        "intent_count": len(stats),
    }
    with open(REPORT_OUT, "w") as f:
        json.dump(report, f, indent=2)
    print(f"  Wrote {REPORT_OUT}", flush=True)

    # Print summary
    print(f"\nSplit complete.  Seed={SPLIT_SEED}")
    print(f"  Input:  {_stratified_split._input_count}")
    print(f"  Train:  {len(train)} ({len(train)/len(rows)*100:.1f}%)")
    print(f"  Val:    {len(val)} ({len(val)/len(rows)*100:.1f}%)")
    print(f"  Intents: {len(stats)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
