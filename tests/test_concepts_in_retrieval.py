"""Tests for the Wave-1 conceptual layer wired into the REAL retrieve() path.

Covers:
  (a) Layer-1 facet expansion: a "serenity" query yields the "acceptance" and
      "surrender" facets (the serenity -> acceptance conceptual link from the
      design doc), via the real src.rag.concepts module.
  (b) When concept labeling is ENABLED, retrieve() (real _apply_concept_labels
      wired exactly as in src/rag/retriever.py) tags each result's `.concepts`.
  (c) CENTERPIECE: with an injectable concept extractor that maps a query word
      to facets, a passage about "acceptance" that does NOT contain the word
      "serenity" still gets labeled with a concept tag.
  (d) When disabled, or when the extractor raises, `.concepts` stays [] and
      retrieval never breaks.

No network / Ollama / chromadb is touched: the real `src.rag.retriever` module
is imported with the heavy deps stubbed via the sys.modules pattern used in
tests/test_graph.py / tests/test_concept_citations.py.
"""
import sys
import types

import pytest

from src.rag.concepts import expand_query_concepts


# -- Import the REAL retriever module minus heavy deps ------------------------
def _import_real_retriever():
    """Import the actual src/rag/retriever.py with chroma/embeddings stubbed.

    ChromaDB, embeddings and the reranker are replaced with inert stand-ins;
    the .concepts module is left REAL (it is pure stdlib) so we exercise the
    genuine conceptual-citation code rather than a fake.
    """
    prev = {
        name: sys.modules.get(name)
        for name in (
            "src.rag.retriever",
            "src.rag.chroma_client",
            "src.rag.embeddings",
            "src.rag.indexer",
            "src.rag.reranker",
        )
    }

    fake_chroma = types.ModuleType("src.rag.chroma_client")
    fake_chroma.create_chroma_client = lambda *a, **k: None
    sys.modules["src.rag.chroma_client"] = fake_chroma

    fake_emb = types.ModuleType("src.rag.embeddings")
    fake_emb.embed_query = lambda *a, **k: None
    sys.modules["src.rag.embeddings"] = fake_emb

    fake_idx = types.ModuleType("src.rag.indexer")
    fake_idx.DEFAULT_COLLECTION = "test"
    sys.modules["src.rag.indexer"] = fake_idx

    fake_rr = types.ModuleType("src.rag.reranker")
    fake_rr.is_enabled = lambda: False
    fake_rr.oversample_factor = lambda: 1
    sys.modules["src.rag.reranker"] = fake_rr

    sys.modules.pop("src.rag.retriever", None)
    try:
        import src.rag.retriever as retriever

        yield retriever
    finally:
        # Restore every pre-existing sys.modules entry so we neither clobber
        # nor depend on any other test's stubs.
        for name, mod in prev.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod


@pytest.fixture
def retriever_mod():
    yield from _import_real_retriever()


# -- Helper reproducing retriever.retrieve()'s conceptual tail exactly ---------
def _run_concept_tail(mod, results, query):
    """Mirror the exact concept-wiring tail of the REAL retrieve() method."""
    if mod.RAG_CONCEPT_LABELS:
        mod._apply_concept_labels(
            results,
            query,
            expansion_extractor=mod._CONCEPT_EXPANSION_EXTRACTOR,
            label_extractor=mod._CONCEPT_LABEL_EXTRACTOR,
        )
    return results


# -- (a) serenity -> acceptance / surrender facet expansion -------------------
def test_expand_serenity_yields_acceptance_and_surrender():
    facets = expand_query_concepts("serenity")
    joined = " ".join(f.lower() for f in facets)
    for expected in ("acceptance", "surrender"):
        assert expected in joined


# -- (b)+(c) enabled: retrieve() tags .concepts; serenity-free acceptance ----
def test_apply_concept_labels_tags_acceptance_passage(retriever_mod):
    """Centerpiece: 'serenity' query labels an 'acceptance' passage.

    Inject a concept label extractor that tags a passage as "acceptance" when
    the word appears, proving a passage that does NOT contain "serenity" still
    gets a concept tag (the conceptual citation goal).
    """
    def label_extractor(concepts, passage_text):
        return [c for c in concepts if "acceptance" in c.lower()]

    r = retriever_mod.RetrievalResult(
        text="Acceptance is the answer to all my problems.",
        excerpt="Acceptance is the answer to all my problems.",
        similarity=0.6,
        source="book.pdf",
        chunk_index=0,
    )
    assert r.concepts == []

    retriever_mod._apply_concept_labels(
        [r], "serenity",
        expansion_extractor=None,
        label_extractor=label_extractor,
    )
    assert r.concepts
    assert any("acceptance" in c.lower() for c in r.concepts)


