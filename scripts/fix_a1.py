#!/usr/bin/env python3
"""
FT-A1: Crosswork fix + negative regeneration.

Phase 1: Crosswork — programmatic title substitution using source_doc_id
to disambiguate block-to-doc mapping (since same block_id can appear in
multiple docs in the FTS5 index).

Phase 2: Negatives — dsv4 generation from diverse topic pool.

Run: python scripts/fix_a1.py
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import sys
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
Q_PATH = REPO_ROOT / "finetune" / "eval" / "questions.jsonl"
CORPUS_PACK = REPO_ROOT / "packs" / "library-v1.scpack"
CACHE_DB = REPO_ROOT / "finetune" / "cache" / "search.db"
API_URL = "http://10.0.0.10:8002/v1/chat/completions"
API_MODEL = "deepseek-v4-flash"

# =========================================================================
# Corpus helpers
# =========================================================================
def ensure_cache_db():
    if not CACHE_DB.exists():
        CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(CORPUS_PACK, "r") as zf:
            with zf.open("search.db") as src, open(CACHE_DB, "wb") as dst:
                shutil.copyfileobj(src, dst)

def get_conn():
    ensure_cache_db()
    conn = sqlite3.connect(f"file:{CACHE_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn

def load_doc_titles() -> dict[str, str]:
    with zipfile.ZipFile(CORPUS_PACK, "r") as zf:
        index = json.loads(zf.read("manifest-index.json"))
    return {entry["doc_id"]: entry["title"] for entry in index}

# =========================================================================
# Deixis detection & substitution
# =========================================================================
CW_DEIXIS_RE = re.compile(
    r'\b(first|second|1st|2nd)\s+(source|reading|work|selection)\b'
    r'|\bsource\s*[12]\b',
    re.IGNORECASE,
)

DEIXIS_PATTERNS = [
    (re.compile(r'\bsource\s*1[''\u2019]s\b', re.IGNORECASE), "'s"),
    (re.compile(r'\bsource\s*2[''\u2019]s\b', re.IGNORECASE), "'s"),
    (re.compile(r'\bfirst\s+source[''\u2019]s\b', re.IGNORECASE), "'s"),
    (re.compile(r'\bsecond\s+source[''\u2019]s\b', re.IGNORECASE), "'s"),
    (re.compile(r'\bfirst\s+reading[''\u2019]s\b', re.IGNORECASE), "'s"),
    (re.compile(r'\bsecond\s+reading[''\u2019]s\b', re.IGNORECASE), "'s"),
    (re.compile(r'\bsource\s*1\b', re.IGNORECASE), ""),
    (re.compile(r'\bsource\s*2\b', re.IGNORECASE), ""),
    (re.compile(r'\bfirst\s+source\b', re.IGNORECASE), ""),
    (re.compile(r'\bsecond\s+source\b', re.IGNORECASE), ""),
    (re.compile(r'\bfirst\s+reading\b', re.IGNORECASE), ""),
    (re.compile(r'\bsecond\s+reading\b', re.IGNORECASE), ""),
    (re.compile(r'\bfirst\s+work\b', re.IGNORECASE), ""),
    (re.compile(r'\bsecond\s+work\b', re.IGNORECASE), ""),
    (re.compile(r'\bfirst\s+selection\b', re.IGNORECASE), ""),
    (re.compile(r'\bsecond\s+selection\b', re.IGNORECASE), ""),
    (re.compile(r'\b1st\s+source\b', re.IGNORECASE), ""),
    (re.compile(r'\b2nd\s+source\b', re.IGNORECASE), ""),
    (re.compile(r'\b1st\s+reading\b', re.IGNORECASE), ""),
    (re.compile(r'\b2nd\s+reading\b', re.IGNORECASE), ""),
]

def has_deixis(text: str) -> bool:
    return bool(CW_DEIXIS_RE.search(text))

def classify_deixis_span(text: str) -> list[tuple[str, str, int, int]]:
    spans = []
    for pat, _ in DEIXIS_PATTERNS:
        for m in pat.finditer(text):
            matched = m.group(0)
            lower = matched.lower().replace("'s", "").replace("\u2019s", "").strip()
            src_num = None
            if re.search(r'\b1\b|first|1st', lower):
                src_num = "1"
            elif re.search(r'\b2\b|second|2nd', lower):
                src_num = "2"
            if src_num:
                spans.append((matched, src_num, m.start(), m.end()))
    spans.sort(key=lambda x: x[2])
    return spans

def substitute_title(text: str, title1: str, title2: str) -> str:
    if not has_deixis(text):
        return text
    spans = classify_deixis_span(text)
    deduped = []
    for span in spans:
        if deduped and span[2] < deduped[-1][3]:
            prev = deduped[-1]
            if (span[3] - span[2]) > (prev[3] - prev[2]):
                deduped[-1] = span
        else:
            deduped.append(span)
    result = list(text)
    for matched, src_num, start, end in reversed(deduped):
        title = title1 if src_num == "1" else title2
        has_poss = matched.endswith("'s") or matched.endswith("\u2019s")
        replacement = f"{title}'s" if has_poss and not (title.endswith('s') or title.endswith('S')) else \
                      f"{title}'" if has_poss else title
        before = ''.join(result[:start]).rstrip()
        if before.endswith(' the') and not title.lower().startswith('the '):
            the_start = start - len('the ')
            if the_start >= 0 and ''.join(result[the_start:start]).strip() == 'the':
                if the_start == 0 or ''.join(result[the_start - 1]) in (' ', '"', "'", '(', '—', '-', ''):
                    start = the_start
                    replacement = title
        result[start:end] = replacement
    return ''.join(result)

# =========================================================================
# Resolve doc_id for a block within a crosswork row
# =========================================================================
def resolve_block_doc(conn: sqlite3.Connection, block_id: str,
                      source_doc_id: str | None) -> str | None:
    """Find the doc_id for a block_id, preferring source_doc_id match."""
    if source_doc_id:
        r = conn.execute(
            "SELECT doc_id FROM blocks WHERE block_id = ? AND doc_id = ?",
            (block_id, source_doc_id)
        ).fetchone()
        if r:
            return r["doc_id"]
    # Fallback: any doc containing this block
    r = conn.execute(
        "SELECT doc_id FROM blocks WHERE block_id = ? LIMIT 1",
        (block_id,)
    ).fetchone()
    return r["doc_id"] if r else None

# =========================================================================
# LLM helper
# =========================================================================
def call_dsv4(prompt: str, system: str | None = None, temp: float = 0.7,
              max_tokens: int = 200) -> str | None:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    data = json.dumps({
        "model": API_MODEL, "messages": messages,
        "temperature": temp, "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(
        API_URL, data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=120)
        result = json.loads(resp.read())
        content = result["choices"][0]["message"].get("content")
        if content and content.strip():
            return content.strip()
        reasoning = result["choices"][0]["message"].get("reasoning", "")
        if reasoning:
            return reasoning.strip()
        return None
    except Exception as e:
        print(f"  [API error] {e}", file=sys.stderr, flush=True)
        return None

# =========================================================================
# Phase 1: Fix crosswork
# =========================================================================
def fix_crosswork(rows: list[dict], doc_titles: dict[str, str]) -> int:
    conn = get_conn()
    fixed = 0
    for row in rows:
        if row["kind"] != "crosswork":
            continue
        q = row["question"]
        if not has_deixis(q):
            continue
        bids = row.get("source_block_ids", [])
        if len(bids) < 2:
            continue
        src_doc = row.get("source_doc_id")

        # Resolve each block's doc_id
        d1 = resolve_block_doc(conn, bids[0], src_doc)
        d2 = resolve_block_doc(conn, bids[1], src_doc)

        t1 = doc_titles.get(d1, d1) if d1 else "the first work"
        t2 = doc_titles.get(d2, d2) if d2 else "the second work"

        new_q = substitute_title(q, t1, t2)
        new_q = re.sub(r'  +', ' ', new_q).strip()
        if new_q and new_q != q and not has_deixis(new_q):
            print(f"  {row['id']}: {t1} / {t2}", flush=True)
            row["question"] = new_q
            fixed += 1
    conn.close()
    return fixed

# =========================================================================
# Phase 2: Generate negatives
# =========================================================================
RECOVERY_LEXICON = [
    'alcohol', 'drink', 'sober', 'recovery', 'addict', 'drug', 'AA', 'NA',
    'step', 'meeting', 'sponsor', 'rehab', 'relapse', 'detox', 'withdrawal',
    'DUI', 'naltrexone', 'twelve', 'program', 'addiction', 'sobriety',
    'clean', 'substance', 'fellowship', 'amends', 'inventory',
    'higher power', 'surrender', 'powerless', 'serenity', 'vivitrol',
    'suboxone', 'methadone', 'outpatient', 'inpatient', 'dual diagnosis',
]

NEGATIVE_TOPICS = [
    "medical dosage for naltrexone in alcohol treatment",
    "medical dosage for Vivitrol injection protocol",
    "medical dosage for Antabuse (disulfiram) prescription",
    "insurance coverage for inpatient rehab",
    "insurance coverage for outpatient treatment programs",
    "DUI expungement process and eligibility in various states",
    "court card signing rules and requirements for AA meetings",
    "AA success rate statistics from peer-reviewed studies",
    "AA dropout rate statistics and long-term retention data",
    "SMART Recovery vs AA effectiveness comparison in clinical studies",
    "Rational Recovery program history, philosophy, and techniques",
    "LifeRing secular recovery approach and meeting structure",
    "dual diagnosis treatment protocols for co-occurring disorders",
    "CBT vs 12-step facilitation therapy outcomes comparison",
    "medical management of alcohol withdrawal syndrome (AWS) protocol",
    "naltrexone vs acamprosate vs disulfiram efficacy comparison",
    "Suboxone induction protocol and monitoring requirements for OUD",
    "methadone clinic regulations and federal dosing guidelines",
    "The Sinclair Method for alcohol use disorder protocol and evidence",
    "harm reduction vs abstinence-based approaches research evidence",
    "court-mandated AA attendance constitutionality and legal issues",
    "probation requirements for alcohol-related first offenses",
    "employer drug testing policies and employee rights in recovery",
    "FMLA leave eligibility for substance abuse treatment",
    "ADA protections for people with substance use disorder history",
    "state licensing requirements for addiction counselors",
    "adolescent substance use treatment program standards and outcomes",
    "elderly alcohol abuse prevalence rates and treatment adaptation",
    "pregnancy and medication-assisted treatment guidelines and safety",
    "genetic predisposition to alcoholism family studies and research",
    "brain chemistry changes and neuroplasticity in long-term recovery",
    "trauma-informed care approaches in addiction treatment settings",
    "patient brokering and unethical practices in the rehab industry",
    "faith-based vs secular treatment outcome comparison studies",
    "LGBTQ+ specific recovery programs availability and resources",
    "how to become a certified addiction counselor state requirements",
    "water heater sediment flushing frequency and maintenance tips",
]

def generate_negative(topic: str, used_questions: set) -> str | None:
    sys_prompt = (
        "You are generating 'negative' eval questions for a RAG system over "
        "recovery/AA literature. These are questions the corpus cannot answer.\n"
        f"Topic: {topic}\n\n"
        "Rules:\n"
        "- Output ONLY the question text (10-25 words).\n"
        "- Make it sound like a genuine user inquiry.\n"
        "- Be specific and concise."
    )
    for attempt in range(3):
        q = call_dsv4(
            f"Generate a concise negative eval question about: {topic}",
            system=sys_prompt, temp=0.7 + attempt * 0.15, max_tokens=150,
        )
        if q and q not in used_questions:
            return q
    return None

def fix_negatives(rows: list[dict]) -> int:
    used = set(r["question"] for r in rows if r["kind"] == "negative")
    neg_indices = [(i, r) for i, r in enumerate(rows) if r["kind"] == "negative"]

    offtopic = sum(
        1 for _, r in neg_indices
        if not any(kw in r["question"].lower() for kw in RECOVERY_LEXICON)
    )
    print(f"  Off-topic to fix: {offtopic}/{len(neg_indices)}", flush=True)

    fixed = 0
    topic_idx = 0
    for idx, row in neg_indices:
        q_lower = row["question"].lower()
        if any(kw in q_lower for kw in RECOVERY_LEXICON):
            print(f"  [skip] {row['id']} already recovery-adjacent", flush=True)
            continue

        topic = NEGATIVE_TOPICS[topic_idx % len(NEGATIVE_TOPICS)]
        topic_idx += 1

        print(f"  {row['id']} topic='{topic[:50]}'...", flush=True)
        new_q = generate_negative(topic, used)
        if new_q:
            rows[idx]["question"] = new_q
            used.add(new_q)
            fixed += 1
            is_rec = any(kw in new_q.lower() for kw in RECOVERY_LEXICON)
            print(f"    {'RECOVERY' if is_rec else 'ANCHOR'}: {new_q[:120]}", flush=True)
        else:
            print(f"    FAILED", flush=True)
    return fixed

# =========================================================================
# Main
# =========================================================================
def main():
    ensure_cache_db()
    doc_titles = load_doc_titles()

    with open(Q_PATH) as f:
        rows = [json.loads(line) for line in f if line.strip()]

    print(f"Loaded {len(rows)} rows", flush=True)
    kinds = Counter(r["kind"] for r in rows)
    for k, c in sorted(kinds.items()):
        print(f"  {k}: {c}", flush=True)

    # Phase 1: Crosswork
    cw_defective = sum(1 for r in rows if r["kind"] == "crosswork" and has_deixis(r["question"]))
    print(f"\n=== Phase 1: Crosswork ({cw_defective} defective) ===", flush=True)
    cw_fixed = fix_crosswork(rows, doc_titles)
    print(f"  Fixed: {cw_fixed}", flush=True)
    _save(rows)

    # Verify crosswork
    remaining_cw = [r for r in rows if r["kind"] == "crosswork" and has_deixis(r["question"])]
    if remaining_cw:
        print(f"  WARNING: {len(remaining_cw)} crosswork rows still have deixis!", file=sys.stderr, flush=True)
        for r in remaining_cw:
            print(f"    {r['id']}: {r['question'][:100]}", file=sys.stderr, flush=True)

    # Phase 2: Negatives
    neg_needed = sum(
        1 for r in rows if r["kind"] == "negative"
        and not any(kw in r["question"].lower() for kw in RECOVERY_LEXICON)
    )
    print(f"\n=== Phase 2: Negatives ({neg_needed} to regenerate) ===", flush=True)
    if neg_needed > 0:
        neg_fixed = fix_negatives(rows)
        print(f"  Fixed: {neg_fixed}", flush=True)
        _save(rows)
    else:
        print(f"  None needed", flush=True)

    # Final summary
    final_negs = [r for r in rows if r["kind"] == "negative"]
    offtopic = [r for r in final_negs if not any(kw in r["question"].lower() for kw in RECOVERY_LEXICON)]
    print(f"\n{'='*60}", flush=True)
    print(f"RESULTS", flush=True)
    print(f"  Crosswork deixis remaining: {len(remaining_cw)}/41", flush=True)
    print(f"  Off-topic negatives: {len(offtopic)}/{len(final_negs)} (max 5 allowed)", flush=True)
    print(f"  Kinds: {dict(sorted(Counter(r['kind'] for r in rows).items()))}", flush=True)

    for r in offtopic:
        print(f"  OFFTOPIC: {r['id']}: {r['question'][:120]}", flush=True)

    if remaining_cw or len(offtopic) > 5:
        print("SOME CHECKS FAILED", file=sys.stderr, flush=True)
        return 1

    # Delete checkpoint if exists
    ckpt = REPO_ROOT / "finetune" / "eval" / ".fix_a1_checkpoint.json"
    if ckpt.exists():
        ckpt.unlink()

    print("\nALL CHECKS PASSED", flush=True)
    return 0


def _save(rows: list[dict]):
    with open(Q_PATH, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  Saved {len(rows)} rows", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
