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
# NOTE (2026-08-03): 10.0.0.100 ("plex") IS blackwell (10.0.0.10) — one machine,
# hostname blackwell, both IPs on one NIC. Agents already on blackwell can work
# on production directly without ssh.
./deploy.sh

# Watch files and auto-deploy to production on save
./watch_and_deploy.sh

# Public beta of the WORKING TREE at https://beta.sobrietycopilot.com, beside
# production (containers beta-app/beta-nginx on 10.0.0.100:5077; Cloudflare
# tunnel route on the NAS's cloudflared, managed in the Cloudflare dashboard).
# The main site's footer has "Try the beta" (cookie sc_beta on
# .sobrietycopilot.com remembers it; the beta's footer links back).
./scripts/deploy_beta.sh            # SKIP_WEB=1 to redeploy server code only

# Release mobile app to App Store Connect / TestFlight & Google Play:
# Automatically bumps build number, syncs Xcode targets, builds & uploads
# iOS archive directly to TestFlight, builds signed release AAB, and pushes to git.
# Builds in a throwaway local copy (Flutter/Xcode can't build on SMB).
./scripts/release_mobile.sh
```

**One repo.** The repo lives on the NAS (`/Volumes/repos/sobriety-copilot`,
mapped on every dev machine) with GitHub as its origin. Edit, commit and run
every script there — never in another clone, worktree or copy. Builds that
can't run on the SMB share (`scripts/build_web.sh`, `scripts/release_mobile.sh`)
copy `mobile_app/` to a temp dir, build, copy the output back and delete the
copy. (2026-10-16: a long-lived `~/development` build clone collected two
months of commits, split the history, and a hand-copied commit silently
reverted FR11 `/api/distill`, the meetings expansion and the UI pass in
production.)

**What `deploy.sh` does and does *not* do.** It tars `src static nginx
docker-compose.yml Dockerfile requirements.txt documents/.manifests` (never
`.env`) to the remote (`NAS_HOST`, default the `litellm` ssh alias for
`joshu@10.0.0.100`), copies it into place, `chmod -R a+rX`'s it, then runs
`docker compose build app worker nginx` and force-recreates `app nginx worker`
(the worker has its own image; until 2026-10-16 it was never rebuilt and ran
August code). It
never deletes files on the server and does **not** verify health — verify
that yourself:

- **Production `.env` diverges deliberately** (custom `LLM_MODEL` /
  `EMBEDDING_MODEL`, among others) and must never be clobbered. After
  deploying, confirm `/api/health` still reports the production models
  (currently `dsv4`, `fine-tuned-embeddinggemma`) rather than the repo defaults.
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

Tests: `python -m pytest tests/` (needs `requirements.txt` + `pytest`). Use
pytest, not `unittest`: several suites (e.g. `test_distill_endpoint`,
`test_sms_reply`) are pytest-style and `unittest` silently runs 0 of them.
`test_sse_path` and `test_model_variant` call a live server
(`SSE_TEST_BASE_URL`, default `http://localhost:5000`). Flutter tests: run
`flutter test` in a temp copy of `mobile_app/`, like `scripts/build_web.sh`.

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
| `TWILIO_SMS_WEBHOOK_URL` | `https://sobrietycopilot.com/api/sms` | Exact URL Twilio posts to; `/api/sms` checks `X-Twilio-Signature` against it |
| `TWILIO_VALIDATE_SIGNATURE` | `1` | `0` disables the signature check (local testing only) |
| `CHAT_ENGINE` | `classic` | What answers `/api/chat` (website + every installed app): `classic` retrieval chat, or `research` = the research-capable chat (router below). No app release needed to flip |
| `CHAT_ROUTER` | `auto` | For research-capable chat: `auto` sends short, plainly conversational messages to the fast classic reply and anything touching the literature (or longer than ~14 words) to the agent; `agent` sends everything to the agent |
| `RESEARCH_RATE_LIMIT` / `RESEARCH_MAX_CONCURRENT` | `90` / `2` | Agent messages per IP per hour / server-wide whole-chapter reading runs (ordinary messages never wait on the latter) |
| `RESEARCH_EFFORT` | `low` | Reasoning effort for the agent's planning/answer turns (`medium` spent ~1 min deliberating per answer) |

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

