# Cloud Re-index Plan: Fine-tuned EmbeddingGemma Retriever (FT-#3)

## Overview

Switch the CLOUD (NAS) server from **all-minilm (384-dim)** to the **fine-tuned
EmbeddingGemma retriever (768-dim)** via a dedicated embedding microservice.

**Current state (production):**
- Embedding: all-minilm via Ollama on the NAS → 384-dim vectors
- ChromaDB collection: `recovery_literature` (384-dim)
- Prompt prefixes: `search_document:` / `search_query:` (nomic-embed-text style)

**Target state:**
- Embedding: fine-tuned EmbeddingGemma (768-dim) via a SentenceTransformer microservice
- ChromaDB collection: e.g. `recovery_literature_gemma_v1` (768-dim)
- Prompt prefixes: `title: none | text:` / `task: search result | query:` (Gemma training format)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Synology NAS (10.0.0.2)                                        │
│                                                                  │
│  ┌──────────────────────┐   ┌──────────────────────────────┐    │
│  │  app + worker         │   │  embed-server (NEW)           │    │
│  │  (FastAPI + Celery)   │──▶│  SentenceTransformer on CPU   │    │
│  │                       │   │  port 8190                    │    │
│  │  EMBEDDING_BASE_URL=  │   │  model: /models/retriever-model│   │
│  │  http://embed:8190/v1 │   └──────────────────────────────┘    │
│  └──────────────────────┘                                        │
│           │                                                      │
│           ▼                                                      │
│  ┌──────────────────────┐                                        │
│  │  ChromaDB             │                                        │
│  │  shadow collection:   │                                        │
│  │  recovery_literature_ │                                        │
│  │  gemma_v1 (768-dim)   │                                        │
│  └──────────────────────┘                                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Step-by-step

### Step (a) — Run the microservice on a host the NAS app reaches

Two options:

#### Option A: Docker sidecar (recommended — auto-restart, no extra host)

Add an `embed` service to `docker-compose.yml`:

```yaml
embed:
  build:
    context: .
    dockerfile: Dockerfile.embed
  image: sobriety-copilot-embed
  restart: always
  environment:
    EMBED_HOST: "0.0.0.0"
    EMBED_PORT: "8190"
  volumes:
    - /home/joshu/ft-runs/eval-assets:/models:ro
  expose:
    - "8190"
```

Create `Dockerfile.embed`:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir sentence-transformers fastapi uvicorn numpy
COPY scripts/embed_server.py .
EXPOSE 8190
CMD ["python", "embed_server.py"]
```

Rebuild & deploy:
```bash
cd /volume1/repos/sobriety-copilot
docker-compose build embed
docker-compose up -d embed
```

Verify health:
```bash
curl http://embed:8190/health
# → {"status":"ok","model":"fine-tuned-embeddinggemma","dim":768,"device":"cpu"}
```

#### Option B: Standalone process (if Docker on NAS has memory constraints)

```bash
# On the NAS or any host the app can reach (e.g. 10.0.0.2)
python scripts/embed_server.py  # listens on 0.0.0.0:8190
```

Manage via systemd (see `scripts/embed_server.service` template in this repo).
Model is loaded once at startup (~1s after first load, ~30s cold).

**CPU constraint**: the microservice uses CPU only. The fine-tuned Gemma-300M
model runs comfortably on CPU — one 768-dim embedding takes ~30ms, well within
indexing latency budgets. The 2× RTX 6000 GPUs at 10.0.0.10 are NOT touched.

---

### Step (b) — Point the server's EMBEDDING_BASE_URL / MODEL at it

#### Required source changes in `src/rag/embeddings.py`:

**1. Update prompt prefixes** (the Gemma model was trained with these, not nomic style):

```python
DOCUMENT_PREFIX = "title: none | text: "
QUERY_PREFIX = "task: search result | query: "
```

**2. Optionally bypass the prefix-prepending in the app** (the microservice can apply
prefixes server-side when `input_type` is set). Two sub-options:

- **Option B1 (recommended — least app change):** The app sends RAW text (no prepended
  prefix). The microservice's `input_type` field controls prefixing. This requires
  modifying `embed_documents()` and `embed_query()` to pass `input_type` in the
  request body to the microservice.

- **Option B2 (simpler — no request-body change):** Keep the app's existing prefix
  logic. Change `DOCUMENT_PREFIX` and `QUERY_PREFIX` to the Gemma prefixes (as above).
  The app sends `title: none | text: <chunk>` to the microservice. The microservice
  embeds AS-IS (no additional prefix). This requires setting the microservice to
  pass-through mode (no `input_type` prefixing).

  **Recommended for minimal changes.** The microservice supports both modes:
  - with `input_type` → server-side prefixing (for direct curl users)
  - without `input_type` → embed as-is (for app integration)

#### Environment variable changes in `.env` or `docker-compose.yml`:

```yaml
EMBEDDING_PROVIDER: "sentence-transformers"   # or leave as ollama; the base URL detection handles it
EMBEDDING_BASE_URL: "http://embed:8190/v1"    # point at microservice
EMBEDDING_MODEL: "fine-tuned-embeddinggemma"  # model name (informational)
```

The existing `EMBEDDING_PROVIDER` can stay `ollama` — the code detects the
backend from `:11434` in the URL. Since `embed:8190` doesn't contain `:11434`,
it would be treated as `vllm` backend, which is fine (no `keep_alive` extra_body).

**Alternative:** Set `EMBEDDING_PROVIDER` to a new value like `"embed-microservice"`
and add a branch that sends the OpenAI-compatible request without prepending
prefixes (letting the microservice handle them).

---

### Step (c) — Re-index into a SHADOW ChromaDB collection (768-dim)

The existing `recovery_literature` collection stores 384-dim vectors (all-minilm).
A 768-dim model CANNOT write to it — ChromaDB validates vector dimension consistency.

Create a **shadow collection**:

```python
# One-time indexing script: scripts/cloud_reindex.py
import os
from src.rag.indexer import RAGIndexer
from src.rag.chroma_client import create_chroma_client

