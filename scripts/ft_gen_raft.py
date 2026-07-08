#!/usr/bin/env python3
"""FT-C2: RAFT sample generator (optimized).

Produces finetune/gen/sft.jsonl with ≥8000 {messages, meta} samples following
the on-device localUserMessage format (byte-match from local_prompts.dart).

Usage:
    source venv/bin/activate
    python scripts/ft_gen_raft.py [--resume] [--dry-run N]

Output:
    finetune/gen/sft.jsonl          — the full dataset
    finetune/gen/sft_checkpoint.json — resume checkpoint (auto-managed)
"""

from __future__ import annotations

import json
import os
import random
import sqlite3
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
TAXONOMY_PATH = REPO_ROOT / "finetune" / "gen" / "taxonomy.json"
QUESTIONS_PATH = REPO_ROOT / "finetune" / "eval" / "questions.jsonl"
GOLD_PATH = REPO_ROOT / "finetune" / "eval" / "gold.jsonl"
OUTPUT_PATH = REPO_ROOT / "finetune" / "gen" / "sft.jsonl"
CHECKPOINT_PATH = REPO_ROOT / "finetune" / "gen" / "sft_checkpoint.json"
CACHE_DB = REPO_ROOT / "finetune" / "cache" / "search.db"
CORPUS_PACK = REPO_ROOT / "packs" / "library-v1.scpack"

# ---------------------------------------------------------------------------
# dsv4 config
# ---------------------------------------------------------------------------
DSV4_BASE = "http://10.0.0.10:8002/v1"
DSV4_MODEL = "deepseek-v4-flash"
TEMPERATURE = 0.7
MAX_TOKENS = 1024
CONCURRENCY = 16  # raised after vLLM max_num_seqs 8->48 (2026-07-08)
REQUEST_TIMEOUT = 180  # seconds per request (increased for longer generations)

# ---------------------------------------------------------------------------
# Generation targets
# ---------------------------------------------------------------------------
TARGET_COUNT = 8000
NO_CONTEXT_RATIO = 0.10
REFUSAL_RATIO = 0.05
MAX_PASSAGES = 5       # total passages in context per sample
GOLD_COUNT = 2         # gold passages (rest are distractors)
VARIANTS_PER_SEED = 8  # ~1080 seeds x 8 = 8640

