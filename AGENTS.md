# sobriety-copilot — Agent Guidance

## Core Truths
- Production stack: Docker Compose (FastAPI, Celery, Redis, ChromaDB, Nginx).
- RAG-powered chat over A.A./recovery literature.
- Deployed at 10.0.0.2 (Port 5000 app, Port 8090 public).
- Uses Ollama by default for local LLM inference.
- Deployment scripts exist locally: `deploy.sh` syncs code changes to the Synology NAS (10.0.0.2) via a tar stream over SSH and rebuilds docker containers. `watch_and_deploy.sh` can run locally to automatically trigger deployment on changes.

## Project Purpose
Recovery-based AI assistant with RAG over 12-step literature.

## Key Files
- docker-compose.yml
- src/
- CLAUDE.md

## RAG Architecture
- **Private Mode:** Fine-tuned EmbeddingGemma (via pack v3) + Base Gemma-4-E2B generator (SFT gated).
- **Cloud:** all-minilm + dsv4.

---
*This file was generated to ensure AI agents maintain continuity across sessions.*