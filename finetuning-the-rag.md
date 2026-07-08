# finetuning-the-rag — Swarm Roadmap

Goal: make the whole stack *measurably* smarter on 12-step literature by
fine-tuning (1) the retriever, (2) the generator — while keeping RAG as the
grounding/citation layer. RAG is not being replaced: citation accuracy is the
product and the legal posture (snippets + citations + purchase notices).

**God metric:** citation-grounded answer quality on the Track-A eval set.
No trained artifact ships unless its eval-gate task beats baseline.

---

## How this file is used (orchestration protocol)

- **Workers**: local coding agents backed by `dsv4` (deepseek-v4-flash) at
  `http://10.0.0.10:8002/v1`. One task = one agent run. Every task below is
  scoped to fit a small context: the agent loads ONLY the files listed in its
  *Context* line plus this file's *System facts* section.
- **Reviewer**: Fable. Every task ends with a **Verify** block — one or two
  commands whose output is small and decisive. Fable's review = run Verify,
  skim the diff of the listed deliverables, mark the ledger. Workers must
  make Verify pass before handing off; anything else is bounced back.
- **Statuses** in the ledger: `todo → in-progress(agent) → verify(fable) → done`.
  Workers edit ONLY their task's deliverables + the ledger row. Never touch
  another track's files.
- **Handoff (on Verify pass), in order:** (1) set your ledger row to
  `verify(fable)`; (2) end your reply with a line
  `HANDOFF: <task-ids> ready for Fable review`; (3) continue to the next
  unblocked task WITHOUT waiting — review is asynchronous. Skipping the
  ledger or the HANDOFF line is a protocol violation even when the work is
  good.
- **Commits**: one commit per task, message `FT-<id>: <summary>`. No pushes
  from workers; Fable pushes after verify.
- **Artifacts** live under `finetune/` (gitignore large files; commit
  configs, scripts, dataset *samples*, and metrics JSON — never full
  datasets > 5 MB or checkpoints).

## System facts (paste into every worker prompt)

- Repo root: `/mnt/repos/sobriety-copilot`. Python: `source venv/bin/activate`
  (torch 2.12 cu130 + sentence-transformers 5.5.1 installed).
- Corpus: `packs/library-v1.scpack` → `search.db` FTS5 table
  `blocks(doc_id, block_id, heading, text)` — 115,673 rows, 79 docs.
  Extracted copy for tooling: build your own tempdir; do NOT edit packs/.
- Teacher/worker LLM: OpenAI-compatible at `http://10.0.0.10:8002/v1`,
  model name `dsv4`, no API key. Use `temperature=0.7` for generation,
  `0.0` for judging.
- Embeddings today: server `all-minilm` (ollama); on-device EmbeddingGemma
  (`google/embeddinggemma-300m`, HF token at `~/.cache/huggingface/token`);
  precompute pipeline `scripts/build_pack_vectors.py` (768-dim int8).
- Eval harness to extend: `tests/eval_rag.py` (RAGAS; deps in
  `requirements-eval.txt`).
- GPUs: 2× RTX PRO 6000 (96 GB). **Both serve prod vLLM.** Training obeys
  the Track-D window protocol; inference-only work (data gen, judging) may
  hit the vLLM endpoint anytime.
- Prompts that define the target voice: `src/prompts/templates.py` (server),
  `mobile_app/lib/features/private_mode/local_prompts.dart` (on-device).

## Dependency graph / parallel lanes

```
Lane 1: A1 → A2 → A3 → A4 ──────────────┐
Lane 2: B1 → B2 → B3 → B4 ── B5         ├─ E2/E4 gates need A4
Lane 3: C1 → C2 → C3 → C5 ── C4         │
Lane 4: D1 ∥ D2 → D3 ∥ D4 → D5          │
Then:   E1(C5+D3) → E2(A4) → E3(C4+D4) → E4(A4)
Spikes: F2 ∥ F3 anytime; F1 after E2 passes.
```
Lanes 1–4 run **fully in parallel** (disjoint files). Within a lane, tasks
are sequential.

---

## Track A — Evaluation harness (gates everything)

### A1. Mine eval questions from the corpus
- **Context:** this file + `scripts/build_pack_vectors.py` (for the
  search.db access pattern only).
