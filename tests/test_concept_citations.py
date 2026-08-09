"""Tests for the conceptual-citation layer (src/rag/concepts.py).

Covers:
  (a) expand_query_concepts returns query + static facets for a known word
      with the default (None) extractor.
  (b) an injected fake extractor's custom facets are used.
  (c) label_concept tags correctly with a fake extractor.
  (d) the concept layer never breaks when the extractor raises (graceful
      fallback).
  (e) a citation dict produced through the server's _build_chat_sources hook
      includes a 'concepts' key defaulting to [].

No network / Ollama / chromadb is touched: src.rag.concepts is pure stdlib,
and the server hook is exercised by exec'ing the *actual* _build_chat_sources
source (the repo's server.py can't be imported here because its native
fastapi/pydantic deps don't load under this bare venv). All the helpers it
needs are defined inline below and mirror the real module.
"""
import ast
import os
from pathlib import Path

from src.rag.concepts import (
    expand_query_concepts,
    label_concept,
)

REPO = Path(__file__).resolve().parent.parent
SERVER_PY = REPO / "src" / "server.py"


# -- Helpers to exercise the server's citation hook without importing server.py --
def _extract_function_source(path: Path, func_name: str) -> str:
    """Return the exact source text of function `func_name` from `path`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return ast.get_source_segment(path.read_text(encoding="utf-8"), node)
    raise AssertionError(f"{func_name} not found in {path}")


# Minimal stand-ins mirroring the real helpers _build_chat_sources depends on.
def _strip_page_headers(text: str) -> str:
    return (text or "").strip()


def _unwrap_excerpt(text: str) -> str:
    return (text or "").strip()


MAX_EXCERPT_CHARS = 1500
DOCUMENTS_DIR = "documents"

# Load the REAL _build_chat_sources source from src/server.py and bind the
# helpers it references so the produced dicts are the genuine server contract.
_build_chat_sources_src = _extract_function_source(SERVER_PY, "_build_chat_sources")
namespace = {
    "os": os,
    "Any": object,
    "DOCUMENTS_DIR": DOCUMENTS_DIR,
    "MAX_EXCERPT_CHARS": MAX_EXCERPT_CHARS,
    "_unwrap_excerpt": _unwrap_excerpt,
    "_strip_page_headers": _strip_page_headers,
}
exec(compile(ast.parse(_build_chat_sources_src), str(SERVER_PY), "exec"), namespace)
_build_chat_sources = namespace["_build_chat_sources"]


# -- (a) default extractor ------------------------------------------------------
def test_expand_default_static_facets():
    facets = expand_query_concepts("serenity")
    assert isinstance(facets, list)
    assert bool(facets)
    # Query always leads.
    assert facets[0].lower() == "serenity"
    joined = " ".join(f.lower() for f in facets)
    for expected in ("serenity", "peace", "acceptance", "surrender"):
        assert expected in joined


def test_expand_unknown_word_defaults_to_query():
    facets = expand_query_concepts("zzzquux")
    # No static entry -> at least the query itself.
    assert facets == ["zzzquux"]


# -- (b) injected extractor -----------------------------------------------------
def test_expand_injected_facets_used():
    def fake_extractor(query: str):
        return [query, "custom-facet-a", "custom-facet-b"]

    facets = expand_query_concepts("whatever", extractor=fake_extractor)
    assert "custom-facet-a" in facets
    assert "custom-facet-b" in facets


def test_expand_injected_empty_falls_back():
    def empty_extractor(query: str):
        return []

    # Empty extractor output -> static fallback still yields the query facet.
    facets = expand_query_concepts("serenity", extractor=empty_extractor)
    assert facets and facets[0].lower() == "serenity"


# -- (c) label_concept ----------------------------------------------------------
def test_label_concept_with_fake_extractor():
    def fake_extractor(concepts, passage_text):
        # Judge: passages mentioning "peace" speak to "peace".
        return [c for c in concepts if "peace" in c.lower()]

    labeled = label_concept(fake_extractor, "serenity", "a passage about inner peace")
    assert len(labeled) == 1
    assert labeled[0].lower() == "peace"


def test_label_concept_static_fallback_tags_present_concept():
    # No extractor -> static token-presence labeling. Passage mentions
    # "acceptance" which is a facet of "serenity".
    tagged = label_concept(None, "serenity", "Acceptance is the answer to all my problems.")
    assert any("acceptance" in t.lower() for t in tagged)


# -- (d) extractor raising is non-fatal -----------------------------------------
def test_expand_does_not_break_when_extractor_raises():
    def broken_extractor(query: str):
        raise RuntimeError("LLM down")

    facets = expand_query_concepts("serenity", extractor=broken_extractor)
    assert facets  # graceful fallback, no exception


def test_label_does_not_break_when_extractor_raises():
    def broken_extractor(concepts, passage_text):
        raise RuntimeError("LLM down")

    tagged = label_concept(broken_extractor, "serenity", "inner peace")
    assert isinstance(tagged, list)  # graceful fallback, no exception


# -- (e) server citation hook exposes 'concepts' with default [] ----------------
class _FakeRetrievalResult:
    """Shape-compatible stand-in for src.rag.retriever.RetrievalResult."""

    def __init__(self, **kwargs):
        self.source = kwargs.pop("source", "book.pdf")
        self.source_path = kwargs.pop("source_path", "/documents/book.pdf")
        self.relative_path = kwargs.pop("relative_path", "book.pdf")
        self.similarity = kwargs.pop("similarity", 0.5)
        self.excerpt = kwargs.pop("excerpt", "a real excerpt")
        self.match_scale = kwargs.pop("match_scale", "medium")
        self.scale = kwargs.pop("scale", "medium")
        # Only set if explicitly provided (so we also prove the missing-field case).
        if "concepts" in kwargs:
            self.concepts = kwargs.pop("concepts")
        if kwargs:
            raise TypeError(f"unexpected kwargs: {kwargs!r}")


def test_citation_dict_exposes_concepts_default():
    result = _FakeRetrievalResult()  # no concepts attribute set
    citation = _build_chat_sources([result])[0]
    assert "concepts" in citation
    assert citation["concepts"] == []


def test_citation_dict_carries_concepts_when_set():
    result = _FakeRetrievalResult(concepts=["acceptance", "surrender"])
    citation = _build_chat_sources([result])[0]
    assert citation["concepts"] == ["acceptance", "surrender"]


def test_real_dataclass_default_concepts_is_empty_list():
    # Exercise the ACTUAL dataclass from retriever.py, stubbing its heavy deps
    # (chromadb/ollama) via the sys.modules pattern test_graph.py uses. The
    # existing `src.rag.retriever` entry is saved/restored so we neither clobber
    # nor depend on any other test's sys.modules stub (e.g. test_graph.py).
    import sys
    import types

    prev_fake = sys.modules.get("src.rag.retriever")

    fake = types.ModuleType("src.rag.chroma_client")
    fake.create_chroma_client = lambda *a, **k: None
    sys.modules["src.rag.chroma_client"] = fake

    fake_emb = types.ModuleType("src.rag.embeddings")
    fake_emb.embed_query = lambda *a, **k: None
    sys.modules["src.rag.embeddings"] = fake_emb

    fake_idx = types.ModuleType("src.rag.indexer")
    fake_idx.DEFAULT_COLLECTION = "test"
    sys.modules["src.rag.indexer"] = fake_idx

    sys.modules.setdefault("src.rag.reranker", types.ModuleType("src.rag.reranker"))

    # Force a fresh import of the real retriever module, ignoring any stub that
    # a previously-collected test left in sys.modules.
    sys.modules.pop("src.rag.retriever", None)
    try:
        from src.rag.retriever import RetrievalResult
    finally:
        if prev_fake is not None:
            sys.modules["src.rag.retriever"] = prev_fake

    r = RetrievalResult(
        text="t",
        excerpt="e",
        similarity=0.5,
        source="s",
        chunk_index=0,
    )
    assert r.concepts == []
    # Equality with a modified copy still behaves like a normal dataclass.
    r.concepts = ["acceptance"]
    assert r.concepts == ["acceptance"]
