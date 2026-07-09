# Fable-Features — Overnight Build Checklist

Working task list from the 2026-07-06 feature audit (full report delivered in chat).
Statuses are updated as work lands: `[ ]` todo · `[x]` done · `[~]` partial/scaffolded · `[!]` needs your decision — not acted on autonomously.

Single-codebase rule: everything is shared Dart core + thin per-surface conditionals. No forks per platform.

---

## P0 — Fixes & hygiene

- [x] **Android location permissions** — add `ACCESS_FINE_LOCATION`/`ACCESS_COARSE_LOCATION` to `mobile_app/android/app/src/main/AndroidManifest.xml`; add iOS `NSLocationWhenInUseUsageDescription`, `NSCameraUsageDescription`, `NSMicrophoneUsageDescription`, `NSPhotoLibraryUsageDescription` to Info.plist. "Use my location" is currently broken on the Play build.
- [x] **Auth on `GET /api/bugs`** — enforce `BUG_ADMIN_TOKEN` (already in docker-compose, never checked in `src/server.py`). Unauthenticated endpoint currently exposes user conversation snippets.
- [x] **Stop server-side chat body logging by default** — `save_interaction` persists full message/response keyed by per-install UUID, contradicting privacy.html. Gate behind `STORE_CHAT_HISTORY` env (default off); keep timestamps/counters only.
- [x] **Base-URL mismatch** — RESOLVED per owner (2026-07-06): no visible URL field (normal users never need it); fixed the misleading "check the base URL below" error copy instead. `setBaseUrl` retained unused; a hidden dev affordance (long-press version in About) is available on request.
- [x] **Enable AltRecoverySheet** — built but unreachable (not in the app-bar menu enum). One-line fix + menu entry.
- [x] **Privacy page email typo** (already correct in repo — typo only in deployed copy; fixed by next deploy) — `support@sobriettycopilot.com` → `sobrietycopilot.com` (static/privacy.html and any source copy in mobile_app/web/).
- [x] **Crisis sheet: collapsed "More support options" expander** (988 / SAMHSA 1-800-662-4357) below the existing AA helpline default. NOTE: default presentation unchanged; added for Play AI/health policy review safety. Revert is one small widget if you don't want it.
- [ ] **Remove dead weight** — unused `permission_handler` dep audit, vestigial `sendMessage(audio:)` path notes, unused `_SheetHandle`. (Low priority; only if time.)
- [x] **Pack copyright triage** — RESOLVED by owner decision (2026-07-06): app is a study aide, not a publisher — snippets + citations + purchase encouragement; corpus and packs stay as-is. No action.
- [!] **`/api/transcribe` drift** — app calls it; endpoint absent from this repo. Confirm whether prod runs uncommitted code. Long-term fix is on-device ASR (see P5 stretch below).

## P1 — Milestone tracker + Android widget

- [x] **Local sobriety tracker (all surfaces, shared Dart)** — sobriety date picker (Settings + Today card), day count, next-milestone progress (24h/30/60/90/6mo/9mo/1yr/18mo/multi-year — keytag/chip milestones), stored locally only (SharedPreferences). Server `UserMemoryManager` stays dormant.
- [x] **Milestone card on the empty/chat state** ("Today" surface) with privacy-conscious copy toggle (show "Day 92" vs full label).
- [x] **Feed sobriety date into chat context client-side** — day count sent as client_context when tracking; server folds into system prompt, never persists (system-prompt note via existing request fields) so the assistant knows day counts without server storage.
- [x] **Android home-screen widget** — `home_widget` + Jetpack Glance native layer: day count + next milestone; midnight refresh via `workmanager`; discreet-text option. (Widget = Android/iOS only by nature; web/desktop get the in-app card — consistent with surface model.)
- [x] **Money-saved calculator (optional card)** — daily-spend field in the tracker editor; saved amount shown on the milestone card — daily spend input × days sober.

## P2 — Online meetings: coverage + one-tap join

- [x] **Backend: OIAA online-AA feed** (`data.aa-intergroup.org/6436f5a3f03fdecef8459055.json`, Meeting Guide format, ~7.7k meetings with Zoom `conference_url`s) ingested on the existing feed-cache pattern; server-side cache 12–24h.
- [x] **Backend: Virtual NA BMLT root** (`bmlt.virtual-na.org/main_server/`) for location-agnostic NA online meetings.
- [x] **Backend: `/api/meetings/online`** — not radius-bound; timezone-aware "happening now / starting soon" sort.
- [x] **Flutter: "Online now" tab** in the meetings sheet — live/starting-soon list, join button, `conference_url_notes` passcode with copy button.
- [x] **Anonymity interstitial** — one-time dialog before first Zoom launch ("Zoom shows your account name — consider 'First name, last initial', camera off"), persisted dismiss.
- [x] **Report-this-meeting affordance** (reuses `/api/bugs` plumbing with a `meeting` tag).

