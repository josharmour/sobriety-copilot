# Sobriety Copilot — SFT Dataset Card

## Dataset statistics

| Metric | Value |
|--------|-------|
| Total rows | 6,446 |
| Train rows | 6,315 (98.0%) |
| Validation rows | 131 (2.0%) |
| Split seed | 42 |
| Validation fraction | 0.02 |
| Intents represented | 28 (all 28 present in both splits) |

### By intent

| Intent | Total | Train | Val |
|--------|-------|-------|-----|
| refusal_out_of_domain | 409 | 401 | 8 |
| ask_humility | 265 | 260 | 5 |
| ask_sponsorship | 251 | 246 | 5 |
| ask_forgiveness | 249 | 244 | 5 |
| ask_step_4 | 246 | 241 | 5 |
| ask_step_2 | 246 | 241 | 5 |
| ask_step_12 | 243 | 238 | 5 |
| ask_step_3 | 242 | 237 | 5 |
| ask_service | 239 | 234 | 5 |
| ask_step_10 | 239 | 234 | 5 |
| ask_step_1 | 239 | 234 | 5 |
| ask_step_6_7 | 239 | 234 | 5 |
| ask_higher_power | 237 | 232 | 5 |
| ask_relapse | 236 | 231 | 5 |
| ask_step_11 | 235 | 230 | 5 |
| ask_fear | 232 | 227 | 5 |
| ask_step_5 | 227 | 222 | 5 |
| ask_work_finances | 219 | 215 | 4 |
| ask_slogan | 216 | 212 | 4 |
| ask_prayer_meditation | 208 | 204 | 4 |
| ask_newcomer | 203 | 199 | 4 |
| ask_resentment | 200 | 196 | 4 |
| ask_step_8_9 | 199 | 195 | 4 |
| ask_traditions | 192 | 188 | 4 |
| ask_meetings | 183 | 179 | 4 |
| ask_family | 244 | 239 | 5 |
| ask_12_and_12 | 155 | 152 | 3 |
| ask_big_book | 153 | 150 | 3 |

### By register

| Register | Train | Val | Total |
|----------|-------|-----|-------|
| brief | 1,698 | 46 | 1,744 |
| factual | 1,642 | 23 | 1,665 |
| reflective | 1,613 | 31 | 1,644 |
| warm | 1,362 | 31 | 1,393 |

### By sample_type

| Type | Train | Val | Total |
|------|-------|-----|-------|
| context (3–5 passages) | 5,265 | 106 | 5,371 |
| no_context (0 passages) | 649 | 17 | 666 |
| refusal (out-of-domain) | 401 | 8 | 409 |

## Generation lineage

```
C1  Prompt taxonomy ──→ C2  RAFT samples ──→ C3  Quality filter ──→ C5  Train/val split
(taxonomy.json)         (sft.jsonl, 8,000)    (sft.filtered.jsonl,   (sft.train.jsonl +
                                               6,446 kept)            sft.val.jsonl)
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
- **Leakage guard:** A1/A2 gold blocks excluded from gold passage selection

### C3 — Quality filter
- **Script:** C3 dsv4-judge pipeline
- **Output:** `finetune/gen/sft.filtered.jsonl` (6,446 kept) + `finetune/gen/filter_report.json`
- **Drop rate:** 19.4% (1,554 of 8,000 dropped)
  - Grounding failures: 1,192 drops (invented quotes, fabricated page references)
  - Voice violations: 65 drops (more than 2 literature titles, fake personal experience)
  - Hotline discipline: 35 drops (hotline offered when not needed)
  - Register fit: 58 drops
  - Refusal correctness: 2 drops
  - Combined reasons: the remainder
- **By-intent drop variation:** `ask_12_and_12` (46.4%) and `ask_big_book` (45.4%) highest — these intents are hardest to ground without quoting verbatim. `refusal_out_of_domain` nearly untouched (0.2% drop).
- **Judging errors:** 0 (all 8,000 received a valid verdict)

### C5 — Train/val split
- **Script:** `scripts/ft_split_sft.py`
- **Output:** `finetune/gen/sft.train.jsonl`, `finetune/gen/sft.val.jsonl`, `finetune/gen/split_report.json`
- **Strategy:** Stratified by `meta.intent_id`. Every intent with ≥50 rows is represented in validation.
  Per-intent allocation: `max(1, round(count × 0.02))`. Deterministic seed 42 (Python `random.Random(42)`).
  Rows shuffled per-intent before split, then globally reshuffled per split.
- **Result:** 6,315 train (98.0%), 131 val (2.0%). All 28 intents present in both splits.

## Leakage guards

### A1/A2-gold exclusion
- Every synthetic sample in C2 and C3 was generated with A1-eval question blocks and A2-gold citation blocks excluded from gold passage selection.
- Gold blocks are read from `finetune/eval/gold.jsonl` (A2). When A2 is not yet finalized, the exclusion list falls back to A1's `source_block_ids` (read from `finetune/eval/questions.jsonl`).
- **Doc-scoped identity:** A block is uniquely identified by `(doc_id, block_id)` — the corpus stores this pair. Two samples referencing the same `(doc_id, block_id)` pair refer to the same passage. The split guarantees no block's textual content appears in both train and val through different rows (by row-index identity — even if two input rows are byte-identical, each is a distinct sample).

### Split isolation
- Train/val split operates on **row identity** (by input file line number / Python object identity), not JSON content hash. This correctly handles the 71 duplicate-content rows in the input (which are intended separate training samples).
- Verification (`scripts/ft_checks_c5`) confirms: sizes sum to input, no input-index overlap between splits, every intent ≥50 rows present in val, per-intent val counts match expected.

## Known caveats

1. **5 rows pending eval-set re-screen (A2 dependency):** The original C2 generation excluded gold passages based on A1's `source_block_ids`. After A2 lands with its curated `gold_block_ids`, these 5 rows (identified during C3 review) may contain gold blocks that A2 would flag. They passed C3 judge screening but the exclusion list was A1-only at generation time. Re-screen these after A2 finalizes: extract `gold_block_ids` from `finetune/eval/gold.jsonl`, cross-reference against each sample's `gold_blocks`, and drop any sample where a C5 gold block appears in the A2 gold set.
2. **Duplicate-content rows:** 71 rows (out of 6,446) have byte-identical `messages`+`meta` with other rows. These are genuine duplicate entries from the RAFT generation process (different random seeds may produce identical results when passages overlap). They are treated as distinct training samples and split independently. If deduplication is desired, apply it before training.
3. **Imbalanced drop by intent:** `ask_12_and_12` and `ask_big_book` suffered ~45% drop rates in C3 vs 8–17% for most other intents. These intents are underrepresented in the filtered set relative to their original C2 allocation. Monitor val loss per intent for signs of degradation on these.
4. **No crisis-adjacent samples in dataset:** Crisis intents were excluded from the RAFT pipeline (they use fixed template responses in production). The SFT dataset contains zero crisis-adjacent samples. The model's crisis response behavior is governed entirely by the template-based system prompt, not fine-tuning.
5. **Single judge model:** All C3 quality judgments used dsv4 (DeepSeek V4 Flash at temperature 0.0). No cross-model or multi-judge arbitration was applied. Systematic judge biases (e.g., leniency toward certain intents) would propagate undetected.
