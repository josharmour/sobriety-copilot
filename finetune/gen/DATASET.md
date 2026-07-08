# Sobriety Copilot — SFT Dataset Card

## Dataset statistics

| Metric | Value |
|--------|-------|
| Total rows | 6,444 |
| Train rows | 6,314 (98.0%) |
| Validation rows | 130 (2.0%) |
| Split seed | 42 |
| Validation fraction | 0.02 |
| Intents represented | 28 (all present in both splits) |

### By intent

| Intent | Total | Train | Val |
|--------|-------|-------|-----|
| refusal_out_of_domain | 414 | 406 | 8 |
| ask_humility | 265 | 260 | 5 |
| ask_sponsorship | 253 | 248 | 5 |
| ask_forgiveness | 251 | 246 | 5 |
| ask_step_2 | 246 | 241 | 5 |
| ask_step_12 | 243 | 238 | 5 |
| ask_family | 242 | 237 | 5 |
| ask_step_4 | 241 | 236 | 5 |
| ask_service | 239 | 234 | 5 |
| ask_step_3 | 239 | 234 | 5 |
| ask_higher_power | 238 | 233 | 5 |
| ask_step_6_7 | 238 | 233 | 5 |
| ask_relapse | 237 | 232 | 5 |
| ask_fear | 235 | 230 | 5 |
| ask_step_1 | 235 | 230 | 5 |
| ask_step_11 | 235 | 230 | 5 |
| ask_step_10 | 234 | 229 | 5 |
| ask_step_5 | 223 | 219 | 4 |
| ask_work_finances | 217 | 213 | 4 |
| ask_slogan | 215 | 211 | 4 |
| ask_prayer_meditation | 212 | 208 | 4 |
| ask_newcomer | 205 | 201 | 4 |
| ask_resentment | 200 | 196 | 4 |
| ask_step_8_9 | 199 | 195 | 4 |
| ask_traditions | 193 | 189 | 4 |
| ask_meetings | 184 | 180 | 4 |
| ask_12_and_12 | 157 | 154 | 3 |
| ask_big_book | 154 | 151 | 3 |

### By register

| Register | Train | Val | Total |
|----------|-------|-----|-------|
| brief | 1,706 | 37 | 1,743 |
| factual | 1,638 | 32 | 1,670 |
| reflective | 1,620 | 23 | 1,643 |
| warm | 1,350 | 38 | 1,388 |

### By sample_type

| Type | Train | Val | Total |
|------|-------|-----|-------|
| context (3–5 passages) | 5,244 | 111 | 5,355 |
| no_context (0 passages) | 664 | 11 | 675 |
| refusal (out-of-domain) | 406 | 8 | 414 |

## Generation lineage

```
C1  Prompt taxonomy ──→ C2  RAFT samples ──→ C3  Quality filter ──→ C5  Train/val split
(taxonomy.json)         (sft.jsonl, ~8,000)    (sft.filtered.jsonl,   (sft.train.jsonl +
                                             6,444 kept)            sft.val.jsonl)
```

### C1 — Prompt taxonomy
- **File:** `finetune/gen/taxonomy.json`
- **Output:** 28 intents × 3 difficulties × 4 registers × 3 seed phrasings = 1,080 seeds
- Crisis-adjacent intents (`crisis_imminent_relapse`, `crisis_harm_urges`, `crisis_overdose_concern`) use fixed safety wording only (no free generation). These intents are not present in the SFT dataset because the C2 generator skips crisis-adjacent intents for the RAFT pipeline (they use template-only responses in production).

### C2 — RAFT sample generation
- **Script:** `scripts/ft_gen_raft.py`
- **Output:** `finetune/gen/sft.jsonl` — 8,000 samples
- Each sample: `{messages: [system, user, assistant], meta}` where the user turn embeds 3–5 retrieved passages (1–2 gold + distractors) with formats matching `local_prompts.dart`
- 10% no-context samples, 5% refusal samples
- Distractors drawn from non-gold blocks; judge audit verified <5% citation of distractor content
- **Leakage guard:** A2 gold blocks excluded from gold passage selection (doc-scoped `(doc_id, block_id)` pairs)

### C3 — Quality filter
- **Script:** C3 dsv4-judge pipeline
- **Output:** `finetune/gen/sft.filtered.jsonl` (6,444 kept) + `finetune/gen/filter_report.json`

### C2FIX — 2026-07-08 leak purge
- **Script:** `scripts/ft_purge_leaks.py`
- **SFT purge:** 72 rows dropped from sft.jsonl (gold (doc_id, block_id) in A2 eval set)
- **Backfill:** 72 fresh RAFT samples generated (dsv4, temp 0.7) with doc-scoped gold exclusion
- **Filtered purge:** 57 leaked rows removed from sft.filtered.jsonl
- **Backfill judge:** 55 backfill samples passed C3 rubric, 17 dropped
- **Splits regenerated:** seed 42, stratified by intent
- **Leakage guard fixed:** exclusion now uses doc-scoped `(doc_id, block_id)` pairs from A2 gold.jsonl (previously used bare block_id only, which collides across docs)

### C5 — Train/val split
- **Script:** `scripts/ft_split_sft.py`
- **Output:** `finetune/gen/sft.train.jsonl`, `finetune/gen/sft.val.jsonl`, `finetune/gen/split_report.json`
- **Strategy:** Stratified by `meta.intent_id`. Every intent with ≥50 rows is represented in validation. Per-intent allocation: `max(1, round(count × 0.02))`. Deterministic seed 42 (Python `random.Random(42)`). Rows shuffled per-intent before split, then globally reshuffled per split.
- **Result:** 6,314 train (98.0%), 130 val (2.0%). All 28 intents present in both splits.

## Leakage guards

### A2-gold exclusion (doc-scoped)
- Every synthetic sample in C2 and C3 was generated with A2-gold citation blocks excluded from gold passage selection.
- **Doc-scoped identity:** A block is uniquely identified by `(doc_id, block_id)` — the corpus stores this pair. Exclusion uses zip-aligned pairs from `finetune/eval/gold.jsonl`.
- The C2FIX purge removed 72 rows whose gold (doc,block) matched the A2 eval gold set. Backfilled samples use the same doc-scoped exclusion at generation time.

### Split isolation
- Train/val split operates on **row identity** (by input file line number), not JSON content hash.
- Verification confirms: sizes sum to input, no input-index overlap between splits, every intent ≥50 rows present in val, per-intent val counts match expected.

## Known caveats

1. **Duplicate-content rows:** Some rows have byte-identical `messages`+`meta` with other rows. These are genuine duplicate entries from the RAFT generation process (different random seeds may produce identical results when passages overlap). They are treated as distinct training samples and split independently. If deduplication is desired, apply it before training.
2. **Backfill quality variance:** The C2FIX backfill samples were generated in a single batch and judged with the C3 rubric. They may have slightly different quality distribution than the original C2 samples.
3. **No crisis-adjacent samples in dataset:** Crisis intents were excluded from the RAFT pipeline (they use fixed template responses in production). The SFT dataset contains zero crisis-adjacent samples. The model's crisis response behavior is governed entirely by the template-based system prompt, not fine-tuning.
4. **Single judge model:** All C3 quality judgments used dsv4 (DeepSeek V4 Flash at temperature 0.0). No cross-model or multi-judge arbitration was applied.
