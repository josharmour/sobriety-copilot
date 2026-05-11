"""RAGAS evaluation harness for the production retrieval + chat pipeline.

Loads question/ground-truth pairs from `tests/eval_cases.json`, runs the
live `RAGRetriever` + `InferenceEngine` to produce contexts and answers,
and scores them with RAGAS's faithfulness, answer relevancy, context
precision, and context recall metrics.

The metrics need an LLM judge. RAGAS defaults to OpenAI — set
`OPENAI_API_KEY` in the environment, or wire a custom judge per the
ragas docs if you want a local model.

Run from the repo root:

    pip install -r requirements.txt -r requirements-eval.txt
    python -m tests.eval_rag                # uses tests/eval_cases.json
    python -m tests.eval_rag path/to/cases.json

Writes `tests/eval_results.csv` (gitignored) and prints the aggregate
scores.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)

from src.inference.engine import InferenceEngine
from src.prompts.templates import (
    NO_CONTEXT_TEMPLATE,
    USER_MESSAGE_TEMPLATE,
    system_message_for_tone,
)
from src.rag.retriever import RAGRetriever

DEFAULT_CASES_PATH = Path(__file__).parent / "eval_cases.json"
RESULTS_PATH = Path(__file__).parent / "eval_results.csv"


def _build_prompt(query: str, context: str) -> str:
    if context:
        return USER_MESSAGE_TEMPLATE.format(context=context, question=query)
    return NO_CONTEXT_TEMPLATE.format(question=query)


def run_evaluation(cases: list[dict]) -> None:
    if not cases:
        raise SystemExit("No test cases provided.")

    retriever = RAGRetriever(
        db_path=os.environ.get("RAG_DB_PATH", "rag_db"),
        collection_name=os.environ.get("RAG_COLLECTION", "recovery_literature"),
    )
    engine = InferenceEngine(
        base_url=os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1"),
        model=os.environ.get("LLM_MODEL", "gemma4:e2b"),
        api_key=os.environ.get("LLM_API_KEY", "ollama"),
    )
    system_message = system_message_for_tone(None)

    questions, ground_truths, answers, contexts = [], [], [], []
    print(f"Evaluating {len(cases)} cases...", flush=True)

    for index, case in enumerate(cases, 1):
        question = case["question"]
        ground_truth = case["ground_truth"]

        results = retriever.retrieve(question)
        context_texts = [r.excerpt or r.text for r in results]
        formatted_context = retriever.format_context(results)
        prompt = _build_prompt(question, formatted_context)
        answer = engine.generate(
            prompt=prompt,
            history=[],
            max_tokens=600,
            system_message=system_message,
        )

        questions.append(question)
        ground_truths.append(ground_truth)
        answers.append((answer or "").strip())
        contexts.append(context_texts)
        print(f"  [{index}/{len(cases)}] {question[:60]}", flush=True)

    dataset = Dataset.from_dict(
        {
            "question": questions,
            "answer": answers,
            "contexts": contexts,
            "ground_truth": ground_truths,
        }
    )

    result = evaluate(
        dataset,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
    )
    df = result.to_pandas()
    df.to_csv(RESULTS_PATH, index=False)
    print(f"\nResults written to {RESULTS_PATH}")
    print(result)


def _load_cases(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(
            f"Test case file not found: {path}. "
            "Provide one as the first CLI arg or create tests/eval_cases.json."
        )
    with path.open() as f:
        cases = json.load(f)
    if not isinstance(cases, list):
        raise SystemExit(f"{path} must contain a JSON list of cases.")
    for case in cases:
        if not isinstance(case, dict) or "question" not in case or "ground_truth" not in case:
            raise SystemExit(
                f"Each case must have 'question' and 'ground_truth' fields: {case!r}"
            )
    return cases


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CASES_PATH
    run_evaluation(_load_cases(path))
