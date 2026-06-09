"""Embedding utilities with Ollama as the default embedding backend."""

from __future__ import annotations

import os

import numpy as np
from openai import OpenAI

DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "
DEFAULT_EMBEDDING_BASE_URL = os.environ.get("LLM_BASE_URL", "http://172.20.48.1:11434/v1")
EMBEDDING_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", "ollama").lower()
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")
EMBEDDING_BASE_URL = os.environ.get("EMBEDDING_BASE_URL", DEFAULT_EMBEDDING_BASE_URL)
EMBEDDING_API_KEY = os.environ.get("EMBEDDING_API_KEY", os.environ.get("LLM_API_KEY", "ollama"))
MAX_EMBED_WORDS = int(os.environ.get("MAX_EMBED_WORDS", "320"))
MAX_EMBED_CHARS = int(os.environ.get("MAX_EMBED_CHARS", "2000"))
MIN_EMBED_WORDS = int(os.environ.get("MIN_EMBED_WORDS", "64"))
MIN_EMBED_CHARS = int(os.environ.get("MIN_EMBED_CHARS", "512"))
OLLAMA_EMBED_BATCH_SIZE = int(os.environ.get("OLLAMA_EMBED_BATCH_SIZE", "8"))

_keep_alive_raw = os.environ.get("OLLAMA_KEEP_ALIVE", "-1").strip()
try:
    EMBED_KEEP_ALIVE: int | str = int(_keep_alive_raw)
except ValueError:
    EMBED_KEEP_ALIVE = _keep_alive_raw

# vLLM rejects unknown extra_body keys; Ollama needs `keep_alive` to pin the
# model. Detect from URL, overridable via INFERENCE_BACKEND.
_embed_backend = os.environ.get("INFERENCE_BACKEND", "").strip().lower()
if not _embed_backend:
    _embed_backend = "ollama" if ":11434" in EMBEDDING_BASE_URL else "vllm"


def _embed_extra_body() -> dict:
    if _embed_backend == "ollama":
        return {"keep_alive": EMBED_KEEP_ALIVE}
    return {}

import threading

_client: OpenAI | None = None
_fallback_model = None
_fallback_model_lock = threading.Lock()


def _truncate(text: str, max_words: int, max_chars: int) -> str:
    words = text.split()
    if len(words) > max_words:
        text = " ".join(words[:max_words])

    if len(text) <= max_chars:
        return text

    shortened = text[:max_chars]
    if " " in shortened:
        shortened = shortened.rsplit(" ", 1)[0]
    shortened = shortened.strip()
    return shortened or text[:max_chars]


def _prepare_text(
    text: str,
    prefix: str,
    max_words: int = MAX_EMBED_WORDS,
    max_chars: int = MAX_EMBED_CHARS,
) -> str:
    return prefix + _truncate(text, max_words=max_words, max_chars=max_chars)


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(base_url=EMBEDDING_BASE_URL, api_key=EMBEDDING_API_KEY)
    return _client


def _get_fallback_model():
    global _fallback_model
    if _fallback_model is not None:
        return _fallback_model
    # Lock so a request arriving during the ~68s startup warmup load waits for
    # that load instead of kicking off a second concurrent one (which contends
    # for CPU and can hang both for over a minute).
    with _fallback_model_lock:
        if _fallback_model is None:
            from sentence_transformers import SentenceTransformer

            model_name = os.environ.get("SENTENCE_TRANSFORMER_MODEL", "nomic-ai/nomic-embed-text-v1.5")
            device = os.environ.get("SENTENCE_TRANSFORMER_DEVICE", "cpu")
            _fallback_model = SentenceTransformer(
                model_name,
                trust_remote_code=True,
                device=device,
            )
    return _fallback_model


def _embed_with_ollama(prepared_texts: list[str]) -> np.ndarray:
    client = _get_client()
    input_value: list[str] | str = prepared_texts if len(prepared_texts) > 1 else prepared_texts[0]
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=input_value,
        extra_body=_embed_extra_body(),
    )
    vectors = [item.embedding for item in response.data]
    return np.array(vectors, dtype=np.float32)


def _embed_single_with_retry(raw_text: str, prefix: str) -> np.ndarray:
    max_words = MAX_EMBED_WORDS
    max_chars = MAX_EMBED_CHARS
    last_error: Exception | None = None

    while True:
        prepared = _prepare_text(raw_text, prefix=prefix, max_words=max_words, max_chars=max_chars)
        try:
            return _embed_with_ollama([prepared])[0]
        except Exception as exc:
            last_error = exc
            next_words = max(MIN_EMBED_WORDS, max_words // 2) if max_words > MIN_EMBED_WORDS else max_words
            next_chars = max(MIN_EMBED_CHARS, int(max_chars * 0.7)) if max_chars > MIN_EMBED_CHARS else max_chars
            if next_words == max_words and next_chars == max_chars:
                raise last_error
            max_words = next_words
            max_chars = next_chars


def _embed_batch_with_retry(raw_texts: list[str], prefix: str) -> np.ndarray:
    prepared = [_prepare_text(text, prefix=prefix) for text in raw_texts]
    try:
        return _embed_with_ollama(prepared)
    except Exception:
        if len(raw_texts) == 1:
            return np.array([_embed_single_with_retry(raw_texts[0], prefix=prefix)], dtype=np.float32)

        midpoint = max(1, len(raw_texts) // 2)
        left = _embed_batch_with_retry(raw_texts[:midpoint], prefix=prefix)
        right = _embed_batch_with_retry(raw_texts[midpoint:], prefix=prefix)
        return np.vstack([left, right])


def embed_documents(texts: list[str], batch_size: int = 64) -> np.ndarray:
    if EMBEDDING_PROVIDER == "sentence-transformers":
        prepared = [_prepare_text(text, prefix=DOCUMENT_PREFIX) for text in texts]
        return _get_fallback_model().encode(
            prepared,
            batch_size=batch_size,
            show_progress_bar=True,
        )

    vectors = []
    effective_batch_size = min(batch_size, OLLAMA_EMBED_BATCH_SIZE)
    for index in range(0, len(texts), effective_batch_size):
        batch = texts[index : index + effective_batch_size]
        vectors.append(_embed_batch_with_retry(batch, prefix=DOCUMENT_PREFIX))
    if not vectors:
        return np.empty((0, 0), dtype=np.float32)
    return np.vstack(vectors)


def embed_query(query: str) -> list[float]:
    if EMBEDDING_PROVIDER == "sentence-transformers":
        prepared_query = _prepare_text(query, prefix=QUERY_PREFIX)
        return _get_fallback_model().encode(prepared_query).tolist()
    return _embed_single_with_retry(query, prefix=QUERY_PREFIX).tolist()


def warmup() -> None:
    """Pre-load the active embedding model so the first real query isn't cold.

    For the sentence-transformers provider this loads the model AND runs one
    encode to JIT the forward path; otherwise the model only loads lazily on
    the first user query, adding ~10s to that request. For Ollama, a tiny
    request loads and pins the model.
    """
    if EMBEDDING_PROVIDER == "sentence-transformers":
        _get_fallback_model().encode(_prepare_text("warmup", prefix=QUERY_PREFIX))
        return
    _embed_with_ollama(["warmup"])
