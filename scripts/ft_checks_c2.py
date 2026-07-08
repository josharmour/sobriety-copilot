#!/usr/bin/env python3
"""FT-C2 Verify: schema, leakage guard, distractor-citation audit.

Registered via @register() decorator so ``python -m scripts.ft_checks c2``
discovers this module through the ft_checks auto-import machinery.

Checks:
  1. Schema — every line is valid JSON with {messages, meta}, messages has
     system/user/assistant roles, meta has required fields.
  2. Leakage guard — no gold block appears in the evaluation exclusion set
     (A2 gold or A1 source blocks from questions.jsonl).
  3. Distractor-citation audit — dsv4 judges 50 random samples for whether
     the assistant answer cites a distractor passage. Pass if rate < 5%.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from scripts.ft_checks import register, open_corpus

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DSV4_BASE = "http://10.0.0.10:8002/v1"
DSV4_MODEL = "deepseek-v4-flash"

QUESTIONS_PATH = REPO_ROOT / "finetune" / "eval" / "questions.jsonl"
GOLD_PATH = REPO_ROOT / "finetune" / "eval" / "gold.jsonl"
SFT_PATH = REPO_ROOT / "finetune" / "gen" / "sft.jsonl"

AUDIT_SAMPLE_SIZE = 50
MAX_CITE_DISTRACTOR_RATE = 0.05  # 5%


def _load_exclusion_set() -> set[tuple[str, str]]:
    """Load (doc_id, block_id) pairs that must NOT appear as gold in RAFT
    samples. Block ids are per-document (e.g. b00406 exists in 66 docs), so
    comparing bare block ids over-flags coincidental id collisions."""
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
                for i, b in enumerate(blocks):
                    d = docs[i] if i < len(docs) else primary
                    if d:
                        excluded.add((d, b))
    elif QUESTIONS_PATH.is_file():
        with open(QUESTIONS_PATH) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                docs = row.get("source_doc_ids") or []
                primary = row.get("source_doc_id")
                blocks = row.get("source_block_ids", [])
                for i, b in enumerate(blocks):
                    d = docs[i] if i < len(docs) else primary
                    if d:
                        excluded.add((d, b))
    return excluded


# Strip reasoning preamble from raw content
_REASONING_CLEANUPS = (
    "we need to", "i need to", "the assistant", "the user",
    "the person", "we should", "i should", "let me",
    "to answer this", "to respond", "yes or no:",
)


def _clean_judge_verdict(raw: str) -> str:
    """Strip reasoning preamble from judge output and extract YES/NO."""
    cleaned = raw.strip()
    for prefix in _REASONING_CLEANUPS:
        if cleaned.lower().startswith(prefix):
            # Find first colon or newline, take what's after
            for sep in (":", "\n", "."):
                idx = cleaned.find(sep)
                if idx > 0 and idx < 150:
                    cleaned = cleaned[idx + 1:].strip()
                    break
    # Extract YES or NO
    for word in ("YES", "NO"):
        if word in cleaned.upper():
            return word
    return cleaned[:20]


def _call_dsv4_judge(system_prompt: str, user_prompt: str) -> str | None:
    """Call dsv4 as a judge (temp=0, no thinking).

    Returns cleaned YES/NO verdict or None on failure.
    """
    for attempt in range(3):
        try:
            resp = requests.post(
                f"{DSV4_BASE}/chat/completions",
                json={
                    "model": DSV4_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 1024,  # generous — model needs room for reasoning before answer
                    "reasoning_effort": "low",
                },
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            msg = data["choices"][0]["message"]
            content = msg.get("content")
            # If content is null, try the reasoning field as fallback
            if not content:
                content = msg.get("reasoning", "")
            if not content:
                if attempt < 2:
                    continue
                return None
            return _clean_judge_verdict(content)
        except Exception as e:
            if attempt < 2:
                continue
            print(f"  [dsv4 judge error] {e}", file=sys.stderr)
            return None
    return None


def _check_leakage(
    rows: list[dict], exclusion_set: set[tuple[str, str]]
) -> list[str]:
    """Check that no gold (doc, block) pair is in the exclusion set."""
    errors: list[str] = []
    for i, row in enumerate(rows):
        meta = row.get("meta", {})
        gold_blocks = meta.get("gold_blocks", [])
        gold_docs = meta.get("gold_docs", [])
        for j, bid in enumerate(gold_blocks):
            doc = gold_docs[j] if j < len(gold_docs) else None
            if doc and (doc, bid) in exclusion_set:
                errors.append(
                    f"row {i} (sample_type={meta.get('sample_type', '?')}): "
                    f"gold block '{doc}/{bid}' is in eval exclusion set"
                )
    return errors


def _check_schema(rows: list[dict]) -> list[str]:
    """Validate the schema of each sample."""
    errors: list[str] = []
    for i, row in enumerate(rows):
        # Top-level keys
        if "messages" not in row:
            errors.append(f"row {i}: missing 'messages'")
            continue
        if "meta" not in row:
            errors.append(f"row {i}: missing 'meta'")

        msgs = row["messages"]
        if not isinstance(msgs, list) or len(msgs) != 3:
            errors.append(f"row {i}: messages must be a list of 3, got {type(msgs).__name__} len={len(msgs) if isinstance(msgs, list) else '?'}")
            continue

        roles = [m.get("role") for m in msgs]
        if roles != ["system", "user", "assistant"]:
            errors.append(f"row {i}: expected roles [system, user, assistant], got {roles}")
            continue

        for j, role in enumerate(["system", "user", "assistant"]):
            if "content" not in msgs[j] or not isinstance(msgs[j]["content"], str):
                errors.append(f"row {i}: messages[{j}] missing or invalid 'content'")

        # Meta required fields
        meta = row.get("meta", {})
        for field in ("intent_id", "difficulty", "register", "crisis_adjacent", "sample_type"):
            if field not in meta:
                errors.append(f"row {i}: meta missing '{field}'")

        sample_type = meta.get("sample_type", "")
        if sample_type == "context":
            for field in ("gold_blocks", "gold_docs", "distractor_blocks", "distractor_docs"):
                if field not in meta:
                    errors.append(f"row {i}: context sample meta missing '{field}'")

        # Check no-context and refusal have no gold blocks
        if sample_type in ("no_context", "refusal"):
            if meta.get("gold_blocks"):
                errors.append(f"row {i}: {sample_type} sample has non-empty gold_blocks")

    return errors


def _audit_distractor_citation(rows: list[dict]) -> list[str]:
    """Audit 50 random context samples for distractor citation.

    Uses dsv4 as judge (temp=0) to check if the assistant answer
    references a distractor passage as if it were authoritative.
    """
    # Filter to context-type samples
    ctx_samples = [
        (i, row) for i, row in enumerate(rows)
        if row["meta"].get("sample_type") in ("context", "context_crisis")
        and row["meta"].get("distractor_blocks")
    ]

    if len(ctx_samples) < AUDIT_SAMPLE_SIZE:
        print(f"  [audit] only {len(ctx_samples)} context samples available (need {AUDIT_SAMPLE_SIZE})")
        return []

    sampled = random.sample(ctx_samples, AUDIT_SAMPLE_SIZE)
    cite_distractor_count = 0

    JUDGE_SYSTEM = (
        "You are a strict judge of whether an AI assistant's answer cites or "
        "draws authority from a distractor passage. A distractor passage is "
        "one that is irrelevant to the user's question and should be ignored. "
        "Answer ONLY with YES or NO.\n"
        "YES = the assistant's answer names, quotes, or clearly draws authority "
        "from a distractor passage (NOT from the gold passages).\n"
        "NO = the assistant answer correctly ignores distractors and only "
        "grounds in the gold passages or general knowledge."
    )

    for idx, (orig_idx, row) in enumerate(sampled):
        meta = row["meta"]
        answer = row["messages"][2]["content"]
        # We need the passages as they appeared — they're embedded in user msg
        user_msg = row["messages"][1]["content"]
        gold_blocks = meta.get("gold_blocks", [])
        distractor_blocks = meta.get("distractor_blocks", [])

        judge_prompt = (
            f"QUESTION: {meta.get('intent_id', '?')}\n\n"
            f"USER MESSAGE:\n{user_msg[:2000]}\n\n"
            f"ASSISTANT ANSWER:\n{answer[:800]}\n\n"
            f"GOLD BLOCK IDs: {gold_blocks}\n"
            f"DISTRACTOR BLOCK IDs: {distractor_blocks}\n\n"
            f"Does the assistant answer cite or draw authority from any "
            f"distractor passage? Answer YES or NO."
        )

        verdict = _call_dsv4_judge(JUDGE_SYSTEM, judge_prompt)

        if verdict and verdict.upper().startswith("YES"):
            cite_distractor_count += 1
            print(
                f"  [audit] sample {orig_idx} ({meta['intent_id']}): "
                f"CITED DISTRACTOR — {answer[:100]}...",
                file=sys.stderr,
            )
        elif verdict is None:
            print(f"  [audit] sample {orig_idx}: judge call failed, skipping", file=sys.stderr)

        if (idx + 1) % 10 == 0:
            print(f"  [audit] {idx + 1}/{AUDIT_SAMPLE_SIZE} judged...", flush=True)

    rate = cite_distractor_count / AUDIT_SAMPLE_SIZE if AUDIT_SAMPLE_SIZE > 0 else 0

    errors: list[str] = []
    if rate >= MAX_CITE_DISTRACTOR_RATE:
        errors.append(
            f"distractor citation rate {rate:.1%} ({cite_distractor_count}/{AUDIT_SAMPLE_SIZE}) "
            f"exceeds threshold {MAX_CITE_DISTRACTOR_RATE:.0%}"
        )
    else:
        print(f"  [audit] distractor citation rate: {rate:.1%} ({cite_distractor_count}/{AUDIT_SAMPLE_SIZE})")

    return errors


@register("c2")
def check_c2(args: list[str]) -> int:
    """Verify FT-C2 output."""
    if not SFT_PATH.is_file():
        print(f"FAIL: {SFT_PATH} not found", file=sys.stderr)
        return 1

    # Parse args for optional seed
    audit_seed = 42
    for a in args:
        if a.startswith("--seed="):
            audit_seed = int(a.split("=", 1)[1])
    random.seed(audit_seed)

    errors: list[str] = []
    rows: list[dict] = []

    # ── Load ──
    with open(SFT_PATH) as f:
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

    if len(rows) < 8000:
        errors.append(f"only {len(rows)} samples (need ≥8000)")
    else:
        print(f"  count: {len(rows)} ✓")

    # ── Schema ──
    schema_errors = _check_schema(rows)
    errors.extend(schema_errors)
    if not schema_errors:
        print("  schema: OK ✓")

    # ── Leakage ──
    exclusion_set = _load_exclusion_set()
    if exclusion_set:
        leak_errors = _check_leakage(rows, exclusion_set)
        errors.extend(leak_errors)
        if not leak_errors:
            print(f"  leakage: OK — no gold blocks from exclusion set ({len(exclusion_set)} excluded) ✓")
        else:
            print(f"  leakage: {len(leak_errors)} violations ✗", file=sys.stderr)
    else:
        print("  leakage: SKIP — no exclusion set available")

    # ── Sample type distribution ──
    type_counts: dict[str, int] = {}
    for row in rows:
        t = row["meta"].get("sample_type", "?")
        type_counts[t] = type_counts.get(t, 0) + 1
    total = len(rows)
    print(f"  types: {type_counts}")
    for t, c in type_counts.items():
        if t == "no_context":
            pct = c / total
            if pct < 0.08 or pct > 0.12:
                errors.append(f"no_context ratio {pct:.1%} ({c}/{total}) outside expected 8-12%")
        if t == "refusal":
            pct = c / total
            if pct < 0.03 or pct > 0.08:
                errors.append(f"refusal ratio {pct:.1%} ({c}/{total}) outside expected 3-8%")

    if errors:
        for e in errors:
            print(f"  FAIL: {e}", file=sys.stderr)
        return 1

    # ── Distractor-citation audit ──
    print("  [audit] running 50-sample distractor-citation audit with dsv4 judge...")
    audit_errors = _audit_distractor_citation(rows)
    errors.extend(audit_errors)

    if errors:
        for e in errors:
            print(f"  FAIL: {e}", file=sys.stderr)
        return 1

    print(f"\nC2 OK — {len(rows)} samples, all checks passed ✓")
    return 0