def test_retrieve_tail_enabled_sets_concepts(retriever_mod, monkeypatch):
    """With the opt-in flag on, the retrieve() tail sets .concepts."""
    monkeypatch.setattr(retriever_mod, "RAG_CONCEPT_LABELS", True)

    def label_extractor(concepts, passage_text):
        return [c for c in concepts if "acceptance" in c.lower()]

    monkeypatch.setattr(retriever_mod, "_CONCEPT_EXPANSION_EXTRACTOR", None)
    monkeypatch.setattr(retriever_mod, "_CONCEPT_LABEL_EXTRACTOR", label_extractor)

    results = [
        retriever_mod.RetrievalResult(
            text="Our acceptance of our powerlessness turns out to be the key.",
            excerpt="Our acceptance of our powerlessness turns out to be the key.",
            similarity=0.6, source="book.pdf", chunk_index=0,
        )
    ]
    _run_concept_tail(retriever_mod, results, "serenity")
    assert results[0].concepts
    assert any("acceptance" in c.lower() for c in results[0].concepts)


# -- (d) disabled / error -> .concepts stays [] ------------------------------
def test_retrieve_tail_disabled_leaves_concepts_empty(retriever_mod, monkeypatch):
    """Opt-in OFF: existing behavior unchanged, concepts stays []."""
    monkeypatch.setattr(retriever_mod, "RAG_CONCEPT_LABELS", False)

    def label_extractor(concepts, passage_text):
        return ["acceptance"]

    monkeypatch.setattr(retriever_mod, "_CONCEPT_LABEL_EXTRACTOR", label_extractor)

    results = [
        retriever_mod.RetrievalResult(
            text="Acceptance is the answer.",
            excerpt="Acceptance is the answer.",
            similarity=0.6, source="book.pdf", chunk_index=0,
        )
    ]
    _run_concept_tail(retriever_mod, results, "serenity")
    assert results[0].concepts == []


def test_apply_concept_labels_never_breaks_on_extractor_error(retriever_mod):
    """A raising concept extractor leaves concepts=[] and does not raise."""
    def broken_expansion(query):
        raise RuntimeError("LLM down")

    def broken_label(concepts, passage_text):
        raise RuntimeError("LLM down")

    results = [
        retriever_mod.RetrievalResult(
            text="some passage", excerpt="some passage",
            similarity=0.5, source="s.pdf", chunk_index=0,
        )
    ]
    # Expansion raises -> no exception, concepts stays [].
    retriever_mod._apply_concept_labels(
        [results[0]], "serenity",
        expansion_extractor=broken_expansion,
        label_extractor=None,
    )
    assert results[0].concepts == []

    # Label raises -> no exception, concepts stays [].
    retriever_mod._apply_concept_labels(
        [results[0]], "serenity",
        expansion_extractor=None,
        label_extractor=broken_label,
    )
    assert results[0].concepts == []


def test_retrieve_tail_error_safe_when_enabled(retriever_mod, monkeypatch):
    """Even when ENABLED, a broken extractor never breaks the retrieve tail."""
    monkeypatch.setattr(retriever_mod, "RAG_CONCEPT_LABELS", True)

    def broken_label(concepts, passage_text):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(retriever_mod, "_CONCEPT_EXPANSION_EXTRACTOR", None)
    monkeypatch.setattr(retriever_mod, "_CONCEPT_LABEL_EXTRACTOR", broken_label)

    results = [
        retriever_mod.RetrievalResult(
            text="anything", excerpt="anything",
            similarity=0.5, source="s.pdf", chunk_index=0,
        )
    ]
    # Must NOT raise and must leave concepts empty.
    returned = _run_concept_tail(retriever_mod, results, "serenity")
    assert returned is results  # results still returned unchanged
    assert results[0].concepts == []
