#!/usr/bin/env python3
"""FT-A1: Mine eval questions from the corpus using dsv4.

Generates ≥240 eval questions (≥40 per kind) into finetune/eval/questions.jsonl.
Uses dsv4 at http://10.0.0.10:8002/v1, temperature=0.7.

Usage:
    source venv/bin/activate
    python -m scripts.ft_gen_questions
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from pathlib import Path

import openai

# Add repo root to path so ft_checks imports work
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from scripts.ft_checks import open_corpus

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TARGET_PER_KIND = 45  # ≥40, slight buffer
KINDS = ["doctrine", "practical", "phrase", "crosswork", "personal", "negative"]

OUT_PATH = _REPO_ROOT / "finetune" / "eval" / "questions.jsonl"

LLM_BASE = os.environ.get("LLM_BASE_URL", "http://10.0.0.10:8002/v1")
LLM_MODEL = "deepseek-v4-flash"
API_KEY = "none"

client = openai.OpenAI(base_url=LLM_BASE, api_key=API_KEY)

random.seed(42)

# ---------------------------------------------------------------------------
# Corpus sampling helpers
# ---------------------------------------------------------------------------

# Keyword sets for heuristic filtering by kind
_DOCTRINE_KW = re.compile(
    r"\b(step\s+(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"
    r"|1st|2nd|3rd|4th|5th|6th|7th|8th|9th|10th|11th|12th)"
    r"|tradition\s+\w+|principle|concept|doctrine|teach|"
    r"spiritual\s+principle|belief|fundamental|creed)\b",
    re.IGNORECASE,
)
_PRACTICAL_KW = re.compile(
    r"\b(how\s+to|guide|practice|action|exercise|suggestion|tip|"
    r"way\s+to|steps?\s+to|method|technique|approach|try\s+|"
    r"remember\s+to|be\s+sure\s+to|always|never|should|must)\b",
    re.IGNORECASE,
)
_PHRASE_KW = re.compile(
    r"\b(one\s+day\s+at\s+a\s+time|live\s+and\s+let\s+live|"
    r"easy\s+does\s+it|first\s+things\s+first|trust\s+god|"
    r"clean\s+house|slogan|saying|motto|proverb|"
    r"wise\s+words|words\s+to\s+live\s+by|principle\s+before\s+personality|"
    r"let\s+go\s+and\s+let\s+god|think\s+think\s+think|"
    r"half\s+measures|stinking\s+thinking)\b",
    re.IGNORECASE,
)
_PERSONAL_KW = re.compile(
    r"\b(hope|courage|strength|support|you\s+can|believe|journey|"
    r"struggle|pain|fear|afraid|lonely|despair|suffering|"
    r"healing|recovery\s+is|you\s+are\s+not\s+alone|"
    r"it\s+gets\s+better|keep\s+coming|progress\s+not\s+perfection)\b",
    re.IGNORECASE,
)


def _match_kind(text: str, heading: str) -> str | None:
    """Heuristic kind assignment based on heading/text keywords."""
    combined = f"{heading} {text[:500]}"
    if _DOCTRINE_KW.search(combined):
        return "doctrine"
    if _PRACTICAL_KW.search(combined):
        return "practical"
    if _PHRASE_KW.search(combined):
        return "phrase"
    if _PERSONAL_KW.search(combined):
        return "personal"
    return None


def sample_blocks(conn, kind: str, n: int):
    """Sample *n* blocks from the corpus suitable for *kind*.

    Uses heuristic keyword filtering, then random selection.
    Falls back to pure random sampling with post-hoc kind assignment.
    """
    kw = {
        "doctrine": _DOCTRINE_KW,
        "practical": _PRACTICAL_KW,
        "phrase": _PHRASE_KW,
        "personal": _PERSONAL_KW,
    }.get(kind)

    if kw and kind != "personal":
        # Use FTS5 to find blocks matching keywords
        like_clause = "%" + kind + "%"
        rows = conn.execute(
            """
            SELECT doc_id, block_id, heading, text FROM blocks
            WHERE text MATCH ?
            ORDER BY rowid
            """,
            (kind,),
        ).fetchall()
        # If FTS5 match didn't work or too few, fall back to LIKE
        if len(rows) < n:
            rows = conn.execute(
                """
                SELECT doc_id, block_id, heading, text FROM blocks
                WHERE heading LIKE ? OR text LIKE ?
                ORDER BY random()
                LIMIT ?
                """,
                (f"%{kind}%", f"%{kind}%", n * 5),
            ).fetchall()
    elif kw:
        # Keyword-based search using LIKE
        # Build a query that ORs keywords
        patterns = []
        terms = []
        # Split the keyword regex into individual terms
        kw_str = kw.pattern
        # Extract word patterns from the regex
        word_patterns = re.findall(r"\\b\(([^)]+)\)\\b", kw_str)
        for group in word_patterns:
            for alt in group.split("|"):
                alt_clean = alt.replace("\\s+", " ").replace("\\+", "+")
                terms.append(alt_clean)

        if terms:
            clauses = " OR ".join(
                ["(heading LIKE ? OR text LIKE ?)" for _ in terms[:20]]
            )
            params = []
            for t in terms[:20]:
                params.extend([f"%{t}%", f"%{t}%"])
            rows = conn.execute(
                f"SELECT doc_id, block_id, heading, text FROM blocks WHERE {clauses} ORDER BY random() LIMIT ?",
                (*params, n * 5),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT doc_id, block_id, heading, text FROM blocks ORDER BY random() LIMIT ?",
                (n * 5,),
            ).fetchall()
    else:
        rows = conn.execute(
            "SELECT doc_id, block_id, heading, text FROM blocks ORDER BY random() LIMIT ?",
            (n * 5,),
        ).fetchall()

    # Filter by length (need enough content for a question)
    candidates = [r for r in rows if len(r["text"] or "") >= 150]

    # Shuffle and take n
    random.shuffle(candidates)
    selected = candidates[:n]

    result = []
    for r in selected:
        result.append(
            {
                "doc_id": r["doc_id"],
                "block_id": r["block_id"],
                "heading": r["heading"] or "",
                "text": r["text"] or "",
            }
        )
    return result


def sample_crosswork_pairs(conn, n: int):
    """Sample *n* pairs of blocks from different documents."""
    # Get all documents
    docs = conn.execute(
        "SELECT DISTINCT doc_id FROM blocks ORDER BY random() LIMIT 50"
    ).fetchall()
    doc_ids = [r["doc_id"] for r in docs]

    pairs = []
    attempts = 0
    while len(pairs) < n and attempts < n * 20:
        attempts += 1
        d1, d2 = random.sample(doc_ids, 2) if len(doc_ids) >= 2 else (doc_ids[0], doc_ids[0])
        if d1 == d2:
            continue
        b1 = conn.execute(
            "SELECT doc_id, block_id, heading, text FROM blocks WHERE doc_id=? ORDER BY random() LIMIT 1",
            (d1,),
        ).fetchone()
        b2 = conn.execute(
            "SELECT doc_id, block_id, heading, text FROM blocks WHERE doc_id=? ORDER BY random() LIMIT 1",
            (d2,),
        ).fetchone()
        if (
            b1
            and b2
            and len(b1["text"] or "") >= 100
            and len(b2["text"] or "") >= 100
        ):
            pairs.append(
                {
                    "blocks": [
                        {
                            "doc_id": b1["doc_id"],
                            "block_id": b1["block_id"],
                            "heading": b1["heading"] or "",
                            "text": b1["text"] or "",
                        },
                        {
                            "doc_id": b2["doc_id"],
                            "block_id": b2["block_id"],
                            "heading": b2["heading"] or "",
                            "text": b2["text"] or "",
                        },
                    ]
                }
            )
    return pairs


# ---------------------------------------------------------------------------
# dsv4 question generation
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are an expert in recovery literature and a skilled question-writer for an AI training dataset.

Your task: Given excerpts from A.A./recovery literature, write a realistic question that:
1. A person in recovery might genuinely ask
2. Is answerable from the given excerpt(s)
3. Does NOT quote the excerpt verbatim (rephrase in the question)
4. Is concise (10-30 words)
5. Uses natural, conversational language

Respond with a JSON array of objects: [{"question": "..."}]
One object per excerpt, in the same order."""

