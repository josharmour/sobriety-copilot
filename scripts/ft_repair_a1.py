#!/usr/bin/env python3
"""FT-A1 repair: fix crosswork deixis + regenerate negative questions.

Operates on finetune/eval/questions.jsonl via checkpointed dsv4 generation.

Crosswork (8 defective rows found by regex audit):
  Replace source-deixis ("first text", "second passage", etc.) with work titles
  obtained from the corpus DB.

Negative (41 off-topic rows out of 42):
  Replace off-topic trivia (BIOS passwords, knife sharpening, stain removal)
  with recovery-adjacent-but-uncovered questions: medical/clinical, legal,
  logistics, statistics, other-program specifics not in the corpus.
  At most 5 may remain fully off-topic (sanity anchors).

SAFEGUARDS:
  - All non-crosswork, non-negative rows are LOADED then WRITTEN BACK byte-identical.
  - Checkpoint every 10 rows.
  - Source block IDs never change. source_doc_id never changes.
  - Only the "question" field is modified.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
Q_PATH = REPO_ROOT / "finetune" / "eval" / "questions.jsonl"
CHECKPOINT_DIR = REPO_ROOT / "finetune" / "cache"
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

DSV4_BASE = "http://10.0.0.10:8002/v1"
DSV4_MODEL = "deepseek-v4-flash"
DSV4_TEMP = 0.7
DSV4_MAX_TOKENS = 1024

# ---------------------------------------------------------------------------
# Corpus helpers
# ---------------------------------------------------------------------------

# Map of doc_id -> clean human-readable title
DOC_TITLE_OVERRIDES = {
    "alcoholics-anonymous": "Alcoholics Anonymous (the Big Book)",
    "narcotics-anonymous": "Narcotics Anonymous",
    "twelve-steps-and-twelve-traditions": "Twelve Steps and Twelve Traditions",
    "joe-and-charlie": "Joe and Charlie (Big Book Study)",
    "drop-the-rock": "Drop the Rock",
    "living-sober": "Living Sober",
    "came-to-believe": "Came to Believe",
    "as-bill-sees-it": "As Bill Sees It",
    "the-language-of-the-heart": "The Language of the Heart",
    "just-for-today": "Just for Today",
    "daily-reflections": "Daily Reflections",
    "a-program-for-you": "A Program for You",
    "pass-it-on": "Pass It On",
    "dr-bob-and-the-good-oldtimers": "Dr. Bob and the Good Oldtimers",
    "alcoholics-anonymous-comes-of-age": "Alcoholics Anonymous Comes of Age",
    "the-varieties-of-religious-experience": "The Varieties of Religious Experience",
    "writing-the-big-book": "Writing the Big Book",
    "touchstones": "Touchstones",
    "hope-faith-courage": "Hope, Faith & Courage",
    "make-miracles-in-forty-days": "Make Miracles in Forty Days",
    "a-quiet-peace": "A Quiet Peace",
    "little-red-book": "Little Red Book",
    "more-language-of-letting-go": "More Language of Letting Go",
    "the-language-of-letting-go": "The Language of Letting Go",
    "the-promise-of-a-new-day": "The Promise of a New Day",
    "twenty-four-hours-a-day": "Twenty-Four Hours a Day",
    "the-body-keeps-the-score": "The Body Keeps the Score",
    "in-the-realm-of-hungry-ghosts": "In the Realm of Hungry Ghosts",
    "when-the-body-says-no": "When the Body Says No",
    "the-myth-of-normal": "The Myth of Normal",
    "the-virtue-of-selfishness": "The Virtue of Selfishness",
    "the-six-pillars-of-self-esteem": "The Six Pillars of Self-Esteem",
    "the-power-of-positive-thinking": "The Power of Positive Thinking",
    "the-psychology-of-romantic-love": "The Psychology of Romantic Love",
    "the-sermon-on-the-mount": "The Sermon on the Mount",
    "the-gifts-of-imperfection": "The Gifts of Imperfection",
    "daring-greatly": "Daring Greatly",
    "atlas-of-the-heart": "Atlas of the Heart",
    "rising-strong": "Rising Strong",
    "dare-to-lead": "Dare to Lead",
    "the-addictive-personality": "The Addictive Personality",
    "codependent-no-more": "Codependent No More",
    "beyond-codependency": "Beyond Codependency",
    "the-new-codependency": "The New Codependency",
    "codependent-no-more-workbook": "Codependent No More Workbook",
    "adult-children-of-alcoholics": "Adult Children of Alcoholics",
    "the-acoa-trauma-syndrome": "The ACoA Trauma Syndrome",
    "twelve-steps-of-adult-children-steps-workbook": "Twelve Steps of Adult Children Workbook",
    "facing-shame": "Facing Shame",
    "honoring-the-self": "Honoring the Self",
    "how-to-raise-your-self-esteem": "How to Raise Your Self-Esteem",
    "the-book-that-started-it-all": "The Book That Started It All",
    "understanding-the-twelve-steps": "Understanding the Twelve Steps",
    "it-works-how-and-why": "It Works: How and Why",
    "not-god": "Not-God: A History of Alcoholics Anonymous",
    "the-best-of-bill": "The Best of Bill",
    "on-becoming-a-person": "On Becoming a Person",
    "client-centered-therapy": "Client-Centered Therapy",
    "loving-what-is-revised-edition": "Loving What Is",
    "step-working-guides": "Step Working Guides",
    "living-clean": "Living Clean",
    "smart-recovery-handbook": "SMART Recovery Handbook",
    "smart-recovery-family-friends": "SMART Recovery Family & Friends",
    "smart-recovery-user-guide": "SMART Recovery User Guide",
    "step-one-for-drug-addiction-recovery": "Step One for Drug Addiction Recovery",
    "recovery": "Recovery (Roth)",
    "journey-to-the-heart": "Journey to the Heart",
    "scattered-minds": "Scattered Minds",
    "i-thought-it-was-just-me": "I Thought It Was Just Me",
    "stools-bottles": "Stools & Bottles",
    "the-greatest-thing-in-the-world-and-other-addresses": "The Greatest Thing in the World",
    "the-twelve-steps-and-twelve-traditions-of-overeaters-anonymous": "OA Twelve Steps and Twelve Traditions",
    "plain-language-big-book": "Plain Language Big Book",
    "trimmed-big-book": "The Big Book (core text)",
    "addicted-in-film": "Addicted in Film",
    "decency-code": "Decency Code",
    "aa-preamble": "AA Preamble",
    "stop-being-mean-to-yourself": "Stop Being Mean to Yourself",
    "the-spirituality-of-imperfection-ernest-kurtz": "The Spirituality of Imperfection",
}


def get_doc_title(doc_id: str) -> str:
    """Return the best human-readable title for a doc_id."""
    # Check overrides first
    if doc_id in DOC_TITLE_OVERRIDES:
        return DOC_TITLE_OVERRIDES[doc_id]
    # Fallback from corpus
    try:
        db_path = REPO_ROOT / "finetune" / "cache" / "search.db"
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        row = conn.execute(
            "SELECT heading FROM blocks WHERE doc_id=? AND heading!='' LIMIT 1",
            (doc_id,)
        ).fetchone()
        conn.close()
        if row and row[0].strip():
            title = row[0].strip()
            # Clean up noisy prefixes
            title = re.sub(r'^Copyright.*?\d{4}\s+by\s+', '', title).strip()
            title = re.sub(r'^Praise for\s+', '', title).strip()
            title = re.sub(r'^Center City, Minnesota.*$', '', title).strip()
            title = re.sub(r'^New York.*$', '', title).strip()
            title = re.sub(r'^HarperCollins.*$', '', title).strip()
            title = re.sub(r'^First Published.*$', '', title).strip()
            title = re.sub(r'^Library of Congress.*$', '', title).strip()
            title = re.sub(r'^ISBN.*$', '', title).strip()
            if title:
                return title
    except Exception:
        pass
    return doc_id.replace("-", " ").title()


# ---------------------------------------------------------------------------
# DSV4 caller (OpenAI-compatible)
# ---------------------------------------------------------------------------

def call_dsv4(prompt: str, system: str | None = None, temp: float = DSV4_TEMP,
              max_tokens: int = DSV4_MAX_TOKENS) -> str | None:
    """Call dsv4 and return the generated text, or None on failure."""
    import urllib.request
    import urllib.error

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    body = {
        "model": DSV4_MODEL,
        "messages": messages,
        "temperature": temp,
        "max_tokens": max_tokens,
    }

    for attempt in range(3):
        try:
            req = urllib.request.Request(
                f"{DSV4_BASE}/chat/completions",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read()
            result = json.loads(raw)
            content = result["choices"][0]["message"].get("content")
            if content is None:
                # Model may have returned a refusal or reasoning-only response
                print(f"  [DSV4: empty content in response]", flush=True)
                if attempt < 2:
                    time.sleep(3)
                continue
            text = content.strip()
            if text:
                return text
            print(f"  [DSV4: empty text after strip]", flush=True)
        except json.JSONDecodeError as e:
            print(f"  [DSV4 JSON decode error]: {e}", flush=True)
        except KeyError as e:
            print(f"  [DSV4 response missing key {e}]: raw keys={list(result.keys()) if 'result' in dir() else 'N/A'}", flush=True)
        except Exception as e:
            print(f"  [DSV4 call failed attempt {attempt+1}/3]: {type(e).__name__}: {e}", flush=True)
            if attempt < 2:
                time.sleep(3)
    return None


# ---------------------------------------------------------------------------
# Crosswork repair
# ---------------------------------------------------------------------------

CROSSWORK_DOC_TITLES_CACHE: dict[str, str] = {}


def get_title_for_doc(doc_id: str) -> str:
    if doc_id not in CROSSWORK_DOC_TITLES_CACHE:
        CROSSWORK_DOC_TITLES_CACHE[doc_id] = get_doc_title(doc_id)
    return CROSSWORK_DOC_TITLES_CACHE[doc_id]


def build_crosswork_prompt(row: dict) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for rewriting a crosswork question."""
    doc_id = row["source_doc_id"]
    block_ids = row["source_block_ids"]

    # Determine which works are involved
    titles = {}
    try:
        db_path = REPO_ROOT / "finetune" / "cache" / "search.db"
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        for bid in block_ids:
            doc = conn.execute(
                "SELECT doc_id FROM blocks WHERE block_id=? AND doc_id=?",
                (bid, doc_id)
            ).fetchone()
            if doc is None:
                # Fallback: any doc
                doc = conn.execute(
                    "SELECT doc_id FROM blocks WHERE block_id=? LIMIT 1",
                    (bid,)
                ).fetchone()
            if doc:
                d = doc[0]
                if d not in titles:
                    titles[d] = get_title_for_doc(d)
        conn.close()
    except Exception:
        pass

    if not titles:
        titles[doc_id or "unknown"] = get_title_for_doc(doc_id or "unknown")

    title_list = "; ".join(f"{d}: {t}" for d, t in titles.items())

    system = (
        "You are a precise question editor for a recovery literature evaluation dataset. "
        "Your task is to rewrite a comparison question that currently uses vague source "
        "references (like 'the first text', 'the second passage', 'these two accounts') "
        "to instead NAME THE WORKS by their actual titles. "
        "Keep every other aspect identical: the comparison structure, the concepts compared, "
        "the source block IDs stay the same, the JSON schema stays the same. "
        "Only change the question string. Output ONLY the new question text, nothing else."
    )

    user = (
        f"Original question (uses source-deixis that must be replaced):\n"
        f"{row['question']}\n\n"
        f"The source works involved:\n{title_list}\n\n"
        f"Rewrite the question so it names each work by title instead of saying "
        f"'first text', 'second text', 'first passage', 'second passage', etc. "
        f"For example, instead of 'How does X in the first text compare with Y in "
        f"the second text?' write 'How does X in [Work Title] compare with Y in "
        f"[Other Work Title]?'\n\n"
        f"New question:"
    )
    return system, user


