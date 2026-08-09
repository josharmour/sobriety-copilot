"""Conceptual-citation layer for the RAG chat.

Implements the two "conceptual" layers described in
docs/plans/beyond-rag-deep-understanding-knowledge-graph.md (Part 2) as
*pure-stdlib* helpers:

- Layer 1 — *concept expansion*: rewrite a user query into the conceptual
  facets it implies (including related-but-unstated concepts), so retrieval
  can broaden past surface word-matching (a "serenity" query should also
  think about "acceptance", "surrender", ...).
- Layer 2 — *relevance labeling*: tag which concepts a given passage actually
  speaks to, so a citation chip can carry a concept tag instead of only a
  similarity percentage.

Both functions accept an injectable ``extractor`` callable (e.g. a thin LLM
wrapper). When it is ``None`` they fall back to a small built-in static
expansion dictionary, which keeps the module fully testable WITHOUT any live
LLM call / network / chromadb / Ollama dependency.

This module intentionally imports nothing beyond the Python standard library.
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence

# A minimal built-in concept -> related facets table. Serves as the *static
# fallback* when no live extractor is injected, and as a documented example of
# the shape an extractor is expected to return. It is intentionally small —
# a production deployment would supply a real (LLM-backed) extractor or a much
# larger curated table.
_STATIC_EXPANSIONS: dict[str, list[str]] = {
    "serenity": [
        "serenity",
        "peace",
        "acceptance",
        "surrender",
        "letting go of control",
    ],
    "acceptance": [
        "acceptance",
        "surrender",
        "letting go",
        "powerlessness",
        "serenity",
    ],
    "powerlessness": [
        "powerlessness",
        "unmanageability",
        "surrender",
        "admitting defeat",
        "step one",
    ],
    "surrender": [
        "surrender",
        "letting go of control",
        "acceptance",
        "humility",
        "higher power",
    ],
    "resentment": [
        "resentment",
        "anger",
        "grievance",
        "forgiveness",
        "inventory",
    ],
    "fear": [
        "fear",
        "anxiety",
        "courage",
        "faith",
        "worry",
    ],
    "forgiveness": [
        "forgiveness",
        "resentment",
        "amends",
        "letting go",
        "step four",
    ],
    "gratitude": [
        "gratitude",
        "thankfulness",
        "appreciation",
        "humility",
        "counting blessings",
    ],
    # Common 12-step framing terms, which no single colloquial facet owns.
    "step": [
        "step",
        "twelve steps",
        "working the program",
        "spiritual growth",
        "recovery program",
    ],
    "amends": [
        "amends",
        "step nine",
        "making things right",
        "repairing harm",
        "responsibility",
    ],
}

# The size/casing normalization applied before dictionary lookup. Kept tiny and
# stdlib-only so callers can rely on the same normalization as the fallback.
_STOPWORDS = frozenset(
    {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "of", "in", "on", "at", "to", "for", "with", "by", "from", "as",
        "and", "or", "but", "if", "how", "what", "why", "when", "do", "does",
        "did", "i", "me", "my", "we", "our", "you", "your", "it", "its",
    }
)


def _normalize(text: str) -> str:
    """Lowercase and strip non-alphanumerics for dictionary/word lookup."""
    out = []
    for ch in (text or ""):
        if ch.isalnum() or ch.isspace():
            out.append(ch.lower())
        else:
            out.append(" ")
    return " ".join("".join(out).split())


def _default_expansion(query: str) -> list[str]:
    """Static fallback: [query] + facets from the built-in table, if any."""
    facets: list[str] = []
    norm = _normalize(query)
    # Try matching whole keyword entries first; fall back to word-level hits so
    # a multi-word query still picks up facets for any keyword it contains.
    if norm in _STATIC_EXPANSIONS:
        facets = list(_STATIC_EXPANSIONS[norm])
    else:
        for word in norm.split():
            if word in _STATIC_EXPANSIONS and word not in _STOPWORDS:
                facets.extend(_STATIC_EXPANSIONS[word])
    # Always keep the original query as the first/primary facet, then dedupe.
    result: list[str] = []
    for facet in [query] + facets:
        facet = facet.strip()
        if facet and facet.lower() not in {r.lower() for r in result}:
            result.append(facet)
    return result or [query]


def expand_query_concepts(
    query: str,
    extractor: Optional[Callable[[str], Sequence[str]]] = None,
) -> list[str]:
    """Return the conceptual facets implied by ``query``.

    ``extractor(query)`` is expected to return a sequence of concept strings.
    When ``extractor`` is ``None`` (or raises), fall back to the built-in
    static table so this never breaks the retrieval path.
    """
    if extractor is not None:
        try:
            facets = extractor(query)
            if facets:
                # Keep the first element as the primary facet, dedupe the rest,
                # and ensure a non-empty stable list.
                result: list[str] = []
                for facet in facets:
                    facet = (facet or "").strip()
                    if facet and facet.lower() not in {r.lower() for r in result}:
                        result.append(facet)
                if result:
                    return result
        except Exception:
            # Best-effort: a flaky extractor must never break expansion.
            pass
    return _default_expansion(query)


def _default_label(concepts: list[str], passage_text: str) -> list[str]:
    """Static fallback relevance labeling.

    Tag a passage with every concept (facet) whose core words or synonyms
    appear in the text. Operates purely on token presence, so it works without
    any model and degrades gracefully to ``[]`` when nothing matches.
    """
    if not passage_text:
        return []
    lower_text = " " + _normalize(passage_text) + " "
    tags: list[str] = []
    for concept in concepts:
        key = _normalize(concept)
        if not key:
            continue
        # Whole-phrase match first; otherwise any significant word of the
        # concept appears in the passage.
        if key in lower_text or any(
            word in lower_text
            for word in key.split()
            if len(word) > 3 and word not in _STOPWORDS
        ):
            tags.append(concept)
    # Dedupe while preserving order.
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        if tag.lower() not in seen:
            seen.add(tag.lower())
            result.append(tag)
    return result


def label_concept(
    extractor: Optional[Callable[[list[str], str], Sequence[str]]],
    query: str,
    passage_text: str,
) -> list[str]:
    """Tag which concepts ``passage_text`` speaks to.

    ``extractor(concepts, passage_text)`` is expected to return the subset of
    concepts the passage addresses. When ``extractor`` is ``None`` (or raises)
    fall back to static token-presence labeling over the query's expanded
    facets.
    """
    concepts = expand_query_concepts(query)
    if extractor is not None:
        try:
            tags = extractor(concepts, passage_text)
            if tags:
                cleaned: list[str] = []
                seen: set[str] = set()
                for tag in tags:
                    tag = (tag or "").strip()
                    if tag and tag.lower() not in seen:
                        seen.add(tag.lower())
                        cleaned.append(tag)
                if cleaned:
                    return cleaned
        except Exception:
            # Best-effort: a flaky extractor must never break labeling.
            pass
    return _default_label(concepts, passage_text)
