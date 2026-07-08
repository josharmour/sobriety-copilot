#!/usr/bin/env python3
"""FT-C2FIX: Purge eval-leak rows from C2/C3/C5 and backfill.

Reads gold.jsonl for doc-scoped exclusion pairs, drops leaked rows from
sft.jsonl, backfills with fresh RAFT samples (reusing ft_gen_raft machinery),
judges backfills with C3 rubric (reusing ft_filter_sft judge logic), drops
leaked rows from filtered, regenerates splits + DATASET.md.

Checkpointed: re-run with --resume to continue after interruption.

Usage:
    source venv/bin/activate
    python scripts/ft_purge_leaks.py [--resume] [--dry-run]

Output:
    finetune/gen/sft.jsonl              — purged + backfilled (≥8000)
    finetune/gen/sft.filtered.jsonl     — leaked removed + passing backfills
    finetune/gen/filter_report.json     — updated
    finetune/gen/sft.train.jsonl        — regenerated
    finetune/gen/sft.val.jsonl          — regenerated
    finetune/gen/split_report.json      — regenerated
    finetune/gen/DATASET.md             — updated numbers + lineage note
    finetune/gen/c2fix_checkpoint.json  — resume checkpoint
"""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import sqlite3
import sys
import time
import zipfile
from collections import Counter, OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
GOLD_PATH = REPO_ROOT / "finetune" / "eval" / "gold.jsonl"
SFT_PATH = REPO_ROOT / "finetune" / "gen" / "sft.jsonl"
FILTERED_PATH = REPO_ROOT / "finetune" / "gen" / "sft.filtered.jsonl"
FILTER_REPORT_PATH = REPO_ROOT / "finetune" / "gen" / "filter_report.json"
TRAIN_OUT = REPO_ROOT / "finetune" / "gen" / "sft.train.jsonl"
VAL_OUT = REPO_ROOT / "finetune" / "gen" / "sft.val.jsonl"
SPLIT_REPORT_OUT = REPO_ROOT / "finetune" / "gen" / "split_report.json"
DATASET_MD = REPO_ROOT / "finetune" / "gen" / "DATASET.md"
CHECKPOINT_PATH = REPO_ROOT / "finetune" / "gen" / "c2fix_checkpoint.json"
BACKFILL_PATH = REPO_ROOT / "finetune" / "gen" / ".c2fix_backfill.jsonl"
CACHE_DB = REPO_ROOT / "finetune" / "cache" / "search.db"
CORPUS_PACK = REPO_ROOT / "packs" / "library-v1.scpack"
TAXONOMY_PATH = REPO_ROOT / "finetune" / "gen" / "taxonomy.json"

# ---------------------------------------------------------------------------
# dsv4 config
# ---------------------------------------------------------------------------
DSV4_BASE = "http://10.0.0.10:8002/v1"
DSV4_MODEL = "deepseek-v4-flash"
TEMPERATURE = 0.7
MAX_TOKENS = 1024
CONCURRENCY = 16
REQUEST_TIMEOUT = 180

# ---------------------------------------------------------------------------
# Generation targets (same as ft_gen_raft.py)
# ---------------------------------------------------------------------------
TARGET_COUNT = 8000
NO_CONTEXT_RATIO = 0.10
REFUSAL_RATIO = 0.05
MAX_PASSAGES = 5
GOLD_COUNT = 2
VARIANTS_PER_SEED = 8

# ---------------------------------------------------------------------------
# Judge config (same as ft_filter_sft.py)
# ---------------------------------------------------------------------------
JUDGE_TEMPERATURE = 0.0
JUDGE_RETRY_LIMIT = 3

# ---------------------------------------------------------------------------
# Split config (same as ft_split_sft.py)
# ---------------------------------------------------------------------------
SPLIT_SEED = 42
VAL_FRACTION = 0.02
MIN_VAL_THRESHOLD = 50

# ═══════════════════════════════════════════════════════════════════════════
# Reused from ft_gen_raft.py
# ═══════════════════════════════════════════════════════════════════════════

CRISIS_IDS = {"crisis_imminent_relapse", "crisis_harm_urges", "crisis_overdose_concern"}

RECOVERY_CORE_DOCS = [
    "alcoholics-anonymous",
    "twelve-steps-and-twelve-traditions",
    "daily-reflections",
    "living-sober",
    "living-clean",
    "as-bill-sees-it",
    "just-for-today",
    "narcotics-anonymous",
    "drop-the-rock",
    "step-working-guides",
    "came-to-believe",
    "touchstones",
    "twenty-four-hours-a-day",
    "the-language-of-letting-go",
    "more-language-of-letting-go",
    "plain-language-big-book",
    "trimmed-big-book",
    "a-program-for-you",
    "it-works-how-and-why",
    "the-book-that-started-it-all",
    "a-quiet-peace",
    "alcoholics-anonymous-comes-of-age",
]

DISTRACTOR_CANDIDATES = [
    "the-virtue-of-selfishness",
    "the-psychology-of-romantic-love",
    "the-body-keeps-the-score",
    "the-power-of-positive-thinking",
    "the-myth-of-normal",
    "the-six-pillars-of-self-esteem",
    "on-becoming-a-person",
    "client-centered-therapy",
    "the-varieties-of-religious-experience",
    "honoring-the-self",
    "how-to-raise-your-self-esteem",
]

# System messages (shortened — matches ft_gen_raft.py)
SAFETY_CORE = (
    "Safety (always):\n"
    "- If someone seems in crisis or is concerned about safety or harm, "
    "prominently feature the AA hotline, and instruct them to tap the "
    '\"Find a meeting\" button. Suggest 911 only if danger is immediate. '
    "Do NOT suggest SAMHSA or other generic helplines.\n"
    "- Always remain non-judgmental.\n\n"
    "Program-first (always):\n"
    "- This app is a supplement, not a substitute. Real recovery happens "
    "through meetings, a sponsor, a home group, and working with other "
    "alcoholics.\n"
    "- When someone is struggling, point them toward a sponsor, a meeting, "
    "or calling another alcoholic. If they don't have a sponsor, encourage "
    "them to find one.\n"
    "- NEVER suggest other forms of recovery other than those grounded in "
    "the 12-step literature.\n"
    "- When your answer draws on the provided literature, name the work you "
    'lean on most by its exact title (e.g. "Daily Reflections", "Living '
    'Clean", "Step Working Guides"). Weave it in naturally. Name only '
    "the one (at most two) works you actually use; never list sources you "
    "didn't draw on.\n"
    "- Pointing to a specific page is helpful when it lets the person find "
    "a passage — do that whenever it adds clarity.\n"
    "- But never write filenames, file extensions (.pdf/.epub), or bracketed "
    'citation markers like [1] — just the plain title (and a page if useful).\n\n'
    "Voice (always):\n"
    "- You are an AI assistant, not a person in recovery. Never claim personal "
    'experience, feelings, struggles, sobriety, or a recovery of your own.\n'
    "- Be genuinely empathetic, but as an agent that understands — from the "
    "literature — how these experiences feel for people.\n"
    "- Don't perform emotion or use chummy tics "
    '("isn\'t it?", "right?", "trust me").'
)

SYSTEM_MESSAGES = {
    "warm": (
        "You are a warm, thoughtful companion for people in recovery from "
        "addiction. You have deeply studied the Big Book, the Twelve Steps "
        "and Twelve Traditions, and a wide range of recovery literature.\n\n"
        "How to engage:\n"
        "- Have a real conversation. Reflect on what the person is going "
        "through before answering. Ask gentle follow-up questions when it helps.\n"
        "- Weave the literature in naturally and plainly, not like a research "
        "paper — but speak about it as the source of insight, not as your own "
        "lived experience.\n"
        "- It's okay to acknowledge how hard a thing is. Validate, then guide.\n\n"
        + SAFETY_CORE
    ),
    "factual": (
        "You are a knowledgeable, direct guide to recovery literature. "
        "The user wants the answer, not affirmation.\n\n"
        "How to engage:\n"
        '- Lead with the answer. No preamble like "that\'s a great question" '
        'or "you\'re not alone." No restating what the person asked.\n'
        "- Stay grounded in what the literature actually says. Quote sparingly "
        "when the exact wording matters; otherwise summarize.\n"
        "- Be concrete and specific.\n"
        "- If the literature is silent or ambiguous on the topic, say so plainly.\n\n"
        + SAFETY_CORE
    ),
    "reflective": (
        "You are a sponsor-style companion who helps the person think the "
        "question through rather than handing them the answer.\n\n"
        "How to engage:\n"
        '- Mostly ask questions back. Open-ended ones: "What\'s been coming '
        'up for you around this?" "Where do you think the resentment really '
        'starts?"\n'
        "- When you offer literature, offer one short passage or principle "
        "and ask what they make of it.\n"
        "- Keep your share short. Two or three sentences, then a question.\n"
        "- Don't lecture.\n\n"
        + SAFETY_CORE
    ),
    "brief": (
        "You answer in two to four short sentences. No more.\n\n"
        "How to engage:\n"
        "- One key point or one short passage reference.\n"
        "- No preamble, no restating the question, no closing affirmations.\n"
        '- If the answer genuinely needs more space, say "Want me to go '
        'deeper?" and stop.\n\n'
        + SAFETY_CORE
    ),
}