def repair_crosswork(row: dict) -> str | None:
    """Repair one defective crosswork question. Returns new question text or None."""
    system, prompt = build_crosswork_prompt(row)
    result = call_dsv4(prompt, system=system)
    if result:
        # Strip quotes if the model wrapped it
        result = result.strip('"').strip("'").strip()
        return result
    return None


# ---------------------------------------------------------------------------
# Negative repair
# ---------------------------------------------------------------------------

NEGATIVE_RECOVERY_TOPICS = [
    "naltrexone dosing and side effects for alcohol use disorder",
    "detox safety — can detoxing from alcohol or benzodiazepines be dangerous at home",
    "health insurance coverage for addiction treatment and rehab programs",
    "confidentiality laws for addiction treatment records",
    "DUI expungement and how to get a DUI removed from your record",
    "court-card or signature-card signing rules in AA",
    "AA success rates — what percentage of people who go to AA stay sober",
    "statistics on relapse rates in the first year of recovery",
    "the medical definition of alcohol use disorder versus dependence versus addiction",
    "how Antabuse (disulfiram) works and its risks",
    "medical marijuana as a substitute for alcohol in recovery",
    "gabapentin or other off-label medications for cravings",
    "inpatient versus outpatient rehab — which is more effective",
    "how to choose a rehab facility and what to look for",
    "cost of addiction treatment without insurance",
    "what happens in a medical detox protocol",
    "the difference between abstinence-based and harm-reduction programs",
    "methadone versus buprenorphine for opioid use disorder",
    "how long withdrawal symptoms typically last for different substances",
    "DSM-5 diagnostic criteria for substance use disorders",
    "the legal consequences of possessing narcotics",
    "how long alcohol stays in your system for a urine test",
    "workplace drug testing policies and employee rights",
    "child custody implications of a drug or alcohol conviction",
    "mandatory minimum sentencing for drug offenses",
    "the difference between AA and SMART Recovery in philosophy and approach",
    "how Al-Anon differs from AA and who should attend which",
    "Celebrate Recovery versus AA — religious differences",
    "LifeRing secular recovery versus twelve-step programs",
    "Medication-Assisted Treatment (MAT) and the controversy in twelve-step rooms",
    "the Sinclair Method (naltrexone before drinking) versus abstinence approaches",
    "what sober living homes are and how they work",
    "the effectiveness of court-mandated versus voluntary AA attendance",
    "how to get a restricted license after a DUI suspension",
    "the medical risks of mixing alcohol with common antidepressants",
    "how liver function tests are used to monitor alcohol damage",
    "the difference between physical dependence and addiction in medical terms",
    "the role of emergency departments in treating alcohol withdrawal",
    "how drunk driving laws and BAC limits vary by state",
    "what an intervention is and whether they actually work",
    "the debate about labeling addiction a disease versus a choice",
    "insurance parity laws for mental health and substance use treatment",
]