# ---------------------------------------------------------------------------
# System messages (shortened copies from src/prompts/templates.py)
# ---------------------------------------------------------------------------
SAFETY_CORE = (
    "Safety (always):\n"
    "- If someone seems in crisis or is concerned about safety or harm, "
    "prominently feature the AA hotline, and instruct them to tap the "
    '"Find a meeting" button. Suggest 911 only if danger is immediate. '
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
    "citation markers like [1] — just the plain title (and a page if useful).\n\n"
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

CRISIS_IDS = {"crisis_imminent_relapse", "crisis_harm_urges", "crisis_overdose_concern"}

# Docs likely to be useful for most 12-step / recovery questions
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

# Distractor docs — unlikely to be relevant to 12-step questions
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


# ---------------------------------------------------------------------------
# Corpus helpers
# ---------------------------------------------------------------------------

def _ensure_cache_db() -> Path:
    if CACHE_DB.exists():
        return CACHE_DB
    CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(CORPUS_PACK, "r") as zf:
        with zf.open("search.db") as src, open(CACHE_DB, "wb") as dst:
            import shutil
            shutil.copyfileobj(src, dst)
    return CACHE_DB


def _load_title_map() -> dict[str, str]:
    with zipfile.ZipFile(CORPUS_PACK, "r") as zf:
        idx = json.loads(zf.read("manifest-index.json"))
    return {e["doc_id"]: e["title"] for e in idx}


def _load_exclusion_blocks() -> set[str]:
    excluded: set[str] = set()
    if GOLD_PATH.is_file():
        with open(GOLD_PATH) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                excluded.update(row.get("gold_block_ids", []))
        print(f"[exclusion] loaded {len(excluded)} gold blocks from {GOLD_PATH}")
    elif QUESTIONS_PATH.is_file():
        with open(QUESTIONS_PATH) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                excluded.update(row.get("source_block_ids", []))
        print(f"[exclusion] loaded {len(excluded)} source blocks from {QUESTIONS_PATH}")
    else:
        print("[exclusion] no question/gold file found — no exclusions")
    return excluded


# ---------------------------------------------------------------------------
# Pre-load blocks into memory for fast random access
# ---------------------------------------------------------------------------

def _load_all_blocks(
    conn: sqlite3.Connection,
    doc_ids: list[str] | None = None,
    exclude_blocks: set[str] | None = None,
) -> dict[str, list[dict]]:
    """Load blocks grouped by doc_id.  Returns {doc_id: [{block_id, heading, text}, ...]}."""
    exclude_blocks = exclude_blocks or set()
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
        bid = row[0]
        if bid in exclude_blocks:
            continue
        doc_id = row[1]
        if doc_id not in blocks_by_doc:
            blocks_by_doc[doc_id] = []
        blocks_by_doc[doc_id].append({
            "block_id": bid,
            "doc_id": doc_id,
            "heading": row[2] or "",
            "text": row[3],
        })

    print(f"[load] {sum(len(v) for v in blocks_by_doc.values())} blocks loaded across {len(blocks_by_doc)} docs")
    return blocks_by_doc


# ---------------------------------------------------------------------------
# Context formatting (byte-match localUserMessage from local_prompts.dart)
# ---------------------------------------------------------------------------

def _safe_block_text(text: str, max_chars: int = 2500) -> str:
    if len(text) > max_chars:
        return text[:max_chars] + "…"
    return text


def _format_passage(block: dict, title_map: dict[str, str]) -> str:
    """Format a single passage as the app does:
    From "Title" — Heading:\n<text>\n
    """
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
    """Byte-matches:
      Relevant passages from recovery literature:

      From "Title" — Heading:
      <text>

      ...

      The person said: <question>

      Ground your answer in the passages above ...
    """
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


# ---------------------------------------------------------------------------
# Seed / sample construction
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Intent → gold doc mapping (heuristic)
# ---------------------------------------------------------------------------

def _intent_to_gold_docs(intent_id: str) -> list[str]:
    """Map intent IDs to likely relevant doc IDs for gold passage selection."""
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


# ---------------------------------------------------------------------------
# dsv4 generation
# ---------------------------------------------------------------------------

def _call_dsv4(
    messages: list[dict],
    temperature: float = TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
    max_retries: int = 3,
) -> str | None:
    """Call dsv4 chat completion and return the assistant response text.

    Retries when content is null (DeepSeek sometimes exhausts the token budget
    on reasoning).  Also strips reasoning preamble from the start of content.
    """
    REASONING_PREFIXES = (
        "we need to", "i need to", "the assistant", "the user",
        "the person", "we should", "i should", "let me",
        "to answer this", "to respond",
    )

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
                    # Top-level reasoning_effort is NOT honored by this vLLM
                    # build; the template default (thinking:true, high) must be
                    # overridden via chat_template_kwargs.
                    "chat_template_kwargs": {"thinking": False},
                },
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            msg = data["choices"][0]["message"]
            content = msg.get("content")
            # If content is null but reasoning is populated, the model ran out
            # of tokens during reasoning — retry with more tokens next attempt.
            if not content:
                if attempt < max_retries - 1:
                    max_tokens = min(max_tokens * 2, 4096)
                    print(f"  [dsv4 retry {attempt+1}] null content, bumping max_tokens to {max_tokens}", file=sys.stderr)
                    continue
                print(f"  [dsv4 error] null content after {max_retries} retries", file=sys.stderr)
                return None

            content = content.strip()

            # If content starts with reasoning preamble, strip up to first colon/newline
            for prefix in REASONING_PREFIXES:
                if content.lower().startswith(prefix):
                    # Try to find where reasoning ends and answer begins
                    # Look for double newline, colon+newline, or period+space after prefix
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


# ---------------------------------------------------------------------------
# Build all sample skeletons (fast — uses pre-loaded blocks)
# ---------------------------------------------------------------------------

