#!/usr/bin/env python3
"""Re-index all documents into a shadow ChromaDB collection (768-dim).

Creates/shadow-swaps into `recovery_literature_gemma_v1` using the fine-tuned
EmbeddingGemma retriever served by the embed microservice.

Checkpointing: saves progress to a JSON file so the script can resume if
interrupted during the long (~40+ min) embedding phase.

Usage (from within app container):
    python3 scripts/cloud_reindex.py [--force]

    Without --force: skips if the shadow collection already exists and is
    non-empty (assumes it's the result of a previous complete index).
    With --force: deletes and rebuilds from scratch.
"""

from __future__ import annotations

import json
import os
import sys
import time

# Ensure the app's source is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.rag.chroma_client import create_chroma_client
from src.rag.indexer import RAGIndexer

SHADOW_COLLECTION = "recovery_literature_gemma_v1"
CHECKPOINT_FILE = "/tmp/cloud_reindex_checkpoint.json"
DOCUMENTS_DIR = os.environ.get("DOCUMENTS_DIR", "/app/documents")


def load_checkpoint() -> dict:
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE) as f:
            return json.load(f)
    return {}


def save_checkpoint(data: dict) -> None:
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(data, f, indent=2)
    print(f"[CHECKPOINT] Saved: {json.dumps(data, default=str)[:200]}", flush=True)


def main():
    force = "--force" in sys.argv

    print("=" * 60, flush=True)
    print(f"Cloud Re-index: {SHADOW_COLLECTION}", flush=True)
    print(f"  Documents dir: {DOCUMENTS_DIR}", flush=True)
    print(f"  Force rebuild: {force}", flush=True)
    print("=" * 60, flush=True)

    # ------------------------------------------------------------------
    # Phase 1: Create/recreate the shadow collection
    # ------------------------------------------------------------------
    client = create_chroma_client("rag_db")
    # List existing collections
    existing_names = {c.name for c in client.list_collections()}
    print(f"Existing collections: {sorted(existing_names)}", flush=True)

    if SHADOW_COLLECTION in existing_names:
        existing_count = next(c.count() for c in client.list_collections() if c.name == SHADOW_COLLECTION)
        print(f"Shadow collection '{SHADOW_COLLECTION}' exists with {existing_count} chunks.", flush=True)

        if existing_count > 0 and not force:
            print("Non-empty and --force not given. Skipping (re-run with --force to rebuild).", flush=True)
            return

        if force:
            print(f"Deleting collection '{SHADOW_COLLECTION}' (--force)...", flush=True)
            client.delete_collection(SHADOW_COLLECTION)
        else:
            # Empty collection from a previous aborted run; recreate
            print(f"Empty collection — recreating clean slate.", flush=True)
            client.delete_collection(SHADOW_COLLECTION)

    # Create fresh 768-dim collection
    client.create_collection(
        name=SHADOW_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )
    print(f"Created new collection '{SHADOW_COLLECTION}' (768-dim)", flush=True)

    # ------------------------------------------------------------------
    # Phase 2: Index all documents into the shadow collection
    # ------------------------------------------------------------------
    indexer = RAGIndexer(
        db_path="rag_db",
        collection_name=SHADOW_COLLECTION,
    )

    t0 = time.time()
    chunk_count = indexer.index_directory(DOCUMENTS_DIR)
    elapsed = time.time() - t0

    print("=" * 60, flush=True)
    print(f"INDEX COMPLETE: {chunk_count} chunks in {elapsed:.0f}s", flush=True)
    print(f"Collection: {SHADOW_COLLECTION}", flush=True)

    # ------------------------------------------------------------------
    # Phase 3: Verify
    # ------------------------------------------------------------------
    col = client.get_collection(SHADOW_COLLECTION)
    final_count = col.count()
    print(f"Final count from ChromaDB: {final_count} chunks", flush=True)

    # Spot-check embedding dimension
    sample = col.get(limit=1, include=["embeddings"])
    if sample["embeddings"]:
        dim = len(sample["embeddings"][0])
        print(f"Vector dimension: {dim}", flush=True)
        assert dim == 768, f"Expected 768-dim, got {dim}!"
        print("✓ 768-dim verified", flush=True)
    else:
        print("WARNING: no embeddings stored in collection", flush=True)

    # Clean up checkpoint file (successful completion)
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
        print("Checkpoint file cleaned up.", flush=True)

    print(f"\nDONE in {elapsed:.0f}s ({elapsed/60:.1f} min)", flush=True)


if __name__ == "__main__":
    main()
