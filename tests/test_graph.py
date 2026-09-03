"""Tests for the corpus knowledge graph (src/rag/graph.py).

Runs against a tiny synthetic corpus shaped like the retriever's BM25 cache
(chunks_by_id + postings), so it needs neither ChromaDB nor the real library.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import unittest
from collections import Counter, defaultdict
from dataclasses import dataclass

from src.rag import graph as G
from src.rag.graph_taxonomy import GROUPS, TOPICS, topic_ids

TOKEN_RE = re.compile(r"[A-Za-z0-9']+")


@dataclass
class _Chunk:
    id: str
    text: str
    source: str
    chunk_index: int
    scale: str = "medium"
    category: str = "conference_approved"
    doc_id: str | None = None
    block_ids: str | None = None
    printed_page_start: object = None
    source_path: str = ""
    relative_path: str = ""


class _Collection:
    name = "test_collection"


class _Retriever:
    """Just enough of RAGRetriever for the builder: chunk cache + postings."""

    def __init__(self, chunks: list[_Chunk]):
        self._chunks_by_id = {c.id: c for c in chunks}
        self._postings: dict[str, dict[str, int]] = defaultdict(dict)
        for c in chunks:
            for tok, n in Counter(t.lower() for t in TOKEN_RE.findall(c.text)).items():
                self._postings[tok][c.id] = n
        self._cache_initialized = True
        self.collection = _Collection()
        self.retrieve_calls: list[str] = []

    def retrieve(self, query, top_k=8, **_):
        self.retrieve_calls.append(query)
        return []


def _words(n: int, seed: str = "lorem") -> str:
    return " ".join(f"{seed}{i}" for i in range(n))


def _manifest(doc_id: str, title: str, author: str, category: str, blocks: list[dict]) -> dict:
    return {"schema_version": 1, "doc_id": doc_id, "title": title, "author": author,
            "category": category, "blocks": blocks}


class GraphBuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        man_dir = os.path.join(cls.tmp, ".manifests")
        os.makedirs(man_dir)

        # Book A: Big-Book-like, with a chapter heading followed by paragraphs.
        a_blocks = [
            {"id": "a01", "type": "toc", "text": "CONTENTS", "printed_page": None},
            {"id": "a02", "type": "heading", "text": "5 HOW IT WORKS 58", "printed_page": None},  # TOC line -> dropped
            {"id": "a03", "type": "heading", "text": "HOW IT WORKS", "printed_page": 58},
            {"id": "a04", "type": "paragraph", "text": "Resentment is the number one offender. " + _words(60), "printed_page": 64},
            {"id": "a05", "type": "paragraph", "text": "We were angry and full of fear about our resentments. " + _words(60), "printed_page": 65},
            {"id": "a06", "type": "paragraph", "text": "Then we made a searching and fearless moral inventory, Step Four. " + _words(60), "printed_page": 66},
            {"id": "a07", "type": "heading", "text": "T", "printed_page": 70},  # drop cap -> dropped
            {"id": "a08", "type": "heading", "text": "INTO ACTION", "printed_page": 72},
            {"id": "a09", "type": "paragraph", "text": "We made direct amends, Step Nine, to those we had harmed. " + _words(60), "printed_page": 76},
            {"id": "a10", "type": "paragraph", "text": "Prayer and meditation improve our conscious contact with God. " + _words(60), "printed_page": 85},
            {"id": "a11", "type": "paragraph", "text": "We carry the message to the newcomer at meetings. " + _words(60), "printed_page": 89},
        ]
        with open(os.path.join(man_dir, "book-a.json"), "w") as f:
            json.dump(_manifest("book-a", "Book A", "AA", "conference_approved", a_blocks), f)

        # Book B: an "other_anonymous" book that also appears as a temp_downloads duplicate.
        b_blocks = [
            {"id": "b01", "type": "heading", "text": "Chapter One", "printed_page": 1},
            {"id": "b02", "type": "paragraph", "text": "Codependent people struggle with boundaries and fear. " + _words(60), "printed_page": 2},
            {"id": "b03", "type": "paragraph", "text": "Resentment and anger toward a spouse. " + _words(60), "printed_page": 3},
            {"id": "b04", "type": "paragraph", "text": "Letting go of control is the heart of detachment. " + _words(60), "printed_page": 4},
        ]
        with open(os.path.join(man_dir, "book-b.json"), "w") as f:
            json.dump(_manifest("book-b", "Book B", "Melody B", "other_anonymous", b_blocks), f)

        def mk(cid, blocks, text, source, doc_id, category, scale="medium", idx=0, page=None):
            return _Chunk(id=cid, text=text, source=source, chunk_index=idx, scale=scale,
                          category=category, doc_id=doc_id, block_ids=json.dumps(blocks),
                          printed_page_start=page)

        chunks = [
            mk("A_medium_0", ["a04"], a_blocks[3]["text"], "Book A - AA.pdf", "book-a", "conference_approved", page=64),
            mk("A_medium_1", ["a05"], a_blocks[4]["text"], "Book A - AA.pdf", "book-a", "conference_approved", idx=1, page=65),
            mk("A_medium_2", ["a06"], a_blocks[5]["text"], "Book A - AA.pdf", "book-a", "conference_approved", idx=2, page=66),
            mk("A_medium_3", ["a09"], a_blocks[8]["text"], "Book A - AA.pdf", "book-a", "conference_approved", idx=3, page=76),
            mk("A_medium_4", ["a10"], a_blocks[9]["text"], "Book A - AA.pdf", "book-a", "conference_approved", idx=4, page=85),
            mk("A_medium_5", ["a11"], a_blocks[10]["text"], "Book A - AA.pdf", "book-a", "conference_approved", idx=5, page=89),
            # A small-scale chunk of the same text must be ignored (medium only).
            mk("A_small_0", ["a04"], "Resentment is the number one offender.", "Book A - AA.pdf", "book-a",
               "conference_approved", scale="small"),
            # Too short to be a passage.
            mk("A_medium_short", ["a04"], "Resentment resentment.", "Book A - AA.pdf", "book-a", "conference_approved", idx=6),
            mk("B_medium_0", ["b02"], b_blocks[1]["text"], "Book B - Melody B.epub", "book-b", "other_anonymous", page=2),
            mk("B_medium_1", ["b03"], b_blocks[2]["text"], "Book B - Melody B.epub", "book-b", "other_anonymous", idx=1, page=3),
            mk("B_medium_2", ["b04"], b_blocks[3]["text"], "Book B - Melody B.epub", "book-b", "other_anonymous", idx=2, page=4),
            # Duplicate copy of Book B from temp_downloads: same block ids -> deduped.
            mk("Bdup_medium_0", ["b02"], b_blocks[1]["text"], "Book B - Melody B.epub", "book-b", "temp_downloads", page=2),
            # Excluded work.
            mk("T_medium_0", ["t01"], "Resentment " + _words(60), "trimmed-big-book.pdf", "trimmed-big-book", "conference_approved"),
        ]
        cls.retriever = _Retriever(chunks)
        cls.graph = G.GraphBuilder(cls.retriever, cls.tmp).build()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # -- taxonomy ---------------------------------------------------------

    def test_taxonomy_is_well_formed(self):
        ids = topic_ids()
        self.assertEqual(len(ids), len(set(ids)), "duplicate topic ids")
        groups = {g for g, _ in GROUPS}
        for tid, label, group, blurb, terms in TOPICS:
            self.assertIn(group, groups, tid)
            self.assertTrue(label and blurb, tid)
            self.assertTrue(terms, tid)
            for t in terms:
                self.assertIsNotNone(G._compile_term(t), f"{tid}: bad term {t!r}")

    def test_term_compilation(self):
        single = G._compile_term("resent*")
        self.assertTrue(single.wildcard)
        self.assertIsNone(single.regex)
        phrase = G._compile_term("self pity")
        self.assertIsNotNone(phrase.regex)
        self.assertTrue(phrase.regex.search("full of self-pity today"))
        self.assertTrue(phrase.regex.search("self pity"))
        self.assertFalse(phrase.regex.search("selfpity"))
        wild = G._compile_term("hungry ghost*")
        self.assertTrue(wild.regex.search("the hungry ghosts realm"))

    # -- books / passages ---------------------------------------------------

    def test_books_and_dedup(self):
        g = self.graph
        self.assertEqual(set(g.books), {"book-a", "book-b"}, "excluded work must not appear")
        self.assertEqual(g.books["book-b"].category, "other_anonymous", "prefer the categorised copy")
        self.assertNotIn("Bdup_medium_0", g.passages, "temp_downloads duplicate deduped")
        self.assertNotIn("A_small_0", g.passages, "only the graph scale is used")
        self.assertNotIn("A_medium_short", g.passages, "short chunks are not passages")
        self.assertEqual(g.books["book-a"].chunk_count, 6)
        self.assertEqual(g.books["book-b"].chunk_count, 3)

    def test_sections_filter_noise_and_map_passages(self):
        book = self.graph.books["book-a"]
        titles = [s.title for s in book.sections]
        self.assertEqual(titles, ["How It Works", "Into Action"])
        self.assertEqual(self.graph.passages["A_medium_0"].section, 0)
        self.assertEqual(self.graph.passages["A_medium_3"].section, 1)
        self.assertEqual(book.sections[0].block_id, "a03")

    def test_heading_cleanup_rules(self):
        clean = G.GraphBuilder._clean_heading
        self.assertIsNone(clean("6 BUILDING A NEW LIFE 476"))
        self.assertIsNone(clean("A"))
        self.assertIsNone(clean("—Jessica Stern, Denial"))
        self.assertIsNone(clean("Step Five. As we took inventory, we began"))
        self.assertIsNone(clean("Copyright © 1939 by Works Publishing"))
        self.assertEqual(clean("22 STEP ONE"), "Step One")
        self.assertEqual(clean("TRADITION ONE 130"), "Tradition One")
        self.assertEqual(clean("Rumbling with Grief"), "Rumbling with Grief")
        self.assertEqual(clean("PIONEERS OF A.A."), "Pioneers of A.A.")

    # -- topic matching -----------------------------------------------------

    def test_topic_hits(self):
        g = self.graph
        self.assertEqual(set(g.topic_hits["resentment"]), {"A_medium_0", "A_medium_1", "B_medium_1"})
        self.assertEqual(set(g.topic_hits["step_4"]), {"A_medium_2"})
        self.assertEqual(set(g.topic_hits["step_9"]), {"A_medium_3"})
        self.assertEqual(set(g.topic_hits["codependency"]), {"B_medium_0"})
        self.assertEqual(set(g.topic_hits["newcomers"]), {"A_medium_5"})
        self.assertEqual(g.topic_hits["resentment"]["A_medium_1"], 1)  # "resentments" via resent*

    def test_chunk_topics_are_the_junctions(self):
        # A_medium_1 mentions resentment, anger and fear -> a hop point between the three.
        ids = {t for t, _ in self.graph.chunk_topics["A_medium_1"]}
        self.assertTrue({"resentment", "anger", "fear"}.issubset(ids), ids)

    def test_edges(self):
        g = self.graph
        pairs = {(e["source"], e["target"]) for e in g.topic_edges}
        # Only pairs sharing >= 5 passages get an edge; the synthetic corpus has none.
        self.assertEqual(pairs, set())
        be = {(e["topic"], e["book"]): e for e in g.book_edges}
        self.assertIn(("resentment", "book-a"), be)
        self.assertEqual(be[("resentment", "book-a")]["count"], 2)
        self.assertNotIn(("step_4", "book-a"), be, "single-passage links are pruned from the map")

    # -- query API ------------------------------------------------------------

    def test_graph_map_shape(self):
        m = G.graph_map(self.graph)
        self.assertEqual(m["stats"]["books"], 2)
        self.assertEqual(m["stats"]["topics"], len(TOPICS))
        self.assertEqual([b["id"] for b in m["books"]], ["book-a", "book-b"])
        topic = next(t for t in m["topics"] if t["id"] == "resentment")
        self.assertEqual(topic["mentions"], 3)
        self.assertEqual(topic["books"], 2)
        self.assertEqual(topic["group"], "struggles")
        self.assertTrue(all("label" in grp for grp in m["groups"]))
        json.dumps(m)  # serialisable

    def test_topic_detail(self):
        d = G.topic_detail(self.graph, self.retriever, "resentment")
        self.assertEqual(d["topic"]["id"], "resentment")
        self.assertEqual([b["id"] for b in d["books"]], ["book-a", "book-b"], "conference literature ranks first")
        a = d["books"][0]
        self.assertEqual(a["count"], 2)
        self.assertEqual(a["sections"][0]["title"], "How It Works")
        p = a["passages"][0]
        self.assertEqual(p["doc_id"], "book-a")
        self.assertIn(p["block_ids"][0], ("a04", "a05"))
        self.assertIn("resent", p["excerpt"].lower())
        self.assertNotIn("resentment", [t["id"] for t in p["topics"]], "own topic is not listed as a hop")
        self.assertIsNone(G.topic_detail(self.graph, self.retriever, "nope"))

    def test_topic_passages_sorting_and_paging(self):
        by_score = G.topic_passages(self.graph, self.retriever, "resentment", None, sort="score", limit=10)
        self.assertEqual(by_score["total"], 3)
        by_pos = G.topic_passages(self.graph, self.retriever, "resentment", "book-a", sort="position", limit=1)
        self.assertEqual(by_pos["total"], 2)
        self.assertEqual(by_pos["passages"][0]["chunk_id"], "A_medium_0")
        page2 = G.topic_passages(self.graph, self.retriever, "resentment", "book-a", sort="position", offset=1, limit=1)
        self.assertEqual(page2["passages"][0]["chunk_id"], "A_medium_1")
        sec = G.topic_passages(self.graph, self.retriever, "resentment", "book-a", section=1)
        self.assertEqual(sec["total"], 0)

    def test_book_detail(self):
        b = G.book_detail(self.graph, "book-a")
        self.assertEqual(b["book"]["title"], "Book A")
        self.assertEqual([s["title"] for s in b["sections"]], ["How It Works", "Into Action"])
        first = b["sections"][0]
        self.assertIn("resentment", [t["id"] for t in first["topics"]])
        self.assertIn("resentment", [t["id"] for t in b["topics"]])
        self.assertIsNone(G.book_detail(self.graph, "nope"))

    def test_search_matches_topics_by_label_and_term(self):
        s = G.search(self.graph, self.retriever, "resentment")
        self.assertEqual(s["topics"][0]["id"], "resentment")
        s = G.search(self.graph, self.retriever, "my sponsor keeps telling me to pray")
        ids = [t["id"] for t in s["topics"]]
        self.assertIn("sponsorship", ids)
        self.assertIn("prayer", ids)
        self.assertEqual(self.retriever.retrieve_calls[-1], "my sponsor keeps telling me to pray")
        empty = G.search(self.graph, self.retriever, "   ")
        self.assertEqual(empty["topics"], [])
        self.assertEqual(empty["passages"], [])

    def test_search_maps_retrieval_results_onto_passages(self):
        class R:
            matched_chunk_id = "A_small_0"   # small-scale hit
            parent_id = "A_medium_0"         # its medium context
            doc_id = "book-a"
            block_ids = ["a04"]
            text = "Resentment is the number one offender."
            excerpt = "Resentment is the number one offender."
            similarity = 0.9
            source = "Book A - AA.pdf"

        class Retr(_Retriever):
            def retrieve(self, query, top_k=8, **_):
                return [R()]

        r = Retr(list(self.retriever._chunks_by_id.values()))
        s = G.search(self.graph, r, "offender")
        self.assertEqual(len(s["passages"]), 1)
        self.assertEqual(s["passages"][0]["chunk_id"], "A_medium_0")
        self.assertEqual(s["passages"][0]["similarity"], 0.9)

    def test_doc_window(self):
        w = G.doc_window(self.tmp, "book-a", ["a05"], radius=1)
        self.assertEqual(w["title"], "Book A")
        self.assertEqual(w["heading"], "How It Works")
        ids = [b["id"] for b in w["blocks"]]
        self.assertEqual(ids, ["a04", "a05", "a06"])
        self.assertEqual([b["highlight"] for b in w["blocks"]], [False, True, False])
        self.assertEqual(w["prev_block"], "a03")
        self.assertEqual(w["next_block"], "a07")
        self.assertIsNone(G.doc_window(self.tmp, "missing", ["x"]))
        self.assertNotIn("a01", [b["id"] for b in G.doc_window(self.tmp, "book-a", [], radius=50)["blocks"]],
                         "toc blocks are dropped from the reading window")

    def test_doc_window_falls_back_to_text_anchor(self):
        # Block ids from an older extraction don't exist; the passage text does.
        w = G.doc_window(self.tmp, "book-a", ["b99999"], radius=1,
                         anchor_text="…We made direct amends, Step Nine, to those we had harmed. lorem0")
        self.assertTrue(w["found"])
        self.assertEqual([b["id"] for b in w["blocks"]], ["a08", "a09", "a10"])
        self.assertTrue(w["blocks"][1]["highlight"])
        missing = G.doc_window(self.tmp, "book-a", ["b99999"], radius=1, anchor_text="text that is nowhere in the book at all")
        self.assertFalse(missing["found"])
        self.assertTrue(G.doc_window(self.tmp, "book-a", [], radius=1)["found"], "no anchor requested -> book start")

    def test_snippet_anchors_on_first_hit(self):
        text = _words(120, "filler") + " Here resentment appears late in the passage. " + _words(80, "tail")
        snip = G._snippet(text, G._compiled_terms("resentment"), max_chars=200)
        self.assertIn("resentment", snip)
        self.assertTrue(snip.startswith("…"))
        self.assertLessEqual(len(snip), 320)


class GraphServiceTest(unittest.TestCase):
    def test_service_builds_caches_and_detects_staleness(self):
        tmp = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmp, ".manifests"))
            os.environ["USER_MEMORY_DB_PATH"] = os.path.join(tmp, "mem.db")
            chunks = [_Chunk(id=f"c{i}_medium", text="Resentment and fear. " + _words(50), source="X - Y.pdf",
                             chunk_index=i, doc_id="x", block_ids=json.dumps([f"b{i}"])) for i in range(3)]
            r = _Retriever(chunks)
            svc = G.GraphService()
            self.assertIsNone(svc._graph)
            g = svc.get(r, tmp, wait=True)
            self.assertIsNotNone(g)
            self.assertEqual(svc.status()["status"], "ready")
            cache = svc._cache_path("test_collection")
            self.assertTrue(os.path.exists(cache), "graph pickled next to the BM25 cache")
            # Same corpus -> same object, no rebuild.
            self.assertIs(svc.get(r, tmp), g)
            # Corpus changed -> stale -> rebuild.
            r2 = _Retriever(chunks + [_Chunk(id="c9_medium", text="Fear " + _words(50), source="X - Y.pdf",
                                             chunk_index=9, doc_id="x", block_ids=json.dumps(["b9"]))])
            self.assertIsNone(svc.get(r2, tmp), "stale graph is not served")
            g2 = svc.get(r2, tmp, wait=True)
            self.assertIsNotNone(g2)
            self.assertEqual(g2.document_count, 4)
            # A fresh service loads the pickle instead of rebuilding.
            svc2 = G.GraphService()
            g3 = svc2.get(r2, tmp, wait=True)
            self.assertEqual(g3.document_count, 4)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