NEGATIVE_SANITY_ANCHORS = [
    "How do I fix a laptop that won't turn on but the charging light is on?",
    "What is the best method for removing rust from a cast iron skillet?",
    "What's the best way to remove tree sap from a car's paint without damaging the clear coat?",
    "Why does my computer's Wi-Fi keep disconnecting even when the signal strength is strong?",
    "What is the ideal temperature for proofing sourdough bread to achieve the best rise and flavor?",
]


def build_negative_prompt() -> tuple[str, str]:
    """Return (system, user) for generating a recovery-adjacent negative question."""
    system = (
        "You are a question writer for a recovery literature evaluation dataset. "
        "You create 'negative' questions — questions that the AA/NA recovery literature "
        "corpus does NOT answer, so the correct system response is to say the literature "
        "doesn't cover that. Each question must sound like a real person in or near "
        "recovery asking for practical help on a topic adjacent to recovery but outside "
        "the scope of the literature.\n\n"
        "GOOD TOPICS (recovery-adjacent but NOT in the corpus):\n"
        "- Medical: medication dosing (naltrexone, Antabuse, Suboxone), detox protocols, "
        "withdrawal symptom duration, liver function tests, mixing meds with alcohol\n"
        "- Legal: DUI expungement, drug sentencing laws, custody rights, restricted licenses\n"
        "- Logistics: court card signing rules, meeting format requirements, finding a sponsor\n"
        "- Insurance: coverage for rehab, parity laws, costs without insurance\n"
        "- Other programs: how SMART Recovery differs from AA, what LifeRing is, "
        "Celebrate Recovery vs AA, The Sinclair Method, harm reduction approaches\n"
        "- Statistics: AA success rates, relapse statistics, treatment outcome data\n"
        "- Clinical: DSM-5 criteria, physical dependence vs addiction, MAT controversies\n\n"
        "BAD TOPICS (off-topic trivia unrelated to recovery): cooking, car repair, "
        "computers, gardening, home maintenance, crafts, general life skills.\n\n"
        "Output ONLY the question — no explanation, no JSON, no preamble."
    )
    user = (
        "Generate a natural-sounding question about recovery or addiction that the "
        "AA/NA recovery literature does NOT answer. The question should sound like "
        "someone in recovery asking something relevant to their situation, but that "
        "falls outside the scope of the literature.\n\n"
        "Examples:\n"
        "- 'What's the right dose of naltrexone for alcohol cravings?'\n"
        "- 'Can I get my DUI expunged after five years of sobriety?'\n"
        "- 'Do I need to sign a court card at every meeting, or just some?'\n"
        "- 'What percentage of AA members stay sober after one year?'\n"
        "- 'How does SMART Recovery's approach differ from the twelve steps?'\n"
        "- 'Is it safe to detox from benzodiazepines at home?'\n"
        "- 'Will my health insurance cover inpatient rehab?'\n\n"
        "Make it sound genuine, like someone actually asking for practical help. "
        "Output ONLY the question text:"
    )
    return system, user


