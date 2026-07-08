#!/usr/bin/env python3
"""FT-A3: Judge + metrics runner for the fine-tuning pipeline.

Runs a *system under test* against the eval set and emits per-question
metrics + aggregates to ``finetune/eval/runs/<name>.json``.

Two system modes:

  retriever-only
    BM25 retrieval (FTS5) over the search.db corpus.  Measures
    retrieval.recall@4 and @8.  Citation, faithfulness, quality,
    and refusal metrics are null (no answer generated).

  server
    POST /api/chat against a running sobriety-copilot instance (default
    http://localhost:5000), collects the SSE stream, and measures all
    metrics: retrieval (from exposed sources), citation accuracy,
    faithfulness, answer quality, and refusal correctness.

Judge calls use dsv4 (DeepSeek V4 Flash) at http://10.0.0.10:8002/v1
with temperature 0, thinking disabled, and concurrency ≤ 8.

Usage:
    python -m scripts.ft_eval --system retriever-only --limit 12
    python -m scripts.ft_eval --system server [--base-url http://localhost:5000]
    python -m scripts.ft_eval --system retriever-only [--name my-run]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
QUESTIONS_PATH = REPO_ROOT / "finetune" / "eval" / "questions.jsonl"
GOLD_PATH = REPO_ROOT / "finetune" / "eval" / "gold.jsonl"
CORPUS_PACK = REPO_ROOT / "packs" / "library-v1.scpack"
CACHE_DB = REPO_ROOT / "finetune" / "cache" / "search.db"
RUNS_DIR = REPO_ROOT / "finetune" / "eval" / "runs"

# ---------------------------------------------------------------------------
# dsv4 judge defaults
# ---------------------------------------------------------------------------
JUDGE_BASE_URL = os.environ.get("JUDGE_BASE_URL", "http://10.0.0.10:8002/v1")
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "dsv4")
JUDGE_CONCURRENCY = 8  # max parallel judge calls (leave headroom for prod)

# ---------------------------------------------------------------------------
# Judge rubrics  (embedded in the script per FT-A3 spec)
# ---------------------------------------------------------------------------

FAITHFULNESS_RUBRIC = """Rate the faithfulness of the following answer on a scale of 1-5.

Faithfulness measures whether ALL claims in the answer are supported by the
provided context passages. An answer is faithful if it does not invent claims,
facts, quotes, or details that are absent from the context provided.

1 = Most claims are unsupported or directly contradicted by the context
2 = Several unsupported claims
3 = Some unsupported claims but mostly faithful overall
4 = Minor issues — one questionable or unsupported claim
5 = Perfectly faithful — every claim is traceable to the provided context

Return ONLY an integer 1-5, no other text."""

ANSWER_QUALITY_RUBRIC = """Rate the quality of this answer on a scale of 1-5 compared to
the reference answer.

Quality measures how helpful, well-written, and appropriately voiced the answer is.
A high-quality answer:
- Is grounded in the literature and names the work by title
- Uses a warm-knowledgeable tone appropriate for recovery support
- Is concise and directly addresses the question
- Matches the reference answer in substance and voice

The reference answer is provided as the gold standard for this question.

1 = Poor — unhelpful, off-topic, or badly written
2 = Below average — misses key points or has tone/register issues
3 = Adequate — covers main points but lacks polish or misses nuance
4 = Good — clear, well-grounded, close to reference quality
5 = Excellent — matches or exceeds the reference answer in substance and voice

Return ONLY an integer 1-5, no other text."""

REFUSAL_RUBRIC = """Rate this answer on refusal correctness on a scale of 1-5.

The question falls OUTSIDE the scope of the recovery literature corpus — it is
about a topic the corpus does not cover. A correct refusal:

1. Clearly states or implies that the question is not covered by the recovery literature
2. Does NOT fabricate citations, sources, or literature-based claims
3. Does NOT invent a recovery-related answer when none exists in the corpus
4. May redirect to appropriate resources or suggest the user consult other sources

1 = Invented a full recovery literature answer with fabricated citations
2 = Gave an unsupported answer or made up a source
3 = Partial refusal — attempted to answer but also acknowledged limits
4 = Mostly correct refusal — minor issues
5 = Perfect refusal — clearly declines, no fabricated citations, appropriate redirect