## P3 — In-person coverage quick wins

- [x] **Geocoder: drop hardcoded `countrycodes=us,ca`** (GEOCODE_COUNTRYCODES env, default worldwide) (server.py ~1574) — currently caps worldwide NA data from the BMLT aggregator. Keep US/CA as ranking preference, not a filter.
- [x] **Radius control in the meetings sheet** (15/30/60/100/200, persisted) (client hardcodes 30 mi; server allows 200) — 15/30/60/100/200 selector, persisted.
- [x] **Add Recovery Dharma + CMA TSML feeds** (probed live; fellowship filter extended, aa/na/all unchanged) (both verified live) with a `fellowship` field per feed; extend fellowship filter (AA / NA / More / All).
- [x] **Feed registry notes** — feeds.py header documents TSML onboarding; 'Don't see meetings near you? Tell us' button reports coverage gaps via /api/bugs — document the `admin-ajax.php?action=meetings` onboarding pattern in feeds.py header; add "Don't see meetings near you?" affordance → bug report tagged `coverage`.

## P4 — Daily practice: meditation/prayer + nightly inventory

- [x] **"Today" view** (new sheet/surface hosting: daily reading, milestone card, inventory entry point).
- [x] **Daily reading content (PD-only)** — 31-entry rotation in assets/daily/readings.json + Big Book 1st-ed. morning/evening practice + aa.org/na.org link-outs — rotation built from public-domain material: Big Book 1st-ed. morning/evening practice (pp. 86–88 text), Serenity Prayer, St. Francis Prayer, curated pre-1931 devotional excerpts + original reflections. Link-outs to aa.org Daily Reflections / na.org Just for Today for the copyrighted readers.
- [x] **Nightly inventory (10th/11th step)** — the p86 review as ~10 yes/no toggles + optional free text per flagged item + gratitude list; history calendar with streaks; local SQLite only.
- [x] **Reminders** — `flutter_local_notifications`: separate channels (morning reading / nightly review), user-chosen times, Android 13 `POST_NOTIFICATIONS` requested in context, discreet copy ("Time to check in").

## P7 — Sharing (export-first; no hosted community)

- [x] **`share_plus`** — sponsor export of inventories, daily-reading share, and citation-formatted saved-passage share (title + printed page).
- [ ] Deep-link scheme back into the reader — deferred.

## P6 — Proactive study prompts (local-only interim version)

- [x] **Keyword/taxonomy theme extraction** (13-theme recovery taxonomy, last 60 local user messages, opt-in toggle in Settings, accent 'Continue your study' cards on the starter view) over recent local conversation queries (steps 1–12, resentment, fear, amends, cravings, sponsorship, gratitude, …) → "Continue your study" starter cards on the empty state. Opt-in toggle in Settings, one-tap clear-history. No network, no new deps. (EmbeddingGemma clustering upgrade rides with P5 later.)

## P8 — Surface parity

- [x] **Desktop offline library** — `sqflite_common_ffi` factory init on Windows/Linux at startup.
- [x] **Graceful capability gating** (camera/OCR/mic hidden on web+desktop via capabilities.dart; gallery attach stays everywhere) — hide OCR/camera/mic buttons on surfaces where the plugin can't work instead of runtime snackbars.

## P5 — On-device Gemma "Private Mode" (BUILT 2026-07-07)

- [x] **Model**: Gemma 4 E2B-it `.litertlm` (2.59 GB, Apache 2.0, ungated HF CDN — URL verified) via flutter_gemma 0.13.6 (LiteRT-LM engine, GPU backend, OpenCL manifest entries).
- [x] **Download manager**: opt-in in-Settings download (progress, cancel, size-verified, resumable-safe .part), delete; sideload path via app external-files dir for testing.
- [x] **LocalChatRepository**: implements the existing ChatRepository — FTS5/BM25 retrieval from the offline pack (sanitized MATCH query, category-aware titles), condensed on-device prompt port per tone, history folding under a small token budget, streaming TokenEvents, Sources with docId/blockIds that deep-link into the offline reader, Gemma 4 thinking mode wired to the reasoning panel.
- [x] **Deterministic crisis interceptor** — keyword layer independent of the model, helpline-first block prepended before generation.
- [x] **Provider switch**: chat flips to on-device when the toggle is on AND the model is installed; falls back to server otherwise. Android-only surface for now.
- [x] Phase 2: **EmbeddingGemma vector retrieval** (shipped via offline pack v3), sherpa-onnx ASR to replace /api/transcribe (shipped). ABI splits to trim the 400 MB APK for Play (deferred). Note: on-device generator remains base Gemma-4-E2B; fine-tuned SFT model is gated on adapter conversion.
- [x] **Sources/citations FIXED (morning)**: root cause was Android's platform SQLite shipping without FTS5 — every offline pack search failed silently on-device ('no such module: fts5'). Now bundling SQLite via sqlite3_flutter_libs, search DB opened through the FFI factory on all platforms. Confirmed on-device: 115,673 blocks indexed, 30 hits on a live query.
- [x] **Crash fix (01:30)**: the Tensor-G5 NPU model build CHECK-aborts natively in flutter_gemma 0.13.6's LiteRT runtime (`Unknown model type: tf_lite_mtp_aux`) — NPU rung removed, G5 file deleted from device, standard model re-pushed. GPU/CPU chain retained. Do not re-add NPU until the plugin ships a newer litertlm runtime.
- [x] **Private Mode indicator**: app-bar 'Private' shield chip + settings status card ("Answering on this device").