# Create new 768-dim collection
SHADOW_COLLECTION = "recovery_literature_gemma_v1"
client = create_chroma_client("rag_db")
client.delete_collection(SHADOW_COLLECTION)  # clean slate
client.create_collection(
    name=SHADOW_COLLECTION,
    metadata={"hnsw:space": "cosine"},
)

# Index all documents, targeting the shadow collection
indexer = RAGIndexer(
    db_path="rag_db",
    collection_name=SHADOW_COLLECTION,
)
indexer.index_directory("/app/documents")
```

Run from within the app container:

```bash
docker-compose exec app python -c "
import os; os.environ['EMBEDDING_BASE_URL'] = 'http://embed:8190/v1'
# ... (see full script below)
"
```

**Important indexing considerations:**
- The `embed_documents()` function in `embeddings.py` sends text with
  `DOCUMENT_PREFIX` prepended. With Option B2 above, this sends
  `title: none | text: <chunk>` to the microservice, which embeds as-is. ✓
- Batch size: the microservice has no batch limit (unlike Ollama's 8). Use
  `CHROMA_BATCH_SIZE=256` or higher.
- Estimated time: ~80k chunks × ~30ms/chunk ≈ 40 minutes.
- No GPU contention — the microservice runs on CPU, the existing vLLM is untouched.

---

### Step (d) — Verify

**1. Embedding quality check:**
```python
from src.rag.embeddings import embed_query, embed_documents, EMBEDDING_PROVIDER

# Confirm provider
print(f"Provider: {EMBEDDING_PROVIDER}")

# Confirm dimension
q = embed_query("What is the first step?")
print(f"Query dim: {len(q)}")  # must be 768

# Spot-check a known query
doc_vecs = embed_documents(["Step One: We admitted we were powerless."])
print(f"Doc dim: {len(doc_vecs[0])}")  # must be 768
```

**2. ChromaDB collection sanity:**
```python
from src.rag.chroma_client import create_chroma_client
client = create_chroma_client("rag_db")
col = client.get_collection("recovery_literature_gemma_v1")
print(f"Shadow collection: {col.count()} chunks, dim from first vector")

# Check first embedding is 768-dim
result = col.get(limit=1, include=["embeddings"])
emb = result["embeddings"][0]
print(f"Embedding dimension: {len(emb)}")  # must be 768
```

**3. End-to-end retrieval test (compare against current):**
```python
# Temporarily switch the active collection and run some test queries
from src.rag.retriever import RAGRetriever

r = RAGRetriever(db_path="rag_db", collection_name="recovery_literature_gemma_v1")
results = r.retrieve("What does it mean to work the steps?", top_k=5)
for res in results:
    print(f"  [{res.similarity:.4f}] {res.source} — {res.excerpt[:120]}...")
```

---

### Step (e) — Cut over

**Non-disruptive switch (no downtime):**

1. Verify everything above passes.
2. Update the `RAG_COLLECTION` env var:

```yaml
RAG_COLLECTION: "recovery_literature_gemma_v1"   # was "recovery_literature"
```

3. Restart the app container (rolling):
```bash
docker-compose restart app
```

The app's `_refresh_retriever()` is called on each request and re-builds the
retriever from the new collection. No downtime — the first request after the
restart pays a ~45s cache-warmup cost (BM25 cache rebuild), then everything
is fast.

4. Once stable, optionally delete the old collection:
```python
client.delete_collection("recovery_literature")
```

---

## Rollback

Instant rollback: change `RAG_COLLECTION` back to `recovery_literature` and
restart the app. The old 384-dim collection is untouched (read-only). The
microservice can keep running or be stopped.

---

## Files touched

| File | Change | Risk |
|---|---|---|
| `docker-compose.yml` | Add `embed` service, update env vars | Low — additive |
| `Dockerfile.embed` | New file | None — new |
| `src/rag/embeddings.py` | Update `DOCUMENT_PREFIX`, `QUERY_PREFIX` | Medium — affects all embedding calls |
| `.env` | Add `EMBEDDING_BASE_URL`, `RAG_COLLECTION` | Low — env-only |
| `deploy.sh` | May need to include the new Dockerfile | Low |

---

## Pre-flight checklist

- [ ] Microservice loads model on CPU (< 2GB RAM, < 30s cold)
- [ ] Microservice returns correct 768-dim embeddings (parity tested ✓ — see scripts/test_embed_parity.py)
- [ ] Prompt prefixes match Gemma training format (`title: none | text:`, `task: search result | query:`)
- [ ] Shadow ChromaDB collection created and indexable
- [ ] Re-index completes without errors
- [ ] BM25 cache regenerated after collection switch
- [ ] Cosine similarity search accuracy verified with spot-queries
- [ ] Rollback procedure documented and tested

---

> **HANDOFF: CLOUD** microservice built & parity-verified. Plan written at
> `finetune/deploy/cloud_reindex_plan.md`. Awaiting Fable to execute steps (b)–(e)
> — prod config changes, re-index, and cutover.
