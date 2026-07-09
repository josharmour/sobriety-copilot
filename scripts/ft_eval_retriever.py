#!/usr/bin/env python3
"""FT-B4: dense-retrieval recall eval for the base vs fine-tuned
EmbeddingGemma, on the A1/A2 eval set. Isolates the fine-tuning effect and
gates against the A4 baseline.

Embeds all corpus blocks with each model (DOC_PREFIX), embeds the 256 eval
questions (QUERY_PREFIX), computes recall@4/@8 (gold (doc_id, block_id) in
top-k — doc-scoped, bare ids collide across docs).

Writes finetune/eval/runs/b4-retriever.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import torch
from sentence_transformers import SentenceTransformer

REPO = Path(__file__).resolve().parent.parent
QUESTIONS = REPO / "finetune" / "eval" / "questions.jsonl"
GOLD = REPO / "finetune" / "eval" / "gold.jsonl"
FT_MODEL = REPO / "finetune" / "retriever" / "model"
OUT = REPO / "finetune" / "eval" / "runs" / "b4-retriever.json"

QUERY_PREFIX = "task: search result | query: "
DOC_PREFIX = "title: none | text: "
BASE = "google/embeddinggemma-300m"


def load_corpus():
    sys.path.insert(0, str(REPO))
    from scripts.ft_checks import ensure_corpus_db, open_corpus
    ensure_corpus_db()
    db = open_corpus()
    rows = db.execute("SELECT doc_id, block_id, text FROM blocks").fetchall()
    ids = [(r[0], r[1]) for r in rows]
    texts = [DOC_PREFIX + (r[2] or "") for r in rows]
    return ids, texts


def load_eval():
    qs = [json.loads(l) for l in open(QUESTIONS) if l.strip()]
    gold = {}
    for l in open(GOLD):
        if not l.strip():
            continue
        r = json.loads(l)
        docs = r.get("gold_doc_ids", [])
        blocks = r.get("gold_block_ids", [])
        primary = docs[0] if docs else None
        pairs = set()
        for i, b in enumerate(blocks):
            d = docs[i] if i < len(docs) else primary
            if d:
                pairs.add((d, b))
        gold[r["id"]] = pairs
    return qs, gold


def eval_model(model_path: str, ids, texts, qs, gold, device):
    m = SentenceTransformer(model_path, device=device)
    m.max_seq_length = 512
    print(f"  embedding {len(texts)} corpus blocks with {model_path} ...", flush=True)
    corpus_emb = m.encode(
        texts, batch_size=128, normalize_embeddings=True,
        convert_to_tensor=True, show_progress_bar=True,
    )
    # eval only the questions that have gold blocks (skip negatives: empty gold)
    evalq = [q for q in qs if gold.get(q["id"])]
    q_texts = [QUERY_PREFIX + q["question"] for q in evalq]
    q_emb = m.encode(q_texts, batch_size=128, normalize_embeddings=True, convert_to_tensor=True)

    id_index = {p: i for i, p in enumerate(ids)}
    sims = q_emb @ corpus_emb.T           # (Q, N)
    top8 = torch.topk(sims, k=8, dim=1).indices.cpu().tolist()

    hit4 = hit8 = 0
    per_kind: dict[str, list[int]] = {}
    for row, tk in zip(evalq, top8):
        gset = gold[row["id"]]
        gold_idx = {id_index[p] for p in gset if p in id_index}
        h8 = int(bool(gold_idx & set(tk)))
        h4 = int(bool(gold_idx & set(tk[:4])))
        hit8 += h8
        hit4 += h4
        per_kind.setdefault(row["kind"], []).append(h8)
    n = len(evalq)
    del corpus_emb, q_emb, sims
    torch.cuda.empty_cache()
    return {
        "n": n,
        "recall@4": hit4 / n,
        "recall@8": hit8 / n,
        "recall@8_by_kind": {k: sum(v) / len(v) for k, v in per_kind.items()},
    }


def main() -> int:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    ids, texts = load_corpus()
    qs, gold = load_eval()
    print(f"[b4] corpus={len(ids)} blocks, eval questions with gold={sum(1 for q in qs if gold.get(q['id']))}")

    print("[b4] === BASE EmbeddingGemma ===")
    base = eval_model(BASE, ids, texts, qs, gold, device)
    print(f"  base recall@4={base['recall@4']:.4f} recall@8={base['recall@8']:.4f}")

    print("[b4] === FINE-TUNED ===")
    ft = eval_model(str(FT_MODEL), ids, texts, qs, gold, device)
    print(f"  fine-tuned recall@4={ft['recall@4']:.4f} recall@8={ft['recall@8']:.4f}")

    # A4 baseline (BM25 retriever)
    bm25 = json.load(open(REPO / "finetune" / "eval" / "runs" / "baseline-retriever.json"))
    bm25_agg = bm25.get("aggregate") or bm25.get("aggregates") or {}
    result = {
        "base_dense": base,
        "finetuned_dense": ft,
        "bm25_baseline": {
            "recall@4": bm25_agg.get("retrieval.recall@4"),
            "recall@8": bm25_agg.get("retrieval.recall@8"),
        },
        "delta_ft_vs_base_recall@8": ft["recall@8"] - base["recall@8"],
    }
    OUT.write_text(json.dumps(result, indent=1))
    print(f"[b4] wrote {OUT}")
    print(f"[b4] delta (ft - base) recall@8 = {result['delta_ft_vs_base_recall@8']:+.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
