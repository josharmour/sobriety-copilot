#!/usr/bin/env python3
"""FT-B1: Synthetic query→passage pairs for retriever fine-tuning (concurrent).

Generates ≥60k {query, doc_id, block_id} rows into finetune/retriever/pairs.jsonl
by asking dsv4 to write a natural question for each eligible corpus block
(text >= 200 chars).  Uses concurrent workers for throughput.

Usage:
    source venv/bin/activate
    python -m scripts.ft_gen_pairs                          # full run (checkpointed)
    python -m scripts.ft_gen_pairs --resume                 # resume from checkpoint
    python -m scripts.ft_gen_pairs --re-exclude             # re-filter against gold.jsonl
    python -m scripts.ft_gen_pairs --dry-run 200            # test run (200 blocks)
"""

from __future__ import annotations

import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import openai

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from scripts.ft_checks import open_corpus

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
OUT_PATH = _REPO_ROOT / "finetune" / "retriever" / "pairs.jsonl"
CHECKPOINT_PATH = _REPO_ROOT / "finetune" / "retriever" / ".gen_pairs_checkpoint.json"
GOLD_PATH = _REPO_ROOT / "finetune" / "eval" / "gold.jsonl"

LLM_BASE = os.environ.get("LLM_BASE_URL", "http://10.0.0.10:8002/v1")
LLM_MODEL = "deepseek-v4-flash"
API_KEY = "none"

MIN_TEXT_LEN = 200       # eligible blocks: text >= 200 chars
BATCH_SIZE = 25          # blocks per LLM call
NUM_WORKERS = 20         # raised after vLLM max_num_seqs 8->48 (2026-07-08)
SECOND_QUESTION_RATE = 0.10  # 10% of blocks get a second question

REGISTERS = [
    "newcomer — simple, direct language as if a newcomer to recovery is asking. Short sentences. Plain words.",
    "casual — natural recovery-community language, may include common slogans or informal phrasing.",
    "formal — measured, reflective tone as if writing in a journal or asking a counselor for deeper understanding.",
]

random.seed(42)

# Thread-safe lock for writing to the output file
_write_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------


def load_eligible_blocks() -> list[dict]:
    conn = open_corpus()
    rows = conn.execute(
        "SELECT doc_id, block_id, heading, text FROM blocks WHERE length(text) >= ?",
        (MIN_TEXT_LEN,),
    ).fetchall()
    conn.close()
    return [
        {
            "doc_id": r["doc_id"],
            "block_id": r["block_id"],
            "heading": r["heading"] or "",
            "text": r["text"],
        }
        for r in rows
    ]


def load_gold_block_ids() -> set[str]:
    if not GOLD_PATH.is_file():
        return set()
    blocked = set()
    with open(GOLD_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            for bid in row.get("gold_block_ids", []):
                blocked.add(bid)
    return blocked


# ---------------------------------------------------------------------------
# Checkpoint (thread-safe via simple file I/O — rare writes, fine without lock)
# ---------------------------------------------------------------------------

CHECKPOINT_LOCK = threading.Lock()
_global_progress = {"completed_batches": 0, "total_pairs": 0, "total_batches": 0, "done": False}


def _save_cp():
    with CHECKPOINT_LOCK:
        p = _global_progress
        cp = {
            "completed_batches": p["completed_batches"],
            "total_pairs": p["total_pairs"],
            "total_batches": p["total_batches"],
            "done": p["done"],
        }
        CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CHECKPOINT_PATH, "w") as f:
            json.dump(cp, f)


def _load_cp() -> dict:
    if CHECKPOINT_PATH.is_file():
        with open(CHECKPOINT_PATH) as f:
            return json.load(f)
    return {}


# ---------------------------------------------------------------------------
# dsv4 API call (per-worker, uses its own OpenAI client)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are an expert in recovery literature building a training dataset for a retriever model.

Your task: Given a passage from A.A./recovery literature, write a short natural question that:
1. A person in recovery might genuinely ask
2. Is directly answerable from the given passage
3. Does NOT quote the passage verbatim (rephrase the question naturally)
4. Is concise (5-20 words)
5. Uses the register/style indicated below