def build_all_samples(
    seeds: list[dict],
    exclusion_set: set[str],
    title_map: dict[str, str],
    blocks_by_doc: dict[str, list[dict]],
    max_gold_attempts: int = 50,
) -> list[dict]:
    """Build all sample skeletons (everything except assistant answer).

    Uses pre-loaded blocks and intent→doc mapping for speed.
    """
    random.shuffle(seeds)
    samples: list[dict] = []

    target_ctx = int(TARGET_COUNT * (1 - NO_CONTEXT_RATIO - REFUSAL_RATIO))
    target_noctx = int(TARGET_COUNT * NO_CONTEXT_RATIO)
    target_refusal = int(TARGET_COUNT * REFUSAL_RATIO)

    ctx_count = 0
    noctx_count = 0
    refusal_count = 0

    refusal_questions = _generate_refusal_questions(target_refusal + 20)

    # ---- Context-based samples ----
    seed_index = 0
    while ctx_count < target_ctx and seed_index < len(seeds) * 10:
        seed = seeds[seed_index % len(seeds)]
        seed_index += 1

        iid = seed["intent_id"]
        if iid in CRISIS_IDS:
            continue  # crisis intents use templated responses, handled separately

        question = seed["seed"]
        register = seed["register"]
        difficulty = seed["difficulty"]

        # Slight variation sometimes
        if random.random() < 0.2:
            leadins = ["I've been thinking: ", "Can you help? ", ""]
            question = random.choice(leadins) + seed["seed"]

        system_msg = SYSTEM_MESSAGES.get(register, SYSTEM_MESSAGES["warm"])

        # Get candidate gold docs for this intent
        gold_doc_ids = _intent_to_gold_docs(iid)
        # Filter to docs we actually have blocks for
        gold_doc_ids = [d for d in gold_doc_ids if d in blocks_by_doc and len(blocks_by_doc[d]) > 0]

        if len(gold_doc_ids) < 1:
            gold_doc_ids = RECOVERY_CORE_DOCS
            gold_doc_ids = [d for d in gold_doc_ids if d in blocks_by_doc and len(blocks_by_doc[d]) > 0]

        if len(gold_doc_ids) < 1:
            continue  # can't get gold blocks

        # Pick 1-2 random gold docs and 1 random block from each
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
            continue  # no gold blocks found

        # Pick distractors from non-gold docs
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
                            if len(b["text"]) > 50 and b["block_id"] not in exclusion_set]
                if not eligible:
                    continue
                distractors.append(random.choice(eligible))

        # Combine and shuffle
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

        if ctx_count % 500 == 0:
            print(f"  [build] {ctx_count} context samples built...", flush=True)

    # ---- Crisis context samples (use recovery docs, templated answers) ----
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
            continue  # crisis should always have some context
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


# ---------------------------------------------------------------------------
# Generation loop with checkpointing
# ---------------------------------------------------------------------------

def _save_checkpoint(samples: list[dict], completed_indices: set[int], output_lines: list[str]) -> None:
    ckpt = {
        "total_samples": len(samples),
        "completed_indices": sorted(completed_indices),
        "output_lines_count": len(output_lines),
    }
    with open(CHECKPOINT_PATH, "w") as f:
        json.dump(ckpt, f)
    with open(OUTPUT_PATH, "w") as f:
        for line in output_lines:
            f.write(line + "\n")


def _load_checkpoint() -> tuple[set[int], list[str]]:
    if not CHECKPOINT_PATH.is_file() or not OUTPUT_PATH.is_file():
        return set(), []
    try:
        with open(CHECKPOINT_PATH) as f:
            ckpt = json.load(f)
        completed = set(ckpt.get("completed_indices", []))
        with open(OUTPUT_PATH) as f:
            output_lines = [line.rstrip("\n") for line in f if line.strip()]
        print(f"[checkpoint] loaded {len(completed)} completed, {len(output_lines)} lines")
        return completed, output_lines
    except Exception as e:
        print(f"[checkpoint] load failed: {e} — fresh start", file=sys.stderr)
        return set(), []


def generate_answers(samples: list[dict], resume: bool = False) -> list[str]:
    completed: set[int] = set()
    output_lines: list[str] = []

    if resume:
        completed, output_lines = _load_checkpoint()

    pending = [(i, s) for i, s in enumerate(samples) if i not in completed]

    print(f"\n[gen] {len(samples)} total, {len(completed)} done, {len(pending)} pending")

    if not pending:
        print("[gen] all done!")
        return output_lines

    batch_size = CONCURRENCY * 2
    total_batches = (len(pending) + batch_size - 1) // batch_size

    for batch_num in range(total_batches):
        batch = pending[batch_num * batch_size : (batch_num + 1) * batch_size]
        batch_results: list[tuple[int, str | None]] = []

        with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
            future_map = {}
            for idx, sample in batch:
                # Crisis samples use templated response (no API call)
                if sample.get("_crisis"):
                    iid = sample["meta"]["intent_id"]
                    answer = _crisis_templated_answer(iid, sample["meta"].get("gold_blocks", []))
                    batch_results.append((idx, answer))
                    continue

                # Refusal samples use templated response (no API call)
                if sample["meta"].get("sample_type") == "refusal":
                    answer = _refusal_templated_answer()
                    batch_results.append((idx, answer))
                    continue

                # Normal samples: call dsv4
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
                continue  # do NOT mark as completed — allow retry on resume

            sample = samples[idx]
            messages = [
                {"role": "system", "content": sample["system"]},
                {"role": "user", "content": sample["user"]},
                {"role": "assistant", "content": answer},
            ]
            output_lines.append(json.dumps({"messages": messages, "meta": sample["meta"]}, ensure_ascii=False))
            completed.add(idx)

        _save_checkpoint(samples, completed, output_lines)

        if batch_num % 5 == 0:
            print(f"  [gen] batch {batch_num+1}/{total_batches} — {len(completed)}/{len(samples)} done", flush=True)

    print(f"\n[gen] done! {len(output_lines)} samples in {OUTPUT_PATH}")
    return output_lines


