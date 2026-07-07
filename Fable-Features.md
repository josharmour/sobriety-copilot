# Fable-Features — Overnight Build Checklist

Working task list from the 2026-07-06 feature audit (full report delivered in chat).
Statuses are updated as work lands: `[ ]` todo · `[x]` done · `[~]` partial/scaffolded · `[!]` needs your decision — not acted on autonomously.

Single-codebase rule: everything is shared Dart core + thin per-surface conditionals. No forks per platform.

---

## P0 — Fixes & hygiene

- [ ] **Android location permissions** — add `ACCESS_FINE_LOCATION`/`ACCESS_COARSE_LOCATION` to `mobile_app/android/app/src/main/AndroidManifest.xml`; add iOS `NSLocationWhenInUseUsageDescription`, `NSCameraUsageDescription`, `NSMicrophoneUsageDescription`, `NSPhotoLibraryUsageDescription` to Info.plist. "Use my location" is currently broken on the Play build.
- [ ] **Auth on `GET /api/bugs`** — enforce `BUG_ADMIN_TOKEN` (already in docker-compose, never checked in `src/server.py`). Unauthenticated endpoint currently exposes user conversation snippets.
- [ ] **Stop server-side chat body logging by default** — `save_interaction` persists full message/response keyed by per-install UUID, contradicting privacy.html. Gate behind `STORE_CHAT_HISTORY` env (default off); keep timestamps/counters only.
- [ ] **Base-URL field in Settings** — `setBaseUrl` exists but has no UI; error copy references a field that isn't there. Unblocks self-hosters.
- [ ] **Enable AltRecoverySheet** — built but unreachable (not in the app-bar menu enum). One-line fix + menu entry.
- [ ] **Privacy page email typo** — `support@sobriettycopilot.com` → `sobrietycopilot.com` (static/privacy.html and any source copy in mobile_app/web/).
- [ ] **Crisis sheet: collapsed "More support options" expander** (988 / SAMHSA 1-800-662-4357) below the existing AA helpline default. NOTE: default presentation unchanged; added for Play AI/health policy review safety. Revert is one small widget if you don't want it.
- [ ] **Remove dead weight** — unused `permission_handler` dep audit, vestigial `sendMessage(audio:)` path notes, unused `_SheetHandle`. (Low priority; only if time.)
- [!] **Pack copyright triage** — `packs/library-v1.scpack` redistributes Hazelden titles + Joe & Charlie transcripts (the material AAWS stripped from Everything AA in May 2026); RAG corpus includes Daily Reflections / As Bill Sees It / 12&12. Legal/content decision — needs you. Recommendation in report §2.5: PD-tier public pack (1939/1955 Big Book, prayers, pre-1931 devotionals), copyrighted works RAG-cite-only.
- [!] **`/api/transcribe` drift** — app calls it; endpoint absent from this repo. Confirm whether prod runs uncommitted code. Long-term fix is on-device ASR (see P5 stretch below).

## P1 — Milestone tracker + Android widget

- [ ] **Local sobriety tracker (all surfaces, shared Dart)** — sobriety date picker (Settings + Today card), day count, next-milestone progress (24h/30/60/90/6mo/9mo/1yr/18mo/multi-year — keytag/chip milestones), stored locally only (SharedPreferences). Server `UserMemoryManager` stays dormant.
- [ ] **Milestone card on the empty/chat state** ("Today" surface) with privacy-conscious copy toggle (show "Day 92" vs full label).
- [ ] **Feed sobriety date into chat context client-side** (system-prompt note via existing request fields) so the assistant knows day counts without server storage.
- [ ] **Android home-screen widget** — `home_widget` + Jetpack Glance native layer: day count + next milestone; midnight refresh via `workmanager`; discreet-text option. (Widget = Android/iOS only by nature; web/desktop get the in-app card — consistent with surface model.)
- [ ] **Money-saved calculator (optional card)** — daily spend input × days sober.

## P2 — Online meetings: coverage + one-tap join