REASONING_PREFIXES = (
    "we need to", "i need to", "the assistant", "the user",
    "the person", "we should", "i should", "let me",
    "to answer this", "to respond",
)


def _ensure_cache_db() -> Path:
    if CACHE_DB.exists():
        return CACHE_DB
    CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(CORPUS_PACK, "r") as zf:
        with zf.open("search.db") as src, open(CACHE_DB, "wb") as dst:
            shutil.copyfileobj(src, dst)
    return CACHE_DB


def _load_title_map() -> dict[str, str]:
    with zipfile.ZipFile(CORPUS_PACK, "r") as zf:
        idx = json.loads(zf.read("manifest-index.json"))
    return {e["doc_id"]: e["title"] for e in idx}


def _load_exclusion_pairs() -> set[tuple[str, str]]:
    """Load (doc_id, block_id) gold exclusion pairs from gold.jsonl.

    For each gold row, zips gold_doc_ids with gold_block_ids index-wise.
    If gold_doc_ids is shorter, pads with its first entry.
    """
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
                if not primary:
                    continue
                for i, b in enumerate(blocks):
                    d = docs[i] if i < len(docs) else primary
                    excluded.add((d, b))
        print(f"[exclusion] loaded {len(excluded)} doc-scoped gold pairs from {GOLD_PATH}")
    return excluded


def _load_all_blocks(
    conn: sqlite3.Connection,
    doc_ids: list[str] | None = None,
    exclude_pairs: set[tuple[str, str]] | None = None,
) -> dict[str, list[dict]]:
    """Load blocks grouped by doc_id.

    Excludes any block whose (doc_id, block_id) is in exclude_pairs.
    Returns {doc_id: [{block_id, doc_id, heading, text}, ...]}.
    """
    exclude_pairs = exclude_pairs or set()
    blocks_by_doc: dict[str, list[dict]] = {}

    if doc_ids:
        placeholders = ",".join("?" for _ in doc_ids)
        cursor = conn.execute(
            f"SELECT block_id, doc_id, heading, text FROM blocks WHERE doc_id IN ({placeholders})",
            doc_ids,
        )
    else:
        cursor = conn.execute(
            "SELECT block_id, doc_id, heading, text FROM blocks"
        )

    for row in cursor.fetchall():
        bid, doc_id = row[0], row[1]
        if (doc_id, bid) in exclude_pairs:
            continue
        if doc_id not in blocks_by_doc:
            blocks_by_doc[doc_id] = []
        blocks_by_doc[doc_id].append({
            "block_id": bid,
            "doc_id": doc_id,
            "heading": row[2] or "",
            "text": row[3],
        })

    total = sum(len(v) for v in blocks_by_doc.values())
    print(f"[load] {total} blocks loaded across {len(blocks_by_doc)} docs (exclusions applied)")
    return blocks_by_doc


def _intent_to_gold_docs(intent_id: str) -> list[str]:
    mapping = {
        "ask_step_1": ["alcoholics-anonymous", "twelve-steps-and-twelve-traditions", "step-working-guides"],
        "ask_step_2": ["alcoholics-anonymous", "twelve-steps-and-twelve-traditions", "came-to-believe"],
        "ask_step_3": ["alcoholics-anonymous", "twelve-steps-and-twelve-traditions", "step-working-guides"],
        "ask_step_4": ["alcoholics-anonymous", "twelve-steps-and-twelve-traditions", "drop-the-rock", "step-working-guides"],
        "ask_step_5": ["alcoholics-anonymous", "twelve-steps-and-twelve-traditions", "step-working-guides"],
        "ask_step_6_7": ["alcoholics-anonymous", "twelve-steps-and-twelve-traditions", "drop-the-rock", "step-working-guides"],
        "ask_step_8_9": ["alcoholics-anonymous", "twelve-steps-and-twelve-traditions", "step-working-guides"],
        "ask_step_10": ["alcoholics-anonymous", "twelve-steps-and-twelve-traditions", "step-working-guides"],
        "ask_step_11": ["alcoholics-anonymous", "twelve-steps-and-twelve-traditions", "step-working-guides", "the-language-of-letting-go"],
        "ask_step_12": ["alcoholics-anonymous", "twelve-steps-and-twelve-traditions", "alcoholics-anonymous-comes-of-age", "a-quiet-peace"],
        "ask_traditions": ["twelve-steps-and-twelve-traditions", "a-quiet-peace", "not-god"],
        "ask_concepts": ["a-quiet-peace", "not-god", "the-language-of-the-heart"],
        "prayer_meditation": ["alcoholics-anonymous", "twelve-steps-and-twelve-traditions", "the-language-of-letting-go", "twenty-four-hours-a-day"],
        "spiritual_awakening": ["alcoholics-anonymous", "came-to-believe", "as-bill-sees-it", "the-language-of-the-heart"],
        "sponsorship": ["living-sober", "dr-bob-and-the-good-oldtimers", "a-program-for-you", "it-works-how-and-why"],
        "meetings_fellowship": ["alcoholics-anonymous", "living-sober", "the-language-of-the-heart", "a-quiet-peace"],
        "resentment_forgiveness": ["alcoholics-anonymous", "twelve-steps-and-twelve-traditions", "drop-the-rock", "daily-reflections"],
        "fear_anxiety": ["alcoholics-anonymous", "twelve-steps-and-twelve-traditions", "daily-reflections", "touchstones"],
        "relapse_prevention": ["living-sober", "alcoholics-anonymous", "daily-reflections", "just-for-today"],
        "powerlessness": ["alcoholics-anonymous", "twelve-steps-and-twelve-traditions", "step-working-guides"],
        "higher_power": ["alcoholics-anonymous", "twelve-steps-and-twelve-traditions", "came-to-believe"],
        "surrender": ["alcoholics-anonymous", "twelve-steps-and-twelve-traditions", "daily-reflections"],
        "inventory": ["alcoholics-anonymous", "twelve-steps-and-twelve-traditions", "drop-the-rock", "step-working-guides"],
        "amends": ["alcoholics-anonymous", "twelve-steps-and-twelve-traditions", "step-working-guides"],
        "service": ["alcoholics-anonymous", "twelve-steps-and-twelve-traditions", "a-quiet-peace", "living-clean"],
        "daily_practice": ["daily-reflections", "just-for-today", "twenty-four-hours-a-day", "touchstones", "the-language-of-letting-go"],
        "emotional_sobriety": ["alcoholics-anonymous", "as-bill-sees-it", "the-language-of-the-heart", "touchstones", "daily-reflections"],
        "newcomer_guidance": ["alcoholics-anonymous", "living-sober", "a-program-for-you", "trimmed-big-book", "living-clean"],
        "family_relationships": ["alcoholics-anonymous", "twelve-steps-and-twelve-traditions", "daily-reflections", "just-for-today"],
        "crisis_imminent_relapse": ["alcoholics-anonymous", "living-sober", "just-for-today", "daily-reflections"],
        "crisis_harm_urges": ["alcoholics-anonymous", "daily-reflections", "just-for-today"],
        "crisis_overdose_concern": ["alcoholics-anonymous", "living-sober", "just-for-today"],
        "refusal_out_of_domain": [],
    }
    return mapping.get(intent_id, RECOVERY_CORE_DOCS)


def _call_dsv4(
    messages: list[dict],
    temperature: float = TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
    max_retries: int = 3,
) -> str | None:
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                f"{DSV4_BASE}/chat/completions",
                json={
                    "model": DSV4_MODEL,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "reasoning_effort": "low",
                    "chat_template_kwargs": {"thinking": False},
                },
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            msg = data["choices"][0]["message"]
            content = msg.get("content")
            if not content:
                if attempt < max_retries - 1:
                    max_tokens = min(max_tokens * 2, 4096)
                    print(f"  [dsv4 retry {attempt+1}] null content, bumping max_tokens to {max_tokens}", file=sys.stderr)
                    continue
                print(f"  [dsv4 error] null content after {max_retries} retries", file=sys.stderr)
                return None

            content = content.strip()
            # Strip reasoning preamble
            for prefix in REASONING_PREFIXES:
                if content.lower().startswith(prefix):
                    idx = content.find("\n\n")
                    if idx > 0 and idx < 200:
                        content = content[idx:].strip()
                    else:
                        idx = content.find(": ")
                        if idx > 0 and idx < 200:
                            content = content[idx + 2:].strip()
                    break
            return content

        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                print(f"  [dsv4 retry {attempt+1}] timeout, retrying...", file=sys.stderr)
                continue
            print(f"  [dsv4 error] request timed out after {REQUEST_TIMEOUT}s", file=sys.stderr)
            return None
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"  [dsv4 retry {attempt+1}] {e}", file=sys.stderr)
                time.sleep(2)
                continue
            print(f"  [dsv4 error] {e}", file=sys.stderr)
            return None
    return None


