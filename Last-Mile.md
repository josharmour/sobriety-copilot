# Last Mile — make the smart app *feel* smart

The intelligence is built: the retriever is fine-tuned and shipping, the
generator is trained, the features (Private Mode, meetings, milestones, Today
view) are in the release. But the **experience** between "we built smart AI"
and "a person in a hard moment gets a fast, reliable answer" is still rough.
This list is that last mile: **fast, reliable, and everywhere** — get the
responsiveness up, the plumbing solid, and the fine-tuned models actually
into users' hands.

> Statuses: `[ ]` todo · `[x]` done · `[~]` partial · `[!]` needs your decision.
> Prior lists complete: **Fable-Features.md** (P0–P8 build) and
> **finetuning-the-rag.md** (retriever + generator fine-tune).

---

## L1 — Fast (responsiveness is the #1 felt problem)

- [ ] **Cloud TTFT: kill the ~20s server-side stall.** Diagnosed 2026-07-09:
  dsv4 returns its first token in **0.04s**, but `/api/chat` takes **~20s to
  emit `sources` and ~23s to first token** — the entire delay is *before* the
  LLM is called. HyDE is off, embedding is 0.06s, reranker off — all ruled
  out. Pin the exact culprit in the retrieval/orchestration path (server logs
  showed retrieval firing many times per window — verify it's not doing
  redundant retrievals / multi-query fan-out per request). **Target: <2s
  TTFT.** Highest-leverage item — the model is already instant.
- [ ] **Local (on-device) TTFT.** Base Gemma-4-E2B prefilling a large RAG
  prompt on a phone is inherently slow. Levers: fewer injected passages
  (3 not 8), shorter system prompt, cap context length, stream the thinking
  panel so *something* appears immediately.
- [ ] **Perceived-speed polish.** Stream `sources` first (already happens) +
  a typing indicator; make sure the SSE isn't buffered by nginx/Cloudflare.

## L1 — Reliable (release-blocking)

- [ ] **Fix the E2B model download.** Diagnosed 2026-07-09: the URL is fine
  (returns the correct 2.4GB public file). The failure is app-side handling
  of the HF **Xet CDN redirect + `Range` resume + 2.4GB**. Prime suspect: the
  redirect lands on a **signed URL with an `Expires`/`Signature`**; a resume
  after a dropped download hits an *expired* signed URL. The recent resume
  hotfix patched the wrong layer. Needs the on-device error to confirm. Fix
  options: re-resolve the redirect fresh on each (re)start, verify 206 vs 200
  handling, add integrity check + clear retry UX. **Blocks Private Mode for
  every user until fixed.**

## L2 — Everywhere (deploy the fine-tuned intelligence)

- [ ] **Fine-tuned generator on-device (F2).** SFT model beats base E2B
  (+0.25 quality). The `.litertlm` export pipeline is *proven* — needs a GPU
  window to run the ~hours-long export (see `finetune/deploy/f2_report.md`:
  one-line `get_max_length` patch, `--quantization_recipe None` for a first
  pass). Then bundle → ship in a release.
- [ ] **Cloud retriever re-index (#3).** Adopt the fine-tuned EmbeddingGemma
  server-side. Microservice is built + parity-verified (`scripts/embed_server.py`);
  plan is turnkey (`finetune/deploy/cloud_reindex_plan.md`): run service →
  shadow collection `recovery_literature_gemma_v1` (768-dim) → verify →
  cutover.

## L2 — Better (quality ceiling)

- [ ] **Lift retrieval recall.** recall@8 = 0.44 is the hard ceiling on
  citation accuracy — the generator can only cite what's retrieved. Levers:
  better chunking, larger top-k into the generator, re-enable/tune the
  cross-encoder reranker on the final candidates, hybrid-fusion weighting.
  This is the biggest remaining *answer-quality* lever, bigger than more
  generator tuning.

## L3 — Reach & size

- [ ] **iOS Private Mode.** On-device chat is Android-only today; bring the
  Private Mode surface to iOS.
- [ ] **APK/AAB ABI splits.** Trim the ~400MB fat bundle for Play (per-ABI
  splits) — faster installs, smaller downloads.
- [ ] **Server A/B flag for the FT model (was F1).** `LLM_MODEL_FT` +
  per-request flag so a fine-tuned server model can be A/B'd against dsv4
  without a redeploy.

## L3 — Housekeeping (carried over, low priority)

- [ ] Deep-link scheme back into the offline reader (deferred).
- [ ] Dead-weight audit: unused `permission_handler`, vestigial
  `sendMessage(audio:)` notes, unused `_SheetHandle`.
