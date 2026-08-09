"""Offline topic-ontology extraction from recovery-literature manifests.

This module builds a **data-driven** concept vocabulary plus a co-occurrence
graph straight from the real ``.manifests/*.json`` corpus — the embryo of the
future dynamic knowledge graph described in
``docs/plans/beyond-rag-deep-understanding-knowledge-graph.md`` (Parts 1B/4A).

Unlike the hand-authored ~20-term ``RECOVERY_TERMS`` and 12-node
``CORE_RECOVERY_NODES`` in :mod:`src.rag.graph`, the vocabulary here is
derived from the actual document sections, so it reflects what the literature
actually talks about (and how often), and its co-occurrence edges are weighted
by how frequently concepts appear together in the same section. Community
detection (Leiden/Louvain) can be layered on top of this graph later; this
module only produces the topic-vocabulary + co-occurrence embryo.

Fully offline — standard library only (``json``, ``re``, ``collections``).
It does **not** import chromadb, Ollama, ``src.rag.retriever``, or anything
else heavy, so it can be imported and tested standalone.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from typing import Any, Iterable

from src.rag import sections

# Default corpus location. The manifests live on a slow, read-only SMB mount
# and are explicitly "never git" — so we point at the mount by default and let
# MANIFESTS_DIR override it (e.g. for tests or a local copy).
DEFAULT_MANIFESTS_DIR = (
    os.environ.get("MANIFESTS_DIR")
    or "/Users/joshu/repos/sobriety-copilot/documents/.manifests"
)

# Words that carry no topical signal. Kept deliberately broad: recovery prose
# is full of small function words and vague verbs, and we want concepts, not
# filler.
STOPWORDS = frozenset(
    """
    the a an and or but if then when while for with without to of in on at by
    from into onto upon as is are was were be been being am do does did done
    have has had having will would shall should can could may might must
    it its it's this that these those there their they them we you your yours
    i me my mine he she his her him our ours us not no nor so too very
    what which who whom whose how why where when all any both each few more
    most other some such only own same than about above below under up down
    out off over through during before after between among across against
    because since until unless even just also again further once here there
    every itself ourselves themselves himself herself oneself another one two
    three four five six seven eight nine ten eleven twelve first second third
    forth fifth sixth seventh eighth ninth tenth say says said tell told
    make makes made making take takes took taken get gets got getting go goes
    went gone come comes came going know knows knew known see sees saw seen
    think thinks thought thing things way ways much many little big great
    really lot lots people person man woman men women life lives day days
    good well new old
    """.split()
)

# A minimal set of multi-word recovery phrases worth counting as a single
# concept alongside single words (they are looked for on a whitespace/lower
# basis). Purely additive; the vocabulary is whatever the corpus yields.
PHRASES: tuple[str, ...] = (
    "higher power",
    "rigorous honesty",
    "defects of character",
    "spiritual awakening",
    "twelve steps",
    "twelve traditions",
    "powerlessness",
)


_WORD_RE = re.compile(r"[a-z][a-z']+")
# The corpus uses both ASCII ' and typographic ’ in contractions (don’t).
_APOSTROPHES = str.maketrans({"\u2019": "'", "\u2018": "'"})
_PHRASE_RE = re.compile(r"(?:^|\s)(" + "|".join(map(re.escape, PHRASES)) + r")(?:\s|$)")


def _tokenize(text: str) -> Iterable[str]:
    """Yield candidate concept tokens (single words + multi-word phrases)."""
    lowered = text.lower().translate(_APOSTROPHES)
    for match in _PHRASE_RE.finditer(lowered):
        yield match.group(1)
    for word in _WORD_RE.findall(lowered):
        if word not in STOPWORDS:
            yield word


def count_section_terms(content_text: str) -> Counter:
    """Return a term-frequency Counter for one section's content."""
    return Counter(_tokenize(content_text))


def extract_keywords(
    content_texts: Iterable[str],
    top_n: int | None = None,
    min_freq: int = 1,
) -> list[dict[str, Any]]:
    """Aggregate term frequencies across an iterable of section texts.

    Returns a list of ``{"term", "freq", "sections", "docs"}`` dicts sorted by
    descending frequency (ties broken for stable output). ``min_freq`` drops
    ultra-rare terms; ``top_n`` truncates the list.
    """
    freq: Counter[str] = Counter()
    term_to_sections: dict[str, set[str]] = {}
    term_to_docs: dict[str, set[str]] = {}
    for text in content_texts:
        for term, count in count_section_terms(text).items():
            freq[term] += count
    rows = [
        {
            "term": term,
            "freq": freq[term],
            "sections": len(term_to_sections.get(term, set())),
            "docs": len(term_to_docs.get(term, set())),
        }
        for term in freq
        if freq[term] >= min_freq
    ]
    rows.sort(key=lambda r: (-r["freq"], r["term"]))
    if top_n is not None:
        rows = rows[:top_n]
    return rows


def _load_doc(source: str | dict[str, Any]) -> dict[str, Any]:
    """Load one manifest (path to JSON or raw dict) into sections form."""
    doc = sections.load(source)
    return doc


