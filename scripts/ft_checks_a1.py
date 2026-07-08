#!/usr/bin/env python3
"""FT-A1 verification (rebuilt by Fable after a worker lane weakened the
enforcement while regenerating the dataset). Registers the 'a1' check.

Enforced (hard failures):
  1. Schema: id/question/kind/source_doc_id/source_block_ids; ≥240 rows,
     ≥40 per kind; source_doc_id non-null except kind=negative.
  2. Source ids exist in search.db, doc-scoped ((doc_id, block_id) pairs —
     bare block ids collide across docs).
  3. No source deixis (broad regex, incl. Source 1 / first source variants).
  4. personal kind: 100% first-person.
  5. Quiz-register ceiling: ≤15% of non-negative questions may be
     third-person What/Which/... with no pronoun and no work title named.
  6. crosswork kind: source_doc_ids present with exactly 2 distinct docs,
     both blocks belong to those docs, and both titles appear in the text.
  7. negative kind: ≥75% recovery-adjacent (boundary probes, not trivia).
"""
from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path

from scripts.ft_checks import ensure_corpus_db, open_corpus, register

REPO = Path(__file__).resolve().parent.parent
QPATH = REPO / "finetune" / "eval" / "questions.jsonl"
PACK = REPO / "packs" / "library-v1.scpack"

KINDS = ("doctrine", "practical", "phrase", "crosswork", "personal", "negative")

DEIXIS = re.compile(
    r"\b(the|this|that)\s+(passage|excerpt|text|exercise|chapter|section|"
    r"story|essay|selection|reading|source|document)s?\b"
    r"|the authors?\b(?!\s+of\s+[\"“'])|the speaker|the writer"
    r"|according to the (excerpt|text|passage)"
    r"|\b(first|second|1st|2nd)\s+(source|reading|work|selection)\b"
    r"|\bsource\s*[12]\b|\breading\s*[12]\b",
    re.I,
)
FIRST_PERSON = re.compile(r"\b(I|I'm|I've|my|me|myself)\b")
PRONOUN = re.compile(r"\b(I|I'm|I've|my|me|myself|you|your|we|our)\b")
QUIZ_START = re.compile(r"^(What|Which|Who|When|Where)\b")
RECOVERY_ADJ = re.compile(
    r"alcohol|drink|sober|sobriety|recover|addict|drug|\bAA\b|\bNA\b|step|"
    r"meeting|sponsor|rehab|relapse|detox|withdraw|DUI|naltrexone|suboxone|"
    r"methadone|liver|twelve|program|big book|antabuse|disulfiram",
    re.I,
)


def _titles() -> dict[str, str]:
    z = zipfile.ZipFile(PACK)
    m = json.loads(z.read("manifest-index.json"))
    items = m if isinstance(m, list) else m.get("docs") or []
    return {d["doc_id"]: d["title"] for d in items}


