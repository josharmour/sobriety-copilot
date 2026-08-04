"""Tests for the RAG knowledge-graph step-linking logic.

Proves the single most important behavioral contract of the interactive graph:
a *specific* step query (e.g. "step 9") must focus on THAT step only, while a
broad overview query ("The Twelve Steps") returns the full wheel of 12 steps.

Regression guard for SC-1.1.3 knowledge graph: previously every step node tap
re-ran the same query and always returned the full 12-step wheel, so the graph
never visibly changed and clicking appeared to do nothing.

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


ALL_STEPS = {f"step_{i}" for i in range(1, 13)}


def _link_steps(query):
    """Return the set of step-node ids build_knowledge_graph links for `query`."""
    graph = build_knowledge_graph(query, retriever=_NoOpRetriever())
    return {node["id"] for node in graph["nodes"] if node["type"] == "step"}


# -- Overview queries: full wheel of 12 ---------------------------------------
@pytest.mark.parametrize(
    "query",
    [
        "The Twelve Steps",
        "the steps",
        "inventory",
        "the 12 steps",
    ],
)
def test_overview_query_links_all_twelve_steps(query):
    assert _link_steps(query) == ALL_STEPS


@pytest.mark.parametrize(
    "query",
    [
        "The Twelve Steps",
        "the steps",
    ],
)
def test_overview_edges_cover_all_steps(query):
    graph = build_knowledge_graph(query, retriever=_NoOpRetriever())
    edge_targets = {edge["target"] for edge in graph["edges"]}
    assert ALL_STEPS <= edge_targets


# -- Specific step queries: focus on that step only ---------------------------
@pytest.mark.parametrize(
    "query,expected",
    [
        ("Step 9", "step_9"),
        ("Step 9: Direct Restitution & Amends", "step_9"),
        ("Step 4: Fourth-Step Inventory", "step_4"),
        ("Step 12: Service & Spiritual Awakening", "step_12"),
        ("step 1", "step_1"),
    ],
)
def test_specific_step_query_focuses_only_that_step(query, expected):
    linked = _link_steps(query)
    assert linked == {expected}


# -- Non-step queries don't pull in steps -------------------------------------
def test_non_step_query_links_no_steps():
    assert _link_steps("sponsorship") == set()
