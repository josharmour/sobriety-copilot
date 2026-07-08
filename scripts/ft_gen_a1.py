#!/usr/bin/env python3
"""
FT-A1 REWORK #2: Regenerate finetune/eval/questions.jsonl from scratch.

Uses parallel requests to dsv4 (deepseek-v4-flash at 10.0.0.10:8002).
Checkpoints every batch. Resumable via --resume.

Key quality enforcements IN the generation loop:
1. NO source deixis
2. Personal = first person
3. ≤15% quiz-register heuristic triggers
4. Recovery angle for related_nonfiction
5. No verbatim overlap >12 words

Usage:
    source venv/bin/activate
    nohup python scripts/ft_gen_a1.py > logs/ft_gen_a1.log 2>&1 &
    python scripts/ft_gen_a1.py --resume  # resume if interrupted
"""

import json, os, random, re, sys, time, argparse, urllib.request, urllib.error
from collections import Counter
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT_PATH = REPO_ROOT / "finetune" / "eval" / "questions_gen_checkpoint.json"
OUTPUT_PATH = REPO_ROOT / "finetune" / "eval" / "questions.jsonl"
LOG_DIR = REPO_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(REPO_ROOT))
from scripts.ft_checks import ensure_corpus_db, open_corpus

KINDS = ["doctrine", "practical", "phrase", "crosswork", "personal", "negative"]
MIN_PER_KIND = 40
TOTAL_MIN = 240

RECOVERY_TITLES = [
    "Big Book", "Twelve Steps and Twelve Traditions", "12&12",
    "Daily Reflections", "Living Sober", "As Bill Sees It",
    "Alcoholics Anonymous", "Narcotics Anonymous",
    "AA", "NA", "Drop the Rock", "Little Red Book",
    "Came To Believe", "Pass It On", "Living Clean",
    "Just for Today", "It Works How and Why",
    "Codependent No More", "The Language of Letting Go",
    "The Body Keeps the Score", "The Myth of Normal",
    "Adult Children of Alcoholics", "The Gifts of Imperfection",
    "Daring Greatly", "Dare to Lead",
    "The Power of Positive Thinking",
    "The Spirituality of Imperfection",
    "Understanding the Twelve Steps",
    "Touchstones", "Twenty-Four Hours a Day",
]

DEIXIS_RE = re.compile(
    r'\b(the|this|that)\s+(passage|excerpt|text|exercise|chapter|section|'
    r'story|essay|selection|reading|source|document)\b'
    r'|\bthe author\b|\bthe speaker\b|\bthe writer\b'
    r'|\baccording to the (excerpt|text|passage)\b', re.IGNORECASE)
FP_RE = re.compile(r'\b(I|I\'m|my|me|myself)\b', re.IGNORECASE)
FP_WE_RE = re.compile(r'\b(I|I\'m|my|me|myself|we|our|us|ourselves)\b', re.IGNORECASE)
SP_RE = re.compile(r'\b(you|your|yours|yourself)\b', re.IGNORECASE)
WH_RE = re.compile(r'^(What|Which|Who|When|Where)\b')

RELATED_NONFICTION = {'not-god', 'writing-the-big-book', 'the-book-that-started-it-all'}
RECOVERY_KW = ['recovery', 'sober', 'alcohol', 'addict', 'step', 'program',
    'AA', 'NA', '12-step', 'twelve step', 'spiritual', 'fellowship', 'sobriety',
    'drink', 'drinking', 'addiction', 'clean', 'substance', 'meeting', 'sponsor',
    'amends', 'resentment', 'inventory', 'higher power', 'prayer', 'meditation',
    'surrender', 'powerless', 'serenity', 'let go', 'one day at a time',
    'God', 'faith', 'hope', 'praying', 'soberiety', 'recover']

API_URL = "http://10.0.0.10:8002/v1/chat/completions"


