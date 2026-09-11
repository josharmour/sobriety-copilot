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

## Mobile Releases (iOS TestFlight / App Store & Google Play)
- **Always automate mobile releases after making changes**: Whenever changes are made to `mobile_app/`, agents MUST run `./scripts/release_mobile.sh` from the local-disk clone (`/Users/joshu/development/sobriety-copilot`).
- `scripts/release_mobile.sh` automatically:
  1. Auto-bumps the build number in `mobile_app/pubspec.yaml`.
  2. Syncs Xcode build versioning via `mobile_app/ios/sync_versions.rb`.
  3. Archives iOS and directly uploads the build to Apple TestFlight / App Store Connect via Xcode (`xcodebuild -exportArchive`).
  4. Compiles the signed release Android App Bundle (AAB) with `release-upload-key.jks` at `mobile_app/build/app/outputs/bundle/release/app-release.aab`.
  5. Commits and pushes the version bump to GitHub.
- Never leave mobile code changes unbuilt or unreleased to TestFlight and Play Store.

---
*This file was generated to ensure AI agents maintain continuity across sessions.*