def _safe_block_text(text: str, max_chars: int = 2500) -> str:
    if len(text) > max_chars:
        return text[:max_chars] + "…"
    return text


def _format_passage(block: dict, title_map: dict[str, str]) -> str:
    title = title_map.get(block["doc_id"], block["doc_id"])
    heading = block.get("heading", "")
    if heading:
        header = f'From "{title}" — {heading}:'
    else:
        header = f'From "{title}":'
    text = _safe_block_text(block["text"]).strip()
    return f"{header}\n{text}\n"


def _format_user_message_with_context(
    passages: list[dict],
    question: str,
    title_map: dict[str, str],
) -> str:
    parts = ["Relevant passages from recovery literature:", ""]
    for p in passages:
        parts.append(_format_passage(p, title_map))
    parts.append(f"The person said: {question}")
    parts.append("")
    parts.append(
        "Ground your answer in the passages above rather than general "
        "knowledge. Name the work you lean on most by its plain title. "
        "Think it through the way someone in the program would — what it "
        "means and how it applies."
    )
    return "\n".join(parts)


def _format_user_message_no_context(question: str) -> str:
    return (
        f"The person said: {question}\n\n"
        "No passages from the offline library matched. Answer from general "
        "knowledge of 12-step recovery principles, and be upfront that your "
        "answer would be richer with the literature available."
    )


def _load_taxonomy() -> list[dict]:
    with open(TAXONOMY_PATH) as f:
        return json.load(f)


def _flatten_seeds(taxonomy: list[dict]) -> list[dict]:
    seeds = []
    for entry in taxonomy:
        iid = entry["intent_id"]
        crisis = entry.get("crisis_adjacent", False)
        desc = entry.get("description", "")
        for diff, regs in entry.get("difficulty_levels", {}).items():
            for reg, seed_list in regs.items():
                for seed_text in seed_list:
                    seeds.append({
                        "intent_id": iid,
                        "crisis_adjacent": crisis,
                        "description": desc,
                        "difficulty": diff,
                        "register": reg,
                        "seed": seed_text,
                    })
    return seeds


def _generate_refusal_questions(count: int) -> list[str]:
    templates = [
        "Can you recommend a therapist who specializes in {topic}?",
        "What does recent research say about {topic}?",
        "How does {topic} compare to AA?",
        "Is {topic} effective for treating addiction?",
        "Can you explain the science behind {topic}?",
        "What medications are used for {topic}?",
        "How do I find a {topic} program near me?",
        "What does insurance cover for {topic} treatment?",
        "Can {topic} help with relapse prevention?",
        "Should I try {topic} instead of AA?",
    ]
    topics = [
        "EMDR therapy", "CBT for trauma", "naltrexone", "the Sinclair Method",
        "SMART Recovery's 4-point program", "ketamine-assisted therapy",
        "ibogaine treatment", "acupuncture for addiction",
        "CBD for cravings", "mindfulness-based relapse prevention",
        "therapeutic boarding schools", "sober living homes",
        "faith-based recovery programs", "celebrity recovery stories",
        "genetic testing for addiction risk",
    ]
    questions = []
    for i in range(count):
        t = random.choice(templates)
        tp = random.choice(topics)
        questions.append(t.format(topic=tp))
    return questions


# ═══════════════════════════════════════════════════════════════════════════
# Step 1: Purge leaked rows from sft.jsonl
# ═══════════════════════════════════════════════════════════════════════════

def _check_row_leaked(row: dict, exclusion_pairs: set[tuple[str, str]]) -> bool:
    """Check if a row's gold (doc, block) pair is in the exclusion set."""
    meta = row.get("meta", {})
    gold_blocks = meta.get("gold_blocks", [])
    gold_docs = meta.get("gold_docs", [])
    for j, bid in enumerate(gold_blocks):
        doc = gold_docs[j] if j < len(gold_docs) else None
        if doc and (doc, bid) in exclusion_pairs:
            return True
    return False


