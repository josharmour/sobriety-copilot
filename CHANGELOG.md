# Changelog

## 1.1.1 (build 3) — 2026-07-09 — internal testing

First feature release since 1.0.0. Adds Private Mode (fully on-device chat),
a much smarter offline library, milestone tracking, an online-meetings
directory, and on-device voice dictation.

### Play Store "What's new" (paste into the internal-testing release notes)

```
• Private Mode: chat fully on your device — private and offline.
• Smarter offline search: the built-in library now uses fine-tuned
  AI embeddings for far better results, even with no signal.
• Milestone tracker with an Android home-screen widget.
• Online meetings directory: find live-now meetings and join in a tap.
• Today view: daily reading, nightly inventory, and reminders.
• On-device voice dictation — speak your message, fully offline.
• Faster, more reliable model downloads (now resumable).
```

### Highlights

- **Private Mode — on-device chat.** Fully offline recovery chat powered by
  Gemma-4-E2B, grounded in the offline library. Private-mode indicator +
  settings status card. (Android surface.)
- **Fine-tuned retriever (pack v3).** On-device search now uses a
  fine-tuned EmbeddingGemma (115,673 int8 vectors) in a hybrid BM25 + vector
  search — measurably better retrieval than the base model. Delivered via
  the `/api/packs` download (server already serving `pack_version: 3`).
- **On-device voice dictation (ASR).** sherpa-onnx streaming Zipformer,
  fully offline, replaces any server transcription.
- **Milestone tracker + home-screen widget** (Android).
- **Online meetings directory** — live-now sorting, join flow, radius
  control, worldwide OIAA + Virtual NA coverage.
- **Today view** — daily reading, nightly inventory, reminders, sponsor
  export.
- **Excerpt-only reader** — bounded study excerpts with purchase notices
  (study-aide posture, never full-book reproduction).

### Fixes

- **Offline search sources fixed** — Android's platform SQLite ships without
  FTS5, which silently broke every offline pack search; now bundles SQLite
  via `sqlite3_flutter_libs` (115,673 blocks indexed, confirmed on-device).
- **Private Mode crash fix** — the Tensor-G5 NPU model build CHECK-aborts in
  flutter_gemma's LiteRT runtime; NPU rung removed, GPU/CPU chain retained.
- **Resumable model download** — the private model download now resumes via
  HTTP Range instead of restarting.
- Retrieval diagnostics gated to debug builds (no query terms in release
  logcat).

### Not in this release (tracked)

- **Fine-tuned on-device *generator*** — trained (SFT, +0.25 answer quality
  vs base E2B) but gated on `.litertlm` conversion (needs a GPU-window
  export; the pipeline is proven). Private Mode uses the base E2B generator
  for now; the fine-tuned retriever ships regardless.
- **Cloud retriever re-index** — the fine-tuned retriever is not yet adopted
  server-side (a shadow-collection re-index; microservice + plan are ready).
- **APK/AAB ABI splits** to trim size — deferred.