_CROSSWORK_SYSTEM = """You are an expert in recovery literature and a skilled question-writer for an AI training dataset.

Your task: Given TWO excerpts from DIFFERENT recovery books, write a comparison question that:
1. A person in recovery might genuinely ask when trying to understand how different sources approach the same topic
2. Is answerable by comparing the two excerpts
3. Does NOT quote either excerpt verbatim
4. Asks about the relationship, difference, or connection between the two sources' teachings
5. Is concise (15-35 words)

Respond with a JSON array: [{"question": "..."}]
One question per pair."""

_NEGATIVE_SYSTEM = """You are generating "negative" test questions for an AI recovery assistant.

Your task: Write questions that a person in recovery MIGHT ask, but that CANNOT be answered from 12-step recovery literature (the corpus has no relevant content on these topics).

Topics to draw from:
- Medical/clinical treatments (medications, detox protocols)
- Legal advice
- Scientific research on addiction (brain chemistry, genetics)
- Specific therapist recommendations
- Financial/insurance questions
- Non-12-step recovery programs (SMART Recovery specifics, etc.)
- Current events or pop culture
- Personal medical history interpretation

Each question must sound like something a real person in recovery would ask (not obviously absurd or off-topic).

Respond with a JSON array: [{"question": "..."}]"""