Return ONLY an integer 1-5, no other text."""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_corpus_db() -> Path:
    """Extract search.db from pack into cache (idempotent)."""
    if CACHE_DB.exists():
        return CACHE_DB
    CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    import shutil
    with zipfile.ZipFile(CORPUS_PACK, "r") as zf:
        with zf.open("search.db") as src, open(CACHE_DB, "wb") as dst:
            shutil.copyfileobj(src, dst)
    conn = sqlite3.connect(str(CACHE_DB))
    row = conn.execute("SELECT COUNT(*) FROM blocks").fetchone()
    print(f"[corpus] {row[0]} blocks at {CACHE_DB}", flush=True)
    conn.close()
    return CACHE_DB


def _open_corpus_ro() -> sqlite3.Connection:
    """Open the corpus DB read-only."""
    _ensure_corpus_db()
    conn = sqlite3.connect(f"file:{CACHE_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _load_questions(limit: int | None = None) -> list[dict]:
    """Load questions.jsonl, optionally limiting to first N rows."""
    rows = []
    with open(QUESTIONS_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    if limit is not None and limit < len(rows):
        rows = rows[:limit]
    print(f"[data] {len(rows)} questions loaded", flush=True)
    return rows


def _load_gold() -> dict[str, dict]:
    """Load gold.jsonl keyed by question id."""
    gold: dict[str, dict] = {}
    with open(GOLD_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            gold[row["id"]] = row
    print(f"[data] {len(gold)} gold rows loaded", flush=True)
    return gold


def _load_manifest_titles() -> dict[str, str]:
    """Load doc_id → title mapping from the pack manifest."""
    with zipfile.ZipFile(CORPUS_PACK, "r") as zf:
        m = json.loads(zf.read("manifest-index.json"))
    items = m if isinstance(m, list) else m.get("docs") or []
    return {d["doc_id"]: d["title"] for d in items}


def _gold_pairs(gold_row: dict) -> list[tuple[str, str]]:
    """Return list of (doc_id, block_id) gold pairs for a row.

    Handles paired docs↔blocks (crosswork) and single-doc multi-block.
    """
    docs = gold_row.get("gold_doc_ids", []) or []
    blocks = gold_row.get("gold_block_ids", []) or []
    if not docs or not blocks:
        return []
    if len(docs) == 1 and len(blocks) >= 1:
        return [(docs[0], b) for b in blocks]
    if len(docs) == len(blocks):
        return list(zip(docs, blocks))
    # Fallback: pair what we can
    n = min(len(docs), len(blocks))
    return list(zip(docs[:n], blocks[:n]))


# ---------------------------------------------------------------------------
# BM25 retrieval via FTS5
# ---------------------------------------------------------------------------

# FTS5 tokenizer stopword list (default unicode61)
_FTS5_STOPWORDS: frozenset[str] = frozenset({
    "i", "me", "my", "myself", "we", "our", "ours", "ourselves",
    "you", "your", "yours", "yourself", "yourselves",
    "he", "him", "his", "himself", "she", "her", "hers", "herself",
    "it", "its", "itself", "they", "them", "their", "theirs", "themselves",
    "what", "which", "who", "whom", "this", "that", "these", "those",
    "am", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "having", "do", "does", "did", "doing",
    "would", "should", "could", "ought",
    "a", "an", "the", "and", "but", "if", "or", "because", "as",
    "until", "while", "of", "at", "by", "for", "with", "about",
    "against", "between", "into", "through", "during", "before",
    "after", "above", "below", "to", "from", "up", "down", "in",
    "out", "on", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how",
    "all", "any", "both", "each", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same",
    "so", "than", "too", "very", "just",
})


# BM25 parameters (matching server defaults in retriever.py)
_BM25_K1 = 1.5
_BM25_B = 0.75


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase alphanumeric tokens (same pattern as server).

    Strips apostrophes to avoid FTS5 syntax errors (e.g. \"don't\").
    """
    # Remove apostrophes before tokenizing so \"don't\" becomes \"dont\"
    text = text.replace("'", "")
    return [t.lower() for t in re.findall(r"[A-Za-z0-9]+", text)]