@register("a1")
def check_a1(args: list[str]) -> int:
    errors: list[str] = []
    rows = [json.loads(l) for l in open(QPATH) if l.strip()]

    # 1. Schema + counts
    by_kind: dict[str, int] = {}
    ids = set()
    for r in rows:
        for key in ("id", "question", "kind", "source_block_ids"):
            if key not in r:
                errors.append(f"{r.get('id','?')}: missing {key}")
        if r["id"] in ids:
            errors.append(f"duplicate id {r['id']}")
        ids.add(r["id"])
        if r["kind"] not in KINDS:
            errors.append(f"{r['id']}: unknown kind {r['kind']}")
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
        if r["kind"] != "negative" and not r.get("source_doc_id"):
            errors.append(f"{r['id']}: null source_doc_id (kind={r['kind']})")
    if len(rows) < 240:
        errors.append(f"only {len(rows)} rows (need ≥240)")
    for k in KINDS:
        if by_kind.get(k, 0) < 40:
            errors.append(f"kind {k}: only {by_kind.get(k,0)} (need ≥40)")

    # 2. Source ids exist (doc-scoped)
    ensure_corpus_db()
    db = open_corpus()
    known: dict[str, set[str]] = {}

    def doc_blocks(d: str) -> set[str]:
        if d not in known:
            known[d] = {
                b for (b,) in db.execute(
                    "SELECT block_id FROM blocks WHERE doc_id=?", (d,)
                )
            }
        return known[d]

    for r in rows:
        if r["kind"] == "crosswork":
            continue  # checked in rule 6
        d = r.get("source_doc_id")
        if d:
            if not doc_blocks(d):
                errors.append(f"{r['id']}: unknown doc {d}")
                continue
            for b in r.get("source_block_ids", []):
                if b not in doc_blocks(d):
                    errors.append(f"{r['id']}: block {d}/{b} not in corpus")

    # 3. Deixis
    for r in rows:
        if DEIXIS.search(r["question"]):
            errors.append(f"{r['id']}: source deixis: {r['question'][:80]}")

    # 4. personal first-person
    for r in rows:
        if r["kind"] == "personal" and not FIRST_PERSON.search(r["question"]):
            errors.append(
                f"{r['id']}: personal not first-person: {r['question'][:80]}"
            )

    # 5. Quiz ceiling
    titles = _titles()
    title_re = re.compile(
        "|".join(re.escape(t) for t in titles.values() if len(t) > 5), re.I
    )
    nonneg = [r for r in rows if r["kind"] != "negative"]
    quiz = [
        r for r in nonneg
        if QUIZ_START.match(r["question"])
        and not PRONOUN.search(r["question"])
        and not title_re.search(r["question"])
    ]
    if nonneg and len(quiz) / len(nonneg) > 0.15:
        errors.append(
            f"quiz-register {len(quiz)}/{len(nonneg)} = "
            f"{100*len(quiz)/len(nonneg):.0f}% (ceiling 15%)"
        )

    # 6. crosswork structure
    for r in rows:
        if r["kind"] != "crosswork":
            continue
        docs = r.get("source_doc_ids") or []
        if len(set(docs)) != 2:
            errors.append(
                f"{r['id']}: crosswork needs 2 distinct docs, got {docs}"
            )
            continue
        blocks = r.get("source_block_ids", [])
        if len(blocks) != 2:
            errors.append(f"{r['id']}: crosswork needs 2 block ids")
            continue
        for d, b in zip(docs, blocks):
            if b not in doc_blocks(d):
                errors.append(f"{r['id']}: block {d}/{b} not in doc")
        q = r["question"].lower()
        for d in docs:
            t = titles.get(d, "")
            if t and t.lower() not in q:
                errors.append(f"{r['id']}: title '{t}' not named in question")

    # 7. negative adjacency
    neg = [r for r in rows if r["kind"] == "negative"]
    adj = [r for r in neg if RECOVERY_ADJ.search(r["question"])]
    if neg and len(adj) / len(neg) < 0.75:
        errors.append(f"negative recovery-adjacent {len(adj)}/{len(neg)} < 75%")

    if errors:
        for e in errors[:25]:
            print(f"  FAIL: {e}", file=sys.stderr)
        if len(errors) > 25:
            print(f"  ... and {len(errors)-25} more", file=sys.stderr)
        return 1

    print(f"A1 OK — {len(rows)} questions")
    for k in KINDS:
        print(f"  {k}: {by_kind.get(k,0)}")
    print("  Deixis violations: 0")
    print("  Personal first-person violations: 0")
    print(f"  Quiz-register pct: {100*len(quiz)/len(nonneg):.1f}% (OK)")
    print(f"  Negative recovery-adjacent: {len(adj)}/{len(neg)} (OK)")
    return 0


# The base scripts/ft_checks.py defines a legacy 'a1' check that predates
# this stricter one. When run as `python -m scripts.ft_checks`, the running
# module (__main__) and the imported scripts.ft_checks are distinct module
# objects, and the gap-filling sync never replaces an existing key — so
# force this check to win in both registries.
_main = sys.modules.get("__main__")
if _main is not None and hasattr(_main, "_CHECKS"):
    _main._CHECKS["a1"] = check_a1
import scripts.ft_checks as _ftc  # noqa: E402
_ftc._CHECKS["a1"] = check_a1