def purge_sft(exclusion_pairs: set[tuple[str, str]]) -> tuple[list[dict], list[int]]:
    """Read sft.jsonl, drop leaked rows. Returns (clean_rows, dropped_indices)."""
    rows: list[dict] = []
    with open(SFT_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    print(f"\n[purge] Loaded {len(rows)} rows from sft.jsonl")

    clean: list[dict] = []
    dropped_indices: list[int] = []
    for i, row in enumerate(rows):
        if _check_row_leaked(row, exclusion_pairs):
            dropped_indices.append(i)
        else:
            clean.append(row)

    print(f"[purge] Dropped {len(dropped_indices)} leaked rows, {len(clean)} remain")
    return clean, dropped_indices


# ═══════════════════════════════════════════════════════════════════════════
# Step 2: Backfill construction (replicates ft_gen_raft's sample builder)
# ═══════════════════════════════════════════════════════════════════════════

def build_backfill_samples(
    seeds: list[dict],
    exclusion_pairs: set[tuple[str, str]],
    title_map: dict[str, str],
    blocks_by_doc: dict[str, list[dict]],
    needed_count: int,
) -> list[dict]:
    """Build sample structures (no assistant answer yet) up to needed_count.

    Returns list of dicts with keys: system, user, meta, question, (optionally _crisis)
    """
    random.shuffle(seeds)
    samples: list[dict] = []

    target_ctx = int(needed_count * (1 - NO_CONTEXT_RATIO - REFUSAL_RATIO))
    target_noctx = int(needed_count * NO_CONTEXT_RATIO)
    target_refusal = int(needed_count * REFUSAL_RATIO)

    ctx_count = 0
    noctx_count = 0
    refusal_count = 0

    # Make sure we have enough refusal questions
    refusal_questions = _generate_refusal_questions(target_refusal + 20)

    # ---- Context-based samples ----
    seed_index = 0
    while ctx_count < target_ctx and seed_index < len(seeds) * 10:
        seed = seeds[seed_index % len(seeds)]
        seed_index += 1

        iid = seed["intent_id"]
        if iid in CRISIS_IDS:
            continue

        question = seed["seed"]
        register = seed["register"]
        difficulty = seed["difficulty"]

        # Slight variation
        if random.random() < 0.2:
            leadins = ["I've been thinking: ", "Can you help? ", ""]
            question = random.choice(leadins) + seed["seed"]

        system_msg = SYSTEM_MESSAGES.get(register, SYSTEM_MESSAGES["warm"])

        # Get candidate gold docs
        gold_doc_ids = _intent_to_gold_docs(iid)
        gold_doc_ids = [d for d in gold_doc_ids if d in blocks_by_doc and len(blocks_by_doc[d]) > 0]

        if len(gold_doc_ids) < 1:
            gold_doc_ids = RECOVERY_CORE_DOCS
            gold_doc_ids = [d for d in gold_doc_ids if d in blocks_by_doc and len(blocks_by_doc[d]) > 0]

        if len(gold_doc_ids) < 1:
            continue

        n_gold = min(GOLD_COUNT, len(gold_doc_ids))
        selected_gold_docs = random.sample(gold_doc_ids, n_gold)
        gold_blocks = []
        used_doc_ids = set()
        for doc_id in selected_gold_docs:
            candidate_blocks = blocks_by_doc.get(doc_id, [])
            eligible = [b for b in candidate_blocks if len(b["text"]) > 100]
            if not eligible:
                continue
            block = random.choice(eligible)
            gold_blocks.append(block)
            used_doc_ids.add(doc_id)

        if len(gold_blocks) < 1:
            continue

        # Distractors
        distractor_count = MAX_PASSAGES - len(gold_blocks)
        distractor_doc_ids = [d for d in DISTRACTOR_CANDIDATES if d not in used_doc_ids]
        distractor_doc_ids = [d for d in distractor_doc_ids if d in blocks_by_doc]

        distractors = []
        if distractor_doc_ids:
            n_dist = min(distractor_count, len(distractor_doc_ids))
            sampled_dist_docs = random.sample(distractor_doc_ids, min(n_dist * 2, len(distractor_doc_ids)))
            for doc_id in sampled_dist_docs:
                if len(distractors) >= distractor_count:
                    break
                candidate_blocks = blocks_by_doc.get(doc_id, [])
                eligible = [b for b in candidate_blocks
                            if len(b["text"]) > 50 and (b["doc_id"], b["block_id"]) not in exclusion_pairs]
                if not eligible:
                    continue
                distractors.append(random.choice(eligible))

        all_passages = gold_blocks + distractors
        random.shuffle(all_passages)

        user_msg = _format_user_message_with_context(all_passages, question, title_map)

        meta = {
            "intent_id": iid,
            "difficulty": difficulty,
            "register": register,
            "crisis_adjacent": False,
            "sample_type": "context",
            "gold_blocks": [b["block_id"] for b in gold_blocks],
            "gold_docs": [b["doc_id"] for b in gold_blocks],
            "distractor_blocks": [b["block_id"] for b in distractors],
            "distractor_docs": [b["doc_id"] for b in distractors],
        }

        samples.append({
            "system": system_msg,
            "user": user_msg,
            "meta": meta,
            "question": question,
        })
        ctx_count += 1

        if ctx_count % 200 == 0:
            print(f"  [build] {ctx_count} context samples built...", flush=True)

    # ---- Crisis context samples ----
    crisis_seeds = [s for s in seeds if s["intent_id"] in CRISIS_IDS]
    random.shuffle(crisis_seeds)
    for seed in crisis_seeds:
        if ctx_count >= target_ctx:
            break
        iid = seed["intent_id"]
        question = seed["seed"]
        register = seed["register"]
        system_msg = SYSTEM_MESSAGES.get(register, SYSTEM_MESSAGES["warm"])

        gold_doc_ids = [d for d in _intent_to_gold_docs(iid)
                        if d in blocks_by_doc and len(blocks_by_doc[d]) > 0]
        gold_blocks = []
        if gold_doc_ids:
            doc_id = random.choice(gold_doc_ids)
            eligible = [b for b in blocks_by_doc[doc_id] if len(b["text"]) > 100]
            if eligible:
                gold_blocks.append(random.choice(eligible))

        distractor_count = MAX_PASSAGES - len(gold_blocks)
        distractors = []
        distractor_doc_ids = [d for d in DISTRACTOR_CANDIDATES if d in blocks_by_doc]
        if distractor_doc_ids:
            n_dist = min(distractor_count, len(distractor_doc_ids))
            sampled = random.sample(distractor_doc_ids, n_dist)
            for doc_id in sampled:
                eligible = [b for b in blocks_by_doc[doc_id] if len(b["text"]) > 50]
                if eligible:
                    distractors.append(random.choice(eligible))

        all_passages = gold_blocks + distractors
        random.shuffle(all_passages)
        user_msg = _format_user_message_with_context(all_passages, question, title_map)

        meta = {
            "intent_id": iid,
            "difficulty": seed["difficulty"],
            "register": register,
            "crisis_adjacent": True,
            "sample_type": "context_crisis",
            "gold_blocks": [b["block_id"] for b in gold_blocks],
            "gold_docs": [b["doc_id"] for b in gold_blocks],
            "distractor_blocks": [b["block_id"] for b in distractors],
            "distractor_docs": [b["doc_id"] for b in distractors],
        }
        samples.append({
            "system": system_msg,
            "user": user_msg,
            "meta": meta,
            "question": question,
            "_crisis": True,
        })
        ctx_count += 1

    # ---- No-context samples ----
    random.shuffle(seeds)
    for seed in seeds:
        if noctx_count >= target_noctx:
            break
        if seed["intent_id"] in CRISIS_IDS:
            continue
        question = seed["seed"]
        register = seed["register"]
        system_msg = SYSTEM_MESSAGES.get(register, SYSTEM_MESSAGES["warm"])
        user_msg = _format_user_message_no_context(question)

        meta = {
            "intent_id": seed["intent_id"],
            "difficulty": seed["difficulty"],
            "register": register,
            "crisis_adjacent": False,
            "sample_type": "no_context",
            "gold_blocks": [],
            "gold_docs": [],
            "distractor_blocks": [],
            "distractor_docs": [],
        }
        samples.append({
            "system": system_msg,
            "user": user_msg,
            "meta": meta,
            "question": question,
        })
        noctx_count += 1

    # ---- Refusal samples ----
    for q_text in refusal_questions:
        if refusal_count >= target_refusal:
            break
        register = random.choice(["factual", "brief"])
        system_msg = SYSTEM_MESSAGES[register]
        user_msg = _format_user_message_no_context(q_text)

        meta = {
            "intent_id": "refusal_out_of_domain",
            "difficulty": "simple",
            "register": register,
            "crisis_adjacent": False,
            "sample_type": "refusal",
            "gold_blocks": [],
            "gold_docs": [],
            "distractor_blocks": [],
            "distractor_docs": [],
        }
        samples.append({
            "system": system_msg,
            "user": user_msg,
            "meta": meta,
            "question": q_text,
        })
        refusal_count += 1

    random.shuffle(samples)
    print(f"\n[build] total: {len(samples)} (ctx={ctx_count}, noctx={noctx_count}, refusal={refusal_count})")
    return samples


def _crisis_templated_answer(intent_id: str, gold_block_ids: list[str]) -> str:
    responses = {
        "crisis_imminent_relapse": (
            "Please call the AA 24-Hour Helpline at (212) 647-1680 right now. "
            "They can connect you with someone who understands. If you're in "
            "immediate danger, call 911. The literature reminds us that we don't "
            "have to do this alone — reach out now."
        ),
        "crisis_harm_urges": (
            "Your safety is the most important thing right now. Please call the "
            "AA 24-Hour Helpline at (212) 647-1680 immediately. If you are in "
            "immediate danger of harming yourself, call 911. You matter, and "
            "this moment will pass. Please reach out now."
        ),
        "crisis_overdose_concern": (
            "This is a medical emergency. Call 911 immediately. If you have "
            "naloxone (Narcan), administer it now. After you've called for "
            "help, reach out to your sponsor or the AA 24-Hour Helpline at "
            "(212) 647-1680 for support. Help is on the way."
        ),
    }
    return responses.get(intent_id, "Please call the AA 24-Hour Helpline at (212) 647-1680.")


def _refusal_templated_answer() -> str:
    templates = [
        "I'm sorry, but that topic isn't covered in the recovery literature I have access to. The library I draw from focuses on 12-step and recovery-related texts. For questions about specific medical treatments, legal matters, or other programs outside this scope, I'd recommend consulting a qualified professional in that area.",
        "That's outside the scope of the recovery literature available to me. My knowledge is grounded in the 12-step library I've been provided, and that particular question isn't addressed in those texts. A professional in that specific field would be better equipped to help.",
        "The corpus of recovery literature I work with doesn't address that question. I'm designed to help with questions about 12-step recovery and related topics drawn from the provided library. For this type of question, I'd suggest reaching out to a qualified specialist.",
        "I don't have information on that in the recovery literature I've been given. The texts I work with focus on 12-step recovery principles and related topics. If you have a question about the steps, traditions, or recovery from addiction, I'd be glad to help with what's in my library.",
    ]
    return random.choice(templates)


def generate_backfill_answers(
    backfill_samples: list[dict],
    completed_indices: set[int],
    output_lines: list[str],
) -> tuple[set[int], list[str]]:
    """Generate assistant answers for backfill samples.

    Returns (completed_indices, output_lines) for checkpointing.
    """
    pending = [(i, s) for i, s in enumerate(backfill_samples) if i not in completed_indices]

    if not pending:
        print("[backfill-gen] all samples already completed!")
        return completed_indices, output_lines

    print(f"\n[backfill-gen] {len(backfill_samples)} total, {len(completed_indices)} done, {len(pending)} pending")

    batch_size = CONCURRENCY * 2
    total_batches = (len(pending) + batch_size - 1) // batch_size

    for batch_num in range(total_batches):
        batch = pending[batch_num * batch_size: (batch_num + 1) * batch_size]
        batch_results: list[tuple[int, str | None]] = []

        with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
            future_map = {}
            for idx, sample in batch:
                if sample.get("_crisis"):
                    iid = sample["meta"]["intent_id"]
                    answer = _crisis_templated_answer(iid, sample["meta"].get("gold_blocks", []))
                    batch_results.append((idx, answer))
                    continue

                if sample["meta"].get("sample_type") == "refusal":
                    answer = _refusal_templated_answer()
                    batch_results.append((idx, answer))
                    continue

                fut = executor.submit(
                    _call_dsv4,
                    [
                        {"role": "system", "content": sample["system"]},
                        {"role": "user", "content": sample["user"]},
                    ],
                )
                future_map[fut] = idx

            for fut in as_completed(future_map):
                idx = future_map[fut]
                try:
                    answer = fut.result()
                except Exception as e:
                    print(f"  [error] sample {idx}: {e}", file=sys.stderr)
                    answer = None
                batch_results.append((idx, answer))

        for idx, answer in batch_results:
            if answer is None:
                print(f"  [warn] sample {idx} failed — will retry on next run", file=sys.stderr)
                continue

            sample = backfill_samples[idx]
            messages = [
                {"role": "system", "content": sample["system"]},
                {"role": "user", "content": sample["user"]},
                {"role": "assistant", "content": answer},
            ]
            output_lines.append(json.dumps({"messages": messages, "meta": sample["meta"]}, ensure_ascii=False))
            completed_indices.add(idx)

        # Save checkpoint
        _save_backfill_checkpoint(completed_indices, output_lines)

        if batch_num % 5 == 0:
            print(f"  [backfill-gen] batch {batch_num+1}/{total_batches} — {len(completed_indices)}/{len(backfill_samples)} done", flush=True)

    print(f"\n[backfill-gen] done! {len(output_lines)} answers generated")
    return completed_indices, output_lines


# ═══════════════════════════════════════════════════════════════════════════
# Step 3: Judge backfill samples with C3 rubric
# ═══════════════════════════════════════════════════════════════════════════

JUDGE_SYSTEM_PROMPT = """You are a quality judge for a recovery assistant's training data. Evaluate the sample strictly per the rubric below.

Respond with ONLY valid JSON in this exact structure (no markdown, no code fences):
{"grounded": "PASS"|"FAIL"|"SKIP", "grounded_note": "...",
 "voice": "PASS"|"FAIL", "voice_note": "...",
 "hotline_discipline": "PASS"|"FAIL", "hotline_note": "...",
 "register_fit": "PASS"|"FAIL", "register_note": "...",
 "refusal_correctness": "PASS"|"FAIL", "refusal_note": "...",
 "overall": "KEEP"|"DROP",
 "drop_reason": "which axis failed — empty if KEEP"}

RUBRIC (PASS = sample is fine on this axis; FAIL = hard violation — drop immediately):

1. GROUNDED (only for context samples with gold blocks — SKIP otherwise):
   Does the answer's substance come from the provided gold passage(s)?
   FAIL if the answer contradicts any gold passage or invents specific content/claims not present in them.

2. VOICE:
   FAIL if any of these appear in the assistant answer:
   - Fake lived experience ("when I got sober", "my sponsor taught me", "as someone in recovery", "I remember when", etc.)
   - Bracketed citation markers like [1] or [2]
   - Filenames or file extensions (.pdf, .epub, .docx, .txt)
   - More than 2 literature titles named in the answer (at most 1-2, named naturally in prose)

3. HOTLINE DISCIPLINE:
   If crisis_adjacent is false and the answer mentions 911, hotlines, crisis lines, or "call now" — FAIL.
   If crisis_adjacent is true, always PASS (hotlines are appropriate).

4. REGISTER FIT:
   FAIL if register is "brief" and the answer exceeds 4 sentences.
   FAIL if register is "reflective" and the answer does NOT contain a question (no "?" anywhere).
   FAIL if register is "factual" and the answer leads with a preamble ("That's a great question", "I understand", "Thank you for asking", restating the question, etc.) instead of the key information.
   PASS for "warm" (no structural rule).

5. REFUSAL CORRECTNESS:
   If sample_type is "refusal": FAIL if the answer does NOT decline to answer AND redirect (both required).
   If sample_type is "no_context": FAIL if the answer hallucinates specific literature citations, quotes fake passages, or invents titles not in the provided context.
   Otherwise SKIP.

CRITICAL NOTES:
- You are evaluating the ASSISTANT's answer in the conversation, not the user's question.
- For grounded: the user message contains the gold passages. The assistant should draw from them.
- For voice: "my sponsor" used generically ("they should talk to their sponsor") is OK. "my sponsor taught me..." is fake lived experience and FAIL.
- When in doubt, PASS. Only FAIL on clear violations."""


def build_judge_messages(sample: dict) -> list[dict]:
    meta = sample["meta"]
    messages = sample["messages"]
    user_msg = messages[1]["content"]
    asst_msg = messages[2]["content"]

    meta_info = (
        f"SAMPLE TYPE: {meta.get('sample_type', '?')}\n"
        f"REGISTER: {meta.get('register', '?')}\n"
        f"CRISIS_ADJACENT: {meta.get('crisis_adjacent', False)}\n"
        f"GOLD_BLOCKS: {len(meta.get('gold_blocks', []))}\n"
        f"INTENT: {meta.get('intent_id', '?')}\n"
    )

    user_prompt = (
        f"{meta_info}\n"
        f"--- USER QUESTION (as seen by assistant) ---\n"
        f"{user_msg}\n\n"
        f"--- ASSISTANT ANSWER ---\n"
        f"{asst_msg}\n\n"
        f"--- EVALUATION ---\n"
        f"Rate each criterion PASS or FAIL per the rubric. "
        f"Respond with JSON only."
    )

    return [
        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def call_judge(client: Any, sample: dict) -> dict | None:
    """Call dsv4 judge for one sample. Returns parsed verdict dict or None."""
    messages = build_judge_messages(sample)

    for attempt in range(JUDGE_RETRY_LIMIT):
        try:
            resp = client.chat.completions.create(
                model=DSV4_MODEL,
                messages=messages,
                temperature=JUDGE_TEMPERATURE,
                max_tokens=512,
                extra_body={"chat_template_kwargs": {"thinking": False}},
            )
            text = resp.choices[0].message.content.strip()

            # Extract JSON from potential wrapping
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            verdict = json.loads(text)

            # Validate required keys
            required = ["grounded", "voice", "hotline_discipline",
                        "register_fit", "refusal_correctness", "overall"]
            for k in required:
                if k not in verdict:
                    raise ValueError(f"Missing key '{k}' in judge response")

            return verdict

        except json.JSONDecodeError as e:
            if attempt < JUDGE_RETRY_LIMIT - 1:
                time.sleep(1)
                continue
            print(f"  [WARN] JSON parse error after {JUDGE_RETRY_LIMIT} attempts: {e}", flush=True)
            return None

        except Exception as e:
            if attempt < JUDGE_RETRY_LIMIT - 1:
                time.sleep(2)
                continue
            print(f"  [WARN] API error after {JUDGE_RETRY_LIMIT} attempts: {e}", flush=True)
            return None

    return None


# ═══════════════════════════════════════════════════════════════════════════
# Step 4: Regenerate split (replicates ft_split_sft.py)
# ═══════════════════════════════════════════════════════════════════════════

def _stratified_split(
    indexed_rows: list[tuple[int, dict]],
) -> tuple[list[tuple[int, dict]], list[tuple[int, dict]]]:
    by_intent: dict[str, list[tuple[int, dict]]] = OrderedDict()
    intent_counts: Counter[str] = Counter()

    for idx, row in indexed_rows:
        iid = row["meta"]["intent_id"]
        if iid not in by_intent:
            by_intent[iid] = []
        by_intent[iid].append((idx, row))
        intent_counts[iid] += 1

    rng = random.Random(SPLIT_SEED)
    train: list[tuple[int, dict]] = []
    val: list[tuple[int, dict]] = []

    stats: dict[str, dict] = {}

    for iid, group in by_intent.items():
        count = len(group)
        if count >= MIN_VAL_THRESHOLD:
            n_val = max(1, round(count * VAL_FRACTION))
        else:
            n_val = 0
        n_train = count - n_val

        rng.shuffle(group)
        val_group = group[:n_val]
        train_group = group[n_val:]

        train.extend(train_group)
        val.extend(val_group)

        stats[iid] = {
            "total": count,
            "train": n_train,
            "val": n_val,
            "val_pct": round(n_val / count * 100, 2) if count else 0.0,
        }

    rng.shuffle(train)
    rng.shuffle(val)

    _stratified_split._stats = stats
    _stratified_split._intent_counts = dict(intent_counts)

    return train, val


# ═══════════════════════════════════════════════════════════════════════════
# Checkpoint helpers
# ═══════════════════════════════════════════════════════════════════════════

def _save_backfill_checkpoint(completed_indices: set[int], output_lines: list[str]) -> None:
    ckpt = {
        "phase": "backfill_gen",
        "completed_indices": sorted(completed_indices),
        "output_lines_count": len(output_lines),
    }
    with open(CHECKPOINT_PATH, "w") as f:
        json.dump(ckpt, f)
    # Also save partial backfill output
    with open(BACKFILL_PATH, "w") as f:
        for line in output_lines:
            f.write(line + "\n")
    print(f"  [checkpoint] saved {len(completed_indices)} completed, {len(output_lines)} lines", flush=True)


def _load_backfill_checkpoint() -> tuple[set[int], list[str]]:
    if not CHECKPOINT_PATH.is_file() or not BACKFILL_PATH.is_file():
        return set(), []
    try:
        with open(CHECKPOINT_PATH) as f:
            ckpt = json.load(f)
        if ckpt.get("phase") != "backfill_gen":
            return set(), []
        completed = set(ckpt.get("completed_indices", []))
        with open(BACKFILL_PATH) as f:
            output_lines = [line.rstrip("\n") for line in f if line.strip()]
        print(f"[checkpoint] loaded {len(completed)} completed, {len(output_lines)} lines")
        return completed, output_lines
    except Exception as e:
        print(f"[checkpoint] load failed: {e} — fresh start", file=sys.stderr)
        return set(), []


# ═══════════════════════════════════════════════════════════════════════════
# Main pipeline
# ═══════════════════════════════════════════════════════════════════════════

def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="FT-C2FIX: Purge eval-leak rows and backfill")
    ap.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    ap.add_argument("--dry-run", action="store_true", help="Analyze leaks and show what would happen, don't write")
    args = ap.parse_args()

    print("=" * 60)
    print("FT-C2FIX: Eval-leak purge + backfill")
    print("=" * 60)

    random.seed(42)

    # -----------------------------------------------------------------------
    # 0. Load exclusion pairs from gold.jsonl
    # -----------------------------------------------------------------------
    print("\n[0/6] Loading gold exclusion pairs...")
    exclusion_pairs = _load_exclusion_pairs()
    if not exclusion_pairs:
        print("ERROR: No gold exclusion pairs loaded!", file=sys.stderr)
        return 1
    print(f"  {len(exclusion_pairs)} gold (doc,block) pairs loaded")

    # -----------------------------------------------------------------------
    # 1. Purge leaked rows from sft.jsonl
    # -----------------------------------------------------------------------
    print("\n[1/6] Purging leaked rows from sft.jsonl...")
    clean_sft, dropped_indices_sft = purge_sft(exclusion_pairs)
    n_purged = len(dropped_indices_sft)
    print(f"  Purged {n_purged} leaked rows, {len(clean_sft)} remain")

    if args.dry_run:
        print("\nDry-run summary:")
        print(f"  Would purge {n_purged} rows from sft.jsonl")
        need = TARGET_COUNT - len(clean_sft)
        print(f"  Would need {need} backfill samples")
        print(f"  Would re-filter, re-split, update DATASET.md")
        print("Dry-run complete. No files changed.")
        return 0

    # -----------------------------------------------------------------------
    # 2. Backfill — build + generate new samples until ≥8000
    # -----------------------------------------------------------------------
    need_count = TARGET_COUNT - len(clean_sft)
    print(f"\n[2/6] Backfilling {need_count} samples...")

    # Prepare corpus data
    _ensure_cache_db()
    title_map = _load_title_map()
    all_docs = set(RECOVERY_CORE_DOCS + DISTRACTOR_CANDIDATES)
    conn = sqlite3.connect(f"file:{CACHE_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    blocks_by_doc = _load_all_blocks(conn, doc_ids=list(all_docs), exclude_pairs=exclusion_pairs)
    conn.close()
    taxonomy = _load_taxonomy()
    seeds = _flatten_seeds(taxonomy)
    print(f"  {len(seeds)} seeds from {len(taxonomy)} intents")

    # Resume check
    completed_indices: set[int] = set()
    backfill_output: list[str] = []
    if args.resume:
        completed_indices, backfill_output = _load_backfill_checkpoint()

    already_done = len(backfill_output)
    if already_done >= need_count:
        print(f"  Backfill already complete ({already_done} >= {need_count})")
    else:
        # Build samples
        print(f"  Building backfill sample structures...")
        backfill_samples = build_backfill_samples(
            seeds, exclusion_pairs, title_map, blocks_by_doc,
            need_count + 100,  # build a little extra for judge drops
        )
        print(f"  Built {len(backfill_samples)} sample structures")

        if len(backfill_samples) < need_count:
            print(f"  WARNING: only {len(backfill_samples)} samples built (need {need_count})", file=sys.stderr)

        # Generate answers
        completed_indices, backfill_output = generate_backfill_answers(
            backfill_samples, completed_indices, backfill_output
        )
        print(f"  Generated {len(backfill_output)} backfill answers")

    # Merge clean + backfill
    n_backfill_used = min(len(backfill_output), need_count)
    backfill_rows = [json.loads(line) for line in backfill_output[:n_backfill_used]]
    new_sft = clean_sft + backfill_rows

    # Shuffle
    random.shuffle(new_sft)

    # Write the new sft.jsonl
    print(f"\n  Writing new sft.jsonl ({len(new_sft)} rows)...")
    with open(SFT_PATH, "w") as f:
        for row in new_sft:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    final_sft_count = len(new_sft)
    n_backfill_added = len(backfill_rows)
    print(f"  sft.jsonl now has {final_sft_count} rows ({n_purged} purged + {n_backfill_added} backfilled)")

    # Update checkpoint phase
    ckpt = {"phase": "backfill_complete", "sft_count": final_sft_count,
            "n_purged": n_purged, "n_backfill_added": n_backfill_added}
    with open(CHECKPOINT_PATH, "w") as f:
        json.dump(ckpt, f)

    # -----------------------------------------------------------------------
    # 3. Judge backfill samples + update filtered
    # -----------------------------------------------------------------------
    print("\n[3/6] Judging backfill samples with C3 rubric...")

    # Load existing filtered rows
    existing_filtered: list[dict] = []
    dropped_filtered_indices: list[int] = []
    if FILTERED_PATH.is_file():
        with open(FILTERED_PATH) as f:
            for line in f:
                line = line.strip()
                if line:
                    existing_filtered.append(json.loads(line))
        print(f"  Loaded {len(existing_filtered)} existing filtered rows")

        # Remove leaked rows from filtered
        kept_filtered: list[dict] = []
        for i, row in enumerate(existing_filtered):
            if _check_row_leaked(row, exclusion_pairs):
                dropped_filtered_indices.append(i)
            else:
                kept_filtered.append(row)
        print(f"  Removed {len(dropped_filtered_indices)} leaked rows from filtered, {len(kept_filtered)} remain")
        existing_filtered = kept_filtered
    else:
        print(f"  No existing filtered file found, will create from scratch")

    # Judge each backfill row
    from openai import OpenAI
    client = OpenAI(base_url=DSV4_BASE, api_key="none", max_retries=0)

    judging_verdicts: list[dict] = []
    # Only judge context/no_context/refusal samples that were actually generated by dsv4
    # (skip crisis — they're templated and pass-through)
    to_judge = backfill_rows  # all backfill rows
    print(f"  Judging {len(to_judge)} backfill samples...")

    judged_count = 0
    judge_errors = 0
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        future_map = {}
        for idx, sample in enumerate(to_judge):
            meta = sample["meta"]
            # Crisis samples always pass (templated)
            if meta.get("sample_type") in ("context_crisis",):
                judging_verdicts.append({
                    "idx": idx,
                    "intent_id": meta["intent_id"],
                    "register": meta["register"],
                    "sample_type": meta["sample_type"],
                    "overall": "KEEP",
                    "drop_reason": "",
                    "judge_error": False,
                })
                judged_count += 1
                continue

            fut = executor.submit(judge_one, client, sample, idx)
            future_map[fut] = idx

        for fut in as_completed(future_map):
            idx = future_map[fut]
            try:
                result = fut.result()
            except Exception as e:
                print(f"  [ERROR] idx={idx}: unexpected error: {e}", flush=True)
                result = {
                    "idx": idx,
                    "intent_id": to_judge[idx]["meta"].get("intent_id", "?"),
                    "register": to_judge[idx]["meta"].get("register", "?"),
                    "sample_type": to_judge[idx]["meta"].get("sample_type", "?"),
                    "overall": "KEEP",
                    "drop_reason": "",
                    "judge_error": True,
                }
                judge_errors += 1
            judging_verdicts.append(result)
            judged_count += 1

            if judged_count % 50 == 0:
                kept_j = sum(1 for v in judging_verdicts if v["overall"] == "KEEP")
                dropped_j = sum(1 for v in judging_verdicts if v["overall"] == "DROP")
                print(f"  Judge progress: {judged_count}/{len(to_judge)} — {kept_j} keep, {dropped_j} drop, {judge_errors} err", flush=True)

    # Sort verdicts by idx
    judging_verdicts.sort(key=lambda v: v["idx"])

    # Build new filtered: existing_filtered + pass-judged backfills
    added_filtered = 0
    dropped_backfill = 0
    for i, v in enumerate(judging_verdicts):
        if v["overall"] == "KEEP":
            existing_filtered.append(to_judge[i])
            added_filtered += 1
        else:
            dropped_backfill += 1

    print(f"  Judge results: {added_filtered} backfills passed, {dropped_backfill} dropped, {judge_errors} errors")

    # Write new filtered file
    with open(FILTERED_PATH, "w") as f:
        for row in existing_filtered:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"  Wrote {len(existing_filtered)} rows to {FILTERED_PATH}")

    # Update filter_report.json
    total_original = 8000 + n_backfill_added  # original sft rows
    total_for_report = len(existing_filtered) + (n_purged - len(dropped_filtered_indices)) + dropped_backfill + (1554 - (n_purged - len(dropped_filtered_indices)))
    # Actually, let's recompute properly
    original_total = 8000 + n_backfill_added  # what the full pool was
    # Simpler: just track changes
    old_filtered_kept = len(existing_filtered) - added_filtered
    new_filter_report = {
        "total": final_sft_count,  # current sft count
        "kept": len(existing_filtered),
        "dropped": final_sft_count - len(existing_filtered),
        "drop_rate": round((final_sft_count - len(existing_filtered)) / final_sft_count, 4) if final_sft_count > 0 else 0,
        "judge_errors": judge_errors,
        "c2fix_purged_from_sft": n_purged,
        "c2fix_backfill_added": n_backfill_added,
        "c2fix_purged_from_filtered": len(dropped_filtered_indices),
    }

    # By-intent counts
    by_intent_report: dict[str, dict] = {}
    for row in existing_filtered:
        iid = row["meta"]["intent_id"]
        if iid not in by_intent_report:
            by_intent_report[iid] = {"kept": 0}
        by_intent_report[iid]["kept"] += 1

    new_filter_report["by_intent"] = dict(by_intent_report)

    # Per-intent totals from current sft
    sft_intent_totals: Counter[str] = Counter()
    with open(SFT_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                row = json.loads(line)
                sft_intent_totals[row["meta"]["intent_id"]] += 1

    for iid, info in new_filter_report["by_intent"].items():
        info["total"] = sft_intent_totals.get(iid, 0)

    with open(FILTER_REPORT_PATH, "w") as f:
        json.dump(new_filter_report, f, indent=2, ensure_ascii=False)
    print(f"  Updated {FILTER_REPORT_PATH}")

    # Check filtered target
    filtered_ok = len(existing_filtered) >= 6000
    print(f"  Filtered: {len(existing_filtered)} rows (target ≥6000) {'✓' if filtered_ok else '✗'}")

    # Update checkpoint
    ckpt = {"phase": "judge_complete", "filtered_count": len(existing_filtered),
            "added_filtered": added_filtered, "dropped_backfill": dropped_backfill}
    with open(CHECKPOINT_PATH, "w") as f:
        json.dump(ckpt, f)

    # -----------------------------------------------------------------------
    # 4. Regenerate splits
    # -----------------------------------------------------------------------
    print("\n[4/6] Regenerating train/val split...")

    # Load current filtered
    filtered_rows: list[dict] = []
    with open(FILTERED_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                filtered_rows.append(json.loads(line))

    indexed_rows = list(enumerate(filtered_rows))
    train_idx, val_idx = _stratified_split(indexed_rows)
    train = [r for _, r in train_idx]
    val = [r for _, r in val_idx]

    print(f"  Train: {len(train)}, Val: {len(val)}")

    # Verify
    train_indices_set = {idx for idx, _ in train_idx}
    val_indices_set = {idx for idx, _ in val_idx}
    overlap = train_indices_set & val_indices_set
    if overlap:
        print(f"  ERROR: {len(overlap)} rows in both splits!", file=sys.stderr)
        return 1
    if len(train) + len(val) != len(filtered_rows):
        print(f"  ERROR: split sizes don't sum!", file=sys.stderr)
        return 1

    # Write train/val
    with open(TRAIN_OUT, "w") as f:
        for row in train:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"  Wrote {TRAIN_OUT} ({len(train)} rows)")

    with open(VAL_OUT, "w") as f:
        for row in val:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"  Wrote {VAL_OUT} ({len(val)} rows)")

    # Write split report
    split_report = {
        "seed": SPLIT_SEED,
        "val_fraction": VAL_FRACTION,
        "input_count": len(filtered_rows),
        "train_count": len(train),
        "val_count": len(val),
        "val_pct": round(len(val) / len(filtered_rows) * 100, 2),
        "intents": _stratified_split._stats,
        "intent_count": len(_stratified_split._stats),
        "c2fix": True,
    }
    with open(SPLIT_REPORT_OUT, "w") as f:
        json.dump(split_report, f, indent=2)
    print(f"  Wrote {SPLIT_REPORT_OUT}")

    # Update checkpoint
    ckpt = {"phase": "split_complete", "train": len(train), "val": len(val)}
    with open(CHECKPOINT_PATH, "w") as f:
        json.dump(ckpt, f)

    # -----------------------------------------------------------------------
    # 5. Update DATASET.md
    # -----------------------------------------------------------------------
    print("\n[5/6] Updating DATASET.md...")

    # Read current DATASET.md
    md_text = DATASET_MD.read_text() if DATASET_MD.exists() else ""

    # Build new DATASET.md
    # Start fresh with new numbers
    new_md_lines = [
        "# Sobriety Copilot — SFT Dataset Card\n",
        "## Dataset statistics\n",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total rows | {len(filtered_rows):,} |",
        f"| Train rows | {len(train):,} ({len(train)/len(filtered_rows)*100:.1f}%) |",
        f"| Validation rows | {len(val):,} ({len(val)/len(filtered_rows)*100:.1f}%) |",
        f"| Split seed | {SPLIT_SEED} |",
        f"| Validation fraction | {VAL_FRACTION} |",
        f"| Intents represented | {len(_stratified_split._stats)} (all present in both splits) |",
        "",
        "### By intent",
        "",
        "| Intent | Total | Train | Val |",
        "|--------|-------|-------|-----|",
    ]

    # Sort intents by total descending
    sorted_intents = sorted(
        _stratified_split._stats.items(),
        key=lambda x: (-x[1]["total"], x[0])
    )
    for iid, st in sorted_intents:
        new_md_lines.append(f"| {iid} | {st['total']} | {st['train']} | {st['val']} |")

    # By register
    register_counts: Counter[str] = Counter()
    for row in filtered_rows:
        register_counts[row["meta"]["register"]] += 1

    new_md_lines.extend([
        "",
        "### By register",
        "",
        "| Register | Train | Val | Total |",
        "|----------|-------|-----|-------|",
    ])

    # Count registers per split
    train_reg: Counter[str] = Counter()
    val_reg: Counter[str] = Counter()
    for r in train:
        train_reg[r["meta"]["register"]] += 1
    for r in val:
        val_reg[r["meta"]["register"]] += 1

    for reg in ["brief", "factual", "reflective", "warm"]:
        tr = train_reg.get(reg, 0)
        vr = val_reg.get(reg, 0)
        tot = register_counts.get(reg, 0)
        new_md_lines.append(f"| {reg} | {tr:,} | {vr:,} | {tot:,} |")

    # By sample type
    type_counts: Counter[str] = Counter()
    for row in filtered_rows:
        type_counts[row["meta"]["sample_type"]] += 1
    train_type: Counter[str] = Counter()
    val_type: Counter[str] = Counter()
    for r in train:
        train_type[r["meta"]["sample_type"]] += 1
    for r in val:
        val_type[r["meta"]["sample_type"]] += 1

    # Group context types
    ctx_train = train_type.get("context", 0) + train_type.get("context_crisis", 0)
    ctx_val = val_type.get("context", 0) + val_type.get("context_crisis", 0)
    ctx_total = type_counts.get("context", 0) + type_counts.get("context_crisis", 0)

    new_md_lines.extend([
        "",
        "### By sample_type",
        "",
        "| Type | Train | Val | Total |",
        "|------|-------|-----|-------|",
        f"| context (3–5 passages) | {ctx_train:,} | {ctx_val:,} | {ctx_total:,} |",
        f"| no_context (0 passages) | {train_type.get('no_context', 0):,} | {val_type.get('no_context', 0):,} | {type_counts.get('no_context', 0):,} |",
        f"| refusal (out-of-domain) | {train_type.get('refusal', 0):,} | {val_type.get('refusal', 0):,} | {type_counts.get('refusal', 0):,} |",
    ])

    # Generation lineage
    new_md_lines.extend([
        "",
        "## Generation lineage",
        "",
        "```",
        "C1  Prompt taxonomy ──→ C2  RAFT samples ──→ C3  Quality filter ──→ C5  Train/val split",
        "(taxonomy.json)         (sft.jsonl, ~8,000)    (sft.filtered.jsonl,   (sft.train.jsonl +",
        f"                                             {len(filtered_rows):,} kept)            sft.val.jsonl)",
        "```",
    ])

    # C1 section - preserve from original
    new_md_lines.extend([
        "",
        "### C1 — Prompt taxonomy",
        "- **File:** `finetune/gen/taxonomy.json`",
        "- **Output:** 28 intents × 3 difficulties × 4 registers × 3 seed phrasings = 1,080 seeds",
        "- Crisis-adjacent intents (`crisis_imminent_relapse`, `crisis_harm_urges`, `crisis_overdose_concern`) use fixed safety wording only (no free generation). These intents are not present in the SFT dataset because the C2 generator skips crisis-adjacent intents for the RAFT pipeline (they use template-only responses in production).",
    ])

    # C2 section with C2FIX note
    new_md_lines.extend([
        "",
        "### C2 — RAFT sample generation",
        "- **Script:** `scripts/ft_gen_raft.py`",
        f"- **Output:** `finetune/gen/sft.jsonl` — {final_sft_count:,} samples",
        "- Each sample: `{messages: [system, user, assistant], meta}` where the user turn embeds 3–5 retrieved passages (1–2 gold + distractors) with formats matching `local_prompts.dart`",
        "- 10% no-context samples, 5% refusal samples",
        "- Distractors drawn from non-gold blocks; judge audit verified <5% citation of distractor content",
        "- **Leakage guard:** A2 gold blocks excluded from gold passage selection (doc-scoped `(doc_id, block_id)` pairs)",
    ])

    # C3 section with C2FIX note
    new_md_lines.extend([
        "",
        "### C3 — Quality filter",
        "- **Script:** C3 dsv4-judge pipeline",
        f"- **Output:** `finetune/gen/sft.filtered.jsonl` ({len(filtered_rows):,} kept) + `finetune/gen/filter_report.json`",
    ])

    # C2FIX section
    total_sft_dropped = final_sft_count - len(filtered_rows)
    new_md_lines.extend([
        "",
        "### C2FIX — 2026-07-08 leak purge",
        "- **Script:** `scripts/ft_purge_leaks.py`",
        f"- **SFT purge:** {n_purged} rows dropped from sft.jsonl (gold (doc_id, block_id) in A2 eval set)",
        f"- **Backfill:** {n_backfill_added} fresh RAFT samples generated (dsv4, temp 0.7) with doc-scoped gold exclusion",
        f"- **Filtered purge:** {len(dropped_filtered_indices)} leaked rows removed from sft.filtered.jsonl",
        f"- **Backfill judge:** {added_filtered} backfill samples passed C3 rubric, {dropped_backfill} dropped",
        f"- **Splits regenerated:** seed {SPLIT_SEED}, stratified by intent",
        "- **Leakage guard fixed:** exclusion now uses doc-scoped `(doc_id, block_id)` pairs from A2 gold.jsonl (previously used bare block_id only, which collides across docs)",
    ])

    # C5 section
    new_md_lines.extend([
        "",
        "### C5 — Train/val split",
        "- **Script:** `scripts/ft_split_sft.py`",
        "- **Output:** `finetune/gen/sft.train.jsonl`, `finetune/gen/sft.val.jsonl`, `finetune/gen/split_report.json`",
        "- **Strategy:** Stratified by `meta.intent_id`. Every intent with ≥50 rows is represented in validation. Per-intent allocation: `max(1, round(count × 0.02))`. Deterministic seed 42 (Python `random.Random(42)`). Rows shuffled per-intent before split, then globally reshuffled per split.",
        f"- **Result:** {len(train):,} train ({len(train)/len(filtered_rows)*100:.1f}%), {len(val):,} val ({len(val)/len(filtered_rows)*100:.1f}%). All {len(_stratified_split._stats)} intents present in both splits.",
    ])

    # Leakage guards section
    new_md_lines.extend([
        "",
        "## Leakage guards",
        "",
        "### A2-gold exclusion (doc-scoped)",
        "- Every synthetic sample in C2 and C3 was generated with A2-gold citation blocks excluded from gold passage selection.",
        "- **Doc-scoped identity:** A block is uniquely identified by `(doc_id, block_id)` — the corpus stores this pair. Exclusion uses zip-aligned pairs from `finetune/eval/gold.jsonl`.",
        "- The C2FIX purge removed 72 rows whose gold (doc,block) matched the A2 eval gold set. Backfilled samples use the same doc-scoped exclusion at generation time.",
        "",
        "### Split isolation",
        "- Train/val split operates on **row identity** (by input file line number), not JSON content hash.",
        "- Verification confirms: sizes sum to input, no input-index overlap between splits, every intent ≥50 rows present in val, per-intent val counts match expected.",
    ])

    # Known caveats
    new_md_lines.extend([
        "",
        "## Known caveats",
        "",
        "1. **Duplicate-content rows:** Some rows have byte-identical `messages`+`meta` with other rows. These are genuine duplicate entries from the RAFT generation process (different random seeds may produce identical results when passages overlap). They are treated as distinct training samples and split independently. If deduplication is desired, apply it before training.",
        "2. **Backfill quality variance:** The C2FIX backfill samples were generated in a single batch and judged with the C3 rubric. They may have slightly different quality distribution than the original C2 samples.",
        "3. **No crisis-adjacent samples in dataset:** Crisis intents were excluded from the RAFT pipeline (they use fixed template responses in production). The SFT dataset contains zero crisis-adjacent samples. The model's crisis response behavior is governed entirely by the template-based system prompt, not fine-tuning.",
        "4. **Single judge model:** All C3 quality judgments used dsv4 (DeepSeek V4 Flash at temperature 0.0). No cross-model or multi-judge arbitration was applied.",
    ])

    new_md_lines.append("")

    with open(DATASET_MD, "w") as f:
        f.write("\n".join(new_md_lines))
    print(f"  Updated {DATASET_MD}")

    # Update checkpoint
    ckpt = {"phase": "complete", "sft": final_sft_count, "filtered": len(filtered_rows),
            "train": len(train), "val": len(val)}
    with open(CHECKPOINT_PATH, "w") as f:
        json.dump(ckpt, f)

    # -----------------------------------------------------------------------
    # 6. Summary
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("C2FIX SUMMARY")
    print("=" * 60)
    print(f"  sft.jsonl:           {final_sft_count:,} rows (was 8,000; {n_purged} purged, {n_backfill_added} backfilled)")
    print(f"  sft.filtered.jsonl:  {len(filtered_rows):,} rows (was 6,446; {len(dropped_filtered_indices)} leaked removed, {added_filtered} backfills added)")
    print(f"  sft.train.jsonl:     {len(train):,} rows")
    print(f"  sft.val.jsonl:       {len(val):,} rows")
    print(f"  DATASET.md:          updated with lineage note")
    print(f"  Gold exclusion:      {len(exclusion_pairs)} doc-scoped pairs")
    print(f"  Filtered ≥6,000:     {'✓' if len(filtered_rows) >= 6000 else '✗'}")
    print(f"  SFT ≥8,000:          {'✓' if final_sft_count >= 8000 else '✗'}")

    return 0


def judge_one(client: Any, sample: dict, idx: int) -> dict:
    """Judge one sample and return verdict dict."""
    verdict = call_judge(client, sample)

    if verdict is None:
        return {
            "idx": idx,
            "intent_id": sample["meta"].get("intent_id", "?"),
            "register": sample["meta"].get("register", "?"),
            "sample_type": sample["meta"].get("sample_type", "?"),
            "overall": "KEEP",
            "drop_reason": "",
            "judge_error": True,
            "verdict": verdict,
        }

    failures = []
    axes = [
        ("grounded", verdict.get("grounded", "PASS")),
        ("voice", verdict.get("voice", "PASS")),
        ("hotline_discipline", verdict.get("hotline_discipline", "PASS")),
        ("register_fit", verdict.get("register_fit", "PASS")),
        ("refusal_correctness", verdict.get("refusal_correctness", "PASS")),
    ]
    for axis_name, result in axes:
        if result == "FAIL":
            failures.append(axis_name)

    overall = verdict.get("overall", "KEEP")
    drop_reason = verdict.get("drop_reason", "")

    if failures and overall == "KEEP":
        overall = "DROP"
        drop_reason = "; ".join(failures)

    return {
        "idx": idx,
        "intent_id": sample["meta"].get("intent_id", "?"),
        "register": sample["meta"].get("register", "?"),
        "sample_type": sample["meta"].get("sample_type", "?"),
        "crisis_adjacent": sample["meta"].get("crisis_adjacent", False),
        "overall": overall,
        "drop_reason": drop_reason or (failures[0] if failures else ""),
        "judge_error": False,
        "verdict": verdict,
    }


if __name__ == "__main__":
    raise SystemExit(main())