def retrieve_bm25(
    question: str, top_k: int = 8
) -> list[tuple[str, str, float]]:
    """Run BM25 retrieval via FTS5 on search.db.

    Uses OR-based query with all non-stopword content terms so that
    FTS5 BM25 ranking properly scores documents by term frequency,
    inverse document frequency, and length normalization.

    Returns list of (doc_id, block_id, bm25_score) sorted by relevance
    (lower BM25 score = more relevant).  Empty list on error.
    """
    # Tokenize and filter stopwords
    tokens = [t for t in _tokenize(question)
              if len(t) > 2 and t not in _FTS5_STOPWORDS]
    if not tokens:
        return []

    # Build an OR query for FTS5
    or_query = " OR ".join(tokens)

    conn = _open_corpus_ro()
    try:
        # BM25 weights: [0, 0, 0, 1] → only the text column (column index 3) matters.
        # doc_id=0, block_id=1, heading=2, text=3
        rows = conn.execute(
            """SELECT doc_id, block_id, bm25(blocks, 0, 0, 0, 1) AS score
               FROM blocks
               WHERE blocks MATCH ?
               ORDER BY score
               LIMIT ?
            """,
            (or_query, top_k),
        ).fetchall()
        return [(r["doc_id"], r["block_id"], r["score"]) for r in rows]
    except sqlite3.OperationalError as e:
        print(f"  [FTS5-ERR] {e} for query: {or_query!r}", flush=True)
        return []
    finally:
        conn.close()


def compute_recall(
    gold_row: dict, top_retrieved: list[tuple[str, str]], k: int
) -> float | None:
    """Compute recall@k for a question.

    Returns fraction of gold (doc_id, block_id) pairs that appear in the
    top-k retrieved results.  None when gold is empty (negative kind).
    """
    pairs = _gold_pairs(gold_row)
    if not pairs:
        return None  # no gold blocks — metric doesn't apply
    retrieved_set = set(top_retrieved[:k])
    hits = sum(1 for p in pairs if p in retrieved_set)
    return hits / len(pairs)


# ---------------------------------------------------------------------------
# Server mode: POST /api/chat + SSE parsing
# ---------------------------------------------------------------------------

def call_server_chat(
    base_url: str, question: str, timeout: int = 120
) -> dict:
    """POST a question to the server's /api/chat endpoint.

    Returns dict with:
      - answer: concatenated token text
      - sources: list of source dicts from first SSE event
      - error: str if failed, else None
    """
    import requests

    url = f"{base_url.rstrip('/')}/api/chat"
    payload = {
        "message": question,
        "history": [],
        "tone": "warm",
        "show_thinking": False,
    }

    answer_parts: list[str] = []
    sources: list[dict] | None = None
    error: str | None = None

    try:
        resp = requests.post(
            url,
            json=payload,
            stream=True,
            timeout=timeout,
        )
        resp.raise_for_status()

        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            if not line.startswith("data: "):
                continue
            data_str = line[6:]  # strip "data: " prefix
            if data_str == '{"done": true}':
                break
            try:
                event = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            if "sources" in event:
                sources = event["sources"]
            elif "token" in event:
                answer_parts.append(event["token"])
            # ignore stats, followups, thinking, diffusion

    except requests.exceptions.RequestException as e:
        error = str(e)

    return {
        "answer": "".join(answer_parts).strip(),
        "sources": sources or [],
        "error": error,
    }


def _source_to_doc_id(source: dict) -> str | None:
    """Try to extract a doc_id from a source dict.

    Sources from the SSE have a ``source`` field which is a filename like
    ``Alcoholics Anonymous - AA.pdf``.  We derive doc_id by stripping
    extension and known suffixes.
    """
    filename = (source.get("source") or "").lower()
    # Remove extension
    filename = re.sub(r"\.[a-z0-9]+$", "", filename)
    # Remove common suffixes like " - aa", " - na"
    filename = re.sub(r"\s*-\s*(aa|na|pdf)$", "", filename)
    # Convert to doc_id format: lowercase, hyphens for spaces
    doc_id = re.sub(r"\s+", "-", filename.strip())
    return doc_id


def compute_citation_accuracy(
    answer: str, gold_row: dict, titles: dict[str, str]
) -> float | None:
    """Check if the answer names at least one gold work's exact title.

    Returns 1.0 if any gold title is mentioned (case-insensitive), 0.0
    otherwise.  None for negative-kind rows (metric skipped).
    """
    kind = gold_row.get("_kind", "")
    if kind == "negative":
        return None

    gold_doc_ids = gold_row.get("gold_doc_ids", []) or []
    if not gold_doc_ids:
        return None

    answer_lower = answer.lower()
    for doc_id in gold_doc_ids:
        title = titles.get(doc_id)
        if title and title.lower() in answer_lower:
            return 1.0

    return 0.0


