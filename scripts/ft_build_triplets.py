#!/usr/bin/env python3
"""FT-B2: Build hard-negative triplets from synthetic pairs + BM25 (FTS5).

Reads finetune/retriever/pairs.jsonl (61,699 rows {query, doc_id, block_id}),
for each pair finds the top-4 BM25-hardest negatives via FTS5 MATCH over
finetune/cache/search.db, and writes finetune/retriever/triplets.jsonl
{query, pos_block:{doc_id, block_id, text}, neg_blocks:[4×{doc_id, block_id, text}]}.

Negatives are blocks that:
  - Are NOT the positive block
  - Are NOT within |block_num| <= 2 of the positive in the same doc (adjacent)
  - Rank highest by BM25 among remaining candidates

Checkpointed + resumable.  Progress reported every 1000 pairs.

Usage:
    python -m scripts.ft_build_triplets
    python -m scripts.ft_build_triplets --checkpoint /tmp/triplets_chk.json  # custom path
"""

from __future__ import annotations

import json
import random
import re
import sqlite3
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
PAIRS_PATH = REPO_ROOT / "finetune" / "retriever" / "pairs.jsonl"
OUTPUT_PATH = REPO_ROOT / "finetune" / "retriever" / "triplets.jsonl"
DB_PATH = REPO_ROOT / "finetune" / "cache" / "search.db"
DEFAULT_CHK_PATH = REPO_ROOT / "finetune" / "retriever" / "triplets_checkpoint.json"

# ---------------------------------------------------------------------------
# FTS5 query sanitizer
# ---------------------------------------------------------------------------

_STOP_WORDS: set[str] = {
    "the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or",
    "is", "are", "was", "were", "be", "been", "being", "have", "has",
    "had", "do", "does", "did", "can", "could", "will", "would", "shall",
    "should", "may", "might", "my", "your", "his", "her", "its", "our",
    "their", "me", "you", "he", "she", "it", "we", "they", "this", "that",
    "these", "those", "i", "how", "what", "why", "when", "where", "which",
    "who", "whom", "whose", "not", "no", "nor", "so", "if", "then", "than",
    "too", "very", "just", "but", "as", "up", "down", "out", "off", "over",
    "under", "again", "further", "more", "less", "all", "each", "every",
    "both", "few", "some", "any", "own", "same", "into", "about", "like",
    "through", "during", "before", "after", "between", "such", "only",
    "other", "new", "much", "many", "also", "well", "now", "here", "there",
}

_FTS5_SPECIAL = re.compile(r'["*^()~:+]')


def sanitize_query(raw: str) -> str | None:
    """Convert a natural-language query into an FTS5-safe OR-joined string.

    Returns None if no usable content words remain (query too short after
    sanitization).
    """
    # Strip FTS5 special chars entirely
    cleaned = _FTS5_SPECIAL.sub(" ", raw)
    # Remove remaining punctuation (keep alphanum + spaces)
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    # Lowercase, split
    words = cleaned.lower().split()
    # Filter: len >= 3, not a stop word
    words = [w for w in words if len(w) >= 3 and w not in _STOP_WORDS]
    # Also drop words that look like numbers only
    words = [w for w in words if not w.isdigit()]
    if not words:
        # Fallback: take the first 3 non-trivial tokens from raw query
        # (bypass stop-word filter, just strip FTS5 specials)
        fallback = _FTS5_SPECIAL.sub(" ", raw).strip()
        fallback_words = [
            w.lower() for w in fallback.split()
            if len(w) >= 3 and not w.isdigit()
        ]
        if fallback_words:
            return " OR ".join(fallback_words[:6])
        return None
    # OR-join for broad recall — BM25 ranking will sort relevance
    return " OR ".join(words)


# ---------------------------------------------------------------------------
# Block number extraction
# ---------------------------------------------------------------------------

_BLOCK_NUM_RE = re.compile(r"^b(\d+)$")


def block_num(block_id: str) -> int | None:
    """Extract the numeric suffix from a block_id like 'b00331' → 331."""
    m = _BLOCK_NUM_RE.match(block_id)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------


