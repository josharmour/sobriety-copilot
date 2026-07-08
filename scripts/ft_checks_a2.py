#!/usr/bin/env python3
"""FT-A2 verification check.

Registers the 'a2' check: validates finetune/eval/gold.jsonl.

Checks:
1. 1:1 id coverage vs questions.jsonl.
2. gold_doc_ids[i] pairs with gold_block_ids[i] (aligned, same length).
3. Every (doc_id, block_id) exists in search.db (doc-scoped).
4. Negative rows: empty gold arrays + refusal-like answer.
5. Every non-negative reference_answer ≤130 words and contains at least one
   gold work title in prose.
6. Print 5 sampled rows for Fable spot-read.
"""

from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path

from scripts.ft_checks import ensure_corpus_db, open_corpus, register

REPO = Path(__file__).resolve().parent.parent
QPATH = REPO / "finetune" / "eval" / "questions.jsonl"
GPATH = REPO / "finetune" / "eval" / "gold.jsonl"
PACK = REPO / "packs" / "library-v1.scpack"

KINDS = ("doctrine", "practical", "phrase", "crosswork", "personal", "negative")


def _titles() -> dict[str, str]:
    """Load doc_id → display title from pack manifest."""
    z = zipfile.ZipFile(PACK)
    m = json.loads(z.read("manifest-index.json"))
    items = m if isinstance(m, list) else m.get("docs") or []
    return {d["doc_id"]: d["title"] for d in items}


def _word_count(text: str) -> int:
    """Count words in a text."""
    return len(text.split())


