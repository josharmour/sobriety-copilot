# Sobriety Copilot Premium — Fully Local "Private Mode"

A paid tier of the Android app where **chat works entirely on-device**: no
query, message, or recovery detail ever leaves the phone. Airplane-mode
capable. This is the privacy play — the pitch is "your recovery stays in your
pocket."

Grounding numbers (prod, 2026-06-09): 28,871 indexed chunks, embeddings are
`nomic-embed-text` (768-dim), server model is `gemma-4-12b-it`. The mobile app
already routes chat through `ChatRepositoryInterface`, has on-demand large-file
downloads (TTS voice manager), and on-device neural TTS via sherpa-onnx — so
voice output is already cloud-free.

---

## Architecture

Mirror the server pipeline on the phone, minus the expensive extras:

```
                    SERVER (unchanged, free tier)
  query → HyDE → embed → hybrid retrieve (ChromaDB+BM25) → rerank → gemma-4-12b → SSE

                    DEVICE (premium "Private Mode")
  query → embed (on-device) → hybrid retrieve (bundled index) → Gemma 3n → token stream
                                      │
                              index bundle: chunk text + vectors + BM25 stats
                              (precomputed server-side, downloaded once)
```

Key insight from design discussion: RAG does **not** need the documents on the
device — only the index (per-chunk text + embedding + metadata). Citation
excerpts come from the chunk text itself.

### On-device components

| Component | Choice | Size | Notes |
|---|---|---|---|
| LLM | Gemma 3n E2B via `flutter_gemma` (LiteRT-LM) | ~3.1 GB | Same model family as prod; GPU-accelerated; supports thinking mode (maps to the existing show-thinking panel) |
| Query embedder | `nomic-embed-text` exported to ONNX, int8 | ~140 MB | **Must be the exact model that embedded the corpus.** Runs via onnxruntime (sherpa-onnx already pulls it in) or `flutter_gemma` embeddings if we re-embed the corpus with EmbeddingGemma instead — decide in Phase 0 |
| Index bundle | exported from ChromaDB server-side | ~50–70 MB | 28,871 × 768 int8 vectors ≈ 22 MB + scales; chunk text ~30 MB gz; BM25 df/avgdl tables; manifest |
| TTS | sherpa-onnx voices | done | already shipped |

Total premium storage footprint: **~3.3–3.7 GB** (LLM + embedder + index +
optional voice). All downloaded on demand after purchase, Wi-Fi-only by default.

---

## Phase 0 — Decisions (blockers, do first)

1. **Corpus licensing.** Distributing chunked text of AA/NA conference
   literature inside an app bundle is *redistribution*, a different legal
   posture than serving retrieval excerpts from our server. Options:
   a) include only license-clear categories in the bundle (the category ids
   already exist: `aa`, `na`, `conference_approved`, …), b) get permission,
   c) accept risk knowingly. **This gates everything; decide before building.**
2. **Embedding model.** Keep `nomic-embed-text` (ONNX export, corpus already
   embedded, zero server work) vs. EmbeddingGemma via `flutter_gemma` (simpler
   app, but requires re-embedding the corpus server-side with it). Default:
   keep nomic.
3. **Minimum device spec.** Gemma 3n E2B wants ~4 GB free RAM and a 2023+ SoC.
   Gate the purchase UI on `flutter_gemma`'s device-capability check so we
   never sell to a phone that can't run it.
4. **Pricing model.** Non-consumable unlock vs. subscription. Non-consumable
   is simpler and fits "you bought private mode" (no server cost to recoup).

## Phase 1 — Index bundle exporter (server side)

New `src/export_bundle.py` (+ Celery task & endpoint):

- Reads the active Chroma collection and emits a versioned artifact:
  - `manifest.json` — bundle version (corpus hash), embed model + dims,
    quantization scale, chunk count, category list, **prompt templates**
    (export `src/prompts/templates.py` tone variants + `USER_MESSAGE_TEMPLATE`
    as JSON so device prompts never drift from server prompts)
  - `vectors.bin` — int8-quantized embeddings + per-vector scale (f32 →
    int8 loses <1% retrieval quality at this scale)
  - `chunks.sqlite` — chunk text, source title, relative path, page, category,
    scale (the same fields `_build_chat_sources` uses today)
  - `bm25.json` — document-frequency table + average doc length (so device
    BM25 scores match `retriever.py`)
- Serve at `GET /api/private-bundle/manifest` + `GET /api/private-bundle/blob`
  (or pre-publish to static hosting). App polls the manifest version; corpus
  changes rarely, so updates are occasional small re-downloads.
- Respect Phase 0's licensing decision via a category allowlist in the export.

## Phase 2 — Purchase gate + asset manager (app)