def build_triplets(checkpoint_path: str | Path = DEFAULT_CHK_PATH,
                   pairs_path: str | Path = PAIRS_PATH,
                   output_path: str | Path | None = None) -> int:
    """Main entry point — checkpointed, resumable."""
    t0 = time.monotonic()
    checkpoint_path = Path(checkpoint_path)
    output_path = Path(output_path) if output_path else OUTPUT_PATH

    # ---- Load pairs -------------------------------------------------------
    print(f"[B2] Loading pairs from {pairs_path} …", flush=True)
    pairs: list[dict] = []
    with open(pairs_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            pairs.append(json.loads(line))
    total = len(pairs)
    print(f"[B2] {total} pairs loaded", flush=True)

    # ---- Load block text dict --------------------------------------------
    print(f"[B2] Loading block texts from {DB_PATH} …", flush=True)
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT doc_id, block_id, text FROM blocks"
    ).fetchall()
    block_text: dict[tuple[str, str], str] = {}
    all_blocks_in_doc: dict[str, set[str]] = {}
    for doc_id, blk_id, text in rows:
        block_text[(doc_id, blk_id)] = text or ""
        all_blocks_in_doc.setdefault(doc_id, set()).add(blk_id)
    conn.close()
    print(f"[B2] {len(block_text)} blocks loaded across "
          f"{len(all_blocks_in_doc)} docs", flush=True)

    # ---- Precompute adjacency maps per doc --------------------------------
    # For each doc, build a set of adjacent block_ids for each block
    # Adjacent = same doc, |block_num diff| <= 2
    print("[B2] Precomputing adjacency maps …", flush=True)
    doc_block_nums: dict[str, dict[int, str]] = {}
    for doc_id, blk_ids in all_blocks_in_doc.items():
        num_map: dict[int, str] = {}
        for blk_id in blk_ids:
            n = block_num(blk_id)
            if n is not None:
                num_map[n] = blk_id
        doc_block_nums[doc_id] = num_map

    def get_adjacent_set(doc_id: str, blk_id: str) -> set[tuple[str, str]]:
        """Return set of (doc_id, block_id) that are adjacent to the given block."""
        n = block_num(blk_id)
        if n is None:
            return {(doc_id, blk_id)}  # can't determine adjacency, just exclude self
        num_map = doc_block_nums.get(doc_id, {})
        adj: set[tuple[str, str]] = set()
        for delta in range(-2, 3):
            neighbor_num = n + delta
            neighbor_id = num_map.get(neighbor_num)
            if neighbor_id is not None:
                adj.add((doc_id, neighbor_id))
        return adj

    # ---- Re-open DB for FTS5 queries -------------------------------------
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.execute("PRAGMA threads=4")

    # ---- Prepare output ---------------------------------------------------
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ---- Resume from checkpoint if exists ---------------------------------
    start_idx = 0
    existing_lines = 0
    if checkpoint_path.exists():
        try:
            chk = json.loads(checkpoint_path.read_text())
            start_idx = chk.get("completed", 0)
            existing_lines = chk.get("written", 0)
            print(f"[B2] Resuming from checkpoint: {start_idx}/{total} pairs "
                  f"completed, {existing_lines} lines written", flush=True)
        except (json.JSONDecodeError, KeyError):
            print("[B2] WARN: corrupt checkpoint, restarting from scratch",
                  file=sys.stderr, flush=True)
            start_idx = 0
            existing_lines = 0
            checkpoint_path.unlink(missing_ok=True)

    # If starting fresh, truncate output
    if start_idx == 0:
        output_path.write_text("")

    out_fh = open(output_path, "a") if start_idx > 0 else open(output_path, "w")
    write_count = existing_lines

    # ---- Stats ------------------------------------------------------------
    stats = {
        "total_pairs": total,
        "sufficient_negatives": 0,
        "insufficient_negatives": 0,
        "skipped_no_query": 0,
        "total_negatives_written": 0,
    }

    # ---- Main loop --------------------------------------------------------
    print(f"[B2] Building triplets …", flush=True)
    for idx, pair in enumerate(pairs):
        if idx < start_idx:
            continue

        query = pair["query"]
        pos_doc = pair["doc_id"]
        pos_block = pair["block_id"]
        pos_key = (pos_doc, pos_block)

        # Sanitize query for FTS5
        sanitized = sanitize_query(query)
        if sanitized is None:
            stats["skipped_no_query"] += 1
            # Write a triplet with a fallback: use random blocks as negatives
            # This is extremely rare; skip for now
            continue

        # ---- BM25 search --------------------------------------------------
        # LIMIT 25 is sufficient: we need 4 non-excluded candidates after
        # removing positive + up to 5 adjacent blocks.
        try:
            cur = conn.execute(
                "SELECT doc_id, block_id, rank "
                "FROM blocks WHERE blocks MATCH ? "
                "ORDER BY rank LIMIT 25",
                (sanitized,),
            )
            candidates = cur.fetchall()
        except sqlite3.OperationalError as e:
            # FTS5 syntax error — try simpler (word-by-word)
            print(f"[B2] WARN: FTS error on idx {idx}: {e}", flush=True)
            simple_words = [w for w in sanitized.replace(" OR ", " ").split()
                           if len(w) >= 3]
            if simple_words:
                try:
                    cur = conn.execute(
                        "SELECT doc_id, block_id, rank "
                        "FROM blocks WHERE blocks MATCH ? "
                        "ORDER BY rank LIMIT 25",
                        (" OR ".join(simple_words),),
                    )
                    candidates = cur.fetchall()
                except sqlite3.OperationalError:
                    candidates = []
            else:
                candidates = []

        # ---- Filter --------------------------------------------------------
        # 1. Remove positive block
        # 2. Remove adjacent blocks (same doc, |block_num| <= 2)
        adj_set = get_adjacent_set(pos_doc, pos_block)
        excluded = {pos_key} | adj_set

        neg_candidates: list[tuple[str, str, float]] = []
        for doc_id, blk_id, score in candidates:
            if (doc_id, blk_id) not in excluded:
                neg_candidates.append((doc_id, blk_id, score))

        # If < 4 after strict filtering, try a broader search (more candidates)
        if len(neg_candidates) < 4:
            try:
                cur = conn.execute(
                    "SELECT doc_id, block_id, rank "
                    "FROM blocks WHERE blocks MATCH ? "
                    "ORDER BY rank LIMIT 100",
                    (sanitized,),
                )
                broader = cur.fetchall()
                seen = {(d, b) for d, b, _ in neg_candidates}
                for d, b, s in broader:
                    if (d, b) not in excluded and (d, b) not in seen and len(neg_candidates) < 4:
                        neg_candidates.append((d, b, s))
                        seen.add((d, b))
            except sqlite3.OperationalError:
                pass

        # If < 4 after filtering, fall through to the random-padding step.
        # We do NOT relax adjacency here — that would violate the spec.

        # If STILL < 4, pad with random blocks from other docs
        if len(neg_candidates) < 4:
            # Get all keys not excluded
            all_keys = list(block_text.keys())
            random.shuffle(all_keys)
            existing_set = {(d, b) for d, b, _ in neg_candidates}
            excluded_full = excluded | existing_set
            for key in all_keys:
                if key not in excluded_full and len(neg_candidates) < 4:
                    neg_candidates.append((key[0], key[1], -999.0))
                    excluded_full.add(key)

        # ---- Build output row ----------------------------------------------
        pos_text = block_text.get(pos_key, "")
        negs = []
        for nd, nb, ns in neg_candidates[:4]:
            nt = block_text.get((nd, nb), "")
            negs.append({"doc_id": nd, "block_id": nb, "text": nt})

        if len(negs) < 4:
            stats["insufficient_negatives"] += 1
        else:
            stats["sufficient_negatives"] += 1
        stats["total_negatives_written"] += len(negs)

        row = {
            "query": query,
            "pos_block": {
                "doc_id": pos_doc,
                "block_id": pos_block,
                "text": pos_text,
            },
            "neg_blocks": negs,
        }
        out_fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        out_fh.flush()
        write_count += 1

        # ---- Checkpoint ---------------------------------------------------
        if (idx + 1) % 1000 == 0:
            chk = {"completed": idx + 1, "written": write_count}
            checkpoint_path.write_text(json.dumps(chk))
            elapsed = time.monotonic() - t0
            rate = (idx + 1 - start_idx) / max(1e-6, elapsed)
            eta = (total - (idx + 1)) / max(1e-6, rate)
            print(
                f"[B2] {idx+1}/{total}  {rate:.0f}/s  "
                f"eta {eta/60:.1f}m  negs_ok={stats['sufficient_negatives']}"
                f"  negs_short={stats['insufficient_negatives']}",
                flush=True,
            )

    # ---- Cleanup -----------------------------------------------------------
    out_fh.close()
    conn.close()

    # Save final checkpoint
    chk = {"completed": total, "written": write_count}
    checkpoint_path.write_text(json.dumps(chk))

    # ---- Report ------------------------------------------------------------
    elapsed = time.monotonic() - t0
    print(f"\n[B2] Done in {elapsed/60:.1f}m", flush=True)
    print(f"     Pairs processed: {total}", flush=True)
    print(f"     Triplets written: {write_count}", flush=True)
    print(f"     Sufficient negs (≥4): {stats['sufficient_negatives']}", flush=True)
    print(f"     Insufficient negs (<4): {stats['insufficient_negatives']}", flush=True)
    print(f"     Skipped (no query): {stats['skipped_no_query']}", flush=True)
    print(f"     Total negs written: {stats['total_negatives_written']}", flush=True)

    if stats["insufficient_negatives"] > 0:
        print(
            f"  WARN: {stats['insufficient_negatives']} rows have <4 negatives "
            "(see ft_checks for details)",
            flush=True,
        )

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="FT-B2: Build hard-negative triplets")
    ap.add_argument("--checkpoint", default=str(DEFAULT_CHK_PATH),
                    help=f"Checkpoint path (default: {DEFAULT_CHK_PATH})")
    ap.add_argument("--pairs", default=str(PAIRS_PATH))
    ap.add_argument("--output", default=None)
    args = ap.parse_args()
    raise SystemExit(build_triplets(checkpoint_path=args.checkpoint,
                                    pairs_path=args.pairs,
                                    output_path=args.output))