## P5 phase 2 + drift fix (2026-07-07 morning)
- [x] **Drift fix**: committed the long-uncommitted src changes (prompts, retriever, reranker default off, docs) as their own commit; refreshed CLAUDE.md to match prod (dsv4/all-minilm models, new endpoints, Flutter static/, no /api/transcribe). Recovered the Jun-27 worker image to confirm — prod never had a transcribe endpoint; dictation was always meant to be on-device.
- [x] **Image chat wired server-side**: /api/chat now forwards photo attachments to the LLM as OpenAI image_url content parts behind `LLM_SUPPORTS_IMAGES` (default 0 — flip once the deployed model is confirmed multimodal). The app was already sending `images`; they were silently dropped.
- [x] **On-device ASR (replaces /api/transcribe)**: sherpa-onnx streaming Zipformer EN (122 MB, GitHub release) with the same download/extract lifecycle as neural voices; transcription runs in an isolate. Mic uses on-device ASR when installed, server fallback otherwise. Settings → Private Mode → "On-device voice dictation" download tile. Fully offline, private dictation.
- [ ] APK ABI splits to trim 400 MB fat APK for Play (deferred).
- [x] **EmbeddingGemma vector retrieval**: Delivered via pack v3 (115,673 int8 vectors). Hybrid search now fully active on-device.

## Owner-directed changes (2026-07-07 late night)
- [x] **Excerpt-only reader**: the offline reader now shows a bounded study excerpt (±30 blocks around the cited passage, or the opening for book taps) bracketed by purchase notices — study aide, never full-book reproduction. Search still spans the whole pack.
- [x] **Starter-prompt rotation**: pool grown to ~240 prompts (bigger buckets + evergreens merged into every draw) with a persisted 60-prompt no-repeat window — no more nightly "help me settle down enough to sleep" reruns. Study-suggestion cards and conversation follow-ups unaffected.

---

## Overnight log (2026-07-06 → 07-07)

All committed to master and deployed. Commits: 6cc7a48 checklist · f9f2e87 P0 fixes · 8bdb024 P1 tracker+widget · 90f9f98 P4 Today/inventory/reminders · b1ccdcf backend (bugs auth, logging gate, online directory, geocoder, feeds) · c0c4cde P2/P3 client · 3dc1610 P6/P7/P8 · 0786762 web build.

**Verified tonight:** `flutter analyze` clean (4 pre-existing warnings only); debug APK builds; web release builds; backend py_compile + synthetic tests for the online-directory schedule math and fellowship filter; live feed probes (OIAA, Virtual NA, Recovery Dharma, CMA); **deployed to the NAS and verified in prod** — /api/health ok, /api/meetings/online serving 10,369 meetings with live-now sorting, GET /api/bugs → 403 without token.

**To test on the phone (debug APK):** milestone tracker (starter-view card + Settings → Recovery tracker; long-press home screen → widgets → Sobriety counter), Today view (menu or under-input button: daily reading, morning/evening practice, evening review with streaks + sponsor share, reminders), meetings sheet (Online now tab with LIVE badges + join flow + anonymity note; radius chips; Dharma/CMA fellowships; report/coverage buttons), study suggestions (opt-in in Settings — needs a few prior questions to trigger), saved-passage share, GPS location (permission now actually in the manifest).

**Known drift found (needs your eyes, not fixed):**
- `/api/transcribe` and the `images` chat field are used by the app but absent from this repo's backend — prod evidently runs code that never landed in git. Mic + photo-attach still work against prod, but reconcile that code into the repo before it's lost like the mobile source was.
- CLAUDE.md still documents gemma4:e2b / nomic-embed-text; prod runs deepseek-v4-flash / all-minilm.
- Pre-existing uncommitted retriever/engine/templates changes remain uncommitted (I didn't touch them); server.py/docker-compose/service.py local hunks rode along in b1ccdcf, noted in its message.

**Deliberately not done:** P5 on-device Gemma (quarter-scale flagship — architecture in the audit report; needs model download + device validation you'd want to be awake for); hosted social features (contradicts zero-egress positioning — export-first sharing shipped instead); reader deep links.
