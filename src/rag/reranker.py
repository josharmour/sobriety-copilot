"""Cross-encoder reranking on top of hybrid retrieval.

Bi-encoder embeddings and BM25 score the query and passage independently;
a cross-encoder scores them jointly, which catches relevance signals the
first pass misses. We oversample the hybrid retriever, score the candidate
pool with the cross-encoder, and trim back to top_k.

The model is lazy-loaded — the import path of `src.rag.retriever` (which
runs at server startup) doesn't pay for the cross-encoder weights until
the first chat query actually triggers reranking.

Configurable via:
- ENABLE_RERANKER   (default "1") — set to "0" to disable entirely.
- RERANKER_MODEL    (default "cross-encoder/ms-marco-MiniLM-L-6-v2").
- RERANK_OVERSAMPLE (default "3") — multiplier on top_k for the candidate
  pool the reranker chooses from.
"""

from __future__ import annotations

import os
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .retriever import RetrievalResult


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


ENABLE_RERANKER = _env_bool("ENABLE_RERANKER", True)
RERANKER_MODEL = os.environ.get("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
RERANK_OVERSAMPLE = max(1, int(os.environ.get("RERANK_OVERSAMPLE", "3")))

_model = None
_model_lock = threading.Lock()


def is_enabled() -> bool:
    return ENABLE_RERANKER


def oversample_factor() -> int:
    return RERANK_OVERSAMPLE if ENABLE_RERANKER else 1


def _get_model():
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is None:
            from sentence_transformers import CrossEncoder
            _model = CrossEncoder(RERANKER_MODEL)
    return _model


def warmup() -> None:
    """Pre-load the model. Safe to call from a lifespan task."""
    if ENABLE_RERANKER:
        try:
            _get_model()
        except Exception as exc:
            print(f"[RERANK-WARMUP-ERR] {type(exc).__name__}: {exc}", flush=True)


def rerank(query: str, results: list["RetrievalResult"], top_k: int) -> list["RetrievalResult"]:
    """Reorder results by cross-encoder relevance and trim to top_k.

    Scores against `excerpt` (the matched chunk) rather than the expanded
    parent `text` — the excerpt is what the upstream retrievers actually
    ranked, and it fits ms-marco's short-passage training distribution.

    On any model failure we fall back to the input order so the chat path
    never breaks because of reranking.
    """
    if not results or not ENABLE_RERANKER:
        return results[:top_k]

    try:
        model = _get_model()
        pairs = [(query, (r.excerpt or r.text or "")[:1500]) for r in results]
        scores = model.predict(pairs)
    except Exception as exc:
        print(f"[RERANK-ERR] {type(exc).__name__}: {exc}", flush=True)
        return results[:top_k]

    ranked = sorted(zip(results, scores), key=lambda pair: float(pair[1]), reverse=True)
    return [r for r, _ in ranked[:top_k]]
