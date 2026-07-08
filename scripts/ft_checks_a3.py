#!/usr/bin/env python3
"""FT-A3 verification check.

Registers the 'a3' check that verifies:
1. A run file exists in finetune/eval/runs/ (first CLI arg or most recent)
2. Schema is valid (meta, results, aggregates)
3. Non-null aggregate metrics exist (at minimum retrieval.recall@4 and @8)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.ft_checks import register

REPO = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO / "finetune" / "eval" / "runs"


@register("a3")
def check_a3(args: list[str]) -> int:
    """Verify an ft_eval run output file."""
    # Determine which run file to check
    if args:
        run_name = args[0].rstrip(".json")
        run_path = RUNS_DIR / f"{run_name}.json"
    else:
        # Use the most recent .json file
        json_files = sorted(RUNS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not json_files:
            print("FAIL: no run files found in finetune/eval/runs/", file=sys.stderr)
            return 1
        run_path = json_files[0]
        run_name = run_path.stem

    print(f"[a3] Checking run: {run_path}", flush=True)

    # 1. File exists
    if not run_path.is_file():
        print(f"FAIL: {run_path} not found", file=sys.stderr)
        return 1

    # 2. Valid JSON
    try:
        with open(run_path) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"FAIL: {run_path} is not valid JSON: {e}", file=sys.stderr)
        return 1

    errors: list[str] = []

    # 3. Meta block
    meta = data.get("meta", {})
    if not isinstance(meta, dict):
        errors.append("'meta' is not a dict")
    else:
        for key in ("system", "name", "total"):
            if key not in meta:
                errors.append(f"meta missing '{key}'")

    # 4. Results block (must be a non-empty list)
    results = data.get("results", [])
    if not isinstance(results, list) or len(results) == 0:
        errors.append("'results' must be a non-empty list")
    else:
        # Check each result has required fields
        for i, row in enumerate(results):
            if not isinstance(row, dict):
                errors.append(f"results[{i}] is not a dict")
                continue
            if "id" not in row:
                errors.append(f"results[{i}] missing 'id'")
            if "retrieval" not in row:
                errors.append(f"results[{i}] missing 'retrieval'")
            elif not isinstance(row["retrieval"], dict):
                errors.append(f"results[{i}]['retrieval'] is not a dict")

    # 5. Aggregates block
    agg = data.get("aggregates", {})
    if not isinstance(agg, dict):
        errors.append("'aggregates' is not a dict")
    else:
        required_metrics = [
            "retrieval.recall@4",
            "retrieval.recall@8",
            "citation_accuracy",
            "faithfulness",
            "answer_quality",
            "refusal_correctness",
        ]
        for metric in required_metrics:
            if metric not in agg:
                errors.append(f"aggregates missing '{metric}'")

        # Non-null recall metrics are mandatory
        recall4 = agg.get("retrieval.recall@4")
        recall8 = agg.get("retrieval.recall@8")
        if recall4 is None:
            errors.append("aggregates['retrieval.recall@4'] is null")
        if recall8 is None:
            errors.append("aggregates['retrieval.recall@8'] is null")

    # 6. Counts match
    if isinstance(results, list) and isinstance(meta, dict):
        total_meta = meta.get("total")
        if total_meta is not None and total_meta != len(results):
            errors.append(
                f"meta.total={total_meta} != len(results)={len(results)}"
            )

    if errors:
        for e in errors:
            print(f"  FAIL: {e}", file=sys.stderr)
        return 1

    # Summary
    print(f"A3 OK — {run_name}: {len(results)} questions")
    for k, v in agg.items():
        if v is not None:
            print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")
        else:
            print(f"  {k}: null")
    return 0