- **Deliverable:** `finetune/eval/questions.jsonl` — ≥240 rows:
  `{id, question, kind, source_doc_id, source_block_ids[]}`.
  Kinds (≥40 each): `doctrine` (what does X teach), `practical` (how do I…),
  `phrase` (explain a phrase/slogan), `crosswork` (compare two works),
  `personal` (struggling-person message that should ground in literature),
  `negative` (question the corpus does NOT answer — expected behavior:
  say so). Generate with dsv4 from randomly sampled blocks; question text
  must NOT quote the block verbatim.
- **Verify:** `python -m scripts.ft_checks a1` → prints row count per kind,
  schema-valid, all source ids exist in search.db. (Worker writes
  `scripts/ft_checks.py` with an `a1` subcommand as part of this task;
  later tasks extend it.)

### A2. Gold citations + reference answers
- **Context:** A1 output + this file.
- **Deliverable:** `finetune/eval/gold.jsonl` — for each A1 question:
  `{id, gold_doc_ids[], gold_block_ids[], reference_answer}`. Reference
  answers written by dsv4 WITH the source blocks in-context, ≤120 words,
  naming the work by title. `negative`-kind rows get
  `gold_doc_ids: []` and a reference refusal.
- **Verify:** `python -m scripts.ft_checks a2` → 1:1 id coverage vs A1,
  every gold block exists, sampled 5 rows printed for spot-read.