# ---------------------------------------------------------------------------
# dsv4 judge
# ---------------------------------------------------------------------------

def _judge_request(prompt: str, rubric: str, context: str = "") -> float | None:
    """Call the dsv4 judge model with a rubric and optional context.

    Returns score 1-5 as float, or None on failure.
    """
    import requests

    messages = [
        {
            "role": "system",
            "content": (
                "You are a careful evaluator.  Rate responses according to the "
                "rubric provided.  Return ONLY an integer 1-5."
            ),
        },
    ]

    if context:
        messages.append({
            "role": "user",
            "content": f"Context passages:\n{context}\n\n{prompt}",
        })
    else:
        messages.append({"role": "user", "content": prompt})

    messages.append({
        "role": "user",
        "content": f"\n\nRubric:\n{rubric}",
    })

    try:
        resp = requests.post(
            f"{JUDGE_BASE_URL}/chat/completions",
            json={
                "model": JUDGE_MODEL,
                "messages": messages,
                "temperature": 0.0,
                "max_tokens": 10,
                "chat_template_kwargs": {"thinking": False},
            },
            timeout=60,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        # Extract first integer
        match = re.search(r"[1-5]", raw)
        if match:
            return float(match.group(0))
        return None
    except Exception as e:
        print(f"  [JUDGE-ERR] {e}", flush=True)
        return None


def run_judges_for_question(
    q_id: str,
    answer: str,
    context_texts: list[str],
    gold_row: dict | None,
    titles: dict[str, str],
) -> dict:
    """Run faithfulness, answer_quality, refusal_correctness judges.

    Returns dict with keys: faithfulness, answer_quality, refusal_correctness.
    Each is either a float 1-5 or None.
    """
    result: dict = {
        "faithfulness": None,
        "answer_quality": None,
        "refusal_correctness": None,
    }

    if not answer or gold_row is None:
        return result  # no answer to judge

    kind = gold_row.get("_kind", "")
    context_str = "\n\n".join(context_texts) if context_texts else ""

    # Faithfulness  (skip if no context or negative kind)
    if context_str and kind != "negative":
        faithfulness_prompt = (
            f"Question: {gold_row.get('_question', '')}\n\n"
            f"Answer: {answer}\n\n"
            f"Context passages provided to the answerer:\n{context_str}"
        )
        result["faithfulness"] = _judge_request(
            faithfulness_prompt, FAITHFULNESS_RUBRIC
        )

    # Answer quality  (compare vs reference_answer)
    if gold_row.get("reference_answer"):
        quality_prompt = (
            f"Question: {gold_row.get('_question', '')}\n\n"
            f"Answer to evaluate: {answer}\n\n"
            f"Reference answer (gold standard):\n{gold_row['reference_answer']}"
        )
        result["answer_quality"] = _judge_request(
            quality_prompt, ANSWER_QUALITY_RUBRIC
        )
    elif kind != "negative":
        # No reference answer available
        result["answer_quality"] = None

    # Refusal correctness (negative kind only)
    if kind == "negative":
        refusal_prompt = (
            f"Question (outside corpus scope): {gold_row.get('_question', '')}\n\n"
            f"Answer: {answer}"
        )
        result["refusal_correctness"] = _judge_request(
            refusal_prompt, REFUSAL_RUBRIC
        )

    return result


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Checkpointing  (resumable per question id)
# ---------------------------------------------------------------------------

def _checkpoint_path(name: str) -> Path:
    """Path for the checkpoint file."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    return RUNS_DIR / f"{name}.checkpoint"


def _load_checkpoint(name: str) -> tuple[set[str], list[dict]]:
    """Load checkpoint if it exists.

    Returns (completed_ids, partial_results).
    """
    ckpt = _checkpoint_path(name)
    if not ckpt.exists():
        return set(), []
    try:
        with open(ckpt) as f:
            data = json.load(f)
        completed = set(data.get("completed", []))
        results = data.get("results", [])
        print(f"[ckpt] Loaded checkpoint: {len(completed)} questions already done", flush=True)
        return completed, results
    except (json.JSONDecodeError, KeyError) as e:
        print(f"[ckpt] Corrupt checkpoint, starting fresh: {e}", flush=True)
        return set(), []


def _save_checkpoint(name: str, completed_ids: set[str], results: list[dict]) -> None:
    """Save checkpoint atomically."""
    ckpt = _checkpoint_path(name)
    tmp = ckpt.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump({"completed": sorted(completed_ids), "results": results}, f)
    tmp.rename(ckpt)


def _cleanup_checkpoint(name: str) -> None:
    """Remove checkpoint after successful completion."""
    ckpt = _checkpoint_path(name)
    if ckpt.exists():
        ckpt.unlink()


def _default_name(system: str, limit: int | None) -> str:
    """Generate a sensible default run name."""
    base = system.replace("-only", "")
    if limit is not None:
        return f"smoke-{base}"
    return base


def _make_result_row(
    q: dict,
    gold_row: dict | None,
    titles: dict[str, str],
    retriever_results: list[tuple[str, str]] | None,
    server_result: dict | None,
    judge_scores: dict | None,
) -> dict:
    """Assemble a single result row for the output JSON."""
    q_id = q["id"]
    kind = q.get("kind", "")
    row: dict = {
        "id": q_id,
        "kind": kind,
        "question": q["question"],
        "retrieval": {"recall@4": None, "recall@8": None},
        "citation_accuracy": None,
        "faithfulness": None,
        "answer_quality": None,
        "refusal_correctness": None,
    }

    # Retrieval metrics
    if retriever_results is not None and gold_row is not None:
        row["retrieval"]["retrieved_top8"] = retriever_results[:8]
        row["retrieval"]["recall@4"] = compute_recall(
            gold_row, retriever_results, 4
        )
        row["retrieval"]["recall@8"] = compute_recall(
            gold_row, retriever_results, 8
        )

    # Server response fields
    if server_result is not None:
        row["answer"] = server_result.get("answer", "")
        row["sources"] = server_result.get("sources", [])
        row["server_error"] = server_result.get("error")

        # Citation accuracy
        answer_text = row.get("answer", "")
        if answer_text and gold_row is not None:
            # Tag gold_row with kind for citation check
            gold_row["_kind"] = kind
            row["citation_accuracy"] = compute_citation_accuracy(
                answer_text, gold_row, titles
            )

        # Judge scores
        if judge_scores:
            row["faithfulness"] = judge_scores.get("faithfulness")
            row["answer_quality"] = judge_scores.get("answer_quality")
            row["refusal_correctness"] = judge_scores.get("refusal_correctness")

    return row


def _mean(values: list[float | None]) -> float | None:
    """Compute mean, ignoring None values."""
    valid = [v for v in values if v is not None]
    if not valid:
        return None
    return sum(valid) / len(valid)


def write_output(
    name: str,
    system: str,
    limit: int | None,
    results: list[dict],
) -> Path:
    """Write the run output JSON."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RUNS_DIR / f"{name}.json"

    # Aggregate
    agg: dict[str, float | None] = {
        "retrieval.recall@4": _mean(
            [r["retrieval"]["recall@4"] for r in results]
        ),
        "retrieval.recall@8": _mean(
            [r["retrieval"]["recall@8"] for r in results]
        ),
        "citation_accuracy": _mean(
            [r.get("citation_accuracy") for r in results]
        ),
        "faithfulness": _mean(
            [r.get("faithfulness") for r in results]
        ),
        "answer_quality": _mean(
            [r.get("answer_quality") for r in results]
        ),
        "refusal_correctness": _mean(
            [r.get("refusal_correctness") for r in results]
        ),
    }

    payload = {
        "meta": {
            "system": system,
            "name": name,
            "limit": limit,
            "total": len(results),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "judge_model": JUDGE_MODEL,
            "judge_base_url": JUDGE_BASE_URL,
        },
        "aggregates": agg,
        "results": results,
    }

    # Write atomically via temp file
    tmp = out_path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    tmp.rename(out_path)

    print(f"[output] Wrote {out_path} ({len(results)} questions)", flush=True)
    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="FT-A3: Judge + metrics runner",
    )
    ap.add_argument(
        "--system",
        required=True,
        choices=["server", "retriever-only"],
        help="System under test",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N questions (for smoke tests)",
    )
    ap.add_argument(
        "--base-url",
        default="http://localhost:5000",
        help="Server base URL (only used with --system server)",
    )
    ap.add_argument(
        "--name",
        default=None,
        help="Run name (default: auto-generated)",
    )
    ap.add_argument(
        "--judge-base-url",
        default=JUDGE_BASE_URL,
        help=f"dsv4 judge API base URL (default: {JUDGE_BASE_URL})",
    )
    return ap.parse_args(argv)


