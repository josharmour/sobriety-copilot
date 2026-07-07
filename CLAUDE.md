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

# Deploy local changes to production Synology NAS (10.0.0.2) and rebuild
./deploy.sh

# Watch files and auto-deploy to Synology NAS on save
./watch_and_deploy.sh
```

For evaluation (heavyweight RAGAS deps live in `requirements-eval.txt`,
kept out of the runtime image):
```bash
pip install -r requirements.txt -r requirements-eval.txt
python -m tests.eval_rag                  # uses tests/eval_cases.json
python -m tests.eval_rag path/to/cases.json
# writes tests/eval_results.csv (gitignored)
```

## Environment variables

The full set lives in `docker-compose.yml` under `x-app-env`. The ones most worth knowing:

| Variable | Default | Description |
|---|---|---|
| `LLM_BASE_URL` | `http://10.0.0.10:8002/v1` | OpenAI-compatible LLM endpoint (vLLM box) |
| `LLM_MODEL` | `dsv4` | Chat model (deepseek-v4-flash, diffusion backend) |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Embedding model name (prod runs `all-minilm`) |
| `CHROMA_HOST` / `CHROMA_PORT` | `chroma` / `8000` | ChromaDB HTTP endpoint |
| `REDIS_URL` | `redis://redis:6379/0` | Celery broker / job store |
| `DOCUMENTS_DIR` | `/app/documents` | Mounted from `./documents` (read-only) |
| `RAG_COLLECTION` | `recovery_literature` | ChromaDB collection name |
| `ENABLE_RERANKER` | `0` | Cross-encoder reranking (off by default — CPU-heavy) |
| `STORE_CHAT_HISTORY` | `0` | Server-side chat transcript storage (privacy default: off) |
| `GEOCODE_COUNTRYCODES` | *(empty)* | Optional Nominatim country filter; empty = worldwide |
| `RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Cross-encoder model name |
| `ENABLE_HYDE` | `1` | Set to `0` to disable hypothetical passage generation (HyDE) |
| `USER_MEMORY_DB_PATH` | `/app/user_memory.db` | SQLite path for `UserMemoryManager` |

## Performance Optimization

To make the app run faster, you can disable the CPU-heavy reranker and/or skip the pre-retrieval HyDE LLM query step. In your `.env` file:
1. Set `ENABLE_HYDE=0` to skip generating hypothetical passages. This saves one entire LLM API call per prompt.
2. Set `ENABLE_RERANKER=0` to disable cross-encoder reranking (which runs slowly on CPU-bound servers).
3. Use a smaller or quantized model (e.g. `llama3:8b` or `gemma:2b` instead of larger reasoning models) to reduce token generation latency.

## Architecture

- **`src/server.py`** — FastAPI app. Endpoints: `/api/chat` (SSE streaming with HyDE + hybrid retrieval; accepts `client_context` for device-supplied notes, never persisted), `/api/suggest`, `/api/explain-snippet[s-batch]`, `/api/meetings` (geo search), `/api/meetings/online` (worldwide online directory: OIAA + Virtual NA, live-now sorting), `/api/geocode`, `/api/packs/*` (offline library packs), `/api/doc/{id}` + `/api/render/...` (readers), `/api/index` (Celery), `/api/bugs` (GET requires X-Admin-Token = BUG_ADMIN_TOKEN), `/api/health`.
  There is NO `/api/transcribe` and never was — voice dictation is on-device (sherpa-onnx ASR in the Flutter app).
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
- **`static/`** — the **Flutter web build** of `mobile_app/` (the hand-written PWA is retired). Rebuild with `cd mobile_app && ../flutter/bin/flutter build web --release && cp -R build/web/. ../static/` (preserves the hand-maintained `privacy.html`). Served by nginx.
- **`mobile_app/`** — the single Flutter codebase for every surface (Android on Play, web at sobrietycopilot.com, desktop). Android builds: vendored SDK at `../flutter/bin/flutter`, `JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64`, `flutter build apk --release`. Private Mode (on-device Gemma 4 E2B via flutter_gemma + offline-pack FTS retrieval) lives in `lib/features/private_mode/` — see Fable-Features.md for its constraints (no Tensor-G5 NPU model; bundled SQLite required for FTS5).
- **`tests/eval_rag.py`** — Out-of-band RAGAS evaluation harness (faithfulness, answer relevancy, context precision/recall). Not run in the image.

## Domain considerations

- This application serves a vulnerable population. Responses must be empathetic, non-judgmental, and privacy-respecting.
- The system prompt directs the LLM to recommend SAMHSA (1-800-662-4357) or 911 for crisis situations.
- User data in this domain is highly sensitive.

## Note on the GitHub history

The git history before the FastAPI import contained a stripped-down Flask scaffold that did not match production. That history was force-replaced on 2026-05-11 after recovering the real codebase from the running Docker images.