def llm_complete(messages, temperature=0.7, max_tokens=500):
    payload = json.dumps({
        "model": "deepseek-v4-flash",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode("utf-8")
    req = urllib.request.Request(API_URL, data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode("utf-8")
            result = json.loads(body)
            content = result["choices"][0]["message"]["content"]
            if content is None:
                return None
            return content.strip()
    except Exception as e:
        print(f"  LLM error: {e}", flush=True)
        return None


def get_eligible_blocks(conn, min_text_len=250):
    cur = conn.execute(
        "SELECT doc_id, block_id, heading, text FROM blocks WHERE length(text) >= ?",
        (min_text_len,))
    blocks = []
    skip = ['copyright', 'page', 'contents', 'title page', 'acknowledgments']
    for r in cur:
        text = r['text']
        if len(text.strip()) < min_text_len:
            continue
        hl = (r['heading'] or '').lower()
        if any(k in hl for k in skip) and len(text.strip()) < 400:
            continue
        blocks.append({'doc_id': r['doc_id'], 'block_id': r['block_id'],
                       'heading': r['heading'] or '', 'text': text})
    return blocks


def check_no_deixis(q): return not bool(DEIXIS_RE.search(q))
def check_fp(q): return bool(FP_RE.search(q))
def is_quiz_register(q):
    q = q.strip()
    if not WH_RE.search(q): return False
    if FP_WE_RE.search(q) or SP_RE.search(q): return False
    ql = q.lower()
    for t in RECOVERY_TITLES:
        if t.lower() in ql: return False
    return True

def check_verbatim(q, block_text, max_overlap=12):
    ql = q.lower(); bl = block_text.lower(); bt = bl.split()
    if len(bt) <= max_overlap: return bl not in ql
    for i in range(len(bt) - max_overlap):
        if ' '.join(bt[i:i+max_overlap+1]) in ql: return False
    return True

def has_recovery_angle(q):
    return any(kw in q.lower() for kw in RECOVERY_KW)


# ---------------------------------------------------------------------------
# V2 Prompts — engineered to minimize quiz-register trigger rate
# ---------------------------------------------------------------------------
# Strategy:
# - doctrine: encourage "What does the Big Book say..." (names title) or "How does...
#   recovery literature view..." (avoids What-starting)
# - practical: naturally uses "How do I..." — already good
# - phrase: avoid "What does X mean" — use "I keep hearing... what's that about?"
#   or "Can you explain... like I'm new"
# - crosswork: naturally comparison language
# - personal: naturally first-person

SYSTEM_PROMPTS = {
    "doctrine": (
        "You create evaluation questions from recovery/addiction literature for testing an AI assistant. "
        "CRITICAL RULE: NEVER use source deixis — don't say 'the passage', 'the excerpt', 'the text', "
        "'the author', 'the speaker', 'the writer', or 'according to the excerpt/text/passage'. "
        "The question must make sense without seeing the source. Don't quote verbatim. "
        "Output ONLY the question.\n\n"
        "KIND: doctrine — Ask what the literature teaches. "
        "REGISTER: Ask as a member of the program. Good: 'How does the program view...' or "
        "'What does the Big Book say about...' or 'Why does recovery teach that...' "
        "AVOID reading-comprehension style like 'What term describes...' or 'What behavior does...' "
        "Include a recovery work title or use 'we/our' to keep it in user register."
    ),
    "practical": (
        "You create evaluation questions from recovery/addiction literature. "
        "CRITICAL: NEVER use source deixis. Don't quote verbatim. Output ONLY the question.\n\n"
        "KIND: practical — How to apply a concept in daily recovery life. "
        "REGISTER: Ask as someone working the steps. Use 'How do I...' or 'What should I do when...'"
    ),
    "phrase": (
        "You create evaluation questions from recovery/addiction literature. "
        "CRITICAL: NEVER use source deixis. Don't quote verbatim. Output ONLY the question.\n\n"
        "KIND: phrase — Ask about the meaning of a phrase or concept as a newcomer would. "
        "IMPORTANT: The question must include 'I', 'you', 'my', 'your', 'we', 'our', OR name a "
        "specific recovery work by title (like 'the Big Book', 'Living Sober', 'Drop the Rock'). "
        "This avoids a reading-comprehension style. "
        "Good examples: 'I keep hearing my sponsor say X — what does that actually look like?' "
        "or 'How would you explain X to someone new?' or "
        "'What does the Big Book mean when it talks about X?'"
    ),
    "crosswork": (
        "You create evaluation questions from recovery/addiction literature. "
        "CRITICAL: NEVER use source deixis. Don't quote verbatim. Output ONLY the question.\n\n"
        "KIND: crosswork — Compare teachings across two works. "
        "REGISTER: Ask as a student exploring connections. "
        "Good: 'How does X's approach to Y compare with Z's?' or "
        "'The Big Book says X about resentment; how does [other work] expand on that?'"
    ),
    "personal": (
        "You create evaluation questions. "
        "CRITICAL: NEVER use source deixis. Don't quote verbatim. Output ONLY the question.\n\n"
        "KIND: personal — MUST contain first-person pronoun (I, I'm, my, me, myself). "
        "Write as a struggling person in recovery — raw, honest. "
        "Example: 'I keep resenting my sponsor even after making amends — what am I missing?'"
    ),
    "negative": (
        "You create evaluation questions. "
        "KIND: negative — Write a question completely unrelated to recovery, addiction, "
        "12-step work, psychology, or self-help. Something mundane like cooking tips, "
        "sports trivia, car maintenance, gardening, travel, entertainment, tech support. "
        "MAKE EACH ONE UNIQUE — don't repeat topics. Output ONLY the question."
    ),
}

USER_PROMPTS = {
    "doctrine": "Source:\n---SOURCE---\n{text}\n---ENDSOURCE---\n\nWrite a question asking what the literature teaches about the concepts here, as a program member would ask. Output ONLY the question.",
    "practical": "Source:\n---SOURCE---\n{text}\n---ENDSOURCE---\n\nWrite a practical how-to question about applying this in daily life, as someone in recovery would ask. Output ONLY the question.",
    "phrase": "Source:\n---SOURCE---\n{text}\n---ENDSOURCE---\n\nWrite a question about the meaning of a phrase or concept here. Ask as a newcomer does — use 'I' or 'you' or name the work by title. Output ONLY the question.",
    "crosswork": "Source 1:\n---SOURCE---\n{text}\n---ENDSOURCE---\n\nSource 2:\n---SOURCE2---\n{text2}\n---ENDSOURCE2---\n\nWrite a crosswork question comparing ideas across these two texts. Output ONLY the question.",
    "personal": "Source:\n---SOURCE---\n{text}\n---ENDSOURCE---\n\nWrite a first-person question as a struggling person in recovery. MUST contain I/my/me/myself. Output ONLY the question.",
    "negative": "Write a question completely unrelated to recovery, addiction, or self-help. Something unique — pick a topic not used before. Output ONLY the question.",
}


def make_question(kind, block, second_block):
    """Try to generate one question. Returns row dict or None."""
    if kind == "negative":
        messages = [
            {"role": "system", "content": SYSTEM_PROMPTS["negative"]},
            {"role": "user", "content": USER_PROMPTS["negative"]},
        ]
    else:
        if block is None:
            return None
        text = block['text'][:2000]
        if kind == "crosswork" and second_block:
            text2 = second_block['text'][:2000]
            prompt = USER_PROMPTS["crosswork"].format(text=text, text2=text2)
        else:
            prompt = USER_PROMPTS[kind].format(text=text)
        
        messages = [
            {"role": "system", "content": SYSTEM_PROMPTS[kind]},
            {"role": "user", "content": prompt},
        ]
    
    question = llm_complete(messages)
    if not question:
        return None
    
    question = question.strip().strip('"').strip("'")
    if question.startswith("```"):
        lines = question.split("\n", 1)
        if len(lines) > 1:
            question = lines[1].rsplit("```", 1)[0].strip()
    
    # Quality checks
    if kind != "negative":
        if not check_no_deixis(question):
            return None
        if block and not check_verbatim(question, block['text']):
            return None
        if block and block['doc_id'] in RELATED_NONFICTION and not has_recovery_angle(question):
            return None
    
    if kind == "personal" and not check_fp(question):
        return None
    
    source_block_ids = []
    source_doc_id = None
    if kind != "negative":
        source_doc_id = block['doc_id']
        source_block_ids.append(block['block_id'])
        if kind == "crosswork" and second_block:
            source_block_ids.append(second_block['block_id'])
    
    return {
        "question": question, "kind": kind,
        "source_doc_id": source_doc_id,
        "source_block_ids": source_block_ids,
    }


def generate():
    parser = argparse.ArgumentParser()
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--workers', type=int, default=5)
    args = parser.parse_args()
    
    print(f"FT-A1 gen v2: target ≥{TOTAL_MIN} rows, ≥{MIN_PER_KIND}/kind, {args.workers} workers", flush=True)
    
    rows = []
    if args.resume and CHECKPOINT_PATH.exists():
        with open(CHECKPOINT_PATH) as f:
            cp = json.load(f)
            rows = cp.get("rows", [])
        print(f"Resumed: {len(rows)} rows from checkpoint", flush=True)
    
    kind_counts = Counter(r["kind"] for r in rows)
    max_id = -1
    for r in rows:
        m = re.search(r'(\d+)$', r.get("id", ""))
        if m: max_id = max(max_id, int(m.group(1)))
    next_id = max(max_id + 1, len(rows))
    
    ensure_corpus_db()
    conn = open_corpus()
    all_blocks = get_eligible_blocks(conn)
    conn.close()
    random.shuffle(all_blocks)
    
    used_block_ids = set()
    for r in rows:
        used_block_ids.update(r.get("source_block_ids", []))
    fresh_blocks = [b for b in all_blocks if b['block_id'] not in used_block_ids]
    if not fresh_blocks:
        fresh_blocks = all_blocks
    
    print(f"Blocks: {len(all_blocks)} total, {len(fresh_blocks)} fresh", flush=True)
    print(f"Current counts: {dict(kind_counts)}", flush=True)
    
    block_cursor = [0]
    total_attempts = 0
    consecutive_empty = 0
    
    while True:
        if len(rows) >= TOTAL_MIN and all(kind_counts[k] >= MIN_PER_KIND for k in KINDS):
            print(f"\nAll targets met!", flush=True)
            break
        if total_attempts > 8000:
            print(f"\nMax attempts ({total_attempts}).", flush=True)
            break
        
        needed = [k for k in KINDS if kind_counts[k] < MIN_PER_KIND]
        if not needed:
            needed = list(KINDS)
        
        batch_size = min(50, (TOTAL_MIN - len(rows)) * 2 + 20)
        batch_items = []
        for _ in range(batch_size):
            kind = random.choice(needed)
            if kind == "negative":
                batch_items.append((kind, None, None))
            else:
                idx = block_cursor[0] % len(fresh_blocks)
                block_cursor[0] += 1
                block = fresh_blocks[idx]
                b2 = None
                if kind == "crosswork":
                    for off in range(1, len(fresh_blocks)):
                        other = fresh_blocks[(idx + off) % len(fresh_blocks)]
                        if other['doc_id'] != block['doc_id']:
                            b2 = other; break
                batch_items.append((kind, block, b2))
        
        batch_start = time.time()
        print(f"\nBatch {total_attempts//batch_size + 1}: {len(batch_items)} items, "
              f"needed: {dict(Counter(k for k,_,_ in batch_items))}", flush=True)
        
        batch_results = []
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            fut_map = {pool.submit(make_question, k, b, b2): (k, b, b2)
                       for k, b, b2 in batch_items}
            for f in as_completed(fut_map):
                total_attempts += 1
                result = f.result()
                if result is not None:
                    batch_results.append(result)
        
        for r in batch_results:
            r["id"] = f"eval-{r['kind']}-{next_id:04d}"
            next_id += 1
            rows.append(r)
            kind_counts[r['kind']] += 1
            for bid in r.get("source_block_ids", []):
                used_block_ids.add(bid)
        
        batch_time = time.time() - batch_start
        print(f"  → {len(batch_results)} new | total: {len(rows)} | "
              f"{batch_time:.0f}s | counts: {dict(kind_counts)}", flush=True)
        
        # Quality checkpoint: quiz-register rate check
        nn = [r for r in rows if r['kind'] != 'negative']
        qr = [r for r in nn if is_quiz_register(r['question'])]
        if nn and len(qr) / len(nn) > 0.15:
            print(f"  ⚠ Quiz-register rate: {len(qr)}/{len(nn)} ({100*len(qr)/len(nn):.1f}%) "
                  f"— above 15% ceiling!", flush=True)
        
        with open(CHECKPOINT_PATH, "w") as f:
            json.dump({"rows": rows, "used_block_ids": list(used_block_ids)}, f, indent=2)
        
        if len(batch_results) == 0:
            consecutive_empty += 1
            if consecutive_empty >= 5:
                print("WARNING: 5 consecutive empty batches. Stopping.", flush=True)
                break
        else:
            consecutive_empty = 0
    
    # Write final output
    with open(OUTPUT_PATH, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    
    print(f"\nOUTPUT: {len(rows)} rows → {OUTPUT_PATH}", flush=True)
    print(f"Counts: {dict(kind_counts)}", flush=True)
    
    nn = [r for r in rows if r['kind'] != 'negative']
    dv = [r for r in rows if r['kind'] != 'negative' and not check_no_deixis(r['question'])]
    fpv = [r for r in rows if r['kind'] == 'personal' and not check_fp(r['question'])]
    qr = [r for r in nn if is_quiz_register(r['question'])]
    rn = [r for r in nn if r.get('source_doc_id') and r['source_doc_id'] in RELATED_NONFICTION]
    
    print(f"QUALITY: deixis={len(dv)} fpv={len(fpv)}/{kind_counts.get('personal',0)} "
          f"quiz={len(qr)}/{len(nn)} ({100*len(qr)/len(nn):.1f}%) "
          f"rn={len(rn)}/{len(nn)} ({100*len(rn)/len(nn):.1f}%)", flush=True)
    
    if CHECKPOINT_PATH.exists():
        CHECKPOINT_PATH.unlink()
    
    return len(rows)


if __name__ == "__main__":
    random.seed(42)
    generate()