- Add `in_app_purchase` (Play Billing). One non-consumable product:
  `private_mode`. Verify + persist entitlement; restore-purchases path.
- Generalize the existing TTS `VoiceManagerNotifier` download/extract/progress
  pattern into a shared `AssetManager` used by: LLM model (`.litertlm`),
  embedder, index bundle. (Same UX: progress bar, resumable, delete to
  reclaim space.)
- New Settings section **Private Mode**: purchase/unlock card → download
  checklist (model / embedder / index) → master toggle. Show total disk usage.

## Phase 3 — On-device retrieval engine (app)

New `lib/features/private/retriever.dart`, ported from `src/rag/retriever.py`:

- Cosine over int8 vectors (28.9k × 768 dot products is single-digit ms in
  Dart; do it in an isolate anyway).
- BM25 keyword scoring from the bundled stats.
- Same fusion weights + category boosts + scale-diversity selection as the
  server. **Skip HyDE and the cross-encoder reranker** (server treats both as
  optional already via `ENABLE_HYDE`/`ENABLE_RERANKER`); quality delta gets
  measured in Phase 5, and HyDE-via-local-LLM is a possible later upgrade.
- Unit-test parity: export ~50 server retrievals (query → top-k chunk ids)
  as fixtures; the Dart engine must reproduce ≥90% overlap.

## Phase 4 — Local chat pipeline (app)

- `LocalChatRepository implements ChatRepositoryInterface` — drop-in next to
  `HttpChatRepository`, selected when Private Mode is on. Emits the same
  event sequence the UI already consumes: `sources` first, then
  `thinking`/`token` stream, then `followups`/`done`.
- Prompting: tone system message + `USER_MESSAGE_TEMPLATE` from the bundle
  manifest, retrieved chunks formatted exactly like the server does.
- Conversation memory stays in the existing local conversation store; the
  server-side `UserMemoryManager` features (sobriety date, current step) move
  to SharedPreferences fields injected into the prompt.
- Follow-up suggestions: one extra short local generation, or static
  starter-prompt fallback if latency is poor.

## Phase 5 — Safety, parity, evaluation

- **Crisis safety is non-negotiable and must not depend on the small model.**
  Add a client-side crisis keyword/regex interceptor that surfaces the crisis
  sheet (SAMHSA 1-800-662-4357 / 911) *above* whatever the model says — in
  both modes, but it's the backstop for the 2B model especially.
- Feature behavior in Private Mode:
  - Chat / citations / saved passages / TTS — fully local
  - Suggest-as-you-type — local BM25 prefix search over chunk titles
  - Meeting finder / geocode — inherently network; show "requires connection"
    (finding a meeting is not a privacy-sensitive query — acceptable)
  - "Open full book" render links — hidden, or explicit "fetches from server"
  - Bug reports — explicit opt-in send only
- Evaluation: extend `tests/eval_rag.py` cases to run against the local
  pipeline (debug build exposes a localhost bridge, or export Q→A transcripts)
  and compare faithfulness/relevancy against the server baseline. Set a
  floor before launch; if E2B misses it, offer E4B on capable devices.

## Phase 6 — Polish & launch

- Download UX hardening: resume after kill, Wi-Fi-only toggle, storage-full
  handling, integrity check (sha256 from manifest).
- Battery/thermal sanity pass (long chats on GPU).
- Play listing + IAP review notes; privacy policy update (the *good* kind:
  "in Private Mode we cannot see your conversations, period").

---

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Corpus redistribution licensing | **High** | Phase 0 decision; category allowlist in exporter |
| 2B model gives shallower/less-grounded answers | Medium | strict prompt template, eval floor, E4B option, keep rerank-free retrieval honest |
| Low-end devices OOM / overheat | Medium | capability gate before purchase, E2B only, CPU fallback off |
| 3+ GB download abandonment | Low | resumable downloads, clear size labels (TTS flow already set the pattern) |
| Prompt/index drift between server and device | Low | prompts + weights ship inside the versioned bundle, never hardcoded in the app |

## Explicit non-goals (v1)

- iOS (Android first; `flutter_gemma` supports iOS later)
- Local meeting database
- On-device reranker / HyDE
- Syncing conversations between devices (defeats the point)

## Suggested order of attack

Phase 0 (decisions) → Phase 1 exporter + Phase 3 retriever in parallel
(retriever can develop against a hand-exported bundle) → Phase 4 local chat →
Phase 2 IAP (last of the build, first of the launch checklist) → Phase 5 → 6.
The riskiest unknown is answer quality from E2B with rerank-free retrieval —
prototype Phase 3+4 with a sideloaded bundle **before** investing in IAP and
exporter polish.