### A3. Judge + metrics runner
- **Context:** `tests/eval_rag.py`, A1/A2 outputs, this file.
- **Deliverable:** `scripts/ft_eval.py` — runs a *system under test* against
  the eval set and emits `finetune/eval/runs/<name>.json` with:
  `retrieval.recall@4/@8` (gold block in top-k), `citation_accuracy`
  (answer names a gold work's title), `faithfulness` + `answer_quality`
  (dsv4-as-judge at temp 0, rubric prompts included in the script),
  `refusal_correctness` (negative kind). Systems pluggable via a small
  interface: `--system server` (POST /api/chat against a base URL) and
  `--system retriever-only`.
- **Verify:** `python -m scripts.ft_eval --system retriever-only --limit 12`
  completes and writes a run file with non-null metrics.

### A4. Baseline report
- **Context:** A3 script.
- **Deliverable:** `finetune/eval/runs/baseline-server.json` +
  `baseline-retriever.json` (full 240), and
  `finetune/eval/BASELINE.md` (one table).
- **Verify:** `python -m scripts.ft_checks a4` → both run files complete
  (240 rows), BASELINE.md table matches the JSONs.

## Track B — Retriever fine-tune (EmbeddingGemma)

### B1. Synthetic (query → passage) pairs
- **Context:** this file only (search.db pattern included above).
- **Deliverable:** `finetune/retriever/pairs.jsonl` — ≥60k rows
  `{query, doc_id, block_id}`: 1–2 dsv4-generated questions per eligible
  block (text len ≥ 200 chars), varied register (newcomer phrasing, slang,
  formal). **Exclude every block cited in A2 gold** (leakage guard) —
  read `finetune/eval/gold.jsonl` if present, else regenerate exclusions
  when A2 lands (note in ledger).
- **Verify:** `python -m scripts.ft_checks b1` → count, no gold leakage,
  10-row sample printed.

### B2. Hard negatives
- **Context:** B1 output + `scripts/build_pack_vectors.py`.
- **Deliverable:** `finetune/retriever/triplets.jsonl` —
  `{query, pos_block, neg_blocks[4]}` where negatives are top-BM25 /
  top-vector hits that are NOT the positive (and not adjacent blocks of it).
- **Verify:** `python -m scripts.ft_checks b2` → no positive leaked into
  negatives, adjacency respected.

### B3. Train the retriever
- **Context:** B2 output + Track-D window protocol (D1).
- **Deliverable:** `finetune/retriever/train_retriever.py` (sentence-
  transformers, MultipleNegativesRankingLoss, EmbeddingGemma base, LoRA or
  full — document choice), checkpoint at
  `finetune/retriever/model/` (gitignored), `metrics.json` (loss curve).
  Runs in a D1 window on ONE gpu.
- **Verify:** `python -m scripts.ft_checks b3` → checkpoint loads, embeds
  8 texts, dim=768.

### B4. Retriever eval gate
- **Context:** A3 script + B3 checkpoint.
- **Deliverable:** `finetune/eval/runs/retriever-ft.json` via
  `ft_eval --system retriever-only --embedder finetune/retriever/model`.
- **Gate:** recall@8 ≥ baseline + 5 points, recall@4 not worse. If failed:
  ledger back to B1/B2 with notes.
- **Verify:** run file exists; Fable compares numbers.

### B5. Re-embed + pack v3 (only after B4 passes)
- **Context:** `scripts/build_pack_vectors.py`, `scripts/assemble_pack_v2.py`.
- **Deliverable:** vectors rebuilt with the tuned embedder;
  `packs/library-v3.scpack`; note that the on-device query embedder must be
  the SAME tuned model exported to tflite — if export is blocked, ship v3
  server-side only and flag F3 dependency.
- **Verify:** `python -m scripts.ft_checks b5` → vector count matches
  block count, pack unzips, meta model id updated.

## Track C — Generator datasets (SFT / RAFT / DPO)

### C1. Prompt taxonomy + seeds
- **Context:** `src/prompts/templates.py`,
  `mobile_app/lib/data/starter_prompts.dart`, this file.
- **Deliverable:** `finetune/gen/taxonomy.json` — ~30 intents × difficulty ×
  register grid with 3 seed phrasings each (crisis-adjacent intents flagged;
  those come only from the fixed safety templates, never free-generated).
- **Verify:** `python -m scripts.ft_checks c1` → schema, counts, crisis
  intents flagged.

### C2. RAFT sample generator
- **Context:** C1 + `src/prompts/templates.py` (voice rules).
- **Deliverable:** `scripts/ft_gen_raft.py` + `finetune/gen/sft.jsonl`
  (≥8k samples): each `{messages:[system,user,assistant], meta}` where the
  user turn embeds 3–5 retrieved passages (1–2 gold + distractors, exact
  formats from `local_prompts.dart`) and the assistant answer (dsv4,
  temp 0.7) grounds in gold, names the title, ignores distractors. Include
  10% no-context samples and 5% "corpus doesn't cover this" refusals.
  **Exclude A2 gold blocks.**
- **Verify:** `python -m scripts.ft_checks c2` → schema, leakage guard,
  distractor-citation rate on 50-row audit < 5% (audited by dsv4 judge).
- **Note:** in every sample the *format* of context injection must
  byte-match the app's `localUserMessage` template — train like you infer.

### C3. Quality filter
- **Context:** C2 output.
- **Deliverable:** `finetune/gen/sft.filtered.jsonl` + `filter_report.json`:
  dsv4-judge screens every sample (grounded? voice rules? no fake lived
  experience? no bracketed citations?); drop < threshold; report drop rate
  by intent.
- **Verify:** `python -m scripts.ft_checks c3` → ≥6k survivors, report sums.

### C4. DPO preference pairs
- **Context:** C3 output + voice rules.
- **Deliverable:** `finetune/gen/dpo.jsonl` (≥1.5k pairs): chosen = filtered
  answer; rejected = systematically flawed variant (fake lived experience /
  hotline-when-unneeded / ignores passages / bracket citations / rambles
  past tone budget). Generate rejected with adversarial prompts, verify each
  flaw is present with the judge.
- **Verify:** `python -m scripts.ft_checks c4` → each pair's flaw labeled +
  judge-confirmed on a 40-row sample.

### C5. Splits + dataset card
- **Context:** C3 output.
- **Deliverable:** train/val split (98/2, stratified by intent),
  `finetune/gen/DATASET.md` (sizes, generation lineage, leakage guards).
- **Verify:** `python -m scripts.ft_checks c5`.

## Track D — Training infra

### D1. GPU window protocol
- **Context:** this file; NAS/vLLM knowledge: vLLM runs TP=2 on both GPUs.
- **APPROVED 2026-07-08 (superseding the TP=1 plan):** owner approved BOTH
  GPUs for one ~3h window. Checklist, in order:
  1. Prereqs: A4 baseline captured (against the config prod keeps: standard-mtp3,
     1M ctx, seqs 48, batched 8192) + all training datasets verified (B2, C5, C4).
  2. Flip prod: point sobriety-copilot `LLM_BASE_URL` on the NAS at the R9700
     box `http://10.0.0.100:<port>/v1` (owner loads the model there); verify
     /api/chat works end-to-end; `docker stop ds4-v9`.
  3. Train in parallel: GPU0 = B3 retriever; GPU1 = D3 SFT dry-run+full, then
     D4 DPO dry-run+full.
  4. **DSpark A/B (while ds4-v9 is down anyway, AFTER training completes):**
     relaunch with a NEWER vllm image if available (Reddit 2026-07 reports
     DSpark much improved; local v9 notes: DSpark works, 191 vs 174 tok/s
     single-stream, but KV caps ctx at ~256-384K — see ~/repos/vllm/CLAUDE.md).
     Benchmark MODE=dspark vs MODE=standard-mtp3 at swarm-like concurrency
     (16-48 short requests) and single-stream. Keep whichever wins ONLY if
     owner accepts the context cap; default = restore standard-mtp3/1M.
  5. Restore: relaunch ds4-v9 (MAX_NUM_SEQS=48, MAX_BATCHED=8192 — 16384
     starves KV below the 1M admission minimum and the engine fails to boot);
     health check; revert NAS LLM_BASE_URL; verify prod /api/chat.
- **Verify:** post-window: prod healthy on ds4-v9, adapters exist, A/B
  numbers recorded in `finetune/eval/runs/dspark-ab.md` (if run).

### D2. Training environment
- **Context:** D1 doc.
- **Deliverable:** `finetune/infra/setup_env.sh` — separate venv
  (`finetune/.venv`) with Unsloth (or TRL+PEFT fallback if Unsloth lacks
  Blackwell wheels — document which), flash-attn if available, bitsandbytes;
  `python -c` smoke test loading Gemma 4 E2B base (HF: `google/gemma-4-e2b-it`
  — verify exact id; token already accepted Gemma terms).
- **Verify:** `bash finetune/infra/setup_env.sh --check` exits 0, prints
  library versions + max seq len that fits 96 GB with chosen config.

### D3. SFT config
- **Context:** D2, C5 sample rows (10 only).
- **Deliverable:** `finetune/infra/sft_config.yaml` + `scripts/ft_train_sft.py`
  (QLoRA r=16..64 documented, seq len 4096, packing on, cosine LR, val loss
  logged) — parameterized by dataset path; supports `--dry-run 20-steps`.
- **Verify:** 20-step dry run on 200 samples completes in a D1 window,
  loss decreases, checkpoint saves + reloads.

### D4. DPO config
- Same shape as D3 for DPO (`scripts/ft_train_dpo.py`, beta documented,
  starts FROM the SFT adapter).
- **Verify:** 20-step dry run as above.

### D5. Export + serve
- **Context:** D3 output format.
- **Deliverable:** `scripts/ft_export.py` — merge adapter → save HF dir →
  (a) vLLM-serve snippet for the merged model on GPU1 (window mode) with a
  distinct model name `dsv4-ft-<date>`; (b) GGUF export stub for later;
  `finetune/infra/serve_ab.md` — how to point `ft_eval --system server
  --base-url` at the A/B instance.
- **Verify:** merged model loads with transformers, 1-prompt generation OK.

## Track E — Training runs (needs C5 + D3/D4; gates need A4)

### E1. SFT run
- Full run per D3 on C5 train split (window per D1). Deliverable:
  adapter + `finetune/runs/sft-01/metrics.json`.
- **Verify:** val loss curve sane (no divergence), samples from 5 fixed
  probes read in-voice.

### E2. SFT eval gate ⛔
- `ft_eval --system server --base-url <A/B instance>` (D5) on all 240.
- **Gate:** citation_accuracy and faithfulness ≥ baseline; answer_quality
  ≥ baseline + 0.5 (judge scale /10); refusal_correctness not worse.
  Fable reviews the diff table and decides ship/iterate.

### E3. DPO run (from E1 adapter, C4 pairs)
- **Verify:** as E1 + flaw-probe suite (the C4 flaw categories) shows
  reduced violation rate vs SFT-only.

### E4. DPO eval gate ⛔ — same as E2, plus voice-violation rate halved.

## Track F — Deployment spikes (parallel, low priority)

- **F1. Server A/B flag** (after E2): env `LLM_MODEL_FT` + per-request
  opt-in header so the tuned model can shadow real traffic before default
  flip. Small server.py change; Fable reviews closely.
- **F2. On-device LoRA spike:** flutter_gemma `createChat(loraPath:)` —
  train a tiny throwaway LoRA, test on the Pixel; report whether the
  MediaPipe/LiteRT-LM runtime accepts it for Gemma 4 E2B `.litertlm`.
  Deliverable: `finetune/infra/ondevice_lora.md` verdict.
- **F3. ai-edge-torch conversion spike:** convert a (merged) small Gemma to
  `.litertlm`/`.task`; document the toolchain + whether the tuned
  EmbeddingGemma can be exported to tflite (blocks B5 on-device parity).

---

## Ledger

| id | status | agent | notes |
|----|--------|-------|-------|
|| A0 | done | dsv4 | scaffolding + ft_checks skeleton; verified by Fable 2026-07-07 (f6b413e) |
|| A1 | verify(fable) | dsv4 | FT-A1 targeted fix applied 2026-07-08: 8/9 crosswork deixis repaired via dsv4 (1 manually), 37/42 negatives regenerated as recovery-adjacent (5 sanity anchors kept). Extended ft_checks_a1.py enforces crosswork deixis + negative recovery-adjacency ≥75%. `python -m scripts.ft_checks a1` passes (0 deixis defects, 5 off-target neg = 88.1% on-target) |
| A2 | in-progress(fable-lane) | dsv4 | headless lane launched 2026-07-08 ~09:30 |
| A3 | todo | | blocked by A2 |
| A4 | todo | | blocked by A3 |
| B1 | done* | dsv4 | verified by Fable 2026-07-08: 61,699 pairs / 56,401 distinct (doc,block), 78 docs, deixis screened (9.3% cut). *gold re-exclude pending A2 (--re-exclude mode ready) |
| B2 | in-progress(fable-lane) | dsv4 | headless lane launched 2026-07-08 ~08:35 |
| B3 | todo | | needs D1 window |
| B4 | todo | | gate vs A4 |
| B5 | todo | | after B4 pass |
| C1 | done | dsv4 | verified by Fable 2026-07-07: 1080 seeds, user-voice register clean, crisis seeds hash-match fixed wording, 0 dupes |
| C2 | verify(fable) | dsv4 | 8000 samples done; ft_checks c2 green except 5 leaked rows pending final A1 set (doc-scoped guard added by Fable) |
| C3 | done | dsv4 | verified by Fable 2026-07-08: 6,446/8,000 kept (19.4% drop, mostly grounding: invented quotes/pages); kept-sample spot-read 60/60 clean |
| C4 | in-progress(fable-lane) | dsv4 | headless lane launched 2026-07-08 ~09:45 |
| C5 | in-progress(fable-lane) | dsv4 | headless lane launched 2026-07-08 ~09:45 |
| D1 | approved | owner | 2026-07-08: owner approved BOTH GPUs for one training window (prod chat fails over to R9700/10.0.0.100 during it). Plan: GPU0=B3 retriever, GPU1=SFT→DPO in parallel, ~3h. Window opens after data lanes drain (A4 baseline must run BEFORE — needs dsv4 serving) |
| D2 | done | dsv4 | verified by Fable 2026-07-07: Unsloth 2026.7.1 native on Blackwell (torch 2.10 cu128), gemma-4-e2b-it smoke pass, QLoRA fits easily; CIFS venv workaround documented |
| D3 | done* | dsv4 | verified by Fable 2026-07-07: CPU-side validation full pass (r=32, packing 2.67x, stratified split). *GPU 20-step dry run pending D1 window; note: full-LM loss (no completion-only masking) — revisit at dry run |
| D4 | done* | dsv4 | verified by Fable 2026-07-07: CPU-side full pass; beta=0.15 documented w/ tuning guidance; prompt-masked DPO loss; assumed C4 schema documented in script header. *GPU dry run pending D1 window |
| D5 | todo | | blocked by D3 |
| E1 | todo | | C5 + D3 |
| E2 | todo | | gate; needs A4 + D5 |
| E3 | todo | | E1 + C4 + D4 |
| E4 | todo | | gate |
| F1 | todo | | after E2 |
| F2 | todo | | anytime |
| F3 | todo | | anytime |
