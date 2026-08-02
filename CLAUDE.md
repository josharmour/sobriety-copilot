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

# FIRST, if any Dart in mobile_app/ changed: rebuild the web bundle (see
# "Shipping UI changes to the website" below). deploy.sh ships static/ as-is,
# so merging Flutter source without rebuilding deploys the OLD UI.

# Deploy local changes to production and rebuild app+nginx there. Production is
# joshu@10.0.0.100 at /home/joshu/docker-stack/sobriety-copilot (the cloudflared
# tunnel origin for sobrietycopilot.com; runs the full stack incl. ollama:rocm).
# The Synology NAS (10.0.0.2) copy is a stale, non-serving mirror — never
# deploy there.
./deploy.sh

# Watch files and auto-deploy to production on save
./watch_and_deploy.sh
```

**What `deploy.sh` does and does *not* do.** It tars `src static nginx
docker-compose.yml Dockerfile requirements.txt .env` to the remote, copies it
into place, and runs `docker compose build app nginx && docker compose up -d`.
That is all. It does **not** verify health, report `.env` drift, or normalize
permissions — verify those yourself:

- **Production `.env` diverges deliberately** (custom `LLM_MODEL` /
  `EMBEDDING_MODEL`, among others) and must never be clobbered. It *is* in the
  tar, and survives only because the script's `cp -R deploy_temp/*` does not
  glob dotfiles — an accident, not a safeguard. After deploying, confirm
  `/api/health` still reports the production models (`sc-generator`,
  `fine-tuned-embeddinggemma`) rather than the repo defaults.
- **File modes are shipped as-is by tar.** Deploy from a local-disk clone;
  the SMB `/Volumes` copy carries `rwx------` modes that make nginx 403.
- **Verify what is actually being served** (a deploy log looks identical
  whether or not the bundle changed):
  ```bash
  curl -s https://sobrietycopilot.com/api/health
  curl -s https://sobrietycopilot.com/version.json          # expect the version you just built
  curl -s https://sobrietycopilot.com/main.dart.js -o /tmp/live.js
  diff -q static/main.dart.js /tmp/live.js && echo "IN SYNC"
  ```
- `deploy.sh` needs its executable bit (`chmod +x`, or run `bash deploy.sh`);
  it has been lost in a commit before.

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

### RAG Models
| Component | Private Mode (on-device) | Cloud (website + online app) |
|---|---|---|
| Retriever (embeddings) | **fine-tuned EmbeddingGemma** via pack v3 | `all-minilm` (fine-tuned retriever pending re-index) |
| Generator | **base Gemma-4-E2B** (fine-tuned SFT pending conversion) | **dsv4 (deepseek-v4-flash)**, unchanged |

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
- **`static/`** — the **committed output** of `flutter build web`, served verbatim by nginx (the hand-written PWA is retired). It is a build artifact, not source: editing `mobile_app/` changes nothing here until you rebuild. See "Shipping UI changes to the website" below.
- **`mobile_app/`** — the single Flutter codebase for every surface (Android on Play, web at sobrietycopilot.com, desktop). Android builds: vendored SDK at `../flutter/bin/flutter`, `JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64`, `flutter build apk --release`. Private Mode (on-device Gemma 4 E2B via flutter_gemma + offline-pack FTS retrieval) lives in `lib/features/private_mode/` — see Fable-Features.md for its constraints (no Tensor-G5 NPU model; bundled SQLite required for FTS5). The meetings sheet (`lib/features/sheets/meetings_sheet.dart`) renders its map with `flutter_map` (added 2026-07-19).
- **`tests/eval_rag.py`** — Out-of-band RAGAS evaluation harness (faithfulness, answer relevancy, context precision/recall). Not run in the image.

## Shipping UI changes to the website

`static/` is a build artifact, so the chain from source to the live site is:

```
mobile_app/lib → flutter build web → static/ → commit → deploy.sh → nginx
```

**Merging Flutter source is not enough.** On 2026-08-02 four merged features
were invisible on sobrietycopilot.com because `static/` still held the previous
release's bundle — source and served site were a whole release apart, and the
deploy would have silently shipped the old UI.

```bash
# 1. Bump mobile_app/pubspec.yaml `version:` so the served version.json
#    distinguishes this build from the one already live.
# 2. Rebuild. On macOS use the flutter-mac SDK — the vendored flutter/ is
#    Linux-only. Build from a local-disk clone, never the SMB /Volumes copy.
cd mobile_app
/Users/joshu/development/flutter-mac/bin/flutter build web --release
cp -R build/web/. ../static/   # cp, NOT rsync --delete: preserves the
                               # hand-maintained static/privacy.html
# 3. Commit static/, then deploy and verify (see the Commands section).
```

Sanity-check the bundle before deploying by grepping it for a distinctive new
UI string — `grep -c "Some New Button" static/main.dart.js` should be ≥ 1.

## Domain considerations

- This application serves a vulnerable population. Responses must be empathetic, non-judgmental, and privacy-respecting.
- The system prompt directs the LLM to recommend SAMHSA (1-800-662-4357) or 911 for crisis situations.
- User data in this domain is highly sensitive.

## Note on the GitHub history

The git history before the FastAPI import contained a stripped-down Flask scaffold that did not match production. That history was force-replaced on 2026-05-11 after recovering the real codebase from the running Docker images.
