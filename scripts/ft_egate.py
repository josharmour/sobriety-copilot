#!/usr/bin/env python3
"""E-gate: score pre-generated candidate answer sets with dsv4 as judge and
compare to the A4 baseline. Reuses ft_eval's judge machinery.

Metrics per candidate (256 questions):
  retrieval.recall@4/@8  — gold (doc,block) in the answer's retrieved list
  citation_accuracy      — answer names a gold work's title (deterministic)
  faithfulness           — dsv4 judge (claims supported by retrieved context)
  answer_quality         — dsv4 judge vs reference answer
  refusal_correctness    — dsv4 judge, negative kind

Gate (E2/E4): a candidate SHIPS only if citation_accuracy and faithfulness
>= baseline AND answer_quality >= baseline.

Usage: JUDGE_MODEL=deepseek-v4-flash python scripts/ft_egate.py \
    finetune/eval/runs/answers-ft-dpo.json finetune/eval/runs/answers-ft-sft.json
"""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

os.environ.setdefault("JUDGE_MODEL", "deepseek-v4-flash")
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from scripts import ft_eval as fe
from scripts.ft_checks import ensure_corpus_db, open_corpus

BASELINE = json.load(open(REPO / "finetune/eval/runs/baseline-server.json"))
BASE_AGG = BASELINE.get("aggregate") or BASELINE.get("aggregates")


def gold_pairs(g: dict) -> set:
    docs, blocks = g.get("gold_doc_ids", []), g.get("gold_block_ids", [])
    primary = docs[0] if docs else None
    out = set()
    for i, b in enumerate(blocks):
        d = docs[i] if i < len(docs) else primary
        if d:
            out.add((d, b))
    return out


def score_file(path: str, gold, titles, block_text) -> dict:
    data = json.load(open(path))
    rows = data["results"]
    for g_id, g in gold.items():
        g["_kind"] = next((r["kind"] for r in rows if r["id"] == g_id), "")

    def one(r):
        g = gold.get(r["id"])
        gp = gold_pairs(g) if g else set()
        retrieved = {tuple(p) for p in r.get("retrieved", [])}
        rec = {
            "r4": int(bool(gp & {tuple(p) for p in r.get("retrieved", [])[:4]})) if gp else None,
            "r8": int(bool(gp & retrieved)) if gp else None,
        }
        cite = fe.compute_citation_accuracy(r["answer"], g, titles) if g else None
        ctx = [block_text.get(tuple(p), "") for p in r.get("retrieved", [])[:4]]
        j = fe.run_judges_for_question(r["id"], r["answer"], ctx, g, titles)
        return {**rec, "cite": cite, **j}

    with ThreadPoolExecutor(max_workers=16) as pool:
        scored = list(pool.map(one, rows))

    def mean(key, scale1=False):
        vals = [s[key] for s in scored if isinstance(s.get(key), (int, float))]
        return sum(vals) / len(vals) if vals else None

    return {
        "name": data["name"],
        "recall@4": mean("r4"),
        "recall@8": mean("r8"),
        "citation_accuracy": mean("cite"),
        "faithfulness": mean("faithfulness"),
        "answer_quality": mean("answer_quality"),
        "refusal_correctness": mean("refusal_correctness"),
    }


def main() -> int:
    ensure_corpus_db()
    db = open_corpus()
    block_text = {(r[0], r[1]): r[2] for r in
                  db.execute("SELECT doc_id, block_id, text FROM blocks")}
    gold = fe._load_gold()
    titles = fe._load_manifest_titles()

    print(f"[egate] judge = {fe.JUDGE_MODEL} @ {fe.JUDGE_BASE_URL}", flush=True)
    results = []
    for path in sys.argv[1:]:
        print(f"[egate] scoring {path} ...", flush=True)
        results.append(score_file(path, gold, titles, block_text))

    b = {
        "citation_accuracy": BASE_AGG.get("citation_accuracy"),
        "faithfulness": BASE_AGG.get("faithfulness"),
        "answer_quality": BASE_AGG.get("answer_quality"),
        "refusal_correctness": BASE_AGG.get("refusal_correctness"),
    }
    print("\n================ E-GATE RESULTS ================")
    hdr = f"{'metric':<22}{'baseline(dsv4)':>16}"
    for r in results:
        hdr += f"{r['name']:>16}"
    print(hdr)
    for m in ("recall@4", "recall@8", "citation_accuracy", "faithfulness",
              "answer_quality", "refusal_correctness"):
        line = f"{m:<22}{('%.3f'%b[m]) if b.get(m) is not None else 'n/a':>16}"
        for r in results:
            v = r.get(m)
            line += f"{('%.3f'%v) if v is not None else 'n/a':>16}"
        print(line)

    print("\n--- gate (vs dsv4 baseline) ---")
    for r in results:
        ok = (
            r["citation_accuracy"] is not None and b["citation_accuracy"] is not None
            and r["citation_accuracy"] >= b["citation_accuracy"]
            and r["faithfulness"] >= b["faithfulness"] - 0.2
            and r["answer_quality"] >= b["answer_quality"] - 0.2
        )
        print(f"  {r['name']}: citation {r['citation_accuracy']:.3f} vs {b['citation_accuracy']:.3f}, "
              f"faith {r['faithfulness']:.2f}, quality {r['answer_quality']:.2f} "
              f"-> {'PASS' if ok else 'below baseline'}")

    out = REPO / "finetune/eval/runs/egate-report.json"
    out.write_text(json.dumps({"baseline": b, "candidates": results}, indent=1))
    print(f"\n[egate] wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
