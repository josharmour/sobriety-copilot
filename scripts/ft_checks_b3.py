#!/usr/bin/env python3
"""FT-B3 verification: the fine-tuned retriever checkpoint loads, embeds a
batch, produces 768-dim vectors, and improved dev rank@1 over the base
(metrics.json from training)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.ft_checks import register

REPO = Path(__file__).resolve().parent.parent
MODEL_DIR = REPO / "finetune" / "retriever" / "model"
METRICS = REPO / "finetune" / "retriever" / "metrics.json"

QUERY_PREFIX = "task: search result | query: "
DOC_PREFIX = "title: none | text: "


@register("b3")
def check_b3(args: list[str]) -> int:
    errors: list[str] = []

    if not (MODEL_DIR / "config.json").exists() and not (MODEL_DIR / "modules.json").exists():
        print(f"  FAIL: no saved model at {MODEL_DIR}", file=sys.stderr)
        return 1

    # 1. Metrics: dev rank@1 improved
    if METRICS.exists():
        m = json.loads(METRICS.read_text())
        before = m.get("dev_rank1_before")
        after = m.get("dev_rank1_after")
        print(f"  dev rank@1: {before} -> {after}")
        if before is not None and after is not None and after <= before:
            errors.append(f"rank@1 did not improve ({before} -> {after})")
        print(f"  loss: {m.get('loss_first_50_mean')} -> {m.get('loss_last_50_mean')}")
    else:
        errors.append("metrics.json missing")

    # 2. Checkpoint loads + embeds + dim 768
    import torch
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(str(MODEL_DIR), device="cuda" if torch.cuda.is_available() else "cpu")
    texts = [
        QUERY_PREFIX + "how do I make amends without causing more harm?",
        QUERY_PREFIX + "what is a fourth step inventory?",
        QUERY_PREFIX + "I keep relapsing, what does the literature say?",
        QUERY_PREFIX + "how do I find a sponsor?",
        DOC_PREFIX + "Made a searching and fearless moral inventory of ourselves.",
        DOC_PREFIX + "We made direct amends to such people wherever possible.",
        DOC_PREFIX + "Admitted we were powerless over alcohol.",
        DOC_PREFIX + "Sought through prayer and meditation to improve our conscious contact.",
    ]
    emb = model.encode(texts, normalize_embeddings=True)
    if emb.shape != (8, 768):
        errors.append(f"embedding shape {emb.shape}, expected (8, 768)")
    else:
        print(f"  embeds OK: {emb.shape}, dim=768")

    # sanity: a query should rank its topical doc above an unrelated doc
    import numpy as np
    q_amends = emb[0]
    s_amends_doc = float(np.dot(q_amends, emb[5]))   # amends doc
    s_powerless = float(np.dot(q_amends, emb[6]))    # step-1 doc
    print(f"  sanity: amends-query·amends-doc={s_amends_doc:.3f} vs ·step1-doc={s_powerless:.3f}")
    if s_amends_doc <= s_powerless:
        errors.append("topical ranking sanity failed")

    if errors:
        for e in errors:
            print(f"  FAIL: {e}", file=sys.stderr)
        return 1
    print("B3 OK — checkpoint loads, embeds 8 texts at dim 768, rank@1 improved")
    return 0
