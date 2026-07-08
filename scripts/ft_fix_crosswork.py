#!/usr/bin/env python3
"""FT-A1 crosswork repair (Fable-run): regenerate the 41 kind=crosswork rows
so each compares TWO DISTINCT recovery-core works by title.

For each crosswork row: pick a theme, FTS-match it in two different core
docs, ask dsv4 (thinking off) for a user-register comparison question that
names both titles. Rewrites question/source_doc_id/source_doc_ids/
source_block_ids in place; all other rows byte-identical.
"""
from __future__ import annotations

import json
import random
import re
import sqlite3
import sys
import zipfile
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parent.parent
QPATH = REPO / "finetune" / "eval" / "questions.jsonl"
DB = REPO / "finetune" / "cache" / "search.db"
PACK = REPO / "packs" / "library-v1.scpack"
BASE = "http://10.0.0.10:8002/v1"
MODEL = "deepseek-v4-flash"

CORE_DOCS = [
    "alcoholics-anonymous", "twelve-steps-and-twelve-traditions",
    "daily-reflections", "living-sober", "living-clean", "as-bill-sees-it",
    "just-for-today", "narcotics-anonymous", "drop-the-rock",
    "step-working-guides", "came-to-believe", "twenty-four-hours-a-day",
    "it-works-how-and-why", "a-program-for-you",
    "alcoholics-anonymous-comes-of-age", "the-best-of-bill",
    "plain-language-big-book", "touchstones",
]

THEMES = [
    "resentment", "surrender", "amends", "prayer and meditation",
    "sponsorship", "honesty", "fear", "service", "gratitude", "relapse",
    "humility", "personal inventory", "higher power", "acceptance",
    "willingness", "forgiveness", "anonymity", "fellowship", "sobriety",
    "character defects", "spiritual awakening",
]


def titles() -> dict[str, str]:
    z = zipfile.ZipFile(PACK)
    m = json.loads(z.read("manifest-index.json"))
    items = m if isinstance(m, list) else m.get("docs") or []
    return {d["doc_id"]: d["title"] for d in items}


def fts_pick(db: sqlite3.Connection, doc: str, theme: str) -> tuple[str, str] | None:
    q = " OR ".join(w for w in re.findall(r"[a-z]+", theme) if len(w) > 3)
    try:
        rows = db.execute(
            "SELECT block_id, text FROM blocks WHERE doc_id=? AND blocks MATCH ? "
            "AND length(text) >= 200 LIMIT 20",
            (doc, q),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = db.execute(
            "SELECT block_id, text FROM blocks WHERE doc_id=? AND text LIKE ? "
            "AND length(text) >= 200 LIMIT 20",
            (doc, f"%{theme.split()[0]}%"),
        ).fetchall()
    return random.choice(rows) if rows else None


def ask(title_a: str, text_a: str, title_b: str, text_b: str, theme: str) -> str:
    prompt = (
        f'Passage from "{title_a}":\n{text_a[:900]}\n\n'
        f'Passage from "{title_b}":\n{text_b[:900]}\n\n'
        f"Write ONE question that a student of 12-step recovery literature "
        f'would ask comparing how "{title_a}" and "{title_b}" each treat '
        f"{theme}, answerable from these two passages. The question MUST name "
        f"both works by their exact titles, must make sense to someone who "
        f"has not seen the passages (no 'this passage'/'the excerpt'/'Source "
        f"1'), and must not quote the passages verbatim. Output ONLY the "
        f"question text."
    )
    r = requests.post(
        f"{BASE}/chat/completions",
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": 200,
            "chat_template_kwargs": {"thinking": False},
        },
        timeout=120,
    )
    r.raise_for_status()
    return (r.json()["choices"][0]["message"]["content"] or "").strip().strip('"')


def main() -> int:
    random.seed(20260708)
    t = titles()
    db = sqlite3.connect(DB)
    rows = [json.loads(l) for l in open(QPATH) if l.strip()]
    n_fixed = 0
    only_bad = "--only-deixis" in sys.argv
    from scripts.ft_checks_a1 import DEIXIS as _DX
    for i, row in enumerate(rows):
        if row["kind"] != "crosswork":
            continue
        if only_bad and not _DX.search(row["question"]):
            continue
        for attempt in range(6):
            theme = random.choice(THEMES)
            da, db_ = random.sample(CORE_DOCS, 2)
            pa, pb = fts_pick(db, da, theme), fts_pick(db, db_, theme)
            if not pa or not pb:
                continue
            try:
                q = ask(t.get(da, da), pa[1], t.get(db_, db_), pb[1], theme)
            except Exception as e:
                print(f"  dsv4 error: {e}", file=sys.stderr)
                continue
            if not q or len(q) < 30 or "\n" in q.strip():
                continue
            from scripts.ft_checks_a1 import DEIXIS
            if DEIXIS.search(q):
                continue
            ta, tb = t.get(da, ""), t.get(db_, "")
            if ta.lower() not in q.lower() or tb.lower() not in q.lower():
                continue
            row["question"] = q
            row["source_doc_id"] = da
            row["source_doc_ids"] = [da, db_]
            row["source_block_ids"] = [pa[0], pb[0]]
            n_fixed += 1
            print(f"[{n_fixed}] {row['id']}: {q[:100]}")
            break
        else:
            print(f"FAILED to fix {row['id']}", file=sys.stderr)
            return 1
    with open(QPATH, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Done: {n_fixed} crosswork rows rewritten, {len(rows)} total rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
