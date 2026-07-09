# Antigravity release prompt — sobriety-copilot (2026-07-08 fine-tuning cycle)

Copy everything below the line into Antigravity when you're ready to cut the
Play Store release. It is self-contained.

---

You are preparing a Play Store release of **sobriety-copilot** (Flutter app,
package under `mobile_app/`, repo root `/mnt/repos/sobriety-copilot`). A large
fine-tuning cycle just landed. Your job: (1) update the architecture docs to
reflect it, (2) bump the version, (3) build + ship the release with the
artifacts that are READY, and (4) leave the on-device fine-tuned generator
OUT of this release (it is gated on a conversion step that is not done — see
"Gated" below). Do not invent or re-derive the ML work; it is described here
and committed to git through commit `51e2e97`.

## What changed this cycle (the facts)

A full RAG fine-tuning effort ran end-to-end. Two models were trained; a 256-
question eval harness with an LLM judge (deepseek-v4-flash) gated everything.

1. **Retriever fine-tune — SHIPPING.** The on-device embedding model
   (`google/embeddinggemma-300m`) was full-fine-tuned on 61k synthetic
   query→passage pairs + 61k hard-negative triplets mined from the recovery
   corpus. Result: held-out rank@1 **0.68→0.84**; eval recall@8 improved
   **+3.3–3.7 points** over the base model in both dense-only and hybrid
   (dense+BM25) configs. Packaged as **`packs/library-v3.scpack`**
   (`pack_version: 3`, 115,673 int8 vectors, one per corpus block). This
   pack REPLACES `library-v2.scpack` on-device.

2. **Generator fine-tune — TRAINED, gated on conversion.** The on-device chat
   model (`google/gemma-4-e2b-it`) was SFT-tuned (then DPO, discarded) to
   ground answers in retrieved passages, name works by title, and refuse
   honestly. Clean eval vs the BASE E2B (the correct on-device baseline):
   answer_quality **+0.25** (3.41→3.66), faithfulness 4.97→4.99, ~2× fuller
   answers, honest-refusal strong. It does NOT beat the cloud model dsv4 —
   nor should it; it's a 2B on-device model. Merged weights live on the
   training box at `/home/joshu/ft-runs/sft-merged` (NOT in git; 10GB).

3. **Eval harness + honest gates** — `scripts/ft_*.py`, `finetune/eval/`.
   Key finding: **retrieval recall (0.44) is the ceiling on citation
   accuracy**, not the generator. Future gains come from better retrieval.

## The new architecture (put this in the docs)

RAG is unchanged as the grounding/citation layer. Per surface:

| Component | Private Mode (on-device) | Cloud (website + online app) |
|---|---|---|
| Retriever (embeddings) | **fine-tuned EmbeddingGemma** via pack v3 | still `all-minilm`; fine-tuned retriever NOT yet deployed (needs a re-index — see Gated) |
| Generator | base Gemma-4-E2B **for now**; fine-tuned SFT gated on conversion | **dsv4 (deepseek-v4-flash)**, unchanged — reached via `http://10.0.0.10:8002/v1` (LAN, prod) or `https://api.mtgacoach.com/v1` (LiteLLM gateway) |

## What to ship in THIS release
- **`packs/library-v3.scpack`** — the fine-tuned retriever vectors (the app's
  offline hybrid search now uses the better embeddings). Confirm the app's
  pack-download / `pack_version` gate accepts v3 and re-extracts vectors.
- Any pending **app feature work** in `mobile_app/` (there are uncommitted
  changes to launcher icons, `AndroidManifest.xml`, `pubspec.yaml`,
  `chat_notifier.dart`, `milestone_card.dart` — review, commit, include).
- Standard release hygiene: bump `pubspec.yaml` version+build, changelog,
  signed AAB, Play internal-testing track first.

## Gated — do NOT include in this release
- **Fine-tuned on-device generator.** Getting the SFT model onto devices
  needs a conversion that is NOT done: either (F2) load the SFT LoRA adapter
  at runtime via `flutter_gemma createChat(loraPath:)`, or (F3) convert the
  merged model to `.litertlm` via `ai-edge-torch`. Both are unproven for a
  custom-tuned Gemma-4-E2B. Until one works, Private Mode keeps the base
  E2B generator. (The retriever improvement ships regardless.)

## Docs to update (reflect the architecture table above)
- `CLAUDE.md`, `mobile_app/`-level `GEMINI.md` / `AGENTS.md` (if present),
  `Fable-Features.md`, and `finetuning-the-rag.md` (already current).
- Note: pack v2 → **pack v3** (fine-tuned retriever vectors) is the
  on-device change; the on-device generator is unchanged this release.
- Note: cloud generator is dsv4, unchanged; cloud retriever re-index is a
  future item.

## Verification before you ship
- App builds (`flutter build appbundle --release`), Private Mode offline
  search returns sources using the v3 pack, crisis routing intact, no query
  terms in release logcat.
