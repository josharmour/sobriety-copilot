#!/usr/bin/env python3
"""FT-B3: fine-tune EmbeddingGemma on the recovery corpus (D1 window, GPU0).

Design choices (documented per spec):
- FULL fine-tune, not LoRA: 300M params on a 96 GB card — VRAM is not the
  constraint, and full FT is the stronger option.
- MultipleNegativesRankingLoss over (anchor, positive, neg1..neg4): B2
  provides 4 BM25-hard negatives per query; MNRL adds in-batch negatives.
- Legacy fit()/DataLoader path instead of SentenceTransformerTrainer: the
  `datasets` library crashes on Python 3.14 (Pickler._batch_setitems
  signature change breaks InMemoryTable serialization), so we avoid it.
- Prompt-prefix parity with production: queries 'task: search result |
  query: ', passages 'title: none | text: ' — identical to the app and
  scripts/build_pack_vectors.py. Train like we infer.

Outputs:
- finetune/retriever/model/    (checkpoint, gitignored)
- finetune/retriever/metrics.json (loss curve + dev rank@1 before/after)
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import torch
from torch.utils.data import DataLoader
from sentence_transformers import InputExample, SentenceTransformer
from sentence_transformers.losses import MultipleNegativesRankingLoss

REPO = Path(__file__).resolve().parent.parent.parent
TRIPLETS = REPO / "finetune" / "retriever" / "triplets.jsonl"
OUT_DIR = REPO / "finetune" / "retriever" / "model"
METRICS = REPO / "finetune" / "retriever" / "metrics.json"

QUERY_PREFIX = "task: search result | query: "
DOC_PREFIX = "title: none | text: "

BATCH = 32
EPOCHS = 2
LR = 2e-5
MAX_SEQ = 512
DEV_N = 1000
SEED = 20260708

LOSS_LOG: list[dict] = []


class LossRecorder(MultipleNegativesRankingLoss):
    def forward(self, *a, **kw):
        out = super().forward(*a, **kw)
        LOSS_LOG.append(float(out.detach().cpu()))
        return out


def load_examples() -> list[InputExample]:
    examples = []
    with open(TRIPLETS) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            negs = r["neg_blocks"][:4]
            if len(negs) < 4:
                continue
            examples.append(
                InputExample(
                    texts=[
                        QUERY_PREFIX + r["query"],
                        DOC_PREFIX + r["pos_block"]["text"],
                        *(DOC_PREFIX + n["text"] for n in negs),
                    ]
                )
            )
    return examples


@torch.no_grad()
def dev_rank1(model: SentenceTransformer, dev: list[InputExample]) -> float:
    """Fraction of dev rows where the positive outranks all 4 hard negatives."""
    hits = 0
    for i in range(0, len(dev), 64):
        chunk = dev[i : i + 64]
        queries = [e.texts[0] for e in chunk]
        cands = [t for e in chunk for t in e.texts[1:]]
        qv = model.encode(queries, convert_to_tensor=True, normalize_embeddings=True)
        cv = model.encode(cands, convert_to_tensor=True, normalize_embeddings=True)
        cv = cv.reshape(len(chunk), 5, -1)
        sims = torch.einsum("bd,bcd->bc", qv, cv)
        hits += int((sims.argmax(dim=1) == 0).sum())
    return hits / len(dev)


def main() -> int:
    print(f"[b3] torch {torch.__version__}, cuda={torch.cuda.is_available()}")
    examples = load_examples()
    print(f"[b3] {len(examples)} rows loaded")
    random.Random(SEED).shuffle(examples)
    dev, train = examples[:DEV_N], examples[DEV_N:]

    model = SentenceTransformer(
        "google/embeddinggemma-300m",
        model_kwargs={
            "torch_dtype": torch.bfloat16,
            # eager attention OOMs 96 GB at batch 32×6 texts; sdpa is memory-safe
            "attn_implementation": "sdpa",
        },
    )
    model.max_seq_length = MAX_SEQ
    model[0].auto_model.gradient_checkpointing_enable(
        gradient_checkpointing_kwargs={"use_reentrant": False}
    )

    before = dev_rank1(model, dev)
    print(f"[b3] dev rank@1 BEFORE: {before:.4f}", flush=True)

    loader = DataLoader(train, shuffle=True, batch_size=BATCH, drop_last=True)
    loss = LossRecorder(model)
    warmup = int(0.05 * len(loader) * EPOCHS)
    model.fit(
        train_objectives=[(loader, loss)],
        epochs=EPOCHS,
        warmup_steps=warmup,
        optimizer_params={"lr": LR},
        scheduler="warmupcosine",
        output_path=None,
        show_progress_bar=True,
        use_amp=False,
    )

    model.save_pretrained(str(OUT_DIR))
    print(f"[b3] saved to {OUT_DIR}")

    after = dev_rank1(model, dev)
    print(f"[b3] dev rank@1 AFTER: {after:.4f}")

    thin = LOSS_LOG[:: max(1, len(LOSS_LOG) // 400)]
    METRICS.write_text(
        json.dumps(
            {
                "train_rows": len(train),
                "dev_rows": len(dev),
                "batch": BATCH,
                "epochs": EPOCHS,
                "lr": LR,
                "max_seq": MAX_SEQ,
                "dev_rank1_before": before,
                "dev_rank1_after": after,
                "loss_first_50_mean": sum(LOSS_LOG[:50]) / max(1, len(LOSS_LOG[:50])),
                "loss_last_50_mean": sum(LOSS_LOG[-50:]) / max(1, len(LOSS_LOG[-50:])),
                "loss_curve_thinned": thin,
            },
            indent=1,
        )
    )
    print(f"[b3] metrics written to {METRICS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
