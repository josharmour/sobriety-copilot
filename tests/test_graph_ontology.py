"""Tests for ontology-enriched knowledge graph building.

Proves the two contracts of making the graph data-driven WITHOUT breaking the
existing hand-authored path:

(a) ``build_knowledge_graph`` with NO ontology returns exactly the same stable
    structure as before (regression — reuses the sys.modules retriever stub
    from ``tests/test_graph.py``).
(b) WITH a small injected ontology (fixture dict), extra ``concept`` +
    ``passage`` nodes drawn from the co-occurrence edges are added and the node
    count grows.

These tests run WITHOUT heavy RAG deps (chromadb, Ollama, ...): we stub the
chromadb-backed ``src.rag.retriever`` module in ``sys.modules`` so
``src.rag.graph`` (which imports ``RAGRetriever`` at module load) can be
imported standalone, and we feed it a retriever that returns no passages.
"""
import sys
import types

import pytest

# -- Stub the chromadb-backed retriever so graph.py imports standalone ---------
_FAKE_RETRIEVER = types.ModuleType("src.rag.retriever")


class _NoOpRetriever:
    """Minimal stand-in for RAGRetriever: returns no passages."""

    def retrieve(self, query, top_k=6):  # noqa: D401 - signature mirrors real
        return []


_FAKE_RETRIEVER.RAGRetriever = _NoOpRetriever
sys.modules.setdefault("src.rag.retriever", _FAKE_RETRIEVER)

from src.rag.graph import build_knowledge_graph  # noqa: E402  (after stub)


# -- Small inline ontology fixture (shape mirrors src.rag.ontology.build_ontology)
ONTOLOGY_FIXTURE = {
    "concepts": [
        {"term": "sponsorship", "freq": 42, "sections": 12, "docs": 3},
        {"term": "serenity", "freq": 38, "sections": 11, "docs": 3},
        {"term": "acceptance", "freq": 30, "sections": 9, "docs": 2},
        {"term": "powerlessness", "freq": 25, "sections": 8, "docs": 2},
        {"term": "amends", "freq": 20, "sections": 7, "docs": 2},
    ],
    "global_top": [
        {"term": "sponsorship", "freq": 42, "sections": 12, "docs": 3},
        {"term": "serenity", "freq": 38, "sections": 11, "docs": 3},
        {"term": "acceptance", "freq": 30, "sections": 9, "docs": 2},
        {"term": "powerlessness", "freq": 25, "sections": 8, "docs": 2},
        {"term": "amends", "freq": 20, "sections": 7, "docs": 2},
    ],
    "edges": [
        # "sponsorship" co-occurs with "serenity" and "acceptance";
        # "powerlessness" co-occurs with "serenity" and "amends".
        {"source": "sponsorship", "target": "serenity", "weight": 5},
        {"source": "sponsorship", "target": "acceptance", "weight": 3},
        {"source": "powerlessness", "target": "serenity", "weight": 4},
        {"source": "powerlessness", "target": "amends", "weight": 2},
    ],
    "doc_coverage": {
        "sponsorship": ["big_book", "twelve_and_twelve"],
        "serenity": ["big_book", "daily_reflections"],
        "acceptance": ["big_book"],
        "powerlessness": ["big_book"],
        "amends": ["twelve_and_twelve"],
    },
    "docs": [
        {"doc_id": "big_book", "title": "Alcoholics Anonymous", "category": "book", "num_sections": 11},
        {"doc_id": "twelve_and_twelve", "title": "Twelve Steps and Twelve Traditions", "category": "book", "num_sections": 12},
        {"doc_id": "daily_reflections", "title": "Daily Reflections", "category": "book", "num_sections": 365},
    ],
    "stats": {"docs": 3, "sections": 11, "vocab_size": 5, "edges": 4},
}


def _node_types(graph):
    return {node["id"]: node["type"] for node in graph["nodes"]}


# (a) Regression: no ontology == unchanged hand-authored behavior.
def test_without_ontology_returns_same_structure():
    graph = build_knowledge_graph("The Twelve Steps", retriever=_NoOpRetriever())
    assert set(graph.keys()) == {"query", "nodes", "edges"}
    assert graph["query"] == "The Twelve Steps"
    # Same stable structure as the legacy path: one central query + prompt nodes,
    # and no ontology-namespaced nodes anywhere.
    ids = [n["id"] for n in graph["nodes"]]
    assert not any(n.startswith("onto_") for n in ids)
    types = {t for _, t in _node_types(graph).items()}
    # The legacy hand-authored graph only ever produces these node types.
    assert types <= {"query", "passage", "term", "step", "prompt"}
    assert "step_12" in [n["id"] for n in graph["nodes"]]


def test_without_ontology_no_promptless_concepts():
    graph = build_knowledge_graph("sponsorship", retriever=_NoOpRetriever())
    ids = [n["id"] for n in graph["nodes"]]
    assert not any(n.startswith("onto_") for n in ids)


# (b) With ontology: extra concept + passage nodes appear, node count grows.
def test_with_ontology_adds_concept_nodes():
    base = build_knowledge_graph("sponsorship", retriever=_NoOpRetriever())
    enriched = build_knowledge_graph(
        "sponsorship", retriever=_NoOpRetriever(), ontology=ONTOLOGY_FIXTURE
    )

    assert len(enriched["nodes"]) > len(base["nodes"])
    assert len(enriched["edges"]) > len(base["edges"])

    concept_ids = [
        n["id"] for n in enriched["nodes"]
        if n.get("type") == "concept" and n.get("category") == "ontology"
    ]
    # "sponsorship" matches the query; its co-occurring neighbours are pulled in.
    assert "onto_c_serenity" in concept_ids
    assert "onto_c_acceptance" in concept_ids

    # Concept→central edge (matched query term links the new concept).
    edge_keys = {(e["source"], e["target"]) for e in enriched["edges"]}
    assert ("term_sponsorship", "onto_c_serenity") in edge_keys
    # The added concepts are grounded in the docs where they appear.
    passage_ids = [n["id"] for n in enriched["nodes"] if n["type"] == "passage"]
    assert any(p.startswith("onto_p_") for p in passage_ids)


def test_with_ontology_query_matching_phrase():
    enriched = build_knowledge_graph(
        "acceptance", retriever=_NoOpRetriever(), ontology=ONTOLOGY_FIXTURE
    )
    # "acceptance" is a single-token concept that appears in the query.
    concept_ids = [
        n["id"] for n in enriched["nodes"]
        if n.get("type") == "concept" and n.get("category") == "ontology"
    ]
    # acceptance's neighbours: sponsorship (weight 3) — pulled in.
    assert concept_ids  # at least one ontology concept added


def test_with_ontology_no_match_is_unchanged():
    base = build_knowledge_graph("unicorn", retriever=_NoOpRetriever())
    enriched = build_knowledge_graph(
        "unicorn", retriever=_NoOpRetriever(), ontology=ONTOLOGY_FIXTURE
    )
    # No ontology concept matches "unicorn" → graph is identical to baseline.
    assert len(enriched["nodes"]) == len(base["nodes"])
    assert not any(n.get("category") == "ontology" for n in enriched["nodes"])