def _call_llm(messages, system, temp=0.7, max_tokens=2048):
    """Call dsv4 and return parsed JSON response."""
    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system},
                *messages,
            ],
            temperature=temp,
            max_tokens=max_tokens,
        )
        content = resp.choices[0].message.content
        if not content:
            return None
        # Strip markdown code fences if present
        content = content.strip()
        if content.startswith("```"):
            # Find the first { or [
            start = content.find("[")
            if start == -1:
                start = content.find("{")
            if start >= 0:
                content = content[start:]
            # Remove trailing ```
            end = content.rfind("```")
            if end >= 0:
                content = content[:end]
            content = content.strip()
        return json.loads(content)
    except Exception as e:
        print(f"  [llm error] {e}", file=sys.stderr)
        return None


def generate_questions(kind: str, blocks: list[dict]) -> list[dict]:
    """Generate questions of *kind* from sampled *blocks*.

    Returns list of {id, question, kind, source_doc_id, source_block_ids[]}.
    """
    results = []

    if kind == "negative":
        # Generate negative questions in batches
        batch_size = 10
        for i in range(0, len(blocks) if blocks else TARGET_PER_KIND, batch_size):
            count = min(batch_size, TARGET_PER_KIND - len(results))
            if count <= 0:
                break
            prompt = f"Generate {count} realistic 'negative' questions (topics the recovery literature doesn't cover) that a person in recovery might ask."
            data = _call_llm(
                [{"role": "user", "content": prompt}],
                _NEGATIVE_SYSTEM,
                temp=0.8,
            )
            if data and isinstance(data, list):
                for item in data:
                    q = item.get("question", "").strip()
                    if q and len(q) >= 10:
                        qid = f"eval-{kind}-{len(results):04d}"
                        results.append(
                            {
                                "id": qid,
                                "question": q,
                                "kind": kind,
                                "source_doc_id": None,
                                "source_block_ids": [],
                            }
                        )
                        if len(results) >= TARGET_PER_KIND:
                            break
            print(
                f"  [{kind}] {len(results)}/{TARGET_PER_KIND}",
                flush=True,
            )
        return results

    if kind == "crosswork":
        batch_size = 5
        for i in range(0, len(blocks), batch_size):
            batch = blocks[i : i + batch_size]
            if len(results) >= TARGET_PER_KIND:
                break
            prompt_lines = []
            for j, pair in enumerate(batch):
                b0, b1 = pair["blocks"]
                prompt_lines.append(
                    f"--- Pair {j+1} ---\n"
                    f"Source A ({b0['doc_id']}): {b0['heading']}\n"
                    f"{b0['text'][:600]}\n\n"
                    f"Source B ({b1['doc_id']}): {b1['heading']}\n"
                    f"{b1['text'][:600]}"
                )
            prompt = "\n\n".join(prompt_lines)
            if not prompt.strip():
                continue
            data = _call_llm(
                [{"role": "user", "content": prompt}],
                _CROSSWORK_SYSTEM,
                temp=0.7,
            )
            if data and isinstance(data, list):
                for j, item in enumerate(data):
                    q = item.get("question", "").strip()
                    if q and len(q) >= 10 and j < len(batch):
                        pair = batch[j]
                        qid = f"eval-{kind}-{len(results):04d}"
                        results.append(
                            {
                                "id": qid,
                                "question": q,
                                "kind": kind,
                                "source_doc_id": None,  # crosswork spans docs
                                "source_block_ids": [
                                    b["block_id"]
                                    for b in pair["blocks"]
                                ],
                            }
                        )
            print(
                f"  [{kind}] {len(results)}/{TARGET_PER_KIND}",
                flush=True,
            )
        return results

    # Standard kinds (doctrine, practical, phrase, personal)
    batch_size = 8
    for i in range(0, len(blocks), batch_size):
        batch = blocks[i : i + batch_size]
        if len(results) >= TARGET_PER_KIND:
            break
        prompt_lines = []
        for j, b in enumerate(batch):
            prompt_lines.append(
                f"--- Excerpt {j+1} (from {b['doc_id']}, heading: {b['heading']}) ---\n"
                f"{b['text'][:800]}"
            )
        prompt = "\n\n".join(prompt_lines)
        if not prompt.strip():
            continue
        data = _call_llm(
            [{"role": "user", "content": prompt}],
            _SYSTEM_PROMPT,
            temp=0.7,
        )
        if data and isinstance(data, list):
            for j, item in enumerate(data):
                q = item.get("question", "").strip()
                if q and len(q) >= 10 and j < len(batch):
                    b = batch[j]
                    qid = f"eval-{kind}-{len(results):04d}"
                    results.append(
                        {
                            "id": qid,
                            "question": q,
                            "kind": kind,
                            "source_doc_id": b["doc_id"],
                            "source_block_ids": [b["block_id"]],
                        }
                    )
        print(
            f"  [{kind}] {len(results)}/{TARGET_PER_KIND}",
            flush=True,
        )
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print("FT-A1: Generating eval questions from corpus using dsv4", flush=True)

    conn = open_corpus()

    all_questions = []

    for kind in KINDS:
        print(f"\n--- Kind: {kind} ---", flush=True)

        if kind == "negative":
            questions = generate_questions(kind, [])
        elif kind == "crosswork":
            pairs = sample_crosswork_pairs(conn, TARGET_PER_KIND + 10)
            print(f"  sampled {len(pairs)} crosswork pairs", flush=True)
            questions = generate_questions(kind, pairs)
        else:
            blocks = sample_blocks(conn, kind, TARGET_PER_KIND + 10)
            print(f"  sampled {len(blocks)} blocks for {kind}", flush=True)
            questions = generate_questions(kind, blocks)

        all_questions.extend(questions)
        print(f"  → {len(questions)} questions for {kind}", flush=True)

    conn.close()

    # Write JSONL
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        for q in all_questions:
            f.write(json.dumps(q) + "\n")

    print(f"\nWritten {len(all_questions)} questions to {OUT_PATH}", flush=True)

    # Summary
    from collections import Counter
    kind_counts = Counter(q["kind"] for q in all_questions)
    print("\nPer-kind counts:")
    for k in KINDS:
        print(f"  {k}: {kind_counts.get(k, 0)}")

    if len(all_questions) < 240:
        print(f"WARNING: only {len(all_questions)} questions (need ≥240)", file=sys.stderr)
        return 1

    missing_kinds = [k for k in KINDS if kind_counts.get(k, 0) < 40]
    if missing_kinds:
        print(f"WARNING: kinds below 40: {missing_kinds}", file=sys.stderr)
        return 1

    print("\nFT-A1 generation complete.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