- **`src/server.py`** — FastAPI app. Endpoints: `/api/chat` (SSE streaming with HyDE + hybrid retrieval; accepts `client_context` for device-supplied notes, never persisted), `/api/suggest`, `/api/explain-snippet[s-batch]`, `/api/meetings` (geo search; `range`/`tod`/`now_day`/`now_min` select soonest-first server-side), `/api/meetings/sources` (per-feed health), `/api/meetings/online` (worldwide online directory: OIAA + Virtual NA, live-now sorting), `/api/geocode`, `/api/packs/*` (offline library packs), `/api/doc/{id}` + `/api/render/...` (readers), `/api/index` (Celery), `/api/bugs` (GET requires X-Admin-Token = BUG_ADMIN_TOKEN), `/api/health`.
  There is NO `/api/transcribe` and never was — voice dictation is on-device (sherpa-onnx ASR in the Flutter app).
- **`src/inference/engine.py`** — OpenAI-compatible streaming client. Splits `thinking` vs `token` chunks for the show-thinking UI.
- **`src/rag/graph.py` + `graph_taxonomy.py`** — the corpus-wide Knowledge Graph
  behind `/api/graph/map`, `/api/graph/topic/{id}`, `/api/graph/book/{id}`,
  `/api/graph/passages`, `/api/graph/search` and the JSON reader window
  `/api/doc/{id}/window`. ~90 curated recovery topics are matched against every
  medium-scale chunk via the retriever's BM25 postings (no re-tokenising), giving
  topic↔topic (NPMI co-occurrence), topic↔book and topic↔chapter edges plus
  per-passage topic tags (the "hop" junctions). Built once per index in a
  background thread (~6 s on 1 CPU) and pickled beside the BM25 cache as
  `graph_cache_<collection>.pkl`; endpoints answer **202 + progress** while it
  builds. Bump `TAXONOMY_VERSION` whenever `graph_taxonomy.py` changes or the
  cached graph will be served stale. The legacy per-query `/api/graph?q=` is kept
  for mobile builds < 1.3.0. Tests: `python -m unittest tests.test_graph`.
  Flutter side: `mobile_app/lib/features/graph/` (canvas + panels + in-app
  passage reader). App builds with the concept graph (below) use it only as
  the fallback when `/api/graph2/map` 404s.
- **`src/rag/concept_graph.py` + `concept_text.py`** — the concept graph behind
  `/api/graph2/{map,node,meet,book/{id},chapter/{id}/{n},search,status}`:
  thousands of concepts (ideas, people, places, sayings, prayers) plus the ~90
  topics as hubs, each with *all* its peers (NPMI over ~40k manifest passages),
  books, chapters, and "where two concepts meet" passages. The concept list,
  map positions and prominence (PageRank) are built **offline** by
  `scripts/build_concepts.py mine|curate|dedupe|layout` (LLM curation via
  structured output) into the committed `src/rag/data/graph_concepts.json`;
  the server only matches concepts to passages (~15 s background build,
  pickled as `concept_graph.pkl`, 202 + progress meanwhile). Re-run the script
  when the manifests change. Tests: `tests/test_concept_graph.py`. Flutter:
  `mobile_app/lib/features/graph2/` (word-cloud canvas with LOD labels).
- **`src/rag/outline.py`** — chapter outline of a manifest (drop caps, running
  headers, contents-page titles glued to paragraphs, oversize sections cut
  into page ranges). Used by both graphs and research mode. Tests:
  `tests/test_outline.py` (asserts every Big Book chapter and every 12&12
  Step/Tradition).
- **`src/research/`** — the research-capable chat, `POST /api/research` (same
  request and SSE events as `/api/chat` plus `research` step/phase/verification
  events). Since 2026-10-16 the app's chat repository posts here for every
  message (Private Mode excepted): the router (`_wants_research` in
  `server.py`) keeps plain conversation on the fast classic path, and the agent
  decides per message whether to reply, look something up, or read chapters
  (passages are prefetched up front; urgent/crisis wording skips the prefetch).
  `agent.py` runs a tool loop on the chat model (GLM tool calling): outline,
  read whole sections, exact `find_text` counts, search, and
  `analyze_sections` (parallel per-chapter readers whose quotes are checked
  against the text). The answer's quotes and page citations are verified
  against what was read. `library.py` serves the manifests (drop caps rejoined,
  ligature splits and embedded running headers repaired). Research requests
  send vLLM `priority` > 0 so live chat goes first; `RESEARCH_RATE_LIMIT`
  (per IP/hour) and `RESEARCH_MAX_CONCURRENT` bound load. Tests:
  `tests/test_research.py` (fake LLM). Depth score against a live server:
  `python -m tests.eval_research --base-url …` (expected answers computed from
  the manifests).
