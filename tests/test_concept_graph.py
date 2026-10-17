"""Concept graph runtime (src/rag/concept_graph.py) on a two-book library and a tiny concept list."""

import json
import os
import shutil

import pytest

from src.rag import concept_graph as CG
from src.rag.concept_text import ConceptMatcher, passages_for_book
from src.research.library import Library

DOCS = os.path.join(os.path.dirname(__file__), "..", "documents", ".manifests")
BOOKS = ["alcoholics-anonymous", "twelve-steps-and-twelve-traditions"]

pytestmark = pytest.mark.skipif(not all(os.path.isfile(os.path.join(DOCS, f"{b}.json")) for b in BOOKS),
                                reason="manifests not present")


@pytest.fixture(scope="module")
def setup(tmp_path_factory):
    root = tmp_path_factory.mktemp("lib")
    os.makedirs(root / ".manifests")
    for b in BOOKS:
        shutil.copy(os.path.join(DOCS, f"{b}.json"), root / ".manifests" / f"{b}.json")
    data = {"version": 1, "groups": [{"id": "struggles", "label": "Struggles"}], "nodes": [
        {"id": "t:resentment", "label": "Resentment", "type": "topic", "group": "struggles", "x": 0.1, "y": 0.1,
         "prominence": 1.0, "forms": []},
        {"id": "t:fear", "label": "Fear", "type": "topic", "group": "struggles", "x": 0.2, "y": 0.1,
         "prominence": 0.8, "forms": []},
        {"id": "c:bill-wilson", "label": "Bill Wilson", "type": "person", "group": "recovery", "x": 0.5, "y": 0.5,
         "prominence": 0.3, "forms": ["bill wilson", "bill w"]},
        {"id": "c:third-step-prayer", "label": "Third Step Prayer", "type": "prayer", "group": "practices",
         "x": 0.7, "y": 0.2, "prominence": 0.2, "forms": ["offer myself to thee"]},
    ]}
    path = root / "graph_concepts.json"
    path.write_text(json.dumps(data))
    old = CG.DATA_PATH
    CG.DATA_PATH = str(path)
    lib = Library(str(root))
    g = CG.build(lib)
    yield lib, g
    CG.DATA_PATH = old


def test_matcher_handles_plurals_wildcards_and_phrases():
    m = ConceptMatcher([("a", ["resentment"]), ("b", ["resent*"]), ("c", ["offer myself to thee"])])
    hits = m.match_counts("Resentments, resented. God, I offer myself to Thee")
    assert hits["a"] == 1 and hits["b"] == 2 and hits["c"] == 1


def test_passages_stay_inside_sections(setup):
    lib, _g = setup
    book = lib.book("alcoholics-anonymous")
    for p in passages_for_book(book)[:300]:
        secs = {book.blocks[book.by_id[b]].section for b in p.block_ids}
        assert len(secs) == 1


def test_peers_and_where_they_meet(setup):
    lib, g = setup
    d = CG.node_payload(g, lib, "t:resentment")
    assert d["node"]["passages"] > 20
    assert "t:fear" in [p["id"] for p in d["peers"]]
    assert {b["id"] for b in d["books"]} == set(BOOKS)
    assert any(c["title"] == "How It Works" for c in d["chapters"])
    meet = CG.meet_payload(g, lib, "t:resentment", "t:fear")
    assert meet["total"] > 0
    text = meet["passages"][0]["excerpt"].lower()
    assert "resent" in text or "fear" in text


def test_prayer_node_finds_the_third_step_prayer(setup):
    lib, g = setup
    d = CG.node_payload(g, lib, "c:third-step-prayer")
    p = d["passages"][0]
    assert p["doc_id"] == "alcoholics-anonymous" and str(p["page"]) == "63"
    assert p["section_title"] == "How It Works"


def test_book_chapter_search_and_map(setup):
    lib, g = setup
    b = CG.book_payload(g, lib, "alcoholics-anonymous")
    assert b["concepts"] and any(c["title"] == "How It Works" for c in b["chapters"])
    sec = next(c["section"] for c in b["chapters"] if c["title"] == "How It Works")
    ch = CG.chapter_payload(g, lib, "alcoholics-anonymous", sec)
    assert "t:resentment" in [c["id"] for c in ch["concepts"]]
    s = CG.search_payload(g, lib, "bill")
    assert s["nodes"][0]["id"] == "c:bill-wilson"
    assert any("Bill" in c["title"] for c in s["chapters"])
    m = CG.map_payload(g, lib)
    assert m["fields"][0] == "id" and len(m["nodes"]) == 4
