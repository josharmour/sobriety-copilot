# sobriety-copilot

A recovery-based assistant for addicts/alcoholics: RAG-powered chat over
A.A./recovery literature, a meeting finder, a Knowledge Graph library browser
(92 curated topics / 77 books / 48k passages), and Daily Reflection
home-screen widgets.

- **Web PWA:** https://sobrietycopilot.com
- **Mobile app:** `mobile_app/` (Flutter — Android + iOS, v1.4.2 build 35)
- Latest release/change history: [`CHANGELOG.md`](CHANGELOG.md)

## Production

Runs as a Docker Compose stack on the **blackwell/plex machine (10.0.0.100)**,
at `/home/joshu/docker-stack/sobriety-copilot/`, deployed from this repo (the
NAS copy, mounted on every dev machine; GitHub is its origin). The stack is the cloudflared-tunnel origin for sobrietycopilot.com
(port 8090 publicly, FastAPI directly on 5000 on the host).

```
nginx → FastAPI app + Celery worker + Redis + ChromaDB
```

- **LLM:** DeepSeek-V4-Flash over OpenAI-compatible API (vLLM @ 10.0.0.10:8002,
  1M context) — single model for all modes.
- **Embeddings:** fine-tuned EmbeddingGemma served by the `embed` microservice
  (`Dockerfile.embed`; profile `embed` — start with
  `docker compose --profile embed up -d embed`, it never auto-starts).
- The Synology NAS (10.0.0.2) only stores this repo; it doesn't serve the
  site — never deploy to it. See `CLAUDE.md` for the full env-var reference.

## Deploy

From this repo:

```bash
./deploy.sh   # syncs code to 10.0.0.100 and rebuilds app, worker and nginx there
```

If any Dart in `mobile_app/` changed, **rebuild the web bundle first**
(`./scripts/build_web.sh`) and commit `static/` — `deploy.sh` ships `static/` as-is, so merging Flutter
source without rebuilding deploys the old UI.

For local development from scratch:

```bash
docker compose up -d --build
# UI:     http://localhost:5000
# Health: http://localhost:5000/api/health
```

## Layout

| Path | What it is |
|---|---|
| `src/` | FastAPI backend: `server.py`, `rag/` (retriever, graph, sections, indexer), `inference/`, `meetings/`, `tasks/` |
| `mobile_app/` | Flutter app (Android/iOS/web) — source of truth for the UI |
| `static/` | Built Flutter web bundle served by the site (commit rebuilt bundles) |
| `tests/` | Unit tests — run with `.venv/bin/python -m pytest tests/ -v` |
| `documents/` | Ingested literature + `.manifests/` structural corpus (never git) |
| `finetune/` | Fine-tuning configs, eval runs, retriever training |
| `packs/` | On-device RAG packs (`embedder-v3`, `library-v1.scpack`) |
| `docs/plans/` | Feature plans and design docs |

Troubleshooting the live stack: see the `sobriety-copilot-troubleshooting`
skill (embed-service 500 pattern, Chroma pool timeouts, the two-`.env` rule).
Architecture and agent guidance: `CLAUDE.md` + `AGENTS.md`.