- **`src/rag/`** —
  - `retriever.py`: hybrid retrieval (cosine semantic + BM25 keyword + category boosts + scale diversity); optional cross-encoder reranking on the final candidates.
  - `reranker.py`: cross-encoder wrapper (`sentence-transformers`). Lazy-loaded so non-chat paths don't pay for it.
  - `embeddings.py`: Ollama-backed embeddings via OpenAI-compatible API. Document/query prefixes for `nomic-embed-text`.
  - `chroma_client.py`: HTTP or embedded client.
  - `indexer.py`, `document_processor.py`, `semantic_chunker.py`: corpus build pipeline (used by the Celery worker).
  - `memory.py`: SQLite-backed `UserMemoryManager` for per-user sobriety date, current step, and interaction history.
- **`src/tasks/`** — Celery app, `indexing` task, Redis-backed `job_store` for shadow-collection indexing.
- **`src/meetings/`** — meeting catalog: ~60 Meeting Guide (TSML) intergroup feeds in `feeds.py` + the NA BMLT aggregator, geocoded search, OIAA/Virtual NA online directory. A background loop refreshes every feed hourly; check `/api/meetings/sources` after deploys for feeds stuck at `error`/`empty`. Gotchas: send the honest `USER_AGENT` (Cloudflare-fronted intergroups 403 a spoofed Chrome UA); BMLT `geo_width` must be **positive** (negative = "N nearest meetings"); sites answering 401 have sharing turned off on purpose — ask, don't scrape (`docs/meeting-feed-outreach.md`). Find new feeds with `python scripts/discover_meeting_feeds.py --generate-us`. Tests: `python -m unittest tests.test_meetings`.
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
# 2. Rebuild from the NAS repo. Builds in a throwaway local copy (Flutter
#    can't build on SMB) with the flutter-mac SDK (the vendored flutter/ is
#    Linux-only; override with FLUTTER_BIN), then cp's build/web/. into
#    static/ — cp, not rsync --delete, so the hand-maintained privacy.html,
#    terms.html and sms-optin.html survive.
./scripts/build_web.sh
# 3. Commit static/, then deploy and verify (see the Commands section).
```

Sanity-check the bundle before deploying by grepping it for a distinctive new
UI string — `grep -c "Some New Button" static/main.dart.js` should be ≥ 1.

## Domain considerations

- This application serves a vulnerable population. Responses must be empathetic, non-judgmental, and privacy-respecting.
- Crisis guidance gives exactly one helpline, A.A. New York Intergroup
  (212) 647-1680 (answered 9 am–1 am Eastern, **not** 24/7, per
  nyintergroup.org), plus 911 for immediate danger, and forbids every other
  number: left alone the model invents plausible "AA hotline" numbers. The
  constant is `AA_HELPLINE` in `src/prompts/templates.py`; the app's crisis and
  About sheets and Private Mode prompt carry the same number, and the crisis
  sheet lists 988 and SAMHSA under "More support options".
- Crisis and self-harm replies must open by strongly urging a call to that
  helpline or getting to an in-person A.A. meeting today, in 3–4 sentences.
  Owner's decision (2026-10-16): the app is not affiliated with 988, SAMHSA or
  other crisis lines, so the model never suggests them.
- SMS: `/api/sms` rejects requests without a valid Twilio signature. Web/app
  sign-ups (`/api/sms/optin`) only text a "Reply YES" confirmation (double
  opt-in), and no endpoint reveals whether a phone number is subscribed.
- User data in this domain is highly sensitive.

## Note on the GitHub history

The git history before the FastAPI import contained a stripped-down Flask scaffold that did not match production. That history was force-replaced on 2026-05-11 after recovering the real codebase from the running Docker images.
