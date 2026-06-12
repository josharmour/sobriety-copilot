# sobriety-copilot

A recovery-based assistant for addicts/alcoholics. RAG-powered chat over A.A./recovery literature, plus a meeting finder.

The production stack runs in Docker Compose (FastAPI + Celery + Redis + ChromaDB + nginx). LLM inference is reached over an OpenAI-compatible API — Ollama by default.

```bash
docker compose up -d --build
# UI:     http://localhost:5000
# Health: http://localhost:5000/api/health
```

See `CLAUDE.md` for architecture and env-var reference.