- [ ] **Backend: OIAA online-AA feed** (`data.aa-intergroup.org/6436f5a3f03fdecef8459055.json`, Meeting Guide format, ~7.7k meetings with Zoom `conference_url`s) ingested on the existing feed-cache pattern; server-side cache 12–24h.
- [ ] **Backend: Virtual NA BMLT root** (`bmlt.virtual-na.org/main_server/`) for location-agnostic NA online meetings.
- [ ] **Backend: `/api/meetings/online` (or `mode=online_directory`)** — not radius-bound; timezone-aware "happening now / starting soon" sort.
- [ ] **Flutter: "Online now" tab** in the meetings sheet — live/starting-soon list, join button, `conference_url_notes` passcode with copy button.
- [ ] **Anonymity interstitial** — one-time dialog before first Zoom launch ("Zoom shows your account name — consider 'First name, last initial', camera off"), persisted dismiss.
- [ ] **Report-this-meeting affordance** (reuses `/api/bugs` plumbing with a `meeting` tag).

## P3 — In-person coverage quick wins

- [ ] **Geocoder: drop hardcoded `countrycodes=us,ca`** (server.py ~1574) — currently caps worldwide NA data from the BMLT aggregator. Keep US/CA as ranking preference, not a filter.
- [ ] **Radius control in the meetings sheet** (client hardcodes 30 mi; server allows 200) — 15/30/60/100/200 selector, persisted.
- [ ] **Add Recovery Dharma + CMA TSML feeds** (both verified live) with a `fellowship` field per feed; extend fellowship filter (AA / NA / More / All).
- [ ] **Feed registry notes** — document the `admin-ajax.php?action=meetings` onboarding pattern in feeds.py header; add "Don't see meetings near you?" affordance → bug report tagged `coverage`.

## P4 — Daily practice: meditation/prayer + nightly inventory

- [ ] **"Today" view** (new sheet/surface hosting: daily reading, milestone card, inventory entry point).
- [ ] **Daily reading content (PD-only)** — rotation built from public-domain material: Big Book 1st-ed. morning/evening practice (pp. 86–88 text), Serenity Prayer, St. Francis Prayer, curated pre-1931 devotional excerpts + original reflections. Link-outs to aa.org Daily Reflections / na.org Just for Today for the copyrighted readers.
- [ ] **Nightly inventory (10th/11th step)** — the p86 review as ~10 yes/no toggles + optional free text per flagged item + gratitude list; history calendar with streaks; local SQLite only.
- [ ] **Reminders** — `flutter_local_notifications`: separate channels (morning reading / nightly review), user-chosen times, Android 13 `POST_NOTIFICATIONS` requested in context, discreet copy ("Time to check in").

## P7 — Sharing (export-first; no hosted community)

- [ ] **`share_plus`** — share saved passages with proper citation formatting; share inventory/gratitude summaries (the sponsor workflow).
- [ ] Deep-link scheme back into the reader — deferred unless time allows.

## P6 — Proactive study prompts (local-only interim version)

- [ ] **Keyword/taxonomy theme extraction** over recent local conversation queries (steps 1–12, resentment, fear, amends, cravings, sponsorship, gratitude, …) → "Continue your study" starter cards on the empty state. Opt-in toggle in Settings, one-tap clear-history. No network, no new deps. (EmbeddingGemma clustering upgrade rides with P5 later.)

## P8 — Surface parity

- [ ] **Desktop offline library** — `sqflite_common_ffi` init on Windows/Linux so packs/FTS/reader work on desktop.
- [ ] **Graceful capability gating** — hide OCR/camera/mic buttons on surfaces where the plugin can't work instead of runtime snackbars.

## P5 — On-device Gemma "Private Mode" (scaffold only overnight)

- [!] **Not buildable/testable overnight** (2.6 GB model download, device GPU validation, pack-vector export pipeline). Report §3-P5 has the full architecture: Gemma 4 E2B `.litertlm` 4-bit via `flutter_gemma`, EmbeddingGemma query embedder, pack-shipped precomputed vectors, opt-in self-hosted download, RAM gating; sherpa-onnx ASR replaces `/api/transcribe`.
- [ ] Stretch if core list finishes: `LocalChatRepository` skeleton behind a hidden flag + design notes, no user-visible UI.

---

## Overnight log

(updated as work proceeds)
