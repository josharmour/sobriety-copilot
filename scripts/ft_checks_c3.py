#!/usr/bin/env python3
"""
FT-C3 Verify check for scripts/ft_checks.py.

Registered as 'c3':
  - sft.filtered.jsonl exists with >= 6000 samples
  - filter_report.json exists and sums are internally consistent
  - Spot-print 3 dropped samples with reasons (for manual review)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.ft_checks import register

REPO_ROOT = Path(__file__).resolve().parent.parent
FILTERED_PATH = REPO_ROOT / "finetune" / "gen" / "sft.filtered.jsonl"
REPORT_PATH = REPO_ROOT / "finetune" / "gen" / "filter_report.json"


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


@register("c3")
def check_c3(args: list[str]) -> int:
    """Verify FT-C3 quality filter output."""
    errors: list[str] = []

    # --- Check filtered file ---
    if not FILTERED_PATH.is_file():
        errors.append(f"Missing: {FILTERED_PATH}")
        for e in errors:
            print(f"  FAIL: {e}", file=sys.stderr)
        return 1

    filtered = _load_jsonl(FILTERED_PATH)
    kept_count = len(filtered)
    print(f"Filtered samples: {kept_count}")

    if kept_count < 6000:
        errors.append(f"Only {kept_count} survivors (need >= 6000)")

    # Verify schema of each kept sample
    for i, s in enumerate(filtered):
        if "messages" not in s or "meta" not in s:
            errors.append(f"row {i}: missing messages or meta")
            continue
        msgs = s["messages"]
        if len(msgs) != 3:
            errors.append(f"row {i}: expected 3 messages, got {len(msgs)}")
        elif not all(m["role"] in ("system", "user", "assistant") for m in msgs):
            errors.append(f"row {i}: unexpected roles in messages")
        meta = s["meta"]
        for key in ("intent_id", "register", "sample_type", "crisis_adjacent",
                     "gold_blocks", "gold_docs", "distractor_blocks", "distractor_docs"):
            if key not in meta:
                errors.append(f"row {i}: meta missing key '{key}'")

    # --- Check report ---
    if not REPORT_PATH.is_file():
        errors.append(f"Missing report: {REPORT_PATH}")
    else:
        with open(REPORT_PATH) as f:
            report = json.load(f)

        print(f"Report: total={report.get('total')}, kept={report.get('kept')}, "
              f"dropped={report.get('dropped')}, drop_rate={report.get('drop_rate','?')}")

        # Internal consistency
        total = report.get("total", 0)
        kept_r = report.get("kept", 0)
        dropped_r = report.get("dropped", 0)

        if total != kept_r + dropped_r:
            errors.append(f"Report sums don't match: {total} != {kept_r} + {dropped_r}")

        if kept_r != kept_count:
            errors.append(f"Report kept ({kept_r}) != filtered file rows ({kept_count})")

        # Check by-intent consistency
        by_intent = report.get("by_intent", {})
        intent_total = sum(v["total"] for v in by_intent.values())
        if intent_total != total:
            errors.append(f"By-intent totals sum to {intent_total}, expected {total}")

        intent_kept = sum(v["kept"] for v in by_intent.values())
        if intent_kept != kept_r:
            errors.append(f"By-intent kept sum to {intent_kept}, expected {kept_r}")

        # Check by_reason
        by_reason = report.get("by_reason", {})
        reason_drops = sum(by_reason.values())
        if reason_drops > dropped_r:
            errors.append(f"By-reason drops ({reason_drops}) exceed total drops ({dropped_r})")

        print(f"  Intents in report: {len(by_intent)}")
        print(f"  Reasons: {json.dumps(by_reason, indent=2)}")

    # --- Spot-print 3 dropped samples ---
    # Read from checkpoint if available, or reconstruct from report
    ckpt_path = REPO_ROOT / "finetune" / "gen" / ".filter_checkpoint.json"
    if ckpt_path.exists():
        with open(ckpt_path) as f:
            ckpt = json.load(f)
        dropped_from_ckpt = [v for v in ckpt.get("verdicts", []) if v.get("overall") == "DROP"]
        print(f"\n=== Spot-check: {min(3, len(dropped_from_ckpt))} dropped samples ===")
        for v in dropped_from_ckpt[:3]:
            print(f"  idx={v['idx']}: {v['drop_reason']} | "
                  f"type={v['sample_type']} register={v['register']} intent={v['intent_id']}")
            if v.get("verdict"):
                vd = v["verdict"]
                for axis in ("grounded", "voice", "hotline_discipline", "register_fit", "refusal_correctness"):
                    note_key = f"{axis}_note"
                    if vd.get(axis) == "FAIL" and note_key in vd:
                        print(f"    {axis}: {vd[note_key][:150]}")
    else:
        print("\nNo checkpoint available for dropped sample spot-check (checkpoint may be empty after completion)")

    # Summary
    if errors:
        for e in errors:
            print(f"  FAIL: {e}", file=sys.stderr)
        return 1

    print(f"\nFT-C3 OK — {kept_count} survivors, report consistent")
    return 0