def load_manifests(manifest_dir: str | None = None) -> list[dict[str, Any]]:
    """Load every ``*.json`` manifest in ``manifest_dir`` (sorted, stable).

    Returns a list of section-form docs (as produced by ``sections.load``).
    Missing/unreadable files are skipped (the corpus is a living mount).
    """
    directory = manifest_dir or DEFAULT_MANIFESTS_DIR
    paths = []
    for name in sorted(os.listdir(directory)):
        if name.endswith(".json"):
            paths.append(os.path.join(directory, name))
    docs = []
    for path in paths:
        try:
            docs.append(_load_doc(path))
        except (OSError, json.JSONDecodeError, ValueError):
            # Skip corrupt / unreadable files rather than aborting the corpus.
            continue
    return docs


# --- Public builder ----------------------------------------------------------


def build_ontology(
    manifests: Iterable[str | dict[str, Any]] | None = None,
    manifest_dir: str | None = None,
    *,
    top_n_per_section: int = 8,
    global_top_n: int = 50,
    min_edge_weight: int = 1,
) -> dict[str, Any]:
    """Build the offline topic ontology from manifests.

    ``manifests`` is an optional explicit list of manifest paths or raw dicts
    (used by tests with small inline fixtures). When omitted, 
    :func:`load_manifests` reads every ``*.json`` in ``manifest_dir`` (or the
    default ``MANIFESTS_DIR`` corpus).

    Returns a dict with:

    * ``concepts``        — the full aggregated vocabulary (term → freq /
      section & doc coverage), sorted by descending frequency.
    * ``global_top``      — the top ``global_top_n`` concepts (same row shape).
    * ``per_section_top`` — for each section, ``doc_id``, ``section_id`` /
      ``title`` and the section's top ``top_n_per_section`` terms.
    * ``edges``           — co-occurrence edges ``{source, target, weight}``
      between concepts that appear together in the same section (weight = number
      of sections where both appear). Sorted by descending weight.
    * ``doc_coverage``    — per global-top concept, which docs it appears in
      (a mapping term → list of doc ids).
    * ``stats``           — counts to sanity-check the build.

    Fully offline: stdlib only, no network, no LLM.
    """
    docs = []
    if manifests is not None:
        for src in manifests:
            docs.append(_load_doc(src))
    else:
        docs = load_manifests(manifest_dir)

    # -- Per-document / per-section term counts -----------------------------
    per_section_top: list[dict[str, Any]] = []
    global_counter: Counter[str] = Counter()
    term_sections: dict[str, set[str]] = {}
    term_docs: dict[str, set[str]] = {}
    doc_index: dict[str, dict[str, Any]] = {}  # doc_id -> {title, category, num_sections}

    for doc in docs:
        doc_id = doc.get("doc_id") or str(id(doc))
        doc_index.setdefault(
            doc_id,
            {
                "doc_id": doc_id,
                "title": doc.get("title"),
                "category": doc.get("category"),
                "num_sections": len(doc.get("sections", [])),
            },
        )
        for sec in doc.get("sections", []):
            content = sec.get("content_text", "")
            if not content:
                continue
            sec_counter = count_section_terms(content)
            sec_id = sec.get("id") or sec.get("title") or f"section_{sec.get('order')}"
            for term in sec_counter:
                global_counter[term] += sec_counter[term]
                term_sections.setdefault(term, set()).add(sec_id)
                term_docs.setdefault(term, set()).add(doc_id)
            top_terms = [
                {"term": t, "freq": f}
                for t, f in sec_counter.most_common(top_n_per_section)
            ]
            per_section_top.append(
                {
                    "doc_id": doc_id,
                    "section_id": sec_id,
                    "title": sec.get("title", ""),
                    "order": sec.get("order"),
                    "word_count": sec.get("word_count", 0),
                    "top_terms": top_terms,
                }
            )

    # -- Global top concepts --------------------------------------------------
    global_rows = [
        {
            "term": term,
            "freq": global_counter[term],
            "sections": len(term_sections.get(term, set())),
            "docs": len(term_docs.get(term, set())),
        }
        for term in global_counter
    ]
    global_rows.sort(key=lambda r: (-r["freq"], r["term"]))

    # -- Co-occurrence edges (within-section co-occurrence) -------------------
    edge_counter: Counter[tuple[str, str]] = Counter()
    sec_counter_cache: list[tuple[str, Counter]] = []
    for doc in docs:
        doc_id = doc.get("doc_id") or str(id(doc))
        for sec in doc.get("sections", []):
            content = sec.get("content_text", "")
            if not content:
                continue
            sec_counter = count_section_terms(content)
            top_terms = [t for t, _ in sec_counter.most_common(top_n_per_section)]
            for i, a in enumerate(top_terms):
                for b in top_terms[i + 1 :]:
                    if a != b:
                        key = tuple(sorted((a, b)))
                        edge_counter[key] += 1
    edges = [
        {"source": a, "target": b, "weight": w}
        for (a, b), w in edge_counter.items()
        if w >= min_edge_weight
    ]
    edges.sort(key=lambda e: (-e["weight"], e["source"], e["target"]))

    # -- Document coverage for the global top ---------------------------------
    doc_coverage: dict[str, list[str]] = {}
    for row in global_rows[:global_top_n]:
        doc_coverage[row["term"]] = sorted(term_docs.get(row["term"], set()))

    return {
        "concepts": global_rows,
        "global_top": global_rows[:global_top_n],
        "per_section_top": per_section_top,
        "edges": edges,
        "doc_coverage": doc_coverage,
        "stats": {
            "docs": len(docs),
            "sections": len(per_section_top),
            "vocab_size": len(global_counter),
            "global_top_n": global_top_n,
            "edges": len(edges),
            "top_n_per_section": top_n_per_section,
        },
        "docs": list(doc_index.values()),
    }
