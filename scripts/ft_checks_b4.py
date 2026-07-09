#!/usr/bin/env python3
"""FT-B4 gate: the fine-tuned retriever must beat the base retriever it
replaces on the eval set (recall@8), in both dense-only and hybrid configs.
Reports the delta vs the +5 stretch target."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.ft_checks import register

REPO = Path(__file__).resolve().parent.parent
DENSE = REPO / "finetune" / "eval" / "runs" / "b4-retriever.json"
HYBRID = REPO / "finetune" / "eval" / "runs" / "b4-hybrid.json"


@register("b4")
def check_b4(args: list[str]) -> int:
    errors: list[str] = []
    d = json.loads(DENSE.read_text())
    h = json.loads(HYBRID.read_text())

    base_d = d["base_dense"]["recall@8"]
    ft_d = d["finetuned_dense"]["recall@8"]
    base_h = h["hybrid_base_dense"]["recall@8"]
    ft_h = h["hybrid_ft_dense"]["recall@8"]
    a4 = d["bm25_baseline"]["recall@8"]

    print(f"  dense:  base {base_d:.4f} -> ft {ft_d:.4f}  ({ft_d-base_d:+.4f})")
    print(f"  hybrid: base {base_h:.4f} -> ft {ft_h:.4f}  ({ft_h-base_h:+.4f})")
    print(f"  A4 BM25 baseline recall@8: {a4:.4f}; hybrid-ft absolute: {ft_h:.4f}")
    print(f"  +5 stretch target: {'MET' if (ft_d-base_d)>=0.05 else 'not met'} "
          f"(dense delta {ft_d-base_d:+.4f})")

    # Gate: fine-tune must beat the base model it replaces in BOTH configs.
    if ft_d <= base_d:
        errors.append(f"dense recall@8 did not improve ({base_d:.4f} -> {ft_d:.4f})")
    if ft_h <= base_h:
        errors.append(f"hybrid recall@8 did not improve ({base_h:.4f} -> {ft_h:.4f})")

    if errors:
        for e in errors:
            print(f"  FAIL: {e}", file=sys.stderr)
        return 1
    print("B4 OK — fine-tuned retriever beats base in dense + hybrid; ships to pack v3")
    return 0
