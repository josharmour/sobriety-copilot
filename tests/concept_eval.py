"""Grounded-on-text / conceptual-coverage evaluation (no ragas dependency).

This module scores how well a retrieval function surfaces passages that
*conceptually* apply to a query — even when those passages share none of the
query's words. It is deliberately offline and dependency-free (stdlib only)
so the evaluation foundation can run in CI without RAGAS or a network reach
to an LLM judge.

The unit of evaluation is a *conceptual case*:

    {
        "question": str,
        "concepts": [str, ...],                 # the facets the passage must speak to
        "support_passages": [str, ...],         # passages that apply WITHOUT sharing
                                                # the query's words
        "distractors": [str, ...]               # passages that share words but do NOT apply
    }

The central metric, ``concept_coverage``, is the fraction of support passages
that the retriever surfaced. A lexical-only retriever scores ~0 on the
serenity/failure cases (it returns word-matching distractors but misses the
on-topic passages); a conceptual retriever scores 1.0.

Pure functions:

    concept_coverage(retrieved_passages, support_passages) -> float
    score_run(cases, retrieve, per_case=...)     -> per-case report
    load_cases(path)                             -> list of conceptual cases
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Iterable, Sequence

# A retrievable is anything that can hold a passage; callers pass either raw
# strings or objects with a text-bearing attribute. We normalize with this
# helper so the metric is agnostic to the downstream `retrieve(...)` return
# type (list[str] or list of dataclass results with `.text` / `.excerpt`).
_TextLike = object


def _passage_text(passage: _TextLike) -> str:
    """Return the string form of a passage.

    Accepts a plain ``str`` or any object exposing a ``text`` or ``excerpt``
    attribute (mirrors the retrieval result shape used by ``RAGRetriever``).
    """
    if isinstance(passage, str):
        return passage
    for attr in ("text", "excerpt", "content"):
        value = getattr(passage, attr, None)
        if isinstance(value, str):
            return value
    return str(passage)


def concept_coverage(
    retrieved_passages: Iterable[_TextLike],
    support_passages: Iterable[str],
) -> float:
    """Fraction of support passages present in the retrieved set.

    A passage counts as retrieved if its normalized text appears verbatim in
    the retrieved set. Matching is on exact passage text (normalized for
    whitespace), not on lexical overlap — that is the whole point: we are
    measuring whether the *conceptually* relevant passage made it into the
    context, regardless of whether it shares words with the query.

    Returns a float in [0.0, 1.0]: 1.0 when every support passage was
    retrieved, 0.0 when none was, 0.5 when half were, etc.
    """
    support = [_normalize(p) for p in support_passages]
    if not support:
        return 0.0
    retrieved = {_normalize(p) for p in retrieved_passages}
    hits = sum(1 for p in support if p in retrieved)
    return hits / len(support)


def _normalize(text: _TextLike) -> str:
    """Collapse runs of whitespace so line-wrapping differences don't matter."""
    return " ".join(_passage_text(text).split())


def score_run(
    cases: Sequence[dict],
    retrieve: Callable[[str], Iterable[_TextLike]],
    *,
    per_case: bool = False,
) -> dict:
    """Run one case through the injectable ``retrieve`` callable and score it.

    ``retrieve`` is *injected* — it is any callable
    ``(query: str) -> Iterable[passages]``. In tests we pass a fake; in
    production you would pass ``RAGRetriever().retrieve`` (or a wrapper that
    returns the passage text). This keeps the scoring utility fully offline
    and testable without touching the live pipeline.

    Returns a report dict:

        {
            "cases": int,
            "mean_coverage": float,
            "mean_distractor_rate": float,
            "per_case": [                    # only when per_case=True
                {"question": str, "coverage": float,
                 "distractor_rate": float,
                 "support_retrieved": int, "support_total": int},
                ...
            ],
        }
    """
    report: dict = {"cases": len(cases), "per_case": []}
    total_coverage = 0.0
    total_distractor = 0.0

    for case in cases:
        question = case["question"]
        support = list(case.get("support_passages", []))
        distractors = list(case.get("distractors", []))

        retrieved = list(retrieve(question))
        coverage = concept_coverage(retrieved, support)
        retrieved_norm = {_normalize(p) for p in retrieved}

        distractor_rate = 0.0
        if distractors:
            distractor_hits = sum(1 for d in distractors if _normalize(d) in retrieved_norm)
            distractor_rate = distractor_hits / len(distractors)

        total_coverage += coverage
        total_distractor += distractor_rate

        if per_case:
            report["per_case"].append(
                {
                    "question": question,
                    "coverage": coverage,
                    "distractor_rate": distractor_rate,
                    "support_retrieved": sum(
                        1 for p in support if _normalize(p) in retrieved_norm
                    ),
                    "support_total": len(support),
                }
            )

    n = max(len(cases), 1)
    report["mean_coverage"] = total_coverage / n
    report["mean_distractor_rate"] = total_distractor / n
    if not per_case:
        report.pop("per_case")
    return report


def load_cases(path: str | Path) -> list[dict]:
    """Load and validate a conceptual-eval case file."""
    with Path(path).open() as f:
        cases = json.load(f)
    if not isinstance(cases, list):
        raise ValueError(f"{path} must contain a JSON list of cases, got {type(cases).__name__}")
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError(f"Each case must be a JSON object, got {case!r}")
        missing = [k for k in ("question", "support_passages") if k not in case]
        if missing:
            raise ValueError(f"Case missing required keys {missing}: {case!r}")
        if not isinstance(case["support_passages"], list):
            raise ValueError(f"'support_passages' must be a list: {case!r}")
        if "distractors" in case and not isinstance(case["distractors"], list):
            raise ValueError(f"'distractors' must be a list: {case!r}")
    return cases
