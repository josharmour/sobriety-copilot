# Structure-Aware Literature Surfacing — Design & Implementation Plan

> **Status:** Design plan only — no code written yet.
> **Owner:** Josh / Hermes
> **Repo:** `~/development/sobriety-copilot` (local-disk clone; ship via `deploy.sh`)

**Goal:** Make the app answer *global, ordered* literature questions ("tell me all twelve steps and deep-dive each one") by reading the source material's **actual section structure** (Step One → Step Twelve, chapters), not just fuzzy-matching 8 fragments.

**Architecture:** Add a structure-aware retrieval path that walks the existing per-document **manifests** (which already record headings, block order, block_ids, and printed pages) to enumerate a corpus's sections in order. Surface these in (a) a new backend endpoint `/api/steps`, and (b) a chat "assembly" path that detects broad/step-wide queries and builds a *per-section* grounded prompt instead of one global top-8 blob. Frontend learns to render the deep dive.

**Tech stack:** Python/FastAPI (`src/server.py`), existing `src/rag/` (retriever + graph), manifest JSONs on the server (`documents/.manifests/`), Flutter mobile + PWA web frontends.

---

## Why this is needed (verified diagnosis)

Current chat retrieval is a **precision top-8 similarity search**, not a structure-aware reader. For "tell me all twelve steps + deep dive":

1. **`retrieve()` returns the top-8 most-similar scattered chunks** (`src/rag/retriever.py:528-708`), diversified across small/medium/large buckets and reranked. That covers maybe **one** Step's worth of material, not twelve.
2. **`ENUMERATION_PENALTY` (0.45×) actively suppresses step-listing chunks** (`retriever.py:96-116`). It correctly stops a "Step N" query from matching a TOC list-page — but it also demotes the exact "tell me all the steps" query we want to succeed.
3. **Context budget caps at `RAG_MAX_CONTEXT_CHARS` (12,000 chars)** (`retriever.py:59`, `format_context:710`). All 12 Steps at ~2,000+ words each can't fit even if retrieval were perfect.
4. **The knowledge graph already knows all 12 steps** (`CORE_RECOVERY_NODES`, `src/rag/graph.py:12-25`) but only renders an interactive wheel — it never produces ordered prose, and it's a separate screen from chat.

**The structure already exists** — it's just never read back out. Verified against the live server manifest `twelve-steps-and-twelve-traditions.json` (1024 blocks, 70 headings, with `Step One`…`Step Twelve` headings at level 2). Per-Step content depth:

| Step | content blocks | ~words |
|------|---------------|--------|
| One | 22 | 1,011 |
| Two | 39 | 2,515 |
| Three | 38 | 2,100 |
| Four | 60 | 3,504 |
| Five | 37 | 2,196 |
| Six | 35 | 1,974 |
| Seven | 32 | 2,012 |
| Eight | 21 | 1,496 |
| Nine | 18 | 1,251 |
| Ten | 37 | 2,080 |
| Eleven | 58 | 2,927 |
| Twelve | 414 | 21,078 |

So each Step has plenty of substantive prose for a genuine deep dive — the retrieval pipeline just never surfaces it in-order.

---

## Design

### 1. Manifest → section index (read structure back out)

Add a module `src/rag/sections.py` that loads a manifest JSON (same loader the indexer already uses at `indexer.py:132-157`) and produces an ordered list of **sections**: `{id, title, order, heading_level, blocks: [block_ids], start/end paragraph, printed_page_start/end, word_count}`. For the 12&12, split on `Step One`…`Step Twelve` headings (level 2 = chapter head). Make it generic over any manifest so other corpus documents (chapters, Daily Reflections entries) can reuse it.

**Lookup by document:** map a `doc_id` (e.g. `twelve-steps-and-twelve-traditions`) → manifest → sections. Store the section→chunk_ids mapping so retrieved chunks can be annotated with "this belongs to Step N" and *vice versa*.

### 2. Structured endpoints

- **`GET /api/steps`** → returns all 12 steps in order: `{number, title, summary, word_count, key_quote, chunk_ids, printed_page}`. Summary/key_quote can be precomputed (see §4) or generated on demand.
- **`GET /api/steps/{n}`** → returns one step with its passages (the manifest blocks / matching chunk text) for a deep-dive screen.

Generalize later to `/api/sections?doc=<doc_id>`.

### 3. Chat "assembly" path (deep-dive generation)

