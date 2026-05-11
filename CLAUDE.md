# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**sobriety-copilot** is a recovery-based assistant that helps addicts/alcoholics via a RAG-powered chat interface. The production stack is FastAPI + Celery + Redis + ChromaDB + nginx, run via Docker Compose. The LLM backend is reached over an OpenAI-compatible API (Ollama by default, vLLM optional).

## Commands

```bash
# Build and start the full stack (FastAPI app, Celery worker, Redis, ChromaDB, nginx)
docker compose up -d --build

# Reach the app
# - direct (FastAPI):  http://localhost:5000  (via nginx → app:5000)
# - health:            http://localhost:5000/api/health

# Tail logs
docker compose logs -f app worker

# Index documents (background Celery job)
curl -X POST http://localhost:5000/api/index

# Stop
docker compose down
```

For evaluation (heavyweight deps not installed in the runtime image):
```bash
pip install -r requirements.txt
python -m tests.eval_rag        # writes rag_eval_results.csv
```

## Environment variables

The full set lives in `docker-compose.yml` under `x-app-env`. The ones most worth knowing:

| Variable | Default | Description |
|---|---|---|
| `LLM_BASE_URL` | `http://host.docker.internal:11434/v1` | OpenAI-compatible LLM endpoint |
| `LLM_MODEL` | `gemma4:e2b` | Chat model name |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Embedding model name (Ollama) |
| `CHROMA_HOST` / `CHROMA_PORT` | `chroma` / `8000` | ChromaDB HTTP endpoint |
| `REDIS_URL` | `redis://redis:6379/0` | Celery broker / job store |
| `DOCUMENTS_DIR` | `/app/documents` | Mounted from `./documents` (read-only) |
| `RAG_COLLECTION` | `recovery_literature` | ChromaDB collection name |
| `ENABLE_RERANKER` | `1` | Set to `0` to disable cross-encoder reranking |
| `RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Cross-encoder model name |
| `USER_MEMORY_DB_PATH` | `/app/user_memory.db` | SQLite path for `UserMemoryManager` |

## Architecture

- **`src/server.py`** — FastAPI app. Endpoints: `/api/chat` (SSE streaming with HyDE + hybrid retrieval), `/api/suggest`, `/api/explain-snippet[s-batch]`, `/api/meetings`, `/api/geocode`, `/api/index` (Celery), `/api/bugs`, `/api/health`, `/api/render/...`.
- **`src/inference/engine.py`** — OpenAI-compatible streaming client. Splits `thinking` vs `token` chunks for the show-thinking UI.
- **`src/rag/`** —
  - `retriever.py`: hybrid retrieval (cosine semantic + BM25 keyword + category boosts + scale diversity); optional cross-encoder reranking on the final candidates.
  - `reranker.py`: cross-encoder wrapper (`sentence-transformers`). Lazy-loaded so non-chat paths don't pay for it.
  - `embeddings.py`: Ollama-backed embeddings via OpenAI-compatible API. Document/query prefixes for `nomic-embed-text`.
  - `chroma_client.py`: HTTP or embedded client.
  - `indexer.py`, `document_processor.py`, `semantic_chunker.py`: corpus build pipeline (used by the Celery worker).
  - `memory.py`: SQLite-backed `UserMemoryManager` for per-user sobriety date, current step, and interaction history.
- **`src/tasks/`** — Celery app, `indexing` task, Redis-backed `job_store` for shadow-collection indexing.
- **`src/meetings/`** — A.A./N.A. meeting feeds (BMLT) and geocoded search.
- **`src/render_cache.py`** — On-disk PDF/EPUB text extraction cache used by `/api/render`.
- **`static/`** — PWA frontend (single-page `index.html` + manifest + service worker). Served directly by nginx, not FastAPI.
- **`tests/eval_rag.py`** — Out-of-band RAGAS evaluation harness (faithfulness, answer relevancy, context precision/recall). Not run in the image.

## Domain considerations

- This application serves a vulnerable population. Responses must be empathetic, non-judgmental, and privacy-respecting.
- The system prompt directs the LLM to recommend SAMHSA (1-800-662-4357) or 911 for crisis situations.
- User data in this domain is highly sensitive.

## Note on the GitHub history

The git history before the FastAPI import contained a stripped-down Flask scaffold that did not match production. That history was force-replaced on 2026-05-11 after recovering the real codebase from the running Docker images.
