#!/usr/bin/env python3
"""Parity test: verify embed_server.py produces embeddings matching direct SentenceTransformer usage.

Tests:
  1. Embedding dimension is 768.
  2. Cosine similarity between microservice and direct .encode() is ~1.0.
  3. Document prefix ("title: none | text: ") vs query prefix ("task: search result | query: ")
     produce different embeddings as expected.

Usage:
    # Start server first
    python scripts/embed_server.py &
    sleep 30  # wait for model load

    # Run test
    python scripts/test_embed_parity.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

import numpy as np

SERVER_URL = os.environ.get("EMBED_TEST_URL", "http://127.0.0.1:8190")
MODEL_PATH = "/home/joshu/ft-runs/eval-assets/retriever-model"

# Test texts covering different aspects of recovery literature
TEST_TEXTS = {
    "short": "The first step to recovery is to stop using.",
    "medium": (
        "We cannot expect the program to work for us if our minds and bodies "
        "are still clouded by drugs. We can do this anywhere."
    ),
    "long": (
        "When we master this technique, we'll be in a powerful position "
        "concerning love and romance. We'll stop searching desperately for "
        "someone to make us happy. We won't create roles for people to fill, "
        "like an employer taking applications. We'll stop using people like "
        "medication to calm our fears. We'll be free to enjoy love, even "
        "the romantic kind."
    ),
}


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two 1-D vectors."""
    a_norm = a / (np.linalg.norm(a) + 1e-12)
    b_norm = b / (np.linalg.norm(b) + 1e-12)
    return float(np.dot(a_norm, b_norm))


def embed_via_server(texts: list[str], input_type: str = "document") -> list[list[float]]:
    """Call the microservice POST /v1/embeddings."""
    body = json.dumps({
        "input": texts,
        "model": "fine-tuned-embeddinggemma",
        "input_type": input_type,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{SERVER_URL}/v1/embeddings",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    # Sort by index to preserve order
    data = sorted(result["data"], key=lambda x: x["index"])
    return [item["embedding"] for item in data]


def embed_direct(texts: list[str]) -> np.ndarray:
    """Load SentenceTransformer directly (no server) and encode."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(MODEL_PATH, device="cpu", trust_remote_code=True)
    return model.encode(texts, show_progress_bar=False)


def main():
    print("=" * 72)
    print("PARITY TEST: embed_server.py vs direct SentenceTransformer")
    print("=" * 72)

    # ---- Test 1: Dimension check ----
    print("\n[1/3] Dimension check...")
    sample_text = "test dimension"
    server_emb = embed_via_server([sample_text], input_type="document")[0]
    dim = len(server_emb)
    print(f"  Microservice embedding dimension: {dim}")
    assert dim == 768, f"Expected 768, got {dim}"
    print("  ✓ 768 dimensions — PASS")

    # ---- Test 2: Cosine parity (document prefix) ----
    print("\n[2/3] Cosine parity — direct .encode() vs microservice (document prefix)...")
    print(f"  Using {len(TEST_TEXTS)} test texts")

    # Build pre-prefixed texts matching what the server applies internally
    prefixed_docs = [f"title: none | text: {t}" for t in TEST_TEXTS.values()]
    prefixed_queries_list = [f"task: search result | query: {t}" for t in TEST_TEXTS.values()]

    # Direct encoding (already prefixed — the caller must prefix before calling raw model)
    direct_doc_embs = embed_direct(prefixed_docs)
    direct_query_embs = embed_direct(prefixed_queries_list)

    # Server encoding (server adds prefix internally via input_type)
    server_doc_embs = embed_via_server(list(TEST_TEXTS.values()), input_type="document")
    server_query_embs = embed_via_server(list(TEST_TEXTS.values()), input_type="query")

    results = []
    for name, direct_emb, server_emb in [
        ("documents", direct_doc_embs, server_doc_embs),
        ("queries", direct_query_embs, server_query_embs),
    ]:
        cos_sims = []
        for i in range(len(direct_emb)):
            sim = cosine_similarity(np.array(direct_emb[i]), np.array(server_emb[i]))
            cos_sims.append(sim)

        min_sim = min(cos_sims)
        mean_sim = float(np.mean(cos_sims))
        results.append((name, min_sim, mean_sim, cos_sims))

        for i, (name_key, text) in enumerate(TEST_TEXTS.items()):
            print(f"  {name}[{name_key}]:  cos_sim={cos_sims[i]:.8f}")

    for name, min_sim, mean_sim, cos_sims in results:
        status = "✓ PASS" if min_sim > 0.999 else "✗ FAIL"
        print(f"  {name}: min={min_sim:.8f}  mean={mean_sim:.8f}  — {status}")

    # ---- Test 3: Document vs query embeddings differ ----
    print("\n[3/3] Document vs query embeddings should differ (different prefixes)...")
    for name_key, text in TEST_TEXTS.items():
        # Compare server doc vs server query for each text
        doc_i = list(TEST_TEXTS.keys()).index(name_key)
        sim = cosine_similarity(
            np.array(server_doc_embs[doc_i]),
            np.array(server_query_embs[doc_i]),
        )
        msg = f"  cos_sim(document, query) [{name_key}]: {sim:.6f}"
        if sim < 0.99:
            msg += " — ✓ embeddings differ (different prefixes)"
        else:
            msg += " — ⚠ unexpectedly similar (prefixes may have small effect)"
        print(msg)

    print("\n" + "=" * 72)
    all_pass = all(min_sim > 0.999 for _, min_sim, _, _ in results)
    if all_pass:
        print("RESULT: ALL PARITY TESTS PASSED")
    else:
        print("RESULT: SOME CHECKS FAILED — see above")
        sys.exit(1)


if __name__ == "__main__":
    main()
