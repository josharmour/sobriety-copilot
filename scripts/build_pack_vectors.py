#!/usr/bin/env python3
"""Precompute EmbeddingGemma vectors for the offline pack's FTS blocks.

Reads every (doc_id, block_id, text) row from a pack's search.db, embeds the
text with EmbeddingGemma-300m (768-dim, official document prompt), L2-
normalizes, and int8-quantizes at a fixed scale. Emits three files that get
zipped into the v2 pack alongside search.db + manifests:

  vectors.i8       raw int8 blob, row-major, DIM per row, aligned to `order`
  vectors.idx      newline-joined "doc_id\\tblock_id", one per row
  vectors.meta.json  {dim, count, scale, model, prompt_name}

On-device: embed the query with the SAME model (retrievalQuery prompt),
L2-normalize, int8-quantize at the same scale, then rank by integer dot
product. Because both sides are unit vectors quantized identically, the
integer dot product is monotonic in cosine similarity.

Usage:
  python -m scripts.build_pack_vectors --db <search.db> --out <dir> [--limit N]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import struct
import sys
import time
from pathlib import Path

MODEL_ID = "google/embeddinggemma-300m"
DIM = 768
SCALE = 127.0  # unit-vector components live in [-1, 1]
BATCH = 512


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="path to the pack's search.db")
    ap.add_argument("--out", required=True, help="output directory for vectors.*")
    ap.add_argument("--limit", type=int, default=0, help="embed only first N rows (proof runs)")
    ap.add_argument("--device", default="cuda", help="cuda | cpu")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(args.db)
    q = "SELECT doc_id, block_id, text FROM blocks ORDER BY rowid"
    if args.limit:
        q += f" LIMIT {args.limit}"
    rows = conn.execute(q).fetchall()
    conn.close()
    print(f"[vectors] {len(rows)} blocks to embed", flush=True)

    # Lazy imports so the script only needs torch when actually run.
    import numpy as np
    from sentence_transformers import SentenceTransformer

    t0 = time.monotonic()
    model = SentenceTransformer(MODEL_ID, device=args.device)
    print(f"[vectors] model loaded in {time.monotonic()-t0:.0f}s", flush=True)

    i8_path = out / "vectors.i8"
    idx_lines: list[str] = []
    written = 0
    with open(i8_path, "wb") as fout:
        for start in range(0, len(rows), BATCH):
            chunk = rows[start:start + BATCH]
            texts = [r[2] or "" for r in chunk]
            # encode_document applies EmbeddingGemma's official document
            # prompt ("title: none | text: ..."), matching flutter_gemma.
            emb = model.encode_document(
                texts,
                normalize_embeddings=True,
                convert_to_numpy=True,
                batch_size=BATCH,
            ).astype(np.float32)
            if emb.shape[1] != DIM:
                print(f"[vectors] FATAL dim={emb.shape[1]} != {DIM}", file=sys.stderr)
                return 1
            q8 = np.clip(np.round(emb * SCALE), -127, 127).astype(np.int8)
            fout.write(q8.tobytes())
            for r in chunk:
                idx_lines.append(f"{r[0]}\t{r[1]}")
            written += len(chunk)
            if start % (BATCH * 20) == 0:
                rate = written / max(1e-6, time.monotonic() - t0)
                eta = (len(rows) - written) / max(1e-6, rate)
                print(f"[vectors] {written}/{len(rows)}  {rate:.0f}/s  eta {eta/60:.1f}m",
                      flush=True)

    (out / "vectors.idx").write_text("\n".join(idx_lines), encoding="utf-8")
    (out / "vectors.meta.json").write_text(json.dumps({
        "dim": DIM,
        "count": written,
        "scale": SCALE,
        "dtype": "int8",
        "model": MODEL_ID,
        "prompt": "document",
        "layout": "row-major, DIM int8 per row, aligned to vectors.idx",
    }), encoding="utf-8")

    size_mb = i8_path.stat().st_size / 1e6
    print(f"[vectors] wrote {written} vectors ({size_mb:.1f} MB) in "
          f"{(time.monotonic()-t0)/60:.1f}m", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
