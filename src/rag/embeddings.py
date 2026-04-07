"""Centralized embedding model for RAG pipeline using nomic-embed-text-v1.5."""

import numpy as np
from sentence_transformers import SentenceTransformer

MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"
DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "

_model = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME, trust_remote_code=True, device="cpu")
    return _model


# Truncate to ~500 words before embedding — captures the topic without
# choking CPU on 1500-word large chunks through the full transformer.
MAX_EMBED_WORDS = 500


def embed_documents(texts: list[str], batch_size: int = 64) -> np.ndarray:
    prefixed = []
    for t in texts:
        words = t.split()
        truncated = " ".join(words[:MAX_EMBED_WORDS]) if len(words) > MAX_EMBED_WORDS else t
        prefixed.append(DOCUMENT_PREFIX + truncated)
    return get_model().encode(prefixed, batch_size=batch_size, show_progress_bar=True)


def embed_query(query: str) -> list[float]:
    return get_model().encode(QUERY_PREFIX + query).tolist()
