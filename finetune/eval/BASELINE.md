# A4 — Baseline report (2026-07-08)

System under test: production sobrietycopilot.com (dsv4 / deepseek-v4-flash,
standard-mtp3, 1M ctx, max_num_seqs=48) via public URL, plus the ft_eval
BM25 retriever replica. Eval set: finetune/eval/questions.jsonl (256) +
gold.jsonl. Judge: deepseek-v4-flash, temp 0, thinking off.

| Metric | baseline-server | baseline-retriever |
|---|---|---|
| retrieval.recall@4 | — (server does not expose block ids) | 0.3715 |
| retrieval.recall@8 | — | 0.3995 |
| citation_accuracy | **0.3224** | — |
| faithfulness (1–5) | 4.944 | — |
| answer_quality (1–5) | 4.559 | — |
| refusal_correctness (1–5, negative kind) | 4.286 | — |

Run files: `finetune/eval/runs/baseline-server.json`,
`finetune/eval/runs/baseline-retriever.json` (256 rows each).

## Reading the numbers

- **citation_accuracy 32% is the headline weakness** — answers are faithful
  and high quality, but only a third name a gold work's exact title. This is
  the primary fine-tuning target (C2 RAFT trains title-naming; B-track
  improves whether the gold block is retrieved at all).
- **recall@4 37% / recall@8 40%** on the BM25 replica is the yardstick the
  B4 gate must beat by ≥5 points with the fine-tuned EmbeddingGemma. It is
  a same-harness comparison only — not the server's full hybrid pipeline.
- faithfulness 4.94 confirms the generator rarely invents content when it
  answers; quality 4.56 leaves headroom the E-gates must not regress.
- Notes: 3 server rows initially failed (Cloudflare timeout / 2×500) and
  were retried successfully; judge model alias corrected from retired
  `dsv4` to `deepseek-v4-flash` mid-run and all rows re-judged.
