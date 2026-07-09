"""FastAPI embedding microservice for the fine-tuned EmbeddingGemma retriever.

OpenAI-compatible POST /v1/embeddings endpoint serving the fine-tuned
SentenceTransformer model on CPU only (no GPU).

Prompt prefixes (matching the fine-tuned model's training data):
  - Documents: "title: none | text: <text>"
  - Queries:   "task: search result | query: <query>"

Usage:
    python scripts/embed_server.py

    curl http://localhost:8190/v1/embeddings \
      -H "Content-Type: application/json" \
      -d '{"input": ["Hello world"], "model": "embedding-gemma", "input_type": "document"}'
"""

from __future__ import annotations

import os
import time

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------
MODEL_PATH = "/home/joshu/ft-runs/eval-assets/retriever-model"
DIMENSION = 768
HOST = os.environ.get("EMBED_HOST", "0.0.0.0")
PORT = int(os.environ.get("EMBED_PORT", "8190"))

# Prompt prefixes the fine-tuned model was trained on
DOCUMENT_PREFIX = "title: none | text: "
QUERY_PREFIX = "task: search result | query: "

# ---------------------------------------------------------------------------
# Load model (CPU only — do NOT take the RTX 6000 GPUs)
# ---------------------------------------------------------------------------
print(f"[embed_server] Loading SentenceTransformer from {MODEL_PATH} on CPU...", flush=True)
t0 = time.time()
model = SentenceTransformer(MODEL_PATH, device="cpu", trust_remote_code=True)
print(
    f"[embed_server] Model loaded in {time.time() - t0:.1f}s — "
    f"dim={model.get_embedding_dimension()}, "
    f"device={model.device}",
    flush=True,
)

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Embedding Microservice (fine-tuned EmbeddingGemma)")


# ---------------------------------------------------------------------------
# Request / response schemas (OpenAI-compatible)
# ---------------------------------------------------------------------------
class EmbeddingRequest(BaseModel):
    input: list[str] | str = Field(..., description="Text or list of texts to embed")
    model: str | None = None
    dimensions: int | None = None
    input_type: str | None = Field(
        default=None,
        description="'document' or 'query' — controls which prompt prefix is applied. "
        "If omitted, defaults to 'document'. Set to 'query' for search queries.",
    )


class EmbeddingObject(BaseModel):
    object: str = "embedding"
    index: int
    embedding: list[float]


class UsageInfo(BaseModel):
    prompt_tokens: int
    total_tokens: int


class EmbeddingResponse(BaseModel):
    object: str = "list"
    data: list[EmbeddingObject]
    model: str
    usage: UsageInfo


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.post("/v1/embeddings", response_model=EmbeddingResponse)
async def get_embeddings(request: EmbeddingRequest):
    """OpenAI-compatible embedding endpoint.

    Accepts standard OpenAI fields plus a custom `input_type` field.
    `input_type` controls which prompt prefix is applied:
      - "document" (default): prepends "title: none | text: "
      - "query":             prepends "task: search result | query: "
    """
    # Normalise input to list
    texts = request.input if isinstance(request.input, list) else [request.input]
    if not texts:
        raise HTTPException(status_code=400, detail="input must not be empty")

    # Determine prefix
    input_type = (request.input_type or "document").lower()
    if input_type == "query":
        prefix = QUERY_PREFIX
    elif input_type == "document":
        prefix = DOCUMENT_PREFIX
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown input_type '{input_type}'. Use 'document' or 'query'.",
        )

    # Prepend prefix
    prepared = [f"{prefix}{text}" for text in texts]

    # Encode (returns np.ndarray, shape [n, 768])
    embeddings: np.ndarray = model.encode(prepared, show_progress_bar=False)

    # Count approximate tokens (char-based estimate for usage reporting)
    # Gemma3 tokenizer averages ~4 chars/token; this is a rough estimate.
    total_chars = sum(len(t) for t in prepared)
    estimated_tokens = max(1, total_chars // 3)

    data = [
        EmbeddingObject(index=i, embedding=emb.tolist())
        for i, emb in enumerate(embeddings)
    ]

    return EmbeddingResponse(
        data=data,
        model=request.model or "fine-tuned-embeddinggemma",
        usage=UsageInfo(prompt_tokens=estimated_tokens, total_tokens=estimated_tokens),
    )


@app.get("/")
@app.get("/health")
async def health():
    """Health check."""
    return {
        "status": "ok",
        "model": "fine-tuned-embeddinggemma",
        "dim": DIMENSION,
        "device": str(model.device),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    print(
        f"[embed_server] Starting on {HOST}:{PORT} — "
        f"POST /v1/embeddings for inference, GET / for health",
        flush=True,
    )
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