Output a JSON array of objects, ONE per passage, in the exact same order:
[{"query": "your question here"}, ...]"""


def _call_llm(messages, system, temp=0.7, max_tokens=4096):
    """Call dsv4 and return parsed JSON (thread-safe: creates own client)."""
    client = openai.OpenAI(base_url=LLM_BASE, api_key=API_KEY)
    content = ""
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role": "system", "content": system}, *messages],
                temperature=temp,
                max_tokens=max_tokens,
                # Server defaults thinking:true/effort high — must opt out via
                # chat_template_kwargs or every call burns reasoning tokens.
                extra_body={"chat_template_kwargs": {"thinking": False}},
            )
            content = resp.choices[0].message.content or ""
            if not content.strip():
                time.sleep(1)
                continue

            # Strip markdown code fences
            content = content.strip()
            if content.startswith("```"):
                start = content.find("[")
                if start == -1:
                    start = content.find("{")
                if start >= 0:
                    content = content[start:]
                end = content.rfind("```")
                if end >= 0:
                    content = content[:end]
                content = content.strip()

            return json.loads(content)
        except json.JSONDecodeError:
            if content:
                print(f"  [worker] JSON error, raw: {content[:300]!r}", file=sys.stderr)
            time.sleep(2)
        except Exception as e:
            print(f"  [worker] API error: {e}", file=sys.stderr)
            time.sleep(3)
    return None


def generate_queries(blocks: list[dict], register: str, temp: float = 0.7):
    """Generate queries for a batch of blocks. Returns list of {query, doc_id, block_id}."""
    prompt_lines = [
        f"Register: {register}",
        "",
        "For each passage below, write ONE natural question it answers.",
        "Output a JSON array with one object per passage, same order.",
        "",
    ]
    for i, b in enumerate(blocks):
        heading_info = f"[{b['doc_id']}] {b['heading']}" if b["heading"] else f"[{b['doc_id']}]"
        prompt_lines.append(f"--- Passage {i+1}: {heading_info} ---")
        prompt_lines.append(b["text"][:1000])
        prompt_lines.append("")

    prompt = "\n".join(prompt_lines)
    data = _call_llm(
        [{"role": "user", "content": prompt}],
        _SYSTEM_PROMPT,
        temp=temp,
    )

    if not data or not isinstance(data, list):
        return None

    results = []
    for i, item in enumerate(data):
        q = (item.get("query") or "").strip()
        if q and len(q) >= 5 and i < len(blocks):
            results.append(
                {
                    "query": q,
                    "doc_id": blocks[i]["doc_id"],
                    "block_id": blocks[i]["block_id"],
                }
            )
    return results


# ---------------------------------------------------------------------------
# Re-exclude mode
# ---------------------------------------------------------------------------


def re_exclude_pairs() -> int:
    print("=== Re-exclude mode ===", flush=True)
    gold_block_ids = load_gold_block_ids()
    print(f"Gold block IDs to exclude: {len(gold_block_ids)}", flush=True)

    if not gold_block_ids:
        print("No gold.jsonl found or no blocks listed — nothing to filter.", flush=True)
        return 0

    kept = []
    removed = 0
    with open(OUT_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row["block_id"] in gold_block_ids:
                removed += 1
            else:
                kept.append(row)

    print(f"Removed: {removed}, Kept: {len(kept)}", flush=True)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        for row in kept:
            f.write(json.dumps(row) + "\n")
    print(f"Re-exclude complete. {len(kept)} pairs in {OUT_PATH}", flush=True)
    return len(kept)


# ---------------------------------------------------------------------------
# Worker task
# ---------------------------------------------------------------------------


def _process_batch(
    batch_idx: int,
    blocks: list[dict],
    register: str,
    temp: float,
    second_question_rate: float,
) -> int:
    """Process a single batch and write results. Returns number of pairs written."""
    # First pass: 1 question per block
    results = generate_queries(blocks, register, temp=temp)
    written = 0

    if results is None:
        return 0

    # Write first-pass results
    with _write_lock:
        with open(OUT_PATH, "a") as f:
            for r in results:
                f.write(json.dumps(r) + "\n")
        written += len(results)

    # Second pass: additional questions for a subset
    if second_question_rate > 0 and results:
        second_candidates = [r for r in results if random.random() < second_question_rate]
        if second_candidates:
            conn = open_corpus()
            second_blocks = []
            for r in second_candidates:
                row = conn.execute(
                    "SELECT heading, text FROM blocks WHERE block_id=?",
                    (r["block_id"],),
                ).fetchone()
                if row:
                    second_blocks.append(
                        {
                            "doc_id": r["doc_id"],
                            "block_id": r["block_id"],
                            "heading": row["heading"] or "",
                            "text": row["text"],
                        }
                    )
            conn.close()

            if second_blocks:
                register2 = random.choice([r for r in REGISTERS if r != register])
                results2 = generate_queries(second_blocks, register2, temp=temp + 0.1)
                if results2:
                    with _write_lock:
                        with open(OUT_PATH, "a") as f:
                            for r2 in results2:
                                f.write(json.dumps(r2) + "\n")
                    written += len(results2)

    return written


# ---------------------------------------------------------------------------
# Main generation (concurrent)
# ---------------------------------------------------------------------------


def generate(blocks: list[dict], dry_run: int = 0) -> int:
    gold_block_ids = load_gold_block_ids()
    if gold_block_ids:
        print(f"Gold.jsonl found — {len(gold_block_ids)} blocks excluded", flush=True)
        blocks = [b for b in blocks if b["block_id"] not in gold_block_ids]
        print(f"Eligible after exclusion: {len(blocks)}", flush=True)

    if dry_run:
        blocks = blocks[:dry_run]

    # Resume: skip blocks already processed. Keyed by (doc_id, block_id) —
    # block ids are per-document, so bare ids collide across docs and would
    # mark nearly the whole corpus as "processed".
    existing_count = 0
    if OUT_PATH.is_file() and not dry_run:
        existing_ids = set()
        with open(OUT_PATH) as f:
            for line in f:
                line = line.strip()
                if line:
                    row = json.loads(line)
                    existing_ids.add((row["doc_id"], row["block_id"]))
        existing_count = len(existing_ids)
        blocks = [
            b for b in blocks
            if (b["doc_id"], b["block_id"]) not in existing_ids
        ]
        print(f"Resume: {existing_count} existing, {len(blocks)} remaining", flush=True)

    if not blocks:
        print("All blocks already processed!", flush=True)
        return existing_count

    random.shuffle(blocks)

    # Build batch work items
    batches = []
    for i in range(0, len(blocks), BATCH_SIZE):
        batch_blocks = blocks[i : i + BATCH_SIZE]
        register = random.choice(REGISTERS)
        temp = 0.7 + random.uniform(-0.2, 0.2)
        batches.append((i // BATCH_SIZE, batch_blocks, register, temp))

    total_batches = len(batches)
    _global_progress["total_batches"] = total_batches
    _global_progress["total_pairs"] = existing_count

    print(
        f"Processing {len(blocks)} blocks in {total_batches} batches "
        f"with {NUM_WORKERS} workers",
        flush=True,
    )
    print(f"Second-question rate: {SECOND_QUESTION_RATE:.0%}", flush=True)

    completed_batches = 0
    total_written = existing_count

    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as pool:
        fut_map = {}
        # Submit all batches
        for bidx, batch_blocks, reg, tmp in batches:
            fut = pool.submit(
                _process_batch, bidx, batch_blocks, reg, tmp, SECOND_QUESTION_RATE
            )
            fut_map[fut] = bidx

        # Process as they complete
        for fut in as_completed(fut_map):
            bidx = fut_map[fut]
            try:
                n_written = fut.result()
            except Exception as e:
                print(f"  [batch {bidx}] worker failed: {e}", file=sys.stderr)
                n_written = 0

            completed_batches += 1
            total_written += n_written
            _global_progress["completed_batches"] = completed_batches
            _global_progress["total_pairs"] = total_written
            _save_cp()

            pct = (completed_batches / total_batches) * 100
            print(
                f"  [{completed_batches}/{total_batches} ({pct:.0f}%)] "
                f"+{n_written} → total={total_written}",
                flush=True,
            )

    _global_progress["done"] = True
    _save_cp()
    print(f"\n=== Generation complete: {total_written} pairs ===", flush=True)
    return total_written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="FT-B1: Generate synthetic query→passage pairs")
    ap.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    ap.add_argument(
        "--re-exclude",
        action="store_true",
        help="Re-filter pairs.jsonl against gold.jsonl (no generation)",
    )
    ap.add_argument("--dry-run", type=int, default=0, help="Process only N blocks for testing")

    args = ap.parse_args()

    if args.re_exclude:
        count = re_exclude_pairs()
        print(f"Re-exclude done: {count} pairs", flush=True)
        return 0 if count >= 60000 else 1

    print("FT-B1: Generating synthetic query→passage pairs (concurrent)", flush=True)
    print(f"  LLM: {LLM_BASE} / {LLM_MODEL}", flush=True)
    print(f"  Output: {OUT_PATH}", flush=True)
    print(f"  Batch size: {BATCH_SIZE}, Workers: {NUM_WORKERS}", flush=True)

    blocks = load_eligible_blocks()
    print(f"Loaded {len(blocks)} eligible blocks (text >= {MIN_TEXT_LEN} chars)", flush=True)

    if len(blocks) < 60000:
        print(f"WARNING: only {len(blocks)} eligible blocks", file=sys.stderr)

    total = generate(blocks, dry_run=args.dry_run)

    if total < 60000:
        print(f"WARNING: only {total} pairs (need ≥60k)", file=sys.stderr)
        return 1

    print(f"FT-B1 generation complete: {total} pairs in {OUT_PATH}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