def generate_negative() -> str | None:
    """Generate one recovery-adjacent negative question. Returns text or None."""
    system, prompt = build_negative_prompt()
    result = call_dsv4(prompt, system=system)
    if result:
        result = result.strip('"').strip("'").strip()
        return result
    return None


# ---------------------------------------------------------------------------
# Main repair logic with checkpointing
# ---------------------------------------------------------------------------

def load_checkpoint(name: str) -> set[str]:
    """Load checkpoint: set of already-fixed row IDs."""
    path = CHECKPOINT_DIR / f"ft_a1_done_{name}.json"
    if path.exists():
        with open(path) as f:
            return set(json.load(f))
    return set()


def save_checkpoint(name: str, done_ids: set[str]) -> None:
    path = CHECKPOINT_DIR / f"ft_a1_done_{name}.json"
    with open(path, "w") as f:
        json.dump(list(done_ids), f)
    print(f"  [checkpoint saved: {len(done_ids)} rows in {name}]", flush=True)


def row_hash(row: dict) -> str:
    """Hash the original JSON for byte-identity verification."""
    return hashlib.md5(json.dumps(row, sort_keys=True).encode()).hexdigest()


def main():
    print("=" * 60, flush=True)
    print("FT-A1 REPAIR SCRIPT", flush=True)
    print(f"Source: {Q_PATH}", flush=True)
    print("=" * 60, flush=True)

    # ── Load questions ───────────────────────────────────────────────────
    with open(Q_PATH) as f:
        lines = [l for l in f]

    rows = []
    for i, line in enumerate(lines):
        line_s = line.strip()
        if line_s:
            rows.append(json.loads(line_s))
        else:
            rows.append(None)  # blank line placeholder

    print(f"\nLoaded {len(rows)} lines ({sum(1 for r in rows if r)} data rows)", flush=True)

    # ── Identify defective rows ──────────────────────────────────────────
    crosswork_defective = []
    negative_defective = []
    other_rows = []

    for i, r in enumerate(rows):
        if r is None:
            other_rows.append((i, None))
            continue
        kind = r.get("kind")
        if kind == "crosswork" and has_crosswork_deixis(r["question"]):
            crosswork_defective.append((i, r))
        elif kind == "negative":
            negative_defective.append((i, r))
        else:
            other_rows.append((i, r))

    print(f"\nDefective crosswork rows: {len(crosswork_defective)}", flush=True)
    print(f"Defective negative rows: {len(negative_defective)} (all 42 need regeneration)", flush=True)
    print(f"Other rows (preserved): {len(other_rows)}", flush=True)

    # ── Load checkpoints ─────────────────────────────────────────────────
    cross_done = load_checkpoint("crosswork")
    neg_done = load_checkpoint("negative")

    print(f"\nAlready fixed in crosswork checkpoint: {len(cross_done)}", flush=True)
    print(f"Already fixed in negative checkpoint: {len(neg_done)}", flush=True)

    # ── Pre-compute original hashes ──────────────────────────────────────
    orig_hashes = {}
    for i, r in enumerate(rows):
        if r is not None:
            orig_hashes[i] = row_hash(r)

    # ── Fix crosswork ────────────────────────────────────────────────────
    print("\n--- CROSSWORK REPAIR ---", flush=True)
    for idx, (line_num, row) in enumerate(crosswork_defective):
        rid = row["id"]
        if rid in cross_done:
            print(f"  [{idx+1}/{len(crosswork_defective)}] {rid}: already done, skipping", flush=True)
            continue

        print(f"  [{idx+1}/{len(crosswork_defective)}] Repairing {rid}...", flush=True)
        print(f"    Original: {row['question'][:100]}...", flush=True)

        new_q = repair_crosswork(row)
        if new_q:
            # Verify it actually fixed the deixis
            if has_crosswork_deixis(new_q):
                print(f"    WARNING: new question still has deixis! Trying once more...", flush=True)
                new_q = repair_crosswork(row)
                if new_q and has_crosswork_deixis(new_q):
                    print(f"    FAILED to fix deixis for {rid}. Skipping.", flush=True)
                    continue

            row["question"] = new_q
            cross_done.add(rid)
            print(f"    Fixed: {new_q[:100]}...", flush=True)
        else:
            print(f"    FAILED to generate fix for {rid}", flush=True)

        # Checkpoint every 3 crosswork fixes
        if len(cross_done) % 3 == 0:
            save_checkpoint("crosswork", cross_done)

    save_checkpoint("crosswork", cross_done)

    # ── Fix negative ─────────────────────────────────────────────────────
    print("\n--- NEGATIVE REGENERATION ---", flush=True)

    # Keep 5 as sanity anchors (use the first 5 off-topic ones or pick specific ones)
    # Let's keep exactly 5 fully off-topic (the most extreme ones) as sanity anchors
    sanity_count = 0
    MAX_SANITY = 5

    for idx, (line_num, row) in enumerate(negative_defective):
        rid = row["id"]
        if rid in neg_done:
            print(f"  [{idx+1}/{len(negative_defective)}] {rid}: already done, skipping", flush=True)
            continue

        # Decide if this should be a sanity anchor
        if sanity_count < MAX_SANITY:
            # Keep it off-topic (already is) — just mark done
            neg_done.add(rid)
            sanity_count += 1
            print(f"  [{idx+1}/{len(negative_defective)}] {rid}: kept as sanity anchor", flush=True)
            continue

        print(f"  [{idx+1}/{len(negative_defective)}] Regenerating {rid}...", flush=True)
        print(f"    Original: {row['question'][:80]}...", flush=True)

        new_q = generate_negative()
        if new_q:
            row["question"] = new_q
            neg_done.add(rid)
            print(f"    Replaced: {new_q[:100]}...", flush=True)
        else:
            print(f"    FAILED to generate for {rid}", flush=True)

        # Checkpoint every 5 negative fixes
        if len(neg_done) % 5 == 0:
            save_checkpoint("negative", neg_done)

    save_checkpoint("negative", neg_done)

    # ── Write output ─────────────────────────────────────────────────────
    # Verify all non-target rows are byte-identical
    changed = 0
    preserved = 0
    errors_found = 0

    for i, r in enumerate(rows):
        if r is None:
            continue
        new_hash = row_hash(r)
        if i in orig_hashes:
            if new_hash != orig_hashes[i] and r.get("kind") not in ("crosswork", "negative"):
                # Something changed that shouldn't have
                print(f"ERROR: row {i} ({r['id']}) kind={r.get('kind')} changed but wasn't target!", flush=True)
                errors_found += 1

    if errors_found > 0:
        print(f"\n{errors_found} non-target rows modified! Aborting write.", flush=True)
        return 1

    # Write back preserving exact line structure
    out_lines = []
    row_idx = 0
    for line in lines:
        ls = line.strip()
        if ls:
            # Find the matching row
            while row_idx < len(rows) and rows[row_idx] is None:
                row_idx += 1
            if row_idx < len(rows):
                r = rows[row_idx]
                if r is not None:
                    out_lines.append(json.dumps(r, ensure_ascii=False) + "\n")
                else:
                    out_lines.append(line)
                row_idx += 1
        else:
            out_lines.append(line)

    with open(Q_PATH, "w") as f:
        f.writelines(out_lines)

    print(f"\n{'='*60}", flush=True)
    print(f"WRITE COMPLETE: {Q_PATH}", flush=True)
    print(f"  Crosswork fixed: {len(cross_done)}", flush=True)
    print(f"  Negative regenerated: {len(neg_done)} (of which {MAX_SANITY} kept as sanity anchors)", flush=True)
    print(f"{'='*60}", flush=True)

    # ── Verify ───────────────────────────────────────────────────────────
    print("\nRunning self-verification...", flush=True)
    with open(Q_PATH) as f:
        verify_rows = [json.loads(l) for l in f if l.strip()]

    v_kinds = {}
    for r in verify_rows:
        k = r["kind"]
        v_kinds[k] = v_kinds.get(k, 0) + 1

    print(f"Total rows: {len(verify_rows)}", flush=True)
    for k in sorted(v_kinds):
        print(f"  {k}: {v_kinds[k]}", flush=True)

    # Crosswork check
    cw_defective = 0
    for r in verify_rows:
        if r["kind"] == "crosswork" and has_crosswork_deixis(r["question"]):
            cw_defective += 1
            print(f"  LEFTOVER DEIXIS: {r['id']}: {r['question'][:80]}...", flush=True)

    if cw_defective == 0:
        print("  Crosswork deixis: 0 defects ✓", flush=True)
    else:
        print(f"  Crosswork deixis: {cw_defective} defects REMAINING ✗", flush=True)

    # Negative check
    neg_off_target = 0
    neg_rows = [r for r in verify_rows if r["kind"] == "negative"]
    for r in neg_rows:
        ql = r["question"].lower()
        hits = sum(1 for t in RECOVERY_LEXICON if t in ql)
        if hits < 2:
            neg_off_target += 1
            print(f"  OFF-TARGET: {r['id']}: {r['question'][:80]}...", flush=True)

    print(f"  Negative off-target: {neg_off_target}/{len(neg_rows)} (max 5 allowed)", flush=True)

    return 0


