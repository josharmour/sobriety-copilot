# Source Documentation Fix — Canonical Document Model + Offline Android Packs

**Status:** design approved, not started.

> **Handoff notes (read first):**
> - Line numbers in this doc are approximate — the files have been edited since;
>   locate symbols by name (`grep -n "<symbol>" <file>`), never by line alone.
> - Already shipped at query/render time (keep, don't rebuild): enumeration/TOC
>   penalty in `src/rag/retriever.py`; a robust excerpt-highlight matcher in
>   `src/server.py` (`_locate_highlight_span`: split-tolerant tokens,
>   multi-candidate heads, stride walking) plus per-text-run `hl-seg` highlight
>   wrapping (a single `<span>` across `</p>` boundaries is invalid HTML and
>   gets auto-closed by browsers — do not regress this). These are the band-aids
>   that Phase 3 (block-id anchors) eventually makes unnecessary.
> - `/api/render` accepts `&debug=1` returning JSON `{hl_len, span, span_words,
>   content_len}` — use it to verify highlight behavior without parsing HTML.
> - Work ONE task per session, in order, and run the task's "done when" check
>   before moving on. Start with T1.1-T1.3 against *Twelve Steps and Twelve
>   Traditions - AA.pdf* and *Alcoholics Anonymous Comes of Age - Bill W.pdf*
>   (the two known-worst sources) before running the whole library.
**Goal:** fix source-material quality at the root (extraction debt), make citations
page/paragraph-accurate, and package the library + citations so the Android app
works **fully offline**.

This document is written so each task can be executed independently by a smaller
model. Every task lists the files to touch, exact steps, and a "done when" check.
Do the tasks in order inside a phase; phases 1-2 must land before 3-5.

---

## 1. Why (defects observed in production, 2026-06-11)

All of these were observed live and are currently *compensated for* at query time
instead of fixed at the root:

| # | Defect | Example seen | Current band-aid |
|---|--------|-------------|------------------|
| D1 | Doubled-character text layers in PDFs | `1122&&1122__IInnssiiddee__EEnnggglliisshh..iinndddd` (12&12 InDesign footer, every glyph doubled) | none — pollutes chunks + viewer |
| D2 | Running heads / page numbers embedded mid-text | `50 ALCOHOLICS ANONYOUS COMES OF AGE` (note OCR typo), bare `297` | partial (`_detect_running_headers` in `src/rag/document_processor.py:29`) |
| D3 | Hard line-wraps + broken ligatures | `practi- cal`, `self-suffi ciency`, `fi rst` | none — viewer shows fragment-per-line |
| D4 | TOC / steps-list pages indexed as content | "Step 10" query returned 4 bare steps-list chunks in top-5 | query-time regex penalty (`RAG_ENUMERATION_PENALTY` in `src/rag/retriever.py`) |
| D5 | Chunks starting mid-sentence | excerpt began `power. Sustained and personal exertion…` | none |
| D6 | Indexer and viewer extract text **independently** and disagree | whole fuzzy-highlight apparatus (`_locate_highlight_span`, `src/server.py:281`) exists only to bridge this | fuzzy token matching |
| D7 | No stable page/paragraph identity | citations show a filename, not "12&12, p. 88"; viewer scrolls by fuzzy match | none |

**Core idea:** extract each book ONCE into a canonical, structured **manifest**.
Three consumers read it: the RAG indexer, the web document viewer, and a new
**offline content pack** for the Android app. Citations carry stable `block_ids`
that mean the same thing on the server and on the phone.

```
documents/*.pdf|epub
        │  (Phase 1: extractor + repairs + lint)
        ▼
documents/.manifests/<doc_id>.json     ←── single source of truth
        │                │                       │
        ▼                ▼                       ▼
  RAG chunks      /api/render viewer      Android content pack
  (Phase 2)          (Phase 4)            (Phase 5, offline)
```

---

## 2. Data contracts (write these first, everything depends on them)

### 2.1 Manifest schema — `documents/.manifests/<doc_id>.json`

```json
{
  "schema_version": 1,
  "doc_id": "twelve-steps-and-twelve-traditions",
  "source_file": "conference_approved/Twelve Steps and Twelve Traditions - AA.pdf",
  "content_sha256": "<sha256 of source file>",
  "extractor_version": 1,
  "title": "Twelve Steps and Twelve Traditions",
  "author": "AA",
  "category": "conference_approved",
  "blocks": [
    {"id": "b00041", "type": "heading",   "level": 2, "text": "Step Ten",
     "printed_page": 88, "physical_page": 92},
    {"id": "b00042", "type": "epigraph",  "text": "“Continued to take personal inventory…”",
     "printed_page": 88, "physical_page": 92},
    {"id": "b00043", "type": "paragraph", "text": "As we work the first nine Steps, we prepare…",
     "printed_page": 88, "physical_page": 92}
  ],
  "lint": {
    "doubled_layer_pages": 3,
    "headers_stripped": 180,
    "hyphen_repairs": 240,
    "ligature_repairs": 55,
    "garbage_lines_removed": 12,
    "toc_blocks": 14,
    "ocr_recommended": false
  }
}
```

Rules:
- `doc_id` = slugified title (lowercase, hyphens, no extension/author). Stable forever.
- `blocks[].id` = `b` + zero-padded ordinal. **Never renumber existing blocks**
  when re-extracting with the same `extractor_version`; bump `extractor_version`
  if numbering changes (consumers treat that as a new edition).
- `type` ∈ `heading | paragraph | list | toc | index | page_header | page_footer | footnote | epigraph | garbage`.
- `printed_page` = the page number printed on the page (nullable); `physical_page` = 1-based file page.
- Block text is fully repaired: no hyphen splits, no hard wraps, no running heads.

### 2.2 Chunk metadata additions (Chroma)

Every indexed chunk gains: `doc_id`, `block_ids` (JSON list), `printed_page_start`,
`printed_page_end`. Existing metadata keys stay unchanged.

### 2.3 `sources` SSE event additions (`_build_chat_sources`, `src/server.py:782`)

Each source dict gains: `"doc_id"`, `"block_ids"`, `"page"` (printed_page_start).
Old clients ignore unknown keys (verified for both web and Flutter parsers).

### 2.4 Android content pack — `packs/library-v<N>.scpack` (a zip)

```
manifest-index.json      # [{doc_id, title, author, category, blocks_count, sha256}]
manifests/<doc_id>.json  # the same files as the server uses, verbatim
search.db                # SQLite with FTS5 table (built in Phase 5, on-device-ready)
pack.json                # {pack_version, schema_version, created_utc, doc_count}
```

The pack ships the *same* manifests as the server. A citation
`{doc_id, block_ids}` resolves identically online (web viewer anchor) and
offline (Android reader scroll-to-block).

---

## 3. Phase 1 — Canonical extractor (the real work)

Existing code to build on: `src/rag/document_processor.py` — extractor classes
with `can_handle()/extract()` (lines 106-150), `_detect_running_headers` (line 29),
`clean_extracted_pages` (line 83), returning `ExtractedDocument`.

### T1.1 Repair functions (pure, unit-testable) — **DONE**
**Files:** new `src/rag/text_repair.py`, new `tests/test_text_repair.py`
**Steps:**
1. `collapse_doubled_layers(line: str) -> str` — detect lines where >60% of
   characters appear doubled in sequence (`AABBCC` pattern, D1 example above);
   collapse pairs. Return the input unchanged when below threshold.
2. `repair_hyphenation(text: str) -> str` — join `word-\nrest` and `word- rest`
   when `wordrest` (lowercased) appears elsewhere in the document OR the
   fragment is not a standalone dictionary-ish token (heuristic: next part
   starts lowercase). Keep real hyphenated compounds.
3. `repair_ligatures(text: str) -> str` — fix `fi `/`fl ` splits: `suffi ciency`
   → `sufficiency`, `fi rst` → `first` (regex: `\b(\w*f[il]) (\w+)` where the
   join produces a word that appears ≥2 times elsewhere, plus a fixed allowlist:
   first, sufficient, fellowship-type common words).
4. `reflow_paragraphs(lines: list[str]) -> list[str]` — join hard-wrapped lines
   into paragraphs: a line joins the previous one unless the previous ends in
   sentence punctuation (.?!:;") or the line starts a list/heading pattern.
5. Unit tests with the literal D1/D3 examples from the table above.
**Done when:** `pytest tests/test_text_repair.py` passes; each function has ≥3 cases.

### T1.2 Block classifier — **DONE**
**Files:** new `src/rag/block_classifier.py`, new `tests/test_block_classifier.py`
**Steps:**
1. `classify_block(text: str, position_on_page: float | None) -> str` returning a
   type from §2.1.
2. Port the enumeration detection from `src/rag/retriever.py`
   (`_ENUMERATION_MARKER`, `_CONTENTS_RE`) → returns `"toc"` or `"list"`.
3. `page_header`/`page_footer`: short line (≤8 words), repeats across ≥3 pages
   (reuse `_detect_running_headers` logic), or bare number.
4. `heading`: short line, no terminal punctuation, title-case or ALL CAPS.
5. `garbage`: doubled-layer residue, lines with <40% alphanumeric chars.
**Done when:** unit tests classify the D1/D2/D4 literal examples correctly.

### T1.3 Manifest builder for PDFs — **DONE**
**Files:** new `src/rag/manifest_builder.py`; reuse the PDF extractor in
`document_processor.py` for raw page text.
**Steps:**
1. `build_manifest(source_path: str, category: str) -> dict` implementing §2.1:
   extract pages → per-page: strip+count headers/footers → repair (T1.1) →
   reflow → classify blocks (T1.2) → detect `printed_page` (most common bare
   number in header/footer position; nullable).
2. Populate `lint` counters as repairs happen. Set `ocr_recommended: true` when
   garbage+unclassifiable lines exceed 5% of total.
3. `write_manifest(manifest, documents_dir)` → `documents/.manifests/<doc_id>.json`;
   skip rebuild when `content_sha256` and `extractor_version` are unchanged.
**Done when:** running it on *Twelve Steps and Twelve Traditions - AA.pdf*
produces a manifest with zero doubled-character blocks, the contents page typed
`toc`, and Step Ten's chapter text in clean paragraphs (manually inspect ~20 blocks).

### T1.4 Manifest builder for EPUBs — **DONE**
**Files:** `src/rag/manifest_builder.py` (extend)
**Steps:** EPUBs are structured HTML — walk the spine; `<h1-h6>` → heading
blocks with `level`, `<p>` → paragraph, `<ol>/<ul>` → list. No page numbers:
`printed_page: null`, `physical_page` = spine index. Reuse T1.1 repairs only
where needed (epub text is usually clean).
**Done when:** *Little Red Book - E A Webster.epub* manifest has chapter
headings as `heading` blocks and prose as full-paragraph blocks.

### T1.5 CLI + lint report — **DONE**
**Files:** new `scripts/build_manifests.py`
**Steps:** iterate `documents/**/*.{pdf,epub}` (skip `@eaDir`, `.manifests`),
build all manifests, print a one-line lint summary per book and a final table
sorted by garbage ratio. Exit nonzero if any `ocr_recommended`.
**Done when:** `python scripts/build_manifests.py documents/` completes over the
whole library and the report flags the known-bad books (D1/D2 sources).

---

## 4. Phase 2 — Index from manifests

### T2.1 Chunker consumes blocks
**Files:** `src/rag/indexer.py` (`_build_records_for_document`, line 119),
`src/rag/semantic_chunker.py`
**Steps:**
1. Load the manifest for each document; build chunker input from `paragraph`,
   `epigraph`, and `footnote` blocks only — **`toc`/`index`/`page_header`/
   `page_footer`/`garbage` blocks never become chunks** (fixes D4 at the root;
   keep the query-time penalty as a backstop).
2. Track which block ids feed each chunk; chunk boundaries may only fall on
   block boundaries (fixes D5).
3. Attach §2.2 metadata to every record. Prepend the nearest `heading` block
   text to the chunk's embedding input (chapter context), not to the stored text.
4. Fall back to the legacy text path when no manifest exists (warn once per doc).
**Done when:** shadow-indexing (T2.2) yields chunks whose `block_ids` resolve to
the right manifest blocks; no chunk starts mid-sentence on a 10-chunk sample.

### T2.2 Shadow index + eval
**Files:** none new — use `perform_shadow_index` (`src/tasks/indexing.py`) and the
eval harness (`requirements-eval.txt`).
**Steps:**
1. Build the new index into a shadow collection.
2. Fixed query set (minimum): `Step 10`, `What's the difference between step
   four and step ten?`, `What does the Big Book say about resentment?`,
   `making amends in Step Nine`, `how do I handle cravings at night`.
3. For each query record top-8 (source, page, first-80-chars) old vs new; a
   human reviews the diff. Hard requirement: zero `toc`-typed content in top-8.
4. Swap collections (existing swap path), keep the old one until verified.
**Done when:** review sheet approved; production flipped; rollback documented
(one-line: re-point `RAG_COLLECTION`).

### T2.3 Citations carry pages + block ids
**Files:** `src/server.py` (`_build_chat_sources`, line 782)
**Steps:** add §2.3 fields from chunk metadata. Update the web chip tooltip to
"Title — p. 88". (Web/Flutter already ignore unknown fields; no breaking change.)
**Done when:** `curl /api/chat` shows `doc_id`, `block_ids`, `page` per source.

---

## 5. Phase 3 — Viewer renders manifests (kills fuzzy highlighting)

### T3.1 Block-render endpoint
**Files:** `src/server.py` (near `/api/render/{filepath:path}`, line 1654)
**Steps:** new `GET /api/doc/{doc_id}?blocks=b00042,b00043` → HTML rendered
*from the manifest*: headings as `<h2-h4>`, paragraphs as `<p id="b00043">`,
page boundaries as subtle `<div class="page-marker">p. 88</div>` (preserves the
page/paragraph index the product wants). Requested blocks get the existing
highlight style + `id="hl"` on the first one.
**Done when:** the Step Ten passage renders as clean paragraphs with its blocks
highlighted — no doubled characters, no line fragments, no running heads.

### T3.2 Web viewer prefers block rendering
**Files:** `static/index.html` (`buildRenderUrl` line ~4362, modal at
`openModal`/`renderModalSource` lines ~4629-4652)
**Steps:** when a source has `doc_id` + `block_ids`, open `/api/doc/...` and
scroll to `#hl`; otherwise fall back to the legacy `/api/render` fuzzy path.
Keep an "open original PDF" link for provenance.
**Done when:** citation clicks land exactly on the cited blocks for
manifest-backed sources; legacy path still works for any unconverted file.
*(Reminder: frontend changes require rebuilding BOTH `app` and `nginx` images.)*

---

## 6. Phase 4 — Android offline packs

Target: the Flutter app (`mobile_app/`) functions **fully offline** for the
library: browse books, full-text search, open citations from past conversations,
read whole chapters. (Offline *chat* is a separate optional tier — §6 T4.5.)

### T4.1 Pack builder
**Files:** new `scripts/build_content_pack.py`
**Steps:** assemble §2.4 zip from `documents/.manifests/`; build `search.db`
(SQLite) with `CREATE VIRTUAL TABLE blocks USING fts5(doc_id, block_id, heading,
text)` — one row per paragraph/epigraph block, `heading` = nearest heading text.
FTS5's built-in BM25 gives offline ranking with zero model weights.
**Done when:** pack builds; `sqlite3 search.db "SELECT doc_id, block_id FROM
blocks WHERE blocks MATCH 'personal inventory' ORDER BY rank LIMIT 5"` returns
sensible Step 4/10 blocks.

### T4.2 Pack hosting + app download
**Files:** `src/server.py` (new `GET /api/packs/latest` → pack.json metadata +
download URL), `mobile_app/lib/data/repositories/` (new `library_repository.dart`)
**Steps:** app checks `pack_version` on launch (when online), downloads to app
storage, verifies sha256, swaps atomically. The pack is served only by the
user's own instance — the literature stays user-provisioned (do not bundle the
corpus into a store-distributed APK; it ships via the private server).
**Done when:** fresh install + one online launch → airplane mode → library opens.

### T4.3 Offline reader + citation deep links
**Files:** `mobile_app/lib/features/` (new `library/` feature),
`mobile_app/lib/data/models/chat_models.dart` (extend `Source` with `docId`,
`blockIds`, `page` — fields already arrive in the SSE event after T2.3)
**Steps:** reader screen renders manifest blocks (ListView of paragraph widgets,
heading styles, page-marker rows). Tapping a citation in any (cached) chat
scrolls to its `block_ids` and highlights them — identical anchor semantics to
the web viewer. Conversations are already client-side; persist them with
`sqflite` so history survives offline restarts.
**Done when:** airplane mode → open old conversation → tap citation → reader
opens at the highlighted passage with "p. NN" visible.

### T4.4 Offline search
**Files:** `mobile_app/lib/features/library/` (search screen), `sqflite` dep
**Steps:** query `search.db` FTS5 (BM25 ranked), group results by book, render
snippet + page, tap → reader anchor. This is deterministic retrieval — the same
literature grounding the server uses, minus embeddings.
**Done when:** offline search for "resentment" surfaces the same passages the
server cites (spot-check 3 queries against server `sources`).

### T4.5 (Optional, later) Offline chat tier
On-device small model (e.g. Gemma-class nano via MediaPipe/AI Edge) using T4.4's
FTS5 retrieval to build the same `USER_MESSAGE_TEMPLATE` context, with the
system prompt from `src/prompts/templates.py`. Out of scope for this effort;
the pack format already provides everything it needs. Until then, offline chat
shows a clear "offline — library and search available" state.

---

## 7. Order, sizing, and ground rules for the implementing model

| Order | Task | Size | Risk |
|------:|------|------|------|
| 1 | T1.1, T1.2 (pure functions + tests) | S | none — additive |
| 2 | T1.3, T1.4, T1.5 (manifest builders) | M | iterate on 3-4 worst PDFs first |
| 3 | T2.1, T2.2 (index + shadow eval) | M | gated by human review before swap |
| 4 | T2.3 (citation fields) | S | none — additive |
| 5 | T3.1, T3.2 (block viewer) | M | legacy fallback retained |
| 6 | T4.1-T4.4 (Android offline) | M-L | new feature surface, isolated |

Ground rules:
- Never modify files under `documents/` — sources are read-only; all output goes
  to `documents/.manifests/` and `packs/`.
- Every task lands with its test; run `python3 -m py_compile` on touched modules
  before deploying.
- Deployment quirks (Synology NAS at 10.0.0.2): copy files with
  `cat file | ssh joshu@10.0.0.2 'cat > /volume1/repos/sobriety-copilot/<path>'`
  (rsync prompts for a password — DSM ACL quirk); rebuild with
  `docker-compose build app nginx && docker-compose up -d` (nginx bakes its own
  copy of `static/`).
- Re-extraction is idempotent: same source hash + extractor version → no-op.
- Keep the query-time enumeration penalty (`src/rag/retriever.py`) even after
  T2.1 — defense in depth for any unconverted document.
