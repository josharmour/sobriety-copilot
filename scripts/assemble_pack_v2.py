#!/usr/bin/env python3
"""Assemble library-v2.scpack: the v1 pack plus precomputed semantic vectors.

Takes the existing v1 pack (manifests + search.db, unchanged) and injects the
EmbeddingGemma vector files produced by scripts/build_pack_vectors.py under
vectors/, bumping pack_version. The mobile client extracts vectors/* into its
vectors dir and enables hybrid retrieval when the embedder is installed.

Usage:
  python -m scripts.assemble_pack_v2 --v1 packs/library-v1.scpack \
      --vectors <dir with vectors.i8/.idx/.meta.json> --out packs/library-v2.scpack
"""

from __future__ import annotations

import argparse
import json
import time
import zipfile
from pathlib import Path

VECTOR_FILES = ("vectors.i8", "vectors.idx", "vectors.meta.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v1", required=True)
    ap.add_argument("--vectors", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    vdir = Path(args.vectors)
    for name in VECTOR_FILES:
        if not (vdir / name).is_file():
            raise SystemExit(f"missing {vdir / name}")

    meta = json.loads((vdir / "vectors.meta.json").read_text())
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(args.v1) as zin, zipfile.ZipFile(
        out, "w", zipfile.ZIP_DEFLATED
    ) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "pack.json":
                pack = json.loads(data)
                pack["pack_version"] = 2
                pack["created_utc"] = int(time.time())
                pack["vectors"] = {
                    "dim": meta["dim"],
                    "count": meta["count"],
                    "model": meta["model"],
                }
                data = json.dumps(pack).encode()
            zout.writestr(item, data)
        for name in VECTOR_FILES:
            # int8 blob barely compresses; store the big one uncompressed so
            # install-time unzip stays fast on-device.
            compress = (
                zipfile.ZIP_STORED if name == "vectors.i8" else zipfile.ZIP_DEFLATED
            )
            zout.write(vdir / name, f"vectors/{name}", compress_type=compress)

    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB), "
          f"{meta['count']} vectors dim={meta['dim']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
