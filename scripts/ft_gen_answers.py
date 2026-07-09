#!/usr/bin/env python3
"""Generate a candidate generator's answers on the 256-question eval set,
using the production-style RAG path: fine-tuned retriever (hybrid dense+BM25)
selects top-k passages, the model answers grounded in them. Saves a run file
for the dsv4 E-gate judge.

Corpus embeddings (fine-tuned retriever) are cached so a second model run is
fast. Usage:
  python scripts/ft_gen_answers.py --model /home/joshu/ft-runs/final-model \
      --name ft-dpo --topk 4
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
QUESTIONS = REPO / "finetune" / "eval" / "questions.jsonl"
GOLD = REPO / "finetune" / "eval" / "gold.jsonl"
FT_RETRIEVER = Path("/home/joshu/ft-runs/eval-assets/retriever-model")  # local (CIFS stalls parallel reads)
LOCAL_DB = "/home/joshu/ft-runs/eval-assets/search.db"
EMB_CACHE = Path("/home/joshu/ft-runs/corpus_ft_emb.pt")
RUNS = REPO / "finetune" / "eval" / "runs"
QUERY_PREFIX = "task: search result | query: "
DOC_PREFIX = "title: none | text: "
RRF_K = 60
STOP = set("the a an of to and or in on at for is are was how do i what my me".split())

SYSTEM = (
    "You are a knowledgeable, direct guide to recovery literature. Lead with "
    "the answer, ground it in the provided passages, name the work you rely on "
    "by its exact title, never use bracketed citations or file names, and "
    "never claim personal recovery experience. If the passages do not cover "
    "the question, say so plainly."
)


def bm25(db, query, k=50):
    words = [w for w in re.findall(r"[a-z']+", query.lower()) if w not in STOP and len(w) > 2]
    if not words:
        return []
    try:
        rows = db.execute(
            "SELECT doc_id, block_id FROM blocks WHERE blocks MATCH ? ORDER BY rank LIMIT ?",
            (" OR ".join(words[:12]), k)).fetchall()
    except Exception:
        return []
    return [(r[0], r[1]) for r in rows]


def rrf(*rankings):
    s = {}
    for r in rankings:
        for i, it in enumerate(r):
            s[it] = s.get(it, 0.0) + 1.0 / (RRF_K + i + 1)
    return sorted(s, key=s.get, reverse=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--topk", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    import torch
    import sqlite3
    db = sqlite3.connect(LOCAL_DB)  # local copy — avoids CIFS read stalls
    rows = db.execute("SELECT doc_id, block_id, heading, text FROM blocks").fetchall()
    ids = [(r[0], r[1]) for r in rows]
    texts = {(r[0], r[1]): (r[2], r[3]) for r in rows}

    from sentence_transformers import SentenceTransformer
    ret = SentenceTransformer(str(FT_RETRIEVER), device="cuda")
    ret.max_seq_length = 512
    if EMB_CACHE.exists():
        print(f"[gen] loading cached corpus embeddings {EMB_CACHE}", flush=True)
        corpus_emb = torch.load(EMB_CACHE).cuda()
    else:
        print(f"[gen] embedding {len(ids)} corpus blocks (fine-tuned retriever)", flush=True)
        corpus_emb = ret.encode([DOC_PREFIX + (texts[i][1] or "") for i in ids],
                                batch_size=128, normalize_embeddings=True,
                                convert_to_tensor=True, show_progress_bar=True)
        torch.save(corpus_emb.cpu(), EMB_CACHE)

    qs = [json.loads(l) for l in open(QUESTIONS) if l.strip()]
    if args.limit:
        qs = qs[:args.limit]
    q_emb = ret.encode([QUERY_PREFIX + q["question"] for q in qs],
                       batch_size=128, normalize_embeddings=True, convert_to_tensor=True)
    dense_top = torch.topk(q_emb @ corpus_emb.T, k=50, dim=1).indices.cpu().tolist()
    del ret, corpus_emb, q_emb
    torch.cuda.empty_cache()

    # Load generator
    from unsloth import FastLanguageModel
    model, tok = FastLanguageModel.from_pretrained(
        args.model, max_seq_length=4096, dtype=torch.bfloat16, load_in_4bit=False)
    FastLanguageModel.for_inference(model)

    results = []
    for n, (q, dt) in enumerate(zip(qs, dense_top), 1):
        dense = [ids[i] for i in dt]
        hybrid = rrf(bm25(db, q["question"]), dense)[:args.topk]
        ctx = "\n\n".join(
            f'From "{texts[p][0] or p[0]}":\n{texts[p][1]}' for p in hybrid if p in texts)
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Relevant passages:\n{ctx}\n\nQuestion: {q['question']}"}]
        prompt = tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)
        inp = tok(text=prompt, return_tensors="pt").to(model.device)
        out = model.generate(**inp, max_new_tokens=512, do_sample=False,
                             repetition_penalty=1.1, pad_token_id=tok.eos_token_id)
        ans = tok.decode(out[0][inp["input_ids"].shape[1]:], skip_special_tokens=True).strip()
        results.append({"id": q["id"], "kind": q["kind"], "question": q["question"],
                        "answer": ans, "retrieved": [list(p) for p in hybrid]})
        if n % 25 == 0:
            print(f"[gen] {n}/{len(qs)}", flush=True)

    RUNS.mkdir(parents=True, exist_ok=True)
    out_path = RUNS / f"answers-{args.name}.json"
    out_path.write_text(json.dumps({"model": args.model, "name": args.name,
                                    "results": results}, indent=1))
    print(f"[gen] wrote {out_path} ({len(results)} answers)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