In `src/server.py` `chat()` (line 1338), add a classifier that recognizes **broad/step-wide queries** (reuse the step-N regex / `any(kw in q for kw in ("step","inventory","twelve"))` logic from `graph.py:109-117`). When triggered:

- Do **not** build one global prompt from top-8 hits.
- Instead walk `Step One`→`Step Twelve`, and for each step pull its passages (from the section index / per-step retrieval at a step-appropriate `top_k`).
- Compose a **structured user prompt** that instructs the generator to cover all twelve in order, each grounded in that step's own passages (or generate sequentially / streaming per-step).
- This sidesteps the enumeration penalty (we go straight to the step sections) and the context cap (assemble step-by-step, not all at once).

Keep the existing single-shot retrieval for ordinary queries — this is an *additional* path, not a replacement.

### 4. Anchored "deep understanding" additions (optional, phase 2)

- **Per-step curated summary + key quote** baked into the manifest/section index so the deep dive opens with a faithful, non-hallucinated anchor rather than only free generation.
- **Cross-step navigation** — "how does Step 4 relate to Step 9" becomes a first-class concept query by grounding each step's passages.
- **Offline reader / saved-passages integration** — a deep-dive screen that lets the user highlight and save the exact Step passages it just surfaced.

### 5. Frontend

- **Mobile (`mobile_app/lib/features/chat/chat_screen.dart` + a new `steps_deep_dive` screen / `rag_graph_view.dart`):** add a "Steps Deep Dive" entry (menu + starter suggestion), render 12 steps with expandable per-step depth, tap a step to read its passages, save to Saved Passages.
- **Web PWA (`static/`):** mirror the same surface. Remember `static/` is a *build artifact* of `flutter build web` — rebuild + `./deploy.sh` to ship (see CLAUDE.md/skill).

---

## Pulling a specific step's text — data flow (concrete)

For "deep-dive Step One", current retrieval returns scattered fragments. The new path:

1. `_referenced_source_substrings` / step classifier sees the query names 12&12 → `doc_id := twelve-steps-and-twelve-traditions`.
2. `sections.load(doc_id)` reads the manifest → finds `Step One` heading → collects its content blocks (verified: 22 blocks, ~1,011 words) → maps to chunk_ids via block_ids.
3. Those chunk_ids become the *grounding context* for that step (optionally passing them to `retriever` as a `where` filter on `block_ids` rather than a fresh similarity search — eliminates any possibility of the enumeration penalty or off-topic hits).
4. `USER_MESSAGE_TEMPLATE.format(context=<that step's text>, question=<deep-dive prompt>)` — one grounded generation per step, ordered.

---

## Anti-goals / guardrails

- **No server-side human moderation, no multi-user** — stays on-device/single-user per the FR triage stance (feature-requests.md:36).
- **Privacy preserved** — deep dive reads local/corpus literature; nothing new leaves the existing privacy boundary.
- **Literature-grounded, not model-invented** — anchored summaries come from curated passages (phase 2), never fabricated. The system prompt's "name the work you actually use" rule still applies.
- **Don't regress precision** — the normal single-shot retrieval path stays untouched for specific questions.

---

## Suggested implementation order

1. **`src/rag/sections.py`** — manifest loader + ordered section extraction + section→chunk_ids map. Unit-testable offline (stub `src.rag.retriever` like `build_knowledge_graph` tests do per CLAUDE.md).
2. **`/api/steps` + `/api/steps/{n}`** endpoints in `src/server.py` (+ `_build_chat_sources` / graph reuse).
3. **Chat assembly path** in `chat()` — step-wide query detection + per-step grounded prompt.
4. **Frontend deep-dive surface** (mobile then web), reusing the palette/sheet patterns.
5. **Deploy** via `deploy.sh`; verify on the live server (`ssh joshu@10.0.0.100` curl the new endpoints).

## Open questions to settle before coding

- Should the deep-dive chat reply stream **step-by-step** (12 chunks) or send one long composed answer? (Affects latency/UX; streaming per-step is friendlier on mobile.)
- Where does the "Steps Deep Dive" surface live: inside chat, the existing knowledge-graph screen, or a new menu entry? (Recommend: extend the graph screen + a chat starter suggestion.)
- Do we need cross-document structure (chapters of other books) in v1, or is 12&12 Steps the only target? (Recommend: 12&12 Steps first; make the loader generic so chapters are a trivial follow-up.)