@register("a2")
def check_a2(args: list[str]) -> int:
    errors: list[str] = []

    # Load questions
    if not QPATH.is_file():
        print(f"FAIL: {QPATH} not found", file=sys.stderr)
        return 1

    questions: list[dict] = []
    with open(QPATH) as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                questions.append(json.loads(line))
            except json.JSONDecodeError as e:
                errors.append(f"questions line {i}: invalid JSON — {e}")

    if not questions:
        errors.append("no questions loaded")

    # Load gold
    if not GPATH.is_file():
        print(f"FAIL: {GPATH} not found", file=sys.stderr)
        return 1

    gold: list[dict] = []
    with open(GPATH) as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                gold.append(json.loads(line))
            except json.JSONDecodeError as e:
                errors.append(f"gold line {i}: invalid JSON — {e}")

    # ── Check 1: 1:1 id coverage ──
    q_ids = {q["id"] for q in questions}
    g_ids = {g["id"] for g in gold}

    missing_in_gold = q_ids - g_ids
    if missing_in_gold:
        errors.append(
            f"questions without gold: {len(missing_in_gold)} — "
            f"{sorted(missing_in_gold)[:10]}"
        )

    extra_in_gold = g_ids - q_ids
    if extra_in_gold:
        errors.append(
            f"gold ids not in questions: {len(extra_in_gold)} — "
            f"{sorted(extra_in_gold)[:10]}"
        )

    if len(gold) != len(questions):
        errors.append(
            f"row count mismatch: gold={len(gold)} vs questions={len(questions)}"
        )

    # Build quick lookup
    gold_by_id: dict[str, dict] = {g["id"]: g for g in gold}
    questions_by_id: dict[str, dict] = {q["id"]: q for q in questions}

    # ── Check 2: aligned arrays ──
    schema_keys = {"id", "gold_doc_ids", "gold_block_ids", "reference_answer"}
    for g in gold:
        missing = schema_keys - set(g.keys())
        if missing:
            errors.append(f"gold {g['id']}: missing keys {missing}")
            continue

        doc_ids = g.get("gold_doc_ids", [])
        block_ids = g.get("gold_block_ids", [])

        if len(doc_ids) != len(block_ids):
            errors.append(
                f"gold {g['id']}: gold_doc_ids ({len(doc_ids)}) and "
                f"gold_block_ids ({len(block_ids)}) length mismatch"
            )

        # Check reference_answer is present and non-empty
        answer = g.get("reference_answer", "")
        if not answer or not answer.strip():
            errors.append(f"gold {g['id']}: empty reference_answer")

    # ── Check 3: every (doc, block) exists in corpus ──
    try:
        ensure_corpus_db()
        conn = open_corpus()

        def doc_blocks(d: str) -> set[str]:
            return {
                b for (b,) in conn.execute(
                    "SELECT block_id FROM blocks WHERE doc_id=?", (d,)
                )
            }

        for g in gold:
            doc_ids = g.get("gold_doc_ids", [])
            block_ids = g.get("gold_block_ids", [])
            for d, b in zip(doc_ids, block_ids):
                all_b = doc_blocks(d)
                if not all_b:
                    errors.append(f"gold {g['id']}: unknown doc '{d}'")
                elif b not in all_b:
                    errors.append(
                        f"gold {g['id']}: block '{b}' not found in doc '{d}'"
                    )

        conn.close()
    except Exception as e:
        errors.append(f"corpus DB check failed: {e}")

    # ── Check 4: negative rows ──
    neg_questions = [q for q in questions if q["kind"] == "negative"]
    for q in neg_questions:
        g = gold_by_id.get(q["id"])
        if not g:
            continue
        if g.get("gold_doc_ids", []):
            errors.append(
                f"negative {q['id']}: gold_doc_ids should be empty, "
                f"got {g['gold_doc_ids']}"
            )
        if g.get("gold_block_ids", []):
            errors.append(
                f"negative {q['id']}: gold_block_ids should be empty, "
                f"got {g['gold_block_ids']}"
            )
        answer = g.get("reference_answer", "")
        refusal_indicators = [
            "does not", "is not", "are not", "cannot", "outside the scope",
            "not addressed", "doesn't cover", "medical", "doctor", "consult",
            "professional", "not covered", "falls outside",
        ]
        if not any(indicator.lower() in answer.lower() for indicator in refusal_indicators):
            errors.append(
                f"negative {q['id']}: answer doesn't read as refusal: "
                f"\"{answer[:80]}...\""
            )

    # ── Check 5: non-negative answers ≤130 words, contain gold work title ──
    titles = _titles()
    title_map = {doc_id: title for doc_id, title in titles.items()
                 if len(title) > 3}

    for q in questions:
        if q["kind"] == "negative":
            continue
        g = gold_by_id.get(q["id"])
        if not g:
            continue

        answer = g.get("reference_answer", "")
        wc = _word_count(answer)

        if wc > 130:
            errors.append(
                f"gold {q['id']}: {wc} words (max 130)"
            )

        # Must contain at least one gold work title
        gold_doc_ids = g.get("gold_doc_ids", [])
        matched_title = False
        for doc_id in gold_doc_ids:
            title = titles.get(doc_id, "")
            if title and title.lower() in answer.lower():
                matched_title = True
                break

        if not matched_title and gold_doc_ids:
            errors.append(
                f"gold {q['id']}: no gold work title found in answer. "
                f"Gold docs: {gold_doc_ids}. "
                f"Answer starts: \"{answer[:80]}...\""
            )

    # ── Report ──
    if errors:
        for e in errors[:25]:
            print(f"  FAIL: {e}", file=sys.stderr)
        if len(errors) > 25:
            print(f"  ... and {len(errors) - 25} more", file=sys.stderr)
        return 1

    # Print success + 5 sampled rows
    print(f"A2 OK — {len(gold)} gold rows, {len(questions)} questions, 1:1 coverage")

    # Summary stats
    nonneg_gold = [g for g in gold if questions_by_id[g["id"]]["kind"] != "negative"]
    neg_gold = [g for g in gold if questions_by_id[g["id"]]["kind"] == "negative"]

    avg_words = sum(_word_count(g["reference_answer"]) for g in nonneg_gold) / len(nonneg_gold) if nonneg_gold else 0
    print(f"  Non-negative: {len(nonneg_gold)} rows, avg {avg_words:.0f} words")
    print(f"  Negative: {len(neg_gold)} rows, avg {sum(_word_count(g['reference_answer']) for g in neg_gold) / len(neg_gold):.0f} words" if neg_gold else "  Negative: 0 rows")

    # Print 5 sampled rows for Fable spot-read
    import random
    rng = random.Random(42)
    sample = rng.sample(gold, min(5, len(gold)))
    print("\n--- Sampled rows for Fable spot-read ---")
    for g in sample:
        kind = questions_by_id.get(g["id"], {}).get("kind", "?")
        doc_ids = g.get("gold_doc_ids", [])
        block_ids = g.get("gold_block_ids", [])
        answer = g.get("reference_answer", "")
        print(f"\n  ID: {g['id']} (kind={kind})")
        print(f"  Gold docs: {doc_ids}")
        print(f"  Gold blocks: {block_ids}")
        print(f"  Answer ({_word_count(answer)} words):")
        print(f"    {answer[:200]}...")
    print("\n--- End sample ---")

    return 0


# Force-register in both module spaces (same pattern as ft_checks_a1.py)
_main = sys.modules.get("__main__")
if _main is not None and hasattr(_main, "_CHECKS"):
    _main._CHECKS["a2"] = check_a2
import scripts.ft_checks as _ftc  # noqa: E402
_ftc._CHECKS["a2"] = check_a2
