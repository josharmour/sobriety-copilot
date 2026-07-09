#!/usr/bin/env python3
"""FT-B5 verification: pack v3 carries the fine-tuned retriever vectors,
one per corpus block, at dim 768, and stamps pack_version 3."""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

from scripts.ft_checks import ensure_corpus_db, open_corpus, register

REPO = Path(__file__).resolve().parent.parent
PACK = REPO / "packs" / "library-v3.scpack"


@register("b5")
def check_b5(args: list[str]) -> int:
    errors: list[str] = []
    if not PACK.is_file():
        print(f"  FAIL: {PACK} missing", file=sys.stderr)
        return 1
    z = zipfile.ZipFile(PACK)
    pack = json.loads(z.read("pack.json"))
    if pack.get("pack_version") != 3:
        errors.append(f"pack_version {pack.get('pack_version')} != 3")
    for f in ("vectors/vectors.i8", "vectors/vectors.idx", "vectors/vectors.meta.json"):
        if f not in z.namelist():
            errors.append(f"missing {f}")
    meta = json.loads(z.read("vectors/vectors.meta.json"))
    if meta["dim"] != 768:
        errors.append(f"dim {meta['dim']} != 768")
    if "fine-tuned" not in meta["model"].lower() and "retriever/model" not in meta["model"]:
        errors.append(f"vectors not from fine-tuned model: {meta['model']}")

    ensure_corpus_db()
    db = open_corpus()
    n_blocks = db.execute("SELECT COUNT(*) FROM blocks").fetchone()[0]
    i8 = z.read("vectors/vectors.i8")
    n_vec = len(i8) // (768)  # int8, 1 byte/dim
    if n_vec != n_blocks:
        errors.append(f"vector count {n_vec} != corpus blocks {n_blocks}")
    if meta["count"] != n_blocks:
        errors.append(f"meta count {meta['count']} != corpus blocks {n_blocks}")

    if errors:
        for e in errors:
            print(f"  FAIL: {e}", file=sys.stderr)
        return 1
    print(f"B5 OK — pack v3: {n_vec} fine-tuned vectors dim 768, one per block, version 3")
    return 0
