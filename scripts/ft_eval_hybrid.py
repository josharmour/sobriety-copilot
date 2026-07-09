#!/usr/bin/env python3
"""FT-B4 (hybrid): the number that actually ships. Compares recall@8 of
BM25-alone vs hybrid(base-dense + BM25) vs hybrid(ft-dense + BM25), fused
with reciprocal-rank fusion (k=60), on the eval set. This mirrors the
on-device / production hybrid retrieval.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import torch
from sentence_transformers import SentenceTransformer

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from scripts.ft_checks import ensure_corpus_db, open_corpus

QUESTIONS = REPO / "finetune" / "eval" / "questions.jsonl"
GOLD = REPO / "finetune" / "eval" / "gold.jsonl"
FT_MODEL = REPO / "finetune" / "retriever" / "model"
BASE = "google/embeddinggemma-300m"
QUERY_PREFIX = "task: search result | query: "
DOC_PREFIX = "title: none | text: "
RRF_K = 60
STOP = set("the a an of to and or in on at for is are was how do i what my me".split())


def load_eval():
    qs = [json.loads(l) for l in open(QUESTIONS) if l.strip()]
    gold = {}
    for l in open(GOLD):
        if not l.strip():
            continue
        r = json.loads(l)
        docs, blocks = r.get("gold_doc_ids", []), r.get("gold_block_ids", [])
        primary = docs[0] if docs else None
        pairs = set()
        for i, b in enumerate(blocks):
            d = docs[i] if i < len(docs) else primary
            if d:
                pairs.add((d, b))
        gold[r["id"]] = pairs
    return qs, gold


def bm25_topk(db, query, k=50):
    words = [w for w in re.findall(r"[a-z']+", query.lower()) if w not in STOP and len(w) > 2]
    if not words:
        return []
    match = " OR ".join(words[:12])
    try:
        rows = db.execute(
            "SELECT doc_id, block_id FROM blocks WHERE blocks MATCH ? "
            "ORDER BY rank LIMIT ?", (match, k),
        ).fetchall()
    except Exception:
        return []
    return [(r[0], r[1]) for r in rows]


def rrf(*rankings):
    scores = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            scores[item] = scores.get(item, 0.0) + 1.0 / (RRF_K + rank + 1)
    return sorted(scores, key=scores.get, reverse=True)


def dense_topk_all(model_path, ids, texts, q_texts, device, k=50):
    m = SentenceTransformer(model_path, device=device)
    m.max_seq_length = 512
    corpus = m.encode(texts, batch_size=128, normalize_embeddings=True,
                      convert_to_tensor=True, show_progress_bar=True)
    q = m.encode(q_texts, batch_size=128, normalize_embeddings=True, convert_to_tensor=True)
    top = torch.topk(q @ corpus.T, k=k, dim=1).indices.cpu().tolist()
    del corpus, q
    torch.cuda.empty_cache()
    return [[ids[i] for i in row] for row in top]


def recall_at(rankings, evalq, gold, k):
    hit = 0
    for row, ranked in zip(evalq, rankings):
        if gold[row["id"]] & set(ranked[:k]):
            hit += 1
    return hit / len(evalq)


def main() -> int:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    ensure_corpus_db()
    db = open_corpus()
    rows = db.execute("SELECT doc_id, block_id, text FROM blocks").fetchall()
    ids = [(r[0], r[1]) for r in rows]
    texts = [DOC_PREFIX + (r[2] or "") for r in rows]

    qs, gold = load_eval()
    evalq = [q for q in qs if gold.get(q["id"])]
    q_texts = [QUERY_PREFIX + q["question"] for q in evalq]
    print(f"[hybrid] corpus={len(ids)} eval={len(evalq)}", flush=True)

    bm25 = [bm25_topk(db, q["question"]) for q in evalq]
    print("[hybrid] BM25 done; embedding base dense ...", flush=True)
    base_d = dense_topk_all(BASE, ids, texts, q_texts, device)
    print("[hybrid] embedding ft dense ...", flush=True)
    ft_d = dense_topk_all(str(FT_MODEL), ids, texts, q_texts, device)

    hybrid_base = [rrf(b, d) for b, d in zip(bm25, base_d)]
    hybrid_ft = [rrf(b, d) for b, d in zip(bm25, ft_d)]

    res = {
        "bm25_only": {"recall@4": recall_at(bm25, evalq, gold, 4),
                      "recall@8": recall_at(bm25, evalq, gold, 8)},
        "hybrid_base_dense": {"recall@4": recall_at(hybrid_base, evalq, gold, 4),
                              "recall@8": recall_at(hybrid_base, evalq, gold, 8)},
        "hybrid_ft_dense": {"recall@4": recall_at(hybrid_ft, evalq, gold, 4),
                            "recall@8": recall_at(hybrid_ft, evalq, gold, 8)},
    }
    res["hybrid_ft_gain_vs_bm25_recall@8"] = (
        res["hybrid_ft_dense"]["recall@8"] - res["bm25_only"]["recall@8"])
    res["hybrid_ft_gain_vs_hybrid_base_recall@8"] = (
        res["hybrid_ft_dense"]["recall@8"] - res["hybrid_base_dense"]["recall@8"])
    out = REPO / "finetune" / "eval" / "runs" / "b4-hybrid.json"
    out.write_text(json.dumps(res, indent=1))
    for k, v in res.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