def _crisis_templated_answer(intent_id: str, gold_block_ids: list[str]) -> str:
    """Generate a crisis answer using template (no API call needed)."""
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
    """Generate a refusal answer using template."""
    templates = [
        "I'm sorry, but that topic isn't covered in the recovery literature I have access to. The library I draw from focuses on 12-step and recovery-related texts. For questions about specific medical treatments, legal matters, or other programs outside this scope, I'd recommend consulting a qualified professional in that area.",
        "That's outside the scope of the recovery literature available to me. My knowledge is grounded in the 12-step library I've been provided, and that particular question isn't addressed in those texts. A professional in that specific field would be better equipped to help.",
        "The corpus of recovery literature I work with doesn't address that question. I'm designed to help with questions about 12-step recovery and related topics drawn from the provided library. For this type of question, I'd suggest reaching out to a qualified specialist.",
        "I don't have information on that in the recovery literature I've been given. The texts I work with focus on 12-step recovery principles and related topics. If you have a question about the steps, traditions, or recovery from addiction, I'd be glad to help with what's in my library.",
    ]
    return random.choice(templates)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="FT-C2 RAFT sample generator")
    ap.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    ap.add_argument("--dry-run", type=int, default=0, help="Build samples and show first N without generating answers")
    ap.add_argument("--seed", type=int, default=42, help="Random seed")
    args = ap.parse_args()

    random.seed(args.seed)

    print("=" * 60)
    print("FT-C2: RAFT Sample Generator")
    print("=" * 60)

    # 1. Corpus
    print("\n[1/5] Ensuring corpus DB...")
    _ensure_cache_db()

    # 2. Load blocks into memory
    print("\n[2/5] Loading blocks and metadata...")
    title_map = _load_title_map()
    exclusion_set = _load_exclusion_blocks()

    all_docs = set(RECOVERY_CORE_DOCS + DISTRACTOR_CANDIDATES)
    conn = sqlite3.connect(f"file:{CACHE_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    blocks_by_doc = _load_all_blocks(conn, doc_ids=list(all_docs), exclude_blocks=exclusion_set)
    conn.close()

    # 3. Taxonomy
    taxonomy = _load_taxonomy()
    seeds = _flatten_seeds(taxonomy)
    print(f"  {len(seeds)} seed phrasings from {len(taxonomy)} intents")

    # 4. Build samples
    print("\n[3/5] Building sample structures...")
    samples = build_all_samples(seeds, exclusion_set, title_map, blocks_by_doc)

    if args.dry_run > 0:
        n = min(args.dry_run, len(samples))
        print(f"\n[dry-run] first {n} samples:")
        for i in range(n):
            s = samples[i]
            print(f"\n--- Sample {i+1} ---")
            print(f"  intent: {s['meta']['intent_id']}, register: {s['meta']['register']}")
            print(f"  type: {s['meta']['sample_type']}")
            print(f"  gold: {s['meta'].get('gold_blocks', [])}")
            print(f"  distractors: {s['meta'].get('distractor_blocks', [])}")
            print(f"  Q: {s['question'][:100]}...")
            print(f"  USER MSG:\n{s['user'][:500]}...")
        print(f"\n  Total: {len(samples)} samples built")
        return 0

    if len(samples) < TARGET_COUNT:
        print(f"\n⚠ Only {len(samples)} samples (target {TARGET_COUNT})", file=sys.stderr)

    # 5. Generate
    print(f"\n[4/5] Generating answers with dsv4 ({DSV4_MODEL})...")
    output_lines = generate_answers(samples, resume=args.resume)

    # 6. Report
    print(f"\n[5/5] Done. {len(output_lines)} samples → {OUTPUT_PATH}")

    types: dict[str, int] = {}
    registers: dict[str, int] = {}
    for line in output_lines:
        row = json.loads(line)
        t = row["meta"]["sample_type"]
        types[t] = types.get(t, 0) + 1
        r = row["meta"]["register"]
        registers[r] = registers.get(r, 0) + 1
    print(f"  By type: {types}")
    print(f"  By register: {registers}")

    if len(output_lines) >= TARGET_COUNT:
        print(f"✓ {len(output_lines)} samples (target {TARGET_COUNT})")
    else:
        print(f"⚠ {len(output_lines)} samples (target {TARGET_COUNT})")

    return 0 if len(output_lines) >= TARGET_COUNT else 1


if __name__ == "__main__":
    raise SystemExit(main())