def main() -> int:
    args = parse_args()
    global JUDGE_BASE_URL
    JUDGE_BASE_URL = args.judge_base_url

    run_name = args.name or _default_name(args.system, args.limit)
    print(f"[ft-eval] system={args.system} name={run_name} limit={args.limit}", flush=True)

    # ------------------------------------------------------------------
    # Load data
    # ------------------------------------------------------------------
    questions = _load_questions(args.limit)
    gold_map = _load_gold()
    titles = _load_manifest_titles()
    print(f"[data] {len(titles)} manifest titles loaded", flush=True)

    # Annotate gold rows with kind and question for judge use
    for q in questions:
        g = gold_map.get(q["id"])
        if g:
            g["_kind"] = q.get("kind", "")
            g["_question"] = q["question"]

    # Ensure corpus DB is extracted
    if args.system == "retriever-only":
        _ensure_corpus_db()

    # ------------------------------------------------------------------
    # Load checkpoint
    # ------------------------------------------------------------------
    completed_ids, results = _load_checkpoint(run_name)

    # ------------------------------------------------------------------
    # Process each question
    # ------------------------------------------------------------------
    remaining = [q for q in questions if q["id"] not in completed_ids]
    skipped = len(questions) - len(remaining)

    if skipped:
        print(f"[ckpt] Skipping {skipped} already-completed questions", flush=True)

    for idx, q in enumerate(remaining, 1):
        q_id = q["id"]
        gold_row = gold_map.get(q_id)
        print(f"[{idx + skipped}/{len(questions)}] {q_id} ({q.get('kind','?')})", flush=True)

        retriever_results: list[tuple[str, str]] | None = None
        server_result: dict | None = None
        judge_scores: dict | None = None
        answer_text = ""

        if args.system == "retriever-only":
            # BM25 retrieval
            retrieved = retrieve_bm25(q["question"], top_k=8)
            retriever_results = [(d, b) for d, b, _ in retrieved]
            # No answer generated — no judge calls

        elif args.system == "server":
            # Call server chat endpoint
            server_result = call_server_chat(args.base_url, q["question"])
            answer_text = server_result.get("answer", "")

            # Extract context texts from sources for faithfulness judge
            context_texts = [
                s.get("excerpt", "") for s in (server_result.get("sources") or [])
            ]

            # Run judges (sequential per question for simplicity; could be parallelized)
            if answer_text and gold_row is not None:
                judge_scores = run_judges_for_question(
                    q_id, answer_text, context_texts, gold_row, titles,
                )

        row = _make_result_row(
            q, gold_row, titles,
            retriever_results, server_result, judge_scores,
        )
        results.append(row)

        # Brief inline summary
        recalls = row["retrieval"]
        if recalls.get("recall@4") is not None:
            print(
                f"  recall@4={recalls['recall@4']:.3f} "
                f"recall@8={recalls['recall@8']:.3f}",
                flush=True,
            )
        if row.get("citation_accuracy") is not None:
            print(f"  citation_acc={row['citation_accuracy']:.2f}", flush=True)
        if row.get("faithfulness") is not None:
            print(
                f"  faith={row['faithfulness']:.1f} "
                f"quality={row['answer_quality']:.1f}",
                flush=True,
            )
        if row.get("refusal_correctness") is not None:
            print(
                f"  refusal_correctness={row['refusal_correctness']:.1f}",
                flush=True,
            )
        if row.get("server_error"):
            print(f"  ERROR: {row['server_error']}", flush=True)

        # Checkpoint after each question
        completed_ids.add(q_id)
        _save_checkpoint(run_name, completed_ids, results)

    # ------------------------------------------------------------------
    # Write output + cleanup checkpoint
    # ------------------------------------------------------------------
    write_output(run_name, args.system, args.limit, results)
    _cleanup_checkpoint(run_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
