"""Unit tests for the grounded-on-text / conceptual-coverage eval foundation.

All tests are offline and ragas-free: they exercise pure functions in
``tests/concept_eval.py`` with fake ``retrieve`` callables, and validate the
dataset in ``tests/conceptual_eval_cases.json``. No network, no LLM judge.

Run from the repo root:

    .venv/bin/python -m pytest tests/test_concept_eval.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from concept_eval import concept_coverage, load_cases, score_run
# NOTE: `tests/` is a rootless module dir (no __init__.py), so under
# `python -m pytest` this file's own directory lands on sys.path and the
# sibling `concept_eval.py` resolves as a top-level import. Kept consistent
# with how existing tests import `src.rag.*` modules from the repo root.

CASES_PATH = Path(__file__).parent / "conceptual_eval_cases.json"

# One local support passage + one distractor used across several tests.
SUPPORT_A = "Acceptance is the answer to all my problems today."
SUPPORT_B = (
    "We admitted we were powerless over alcohol—that our lives had become "
    "unmanageable. The first step is the foundation of our entire program."
)
DISTRACTOR = (
    "The word serenity appears here many, many times, serenity serenity, but "
    "this passage says nothing about actually finding serenity."
)


def _norm(text: str) -> str:
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# (a) concept_coverage: the core fraction metric
# ---------------------------------------------------------------------------

def test_coverage_full_when_all_support_retrieved():
    retrieved = [SUPPORT_A, SUPPORT_B]
    assert concept_coverage(retrieved, [SUPPORT_A, SUPPORT_B]) == 1.0


def test_coverage_zero_when_none_retrieved():
    retrieved = [DISTRACTOR]
    assert concept_coverage(retrieved, [SUPPORT_A, SUPPORT_B]) == 0.0


def test_coverage_half_when_half_retrieved():
    retrieved = [SUPPORT_A, DISTRACTOR]
    assert concept_coverage(retrieved, [SUPPORT_A, SUPPORT_B]) == 0.5


def test_coverage_ignores_whitespace_differences():
    # line-wrap / extra whitespace in the retrieved copy must still count as found
    retrieved = ["Acceptance   is the\nanswer to all my problems today."]
    assert concept_coverage(retrieved, [SUPPORT_A]) == 1.0


def test_coverage_accepts_object_passages_with_text_attr():
    class Result:
        def __init__(self, text: str):
            self.text = text

    retrieved = [Result(SUPPORT_A)]
    assert concept_coverage(retrieved, [SUPPORT_A]) == 1.0


def test_coverage_empty_support_returns_zero():
    assert concept_coverage([SUPPORT_A], []) == 0.0


# ---------------------------------------------------------------------------
# (b) full scoring run with an injectable retrieve callable
# ---------------------------------------------------------------------------

def _fake_retrieve_support(query: str):
    """A 'conceptual' retriever: returns the on-topic support passages."""
    cases = load_cases(CASES_PATH)
    for case in cases:
        if _norm(query) == _norm(case["question"]):
            return list(case["support_passages"])
    return []


def _fake_retrieve_lexical_distractors(query: str):
    """A 'lexical' retriever: returns only word-matching distractors."""
    cases = load_cases(CASES_PATH)
    for case in cases:
        if _norm(query) == _norm(case["question"]):
            return list(case["distractors"])
    return []


def test_full_run_conceptual_retriever_scores_high():
    cases = load_cases(CASES_PATH)
    assert len(cases) >= 1
    report = score_run(cases, _fake_retrieve_support, per_case=True)
    assert report["cases"] == len(cases)
    assert report["mean_coverage"] == 1.0
    # a conceptual retriever should also reject the lexical distractors
    assert report["mean_distractor_rate"] == 0.0
    for row in report["per_case"]:
        assert row["coverage"] == 1.0
        assert row["support_retrieved"] == row["support_total"]


def test_full_run_lexical_retriever_scores_low():
    cases = load_cases(CASES_PATH)
    report = score_run(cases, _fake_retrieve_lexical_distractors, per_case=True)
    # distractors share words but are NOT conceptually relevant
    assert report["mean_coverage"] == 0.0
    assert report["mean_distractor_rate"] == 1.0


def test_per_case_disabled_omits_per_case_key():
    report = score_run([{"question": "q", "support_passages": [SUPPORT_A]}], lambda q: [SUPPORT_A])
    assert "per_case" not in report
    assert report["mean_coverage"] == 1.0


# ---------------------------------------------------------------------------
# (c) dataset validity + the conceptual-vs-lexical design contract
# ---------------------------------------------------------------------------

def test_dataset_is_valid_parseable_json():
    data = json.loads(CASES_PATH.read_text())
    assert isinstance(data, list) and len(data) >= 3


def test_dataset_schema_fields():
    cases = load_cases(CASES_PATH)
    for case in cases:
        assert "question" in case
        assert "concepts" in case and isinstance(case["concepts"], list)
        assert "support_passages" in case and len(case["support_passages"]) >= 1
        assert "distractors" in case and len(case["distractors"]) >= 1


def test_serenity_support_passage_omits_query_word():
    """The serenity case's support passages must NOT contain the word 'serenity'.
    This is the crux: a lexical retriever fails here, a conceptual one succeeds."""
    cases = {c["question"]: c for c in load_cases(CASES_PATH)}
    serenity = next(c for c in cases.values() if "serenity" in c["question"].lower())
    assert "serenity" in serenity["question"].lower()
    for passage in serenity["support_passages"]:
        # 'serenity' must not appear (case-insensitive) in the on-topic passage
        assert "serenity" not in passage.lower()


def test_failure_support_passage_omits_query_word():
    """The failure case's support passages must NOT contain the word 'failure'.
    They speak to Step One powerlessness / all-or-nothing instead."""
    cases = {c["question"]: c for c in load_cases(CASES_PATH)}
    failure = next(c for c in cases.values() if "failure" in c["question"].lower())
    assert "failure" in failure["question"].lower()
    for passage in failure["support_passages"]:
        assert "failure" not in passage.lower()
    # and they genuinely speak to the underlying concept
    assert "powerless" in " ".join(failure["support_passages"]).lower()


def test_distractors_do_contain_or_echo_query_words():
    """Sanity: the distractors must actually bleed the query's lexical surface
    (that is why they fool a lexical retriever) while staying off-topic."""
    cases = {c["question"]: c for c in load_cases(CASES_PATH)}
    for case in cases.values():
        q_norm = _norm(case["question"]).lower()
        words = {w.strip(",.!?—") for w in q_norm.split() if len(w.strip(",.!?—")) > 4}
        for d in case["distractors"]:
            assert any(w in d.lower() for w in words), (
                f"distractor for {case['question'][:30]!r} shares no query words"
            )