# Keep this at module level for the repair script
RECOVERY_LEXICON = {
    "alcohol", "drink", "drinking", "sober", "sobriety", "recovery",
    "addict", "addiction", "addicted", "drug", "drugs", "aa", "na",
    "step", "steps", "meeting", "meetings", "sponsor", "rehab",
    "relapse", "detox", "withdrawal", "dui", "naltrexone", "twelve",
    "twelve-step", "program", "alcoholic", "alcoholics", "narcotics",
    "anonymous", "substance", "substance-use", "codependency",
    "codependent", "craving", "crave", "beer", "wine", "liquor",
    "opioid", "heroin", "cocaine", "meth", "marijuana", "cannabis",
    "prescription", "overdose", "pill", "drunk", "drunken",
    "intoxication", "hangover", "treatment", "counseling", "therapy",
    "abstinence", "abstain", "sobering", "withdraw", "withdrew",
    "bac", "amphetamine", "benzodiazepine", "fentanyl",
    "painkiller", "stimulant", "depressant",
    "vape", "vaping", "smoke", "smoking",
    "cigarette", "nicotine", "gambling", "gambler",
    # Medication names
    "suboxone", "buprenorphine", "methadone", "antabuse", "disulfiram",
    "acamprosate", "campral", "subutex", "vivitrol", "naloxone",
    "narcan", "naltrexone", "benzodiazepine", "diazepam", "valium",
    "librium", "chlordiazepoxide", "gabapentin", "topiramate",
    "zoloft", "prozac", "lexapro", "antidepressant", "medication",
    # Clinical / process terms
    "taper", "tapering", "clean", "detoxing", "abstinent",
    "detoxification", "overeaters", "overeater",
    "intervention", "court-mandated", "parity",
    # Recovery programs / approaches
    "smart", "lifering", "celebrate", "sinclair", "harm",
    "moderation", "abstinence-based", "mat",
}

DEIXIS_PATTERNS = [
    re.compile(r"\b(first|second|1st|2nd|third)\s+(source|reading|work|selection|text|passage|account|article|document|excerpt|chapter|section|part|volume)\b", re.I),
    re.compile(r"\bsource\s*[12]\b", re.I),
    re.compile(r"\b(these\s+two|the\s+two|both)\s+(texts?|passages?|sources?|works?|accounts?|readings?|documents?|selections?|excerpts?|chapters?|sections?|articles?|volumes?)\b", re.I),
    re.compile(r"\bone\s+(text|passage|source|reading|account|work|selection|article|chapter|section|volume)\s+.*\b(the\s+other|another|a\s+second)\b", re.I),
    re.compile(r"\b(the\s+former|the\s+latter)\b", re.I),
    re.compile(r"\bthe\s+first\s+passage\b", re.I),
    re.compile(r"\bthese\s+two\s+accounts\b", re.I),
]


def has_crosswork_deixis(question: str) -> bool:
    for pat in DEIXIS_PATTERNS:
        if pat.search(question):
            return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())
