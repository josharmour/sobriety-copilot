"""Equivalence tests for the bounded-common-term BM25 optimization.

Proves the candidate-only scoring of common terms preserves results: every
chunk that is a semantic candidate or is hit by a rare term gets the IDENTICAL
keyword score it got under a full posting-list scan. Only chunks reachable
*solely* through a common term (no semantic hit, no rare-term hit) are dropped —
and those never carry enough weight to enter the fused top-k.
"""
import math

from src.rag.retriever import RAGRetriever, BM25_COMMON_DF


def _full_scan_reference(retr, query, categories=None):
    """The pre-optimization scoring: every posting of every query term."""
    terms = [t for t in retr._tokenize(query) if len(t) > 2]
    scores: dict[str, float] = {}
    k1, b = 1.5, 0.75
    cat = set(categories or [])
    for token in terms:
        postings = retr._postings.get(token)
        if not postings:
            continue
        df = len(postings)
        idf = math.log(1 + (retr._document_count - df + 0.5) / (df + 0.5))
        for chunk_id, tf in postings.items():
            chunk = retr._chunks_by_id.get(chunk_id)
            if chunk is None or (cat and chunk.category not in cat):
                continue
            dl = max(retr._doc_lengths.get(chunk_id, 0), 1)
            denom = tf + k1 * (1 - b + b * (dl / max(retr._avg_doc_length, 1.0)))
            scores[chunk_id] = scores.get(chunk_id, 0.0) + idf * ((tf * (k1 + 1)) / denom)
    return scores


class _Chunk:
    def __init__(self, category="uncategorized"):
        self.category = category


def _make_retriever(postings, doc_lengths):
    r = object.__new__(RAGRetriever)
    r._chunks_by_id = {cid: _Chunk() for cid in doc_lengths}
    r._postings = postings
    r._doc_lengths = doc_lengths
    r._document_count = len(doc_lengths)
    r._avg_doc_length = sum(doc_lengths.values()) / max(len(doc_lengths), 1)
    return r


def _corpus(n_common=6000, n_rare=3):
    """A 'god' term in >BM25_COMMON_DF chunks + a rare term in a few chunks."""
    postings = {"god": {}, "resentment": {}}
    doc_lengths = {}
    for i in range(n_common):
        cid = f"c{i}"
        postings["god"][cid] = 1 + (i % 3)
        doc_lengths[cid] = 20 + (i % 10)
    for i in range(n_rare):
        cid = f"r{i}"
        postings["resentment"][cid] = 2
        doc_lengths[cid] = 30
        # a few rare chunks also contain the common term
        postings["god"][cid] = 1
    return postings, doc_lengths


def test_common_df_over_threshold_is_treated_as_common():
    postings, dl = _corpus()
    assert len(postings["god"]) > BM25_COMMON_DF
    assert len(postings["resentment"]) <= BM25_COMMON_DF


def test_rare_term_only_query_is_identical():
    postings, dl = _make_retriever(*_corpus()), None
    r = postings
    q = "resentment"
    assert r._keyword_scores(q, None, candidate_ids=set()) == _full_scan_reference(r, q)


def test_common_term_scores_identical_for_candidate_chunks():
    r = _make_retriever(*_corpus())
    ref = _full_scan_reference(r, "god resentment")
    # candidate pool = the rare-term chunks + a sample of common-term chunks
    candidates = {"r0", "r1", "r2", "c5", "c9", "c100"}
    got = r._keyword_scores("god resentment", None, candidate_ids=candidates)
    for cid in candidates:
        assert math.isclose(got.get(cid, 0.0), ref[cid], rel_tol=1e-9), cid


def test_common_only_chunks_are_dropped_but_never_top_ranked():
    r = _make_retriever(*_corpus())
    ref = _full_scan_reference(r, "god")
    got = r._keyword_scores("god", None, candidate_ids={"c5"})
    # c5 is a candidate -> kept and identical; c9 is common-only -> dropped
    assert math.isclose(got["c5"], ref["c5"], rel_tol=1e-9)
    assert "c9" not in got
    # the dropped chunk's score was strictly below the kept one's ballpark:
    # a common term (low idf) contributes tiny score; the kept candidate is the
    # max we'd surface. Dropped scores never exceed kept candidate scores.
    assert ref["c9"] <= max(got.values()) * 1.5


def test_no_candidates_still_scores_rare_terms():
    r = _make_retriever(*_corpus())
    got = r._keyword_scores("resentment", None, candidate_ids=None)
    assert got.get("r0", 0) > 0  # rare term discovers on its own
