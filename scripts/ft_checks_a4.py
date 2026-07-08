#!/usr/bin/env python3
"""FT-A4 verification: both baseline run files complete (256 rows) with
non-null aggregates for their applicable metrics, and BASELINE.md quotes
numbers that match the JSONs."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from scripts.ft_checks import register

REPO = Path(__file__).resolve().parent.parent
RUNS = REPO / "finetune" / "eval" / "runs"
BASELINE_MD = REPO / "finetune" / "eval" / "BASELINE.md"


@register("a4")
def check_a4(args: list[str]) -> int:
    errors: list[str] = []
    server = json.load(open(RUNS / "baseline-server.json"))
    retr = json.load(open(RUNS / "baseline-retriever.json"))

    for name, run, metrics in (
        ("server", server, ("citation_accuracy", "faithfulness",
                            "answer_quality", "refusal_correctness")),
        ("retriever", retr, ("retrieval.recall@4", "retrieval.recall@8")),
    ):
        rows = run.get("results", [])
        if len(rows) != 256:
            errors.append(f"{name}: {len(rows)} rows (need 256)")
        agg = run.get("aggregate") or run.get("aggregates") or {}
        for m in metrics:
            if not isinstance(agg.get(m), (int, float)):
                errors.append(f"{name}: aggregate {m} is null")

    md = BASELINE_MD.read_text()
    expect = {
        "0.3224": (server.get("aggregate") or server["aggregates"])["citation_accuracy"],
        "0.3715": (retr.get("aggregate") or retr["aggregates"])["retrieval.recall@4"],
        "0.3995": (retr.get("aggregate") or retr["aggregates"])["retrieval.recall@8"],
        "4.944": (server.get("aggregate") or server["aggregates"])["faithfulness"],
        "4.559": (server.get("aggregate") or server["aggregates"])["answer_quality"],
        "4.286": (server.get("aggregate") or server["aggregates"])["refusal_correctness"],
    }
    for quoted, actual in expect.items():
        if quoted not in md:
            errors.append(f"BASELINE.md missing {quoted}")
        elif abs(float(quoted) - float(actual)) > 0.001:
            errors.append(f"BASELINE.md {quoted} != json {actual:.4f}")

    if errors:
        for e in errors:
            print(f"  FAIL: {e}", file=sys.stderr)
        return 1
    print("A4 OK — both baselines complete (256 rows), BASELINE.md matches")
    for k, v in {**(retr.get("aggregate") or retr["aggregates"]), **(server.get("aggregate") or server["aggregates"])}.items():
        if isinstance(v, (int, float)):
            print(f"  {k}: {v:.4f}")
    return 0
