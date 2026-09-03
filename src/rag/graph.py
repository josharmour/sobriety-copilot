"""Corpus-wide recovery knowledge graph.

Builds a navigable graph over the *entire* indexed library rather than around a
single query:

* **Topic nodes** come from the curated taxonomy in ``graph_taxonomy.py``.
* **Book nodes** are the indexed works (one per manifest ``doc_id``).
* **Section nodes** are chapter-level headings inside a book (from the
  manifest), so a topic can be followed *through* a book.
* **Passages** are the medium-scale chunks in which a topic's terms occur; each
  carries the ``doc_id`` + ``block_ids`` needed to open the reader at exactly
  that spot, plus the *other* topics that occur in the same passage — that is
  the junction the UI uses to hop from topic to topic through the literature.

Edges:

* topic — topic: co-occurrence in the same passage (cosine-normalised).
* topic — book: number of passages in the book that mention the topic.
* topic — section: same, at chapter granularity.

Matching runs against the retriever's in-memory BM25 postings so it never has
to re-tokenise the corpus: single-word terms are direct posting lookups,
wildcard terms bisect the sorted vocabulary, and multi-word phrases intersect
their tokens' postings and then verify the phrase with a regex over only those
candidate chunks. The whole graph (~55k medium chunks, ~90 topics) builds in a
few seconds and is pickled beside the BM25 cache keyed on the collection's
chunk count + TAXONOMY_VERSION.
"""

from __future__ import annotations

import bisect
import json
import math
import os
import pickle
import re
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

from src.rag.graph_taxonomy import GROUPS, TAXONOMY_VERSION, TOPICS

TOKEN_RE = re.compile(r"[A-Za-z0-9']+")
GRAPH_SCALE = os.environ.get("GRAPH_CHUNK_SCALE", "medium")
MIN_PASSAGE_WORDS = 40
# Books that duplicate another work in the corpus, or hold no readable content.
EXCLUDED_DOC_IDS = frozenset({"trimmed-big-book", "serenity-prayer"})
# temp_downloads holds duplicate copies of books that also live in a real
# category; when both exist we keep the categorised one.
DUPLICATE_CATEGORY = "temp_downloads"
CATEGORY_LABELS = {
    "conference_approved": "Conference-approved",
    "books_about_aa": "Books about A.A.",
    "related_nonfiction": "Related nonfiction",
    "other_anonymous": "Other fellowships & authors",
    "temp_downloads": "Other",
    "uncategorized": "Other",
}
# Ranking prior per category — conference literature first, as in retrieval.
CATEGORY_PRIOR = {
    "conference_approved": 1.35,
    "books_about_aa": 1.05,
    "related_nonfiction": 0.9,
    "other_anonymous": 0.95,
    "temp_downloads": 0.8,
    "uncategorized": 0.8,
}
# Manifest title/author fixes for files whose "Title - Author" name didn't
# split cleanly.
BOOK_OVERRIDES: dict[str, dict[str, str]] = {
    "recovery": {"title": "Recovery: A Guide for Adult Children of Alcoholics",
                 "author": "Herbert Gravitz & Julie Bowden"},
    "scattered-minds": {"author": "Gabor Maté"},
    "the-myth-of-normal": {"author": "Gabor Maté"},
    "in-the-realm-of-hungry-ghosts": {"author": "Gabor Maté"},
    "when-the-body-says-no": {"author": "Gabor Maté"},
    "a-quiet-peace": {"author": "Cocaine Anonymous"},
    "hope-faith-courage": {"author": "Cocaine Anonymous"},
    "touchstones": {"author": "Hazelden"},
    "the-virtue-of-selfishness": {"title": "The Virtue of Selfishness", "author": "Nathaniel Branden"},
    "the-spirituality-of-imperfection-ernest-kurtz": {"title": "The Spirituality of Imperfection",
                                                      "author": "Ernest Kurtz & Katherine Ketcham"},
    "alcoholics-anonymous": {"title": "Alcoholics Anonymous (the Big Book)", "author": "A.A. World Services"},
    "twelve-steps-and-twelve-traditions": {"title": "Twelve Steps and Twelve Traditions", "author": "A.A. World Services"},
    "narcotics-anonymous": {"title": "Narcotics Anonymous (Basic Text)", "author": "N.A. World Services"},
    "aa-preamble": {"author": "A.A. World Services"},
    "decency-code": {"author": "Unknown"},
}
# Section headings shorter than this or made of a single letter (drop caps
# mis-classified as headings) are not chapters.
_SECTION_MIN_CONTENT_BLOCKS = 3
_SECTION_MAX_PER_BOOK = 160
_DROP_CAP_RE = re.compile(r"^[\W\d]*[A-Za-z]?[\W\d]*$")
# "6 BUILDING A NEW LIFE 476" — a contents line with chapter and page numbers.
_TOC_LINE_RE = re.compile(r"^\d{1,3}\s+.+\s\d{1,4}$")
_NOISE_HEADING_RE = re.compile(
    r"copyright|©|isbn|printed in|all rights reserved|library of congress|www\.|\.com\b|"
    r"^contents$|^chapter page$|^page$|^index$|world services|\binc\.|medical association",
    re.IGNORECASE,
)
_SMALL_WORDS = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on", "or", "the", "to", "vs", "with"}


def _title_case(text: str) -> str:
    words = text.lower().split()
    out = []
    for i, w in enumerate(words):
        if i and w in _SMALL_WORDS:
            out.append(w)
        elif re.fullmatch(r"a\.a\.?|n\.a\.?|c\.a\.?|o\.a\.?", w):
            out.append(w.upper())
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)
_PAGE_HEADER_RE = re.compile(
    r"^(?:"
    r"[A-Z][A-Z\s\-\.',&]+\d+|"
    r"\d+\s+[A-Z][A-Z\s\-\.',&]+|"
    r"[\-•]\s*\w+\s+\d+\s*[\-•]"
    r")\s*\n",
)


# ── Term compilation ──────────────────────────────────────────────────────


@dataclass
class CompiledTerm:
    raw: str
    tokens: list[str]
    wildcard: bool
    regex: re.Pattern | None  # only for multi-word phrases


def _compile_term(term: str) -> CompiledTerm | None:
    t = term.strip().lower()
    wildcard = t.endswith("*")
    if wildcard:
        t = t[:-1]
    tokens = [tok for tok in TOKEN_RE.findall(t)]
    if not tokens:
        return None
    regex = None
    if len(tokens) > 1:
        parts = [re.escape(tok) for tok in tokens]
        tail = r"\w*" if wildcard else r"\b"
        regex = re.compile(r"\b" + r"\W+".join(parts[:-1]) + r"\W+" + parts[-1] + tail)
    return CompiledTerm(raw=term, tokens=tokens, wildcard=wildcard, regex=regex)


# ── Graph data ────────────────────────────────────────────────────────────


@dataclass
class Section:
    index: int
    title: str
    start: int          # block index (inclusive) in the manifest's block list
    end: int            # block index (exclusive)
    printed_page: Any = None
    block_id: str = ""  # first block id, for opening the reader


@dataclass
class Book:
    id: str
    title: str
    author: str
    category: str
    doc_id: str | None
    source: str
    chunk_count: int = 0
    sections: list[Section] = field(default_factory=list)
    block_index: dict[str, int] = field(default_factory=dict)
    section_starts: list[int] = field(default_factory=list)

    def section_for_block(self, block_id: str | None) -> int | None:
        if not block_id or not self.sections:
            return None
        idx = self.block_index.get(block_id)
        if idx is None:
            return None
        pos = bisect.bisect_right(self.section_starts, idx) - 1
        if pos < 0:
            return None
        return pos


@dataclass
class PassageMeta:
    chunk_id: str
    book_id: str
    block_ids: list[str]
    section: int | None
    words: int
    printed_page: Any
    position: int  # block index of first block, for reading order


@dataclass
class KnowledgeGraph:
    version: int
    document_count: int
    collection: str
    built_at: float
    build_seconds: float
    books: dict[str, Book]
    passages: dict[str, PassageMeta]
    topic_hits: dict[str, dict[str, int]]          # topic -> chunk_id -> hits
    topic_book_counts: dict[str, Counter]           # topic -> book_id -> passages
    topic_section_counts: dict[str, Counter]        # topic -> (book_id, section) -> passages
    topic_edges: list[dict[str, Any]]
    book_edges: list[dict[str, Any]]
    topic_stats: dict[str, dict[str, Any]]
    chunk_topics: dict[str, list[tuple[str, int]]]  # chunk_id -> [(topic, hits)] sorted


# ── Builder ───────────────────────────────────────────────────────────────


class GraphBuilder:
    """Builds a KnowledgeGraph from a warmed RAGRetriever's chunk cache."""

    def __init__(self, retriever: Any, documents_dir: str,
                 progress: Callable[[str, int], None] | None = None):
        self.retriever = retriever
        self.documents_dir = documents_dir
        self._progress = progress or (lambda *_: None)

    # -- corpus access ------------------------------------------------------

    def _chunks(self) -> dict[str, Any]:
        return getattr(self.retriever, "_chunks_by_id", {})

    def _postings(self) -> dict[str, dict[str, int]]:
        return getattr(self.retriever, "_postings", {})

    # -- books & sections ---------------------------------------------------

    @staticmethod
    def _display_title(source: str) -> tuple[str, str]:
        title = os.path.splitext(os.path.basename(source or ""))[0].replace("_", " ").strip()
        author = ""
        if " - " in title:
            title, author = (s.strip() for s in title.split(" - ", 1))
        return title, author

    def _load_manifest_meta(self, doc_id: str) -> dict[str, Any] | None:
        path = os.path.join(self.documents_dir, ".manifests", f"{doc_id}.json")
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    @staticmethod
    def _clean_heading(raw: str) -> str | None:
        """Normalise a manifest heading into a chapter title, or None if it's noise."""
        text = re.sub(r"\s+", " ", (raw or "")).strip()
        if len(text) < 3 or _DROP_CAP_RE.match(text):
            return None
        if _TOC_LINE_RE.match(text) or _NOISE_HEADING_RE.search(text):
            return None
        # Epigraph attributions ("—Jessica Stern"), index lines ("Step Twelve and, 50–52"),
        # and sentence fragments that begin mid-sentence in lowercase.
        if text[0] in "—–-" or not (text[0].isupper() or text[0].isdigit() or text[0] in "“\"'"):
            return None
        if re.search(r"\d+\s*[–-]\s*\d+$", text):
            return None
        # Sentence fragments mis-tagged as headings ("Step Five. As we took…").
        if ". " in text and not re.search(r"\b[A-Z]\.\s?[A-Z]\.", text):
            return None
        if text.endswith((")", ",", ";")) or (text.endswith(".") and not re.search(r"[A-Z]\.[A-Z]\.$", text)):
            return None
        # Running-header page numbers: "22 STEP ONE" / "STEP ONE 22".
        text = re.sub(r"^\d{1,4}\s+(?=[A-Za-z“\"'])", "", text)
        text = re.sub(r"(?<=[A-Za-z.!?’'\"”])\s+\d{1,4}$", "", text)
        if len(text) < 3 or not re.search(r"[A-Za-z]{2}", text):
            return None
        if text.isupper():
            text = _title_case(text)
        if len(text) > 80:
            text = text[:77].rstrip() + "…"
        return text

    @staticmethod
    def _sections_from_blocks(blocks: list[dict[str, Any]]) -> tuple[list[Section], dict[str, int]]:
        block_index = {b.get("id"): i for i, b in enumerate(blocks) if b.get("id")}
        heads: list[tuple[int, str, Any, str]] = []
        for i, b in enumerate(blocks):
            if b.get("type") != "heading":
                continue
            text = GraphBuilder._clean_heading(b.get("text") or "")
            if text is None:
                continue
            # Count substantive blocks until the next heading.
            n = 0
            j = i + 1
            while j < len(blocks) and blocks[j].get("type") != "heading":
                if blocks[j].get("type") in ("paragraph", "epigraph", "list"):
                    n += 1
                j += 1
            if n < _SECTION_MIN_CONTENT_BLOCKS:
                continue
            heads.append((i, text, b.get("printed_page"), b.get("id") or ""))
        sections: list[Section] = []
        for k, (start, title, page, bid) in enumerate(heads):
            end = heads[k + 1][0] if k + 1 < len(heads) else len(blocks)
            sections.append(Section(index=k, title=title, start=start, end=end, printed_page=page, block_id=bid))
        if len(sections) > _SECTION_MAX_PER_BOOK:
            # Keep the longest sections so daily-reader books (one heading per
            # day) collapse to something navigable.
            keep = sorted(sections, key=lambda s: s.end - s.start, reverse=True)[:_SECTION_MAX_PER_BOOK]
            keep.sort(key=lambda s: s.start)
            for k, s in enumerate(keep):
                s.index = k
                s.end = keep[k + 1].start if k + 1 < len(keep) else len(blocks)
            sections = keep
        return sections, block_index

    def _build_books(self, chunk_ids: list[str]) -> tuple[dict[str, Book], dict[str, str]]:
        """Returns (books, chunk_id -> book_id). Chunks of excluded/duplicate works map to nothing."""
        chunks = self._chunks()
        by_key: dict[str, list[Any]] = defaultdict(list)
        for cid in chunk_ids:
            c = chunks[cid]
            key = c.doc_id or f"src:{c.source}"
            by_key[key].append(c)

        books: dict[str, Book] = {}
        chunk_book: dict[str, str] = {}
        for key, group in by_key.items():
            sample = group[0]
            doc_id = sample.doc_id
            if doc_id in EXCLUDED_DOC_IDS:
                continue
            book_id = doc_id or re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")
            title, author = self._display_title(sample.source)
            category = Counter(c.category for c in group).most_common(1)[0][0]
            cats = {c.category for c in group}
            if DUPLICATE_CATEGORY in cats and len(cats) > 1:
                category = next(c for c in cats if c != DUPLICATE_CATEGORY)
            sections: list[Section] = []
            block_index: dict[str, int] = {}
            if doc_id:
                manifest = self._load_manifest_meta(doc_id)
                if manifest:
                    title = manifest.get("title") or title
                    author = manifest.get("author") or author
                    category = manifest.get("category") or category
                    if category == DUPLICATE_CATEGORY and len(cats) > 1:
                        category = next(c for c in cats if c != DUPLICATE_CATEGORY)
                    sections, block_index = self._sections_from_blocks(manifest.get("blocks", []))
            override = BOOK_OVERRIDES.get(book_id, {})
            title = override.get("title", title)
            author = override.get("author", author)
            if author.lower() in ("unknown", ""):
                author = ""
            book = Book(
                id=book_id, title=title, author=author, category=category, doc_id=doc_id,
                source=sample.source, sections=sections, block_index=block_index,
                section_starts=[s.start for s in sections],
            )
            books[book_id] = book
            # Dedupe duplicate copies of the same passage (temp_downloads).
            seen: set[str] = set()
            preferred = sorted(group, key=lambda c: c.category == DUPLICATE_CATEGORY)
            for c in preferred:
                sig = c.block_ids or f"{c.chunk_index}:{c.text[:120]}"
                if sig in seen:
                    continue
                seen.add(sig)
                chunk_book[c.id] = book_id
        return books, chunk_book

    # -- term matching ------------------------------------------------------

    def _vocab(self) -> list[str]:
        if not hasattr(self, "_sorted_vocab"):
            self._sorted_vocab = sorted(self._postings().keys())
        return self._sorted_vocab

    def _tokens_for(self, token: str, wildcard: bool) -> list[str]:
        if not wildcard:
            return [token] if token in self._postings() else []
        vocab = self._vocab()
        lo = bisect.bisect_left(vocab, token)
        out: list[str] = []
        for i in range(lo, len(vocab)):
            if not vocab[i].startswith(token):
                break
            out.append(vocab[i])
        return out

    def _term_hits(self, term: CompiledTerm, eligible: dict[str, str]) -> dict[str, int]:
        """chunk_id -> hit count for one term, restricted to `eligible` chunk ids."""
        postings = self._postings()
        hits: dict[str, int] = {}
        if term.regex is None:
            for tok in self._tokens_for(term.tokens[0], term.wildcard):
                for cid, tf in postings.get(tok, {}).items():
                    if cid in eligible:
                        hits[cid] = hits.get(cid, 0) + tf
            return hits
        # Phrase: intersect candidate sets, then verify.
        candidate_sets: list[set[str]] = []
        for i, tok in enumerate(term.tokens):
            toks = self._tokens_for(tok, term.wildcard and i == len(term.tokens) - 1)
            s: set[str] = set()
            for t in toks:
                s.update(cid for cid in postings.get(t, {}) if cid in eligible)
            if not s:
                return {}
            candidate_sets.append(s)
        candidates = set.intersection(*candidate_sets)
        chunks = self._chunks()
        for cid in candidates:
            n = len(term.regex.findall(chunks[cid].text.lower()))
            if n:
                hits[cid] = n
        return hits

    # -- build --------------------------------------------------------------

    def build(self) -> KnowledgeGraph:
        t0 = time.monotonic()
        chunks = self._chunks()
        self._progress("scanning corpus", 5)
        scale_ids = [cid for cid, c in chunks.items() if c.scale == GRAPH_SCALE]
        if not scale_ids:  # legacy single-scale corpus
            scale_ids = list(chunks.keys())

        books, chunk_book = self._build_books(scale_ids)
        self._progress("indexing books", 15)

        passages: dict[str, PassageMeta] = {}
        for cid, book_id in chunk_book.items():
            c = chunks[cid]
            words = len(c.text.split())
            if words < MIN_PASSAGE_WORDS:
                continue
            try:
                block_ids = json.loads(c.block_ids) if c.block_ids else []
            except Exception:
                block_ids = []
            book = books[book_id]
            first = block_ids[0] if block_ids else None
            position = book.block_index.get(first, c.chunk_index) if first else c.chunk_index
            passages[cid] = PassageMeta(
                chunk_id=cid, book_id=book_id, block_ids=block_ids,
                section=book.section_for_block(first), words=words,
                printed_page=c.printed_page_start, position=position,
            )
        eligible = {cid: p.book_id for cid, p in passages.items()}

        topic_hits: dict[str, dict[str, int]] = {}
        total = len(TOPICS)
        for n, (tid, _label, _group, _blurb, terms) in enumerate(TOPICS):
            hits: dict[str, int] = {}
            for raw in terms:
                term = _compile_term(raw)
                if term is None:
                    continue
                for cid, k in self._term_hits(term, eligible).items():
                    hits[cid] = hits.get(cid, 0) + k
            topic_hits[tid] = hits
            self._progress(f"matching {_label}", 15 + int(70 * (n + 1) / total))

        self._progress("linking", 88)
        chunk_topics: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for tid, hits in topic_hits.items():
            for cid, k in hits.items():
                chunk_topics[cid].append((tid, k))
        for cid in chunk_topics:
            chunk_topics[cid].sort(key=lambda x: -x[1])

        topic_book_counts: dict[str, Counter] = {}
        topic_section_counts: dict[str, Counter] = {}
        for tid, hits in topic_hits.items():
            bc: Counter = Counter()
            sc: Counter = Counter()
            for cid in hits:
                p = passages[cid]
                bc[p.book_id] += 1
                if p.section is not None:
                    sc[(p.book_id, p.section)] += 1
            topic_book_counts[tid] = bc
            topic_section_counts[tid] = sc

        # Topic-topic co-occurrence, cosine normalised.
        pair_counts: Counter = Counter()
        for cid, tl in chunk_topics.items():
            ids = [t for t, _ in tl]
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    a, b = sorted((ids[i], ids[j]))
                    pair_counts[(a, b)] += 1
        topic_edges: list[dict[str, Any]] = []
        sizes = {tid: len(h) for tid, h in topic_hits.items()}
        n_pass = max(len(passages), 1)
        for (a, b), shared in pair_counts.items():
            if shared < 5 or not sizes[a] or not sizes[b]:
                continue
            # Normalised pointwise mutual information: +1 = always together,
            # 0 = independent. Unlike raw co-occurrence it doesn't let the
            # biggest topics become everyone's nearest neighbour.
            p_ab = shared / n_pass
            p_a = sizes[a] / n_pass
            p_b = sizes[b] / n_pass
            pmi = math.log(p_ab / (p_a * p_b))
            npmi = pmi / (-math.log(p_ab))
            if npmi <= 0.02:
                continue
            topic_edges.append({"source": a, "target": b, "shared": shared, "weight": round(npmi, 4)})
        topic_edges.sort(key=lambda e: -e["weight"])

        # Topic-book edges, density-weighted (passages per 100 book passages).
        book_passage_counts: Counter = Counter(p.book_id for p in passages.values())
        book_edges: list[dict[str, Any]] = []
        for tid, bc in topic_book_counts.items():
            for book_id, count in bc.items():
                if count < 2:
                    continue
                density = 100.0 * count / max(book_passage_counts[book_id], 1)
                book_edges.append({"topic": tid, "book": book_id, "count": count, "density": round(density, 2)})

        topic_stats: dict[str, dict[str, Any]] = {}
        for tid, _label, _group, _blurb, _terms in TOPICS:
            topic_stats[tid] = {
                "mentions": sizes[tid],
                "books": len(topic_book_counts[tid]),
            }

        for book_id in list(books):
            books[book_id].chunk_count = book_passage_counts.get(book_id, 0)
            if books[book_id].chunk_count == 0:
                del books[book_id]

        self._progress("done", 100)
        return KnowledgeGraph(
            version=TAXONOMY_VERSION,
            document_count=len(chunks),
            collection=getattr(getattr(self.retriever, "collection", None), "name", "") or "",
            built_at=time.time(),
            build_seconds=round(time.monotonic() - t0, 2),
            books=books,
            passages=passages,
            topic_hits=topic_hits,
            topic_book_counts=topic_book_counts,
            topic_section_counts=topic_section_counts,
            topic_edges=topic_edges,
            book_edges=book_edges,
            topic_stats=topic_stats,
            chunk_topics=dict(chunk_topics),
        )


# ── Cache / lifecycle ─────────────────────────────────────────────────────


def _cache_dir() -> str:
    cache_dir = "/home/app/memory"
    if not os.path.exists(cache_dir):
        cache_dir = os.path.dirname(os.environ.get("USER_MEMORY_DB_PATH", "/tmp")) or "/tmp"
    return cache_dir


class GraphService:
    """Owns the singleton graph, its background build, and the pickle cache."""

    def __init__(self) -> None:
        self._graph: KnowledgeGraph | None = None
        self._lock = threading.Lock()
        self._building = False
        self._status = "idle"
        self._progress = 0
        self._error: str | None = None
        self._thread: threading.Thread | None = None

    # -- state ------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        g = self._graph
        return {
            "status": "ready" if g else self._status,
            "progress": 100 if g else self._progress,
            "error": self._error,
            "built_at": g.built_at if g else None,
            "build_seconds": g.build_seconds if g else None,
            "document_count": g.document_count if g else None,
            "version": TAXONOMY_VERSION,
        }

    def _cache_path(self, collection: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", collection or "default")
        return os.path.join(_cache_dir(), f"graph_cache_{safe}.pkl")

    def _is_current(self, retriever: Any) -> bool:
        g = self._graph
        if g is None:
            return False
        count = len(getattr(retriever, "_chunks_by_id", {}))
        coll = getattr(getattr(retriever, "collection", None), "name", "") or ""
        return g.version == TAXONOMY_VERSION and g.document_count == count and (not coll or g.collection == coll)

    def get(self, retriever: Any, documents_dir: str, wait: bool = False) -> KnowledgeGraph | None:
        """Return the graph, kicking off a (background) build if it is missing or stale."""
        if self._is_current(retriever):
            return self._graph
        self.ensure_building(retriever, documents_dir)
        if wait and self._thread is not None:
            self._thread.join()
        return self._graph if self._is_current(retriever) else None

    def ensure_building(self, retriever: Any, documents_dir: str) -> None:
        with self._lock:
            if self._building:
                return
            self._building = True
            self._status = "building"
            self._progress = 0
            self._error = None
            self._thread = threading.Thread(
                target=self._build, args=(retriever, documents_dir), daemon=True, name="graph-build",
            )
            self._thread.start()

    def _set_progress(self, message: str, pct: int) -> None:
        self._status = f"building: {message}"
        self._progress = pct

    def _build(self, retriever: Any, documents_dir: str) -> None:
        try:
            if not getattr(retriever, "_cache_initialized", False) and hasattr(retriever, "refresh_cache"):
                self._set_progress("loading keyword cache", 1)
                retriever.refresh_cache()
            coll = getattr(getattr(retriever, "collection", None), "name", "") or ""
            count = len(getattr(retriever, "_chunks_by_id", {}))
            path = self._cache_path(coll)
            graph: KnowledgeGraph | None = None
            if os.path.exists(path):
                try:
                    with open(path, "rb") as f:
                        cached = pickle.load(f)
                    if (
                        isinstance(cached, KnowledgeGraph)
                        and cached.version == TAXONOMY_VERSION
                        and cached.document_count == count
                    ):
                        graph = cached
                        print(f"[GRAPH] loaded cache {path} ({count} chunks)", flush=True)
                except Exception as exc:
                    print(f"[GRAPH] cache load failed: {exc}", flush=True)
            if graph is None:
                graph = GraphBuilder(retriever, documents_dir, progress=self._set_progress).build()
                try:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "wb") as f:
                        pickle.dump(graph, f, protocol=pickle.HIGHEST_PROTOCOL)
                except Exception as exc:
                    print(f"[GRAPH] cache save failed: {exc}", flush=True)
                print(f"[GRAPH] built in {graph.build_seconds}s: {len(graph.books)} books, "
                      f"{len(graph.passages)} passages", flush=True)
            self._graph = graph
            self._status = "ready"
            self._progress = 100
        except Exception as exc:  # pragma: no cover - defensive
            self._error = f"{type(exc).__name__}: {exc}"
            self._status = "error"
            print(f"[GRAPH] build failed: {self._error}", flush=True)
        finally:
            self._building = False


graph_service = GraphService()


# ── Query API (pure functions over a built graph) ─────────────────────────


_TOPIC_BY_ID = {t[0]: t for t in TOPICS}


def _topic_node(tid: str, g: KnowledgeGraph) -> dict[str, Any]:
    _id, label, group, blurb, _terms = _TOPIC_BY_ID[tid]
    st = g.topic_stats.get(tid, {})
    return {"id": tid, "label": label, "group": group, "blurb": blurb,
            "mentions": st.get("mentions", 0), "books": st.get("books", 0)}


def _book_node(book: Book, g: KnowledgeGraph) -> dict[str, Any]:
    return {
        "id": book.id, "title": book.title, "author": book.author,
        "category": book.category, "category_label": CATEGORY_LABELS.get(book.category, "Other"),
        "doc_id": book.doc_id, "passages": book.chunk_count, "sections": len(book.sections),
    }


def _strip_headers(text: str) -> str:
    out = text
    for _ in range(3):
        new = _PAGE_HEADER_RE.sub("", out, count=1)
        if new == out:
            break
        out = new
    return out.strip()


def _snippet(text: str, terms: list[CompiledTerm], max_chars: int = 420) -> str:
    """A readable window around the first topic-term hit, snapped to sentences."""
    clean = re.sub(r"\s+", " ", _strip_headers(text)).strip()
    if len(clean) <= max_chars:
        return clean
    low = clean.lower()
    anchor = -1
    for term in terms:
        if term.regex is not None:
            m = term.regex.search(low)
            if m:
                anchor = m.start()
                break
        else:
            pat = re.compile(r"\b" + re.escape(term.tokens[0]) + (r"\w*" if term.wildcard else r"\b"))
            m = pat.search(low)
            if m:
                anchor = m.start()
                break
    if anchor < 0:
        anchor = 0
    start = max(0, anchor - max_chars // 3)
    end = min(len(clean), start + max_chars)
    # Snap to sentence boundaries where possible.
    if start > 0:
        s = clean.rfind(". ", start - 80, start + 80)
        if s >= 0:
            start = s + 2
    if end < len(clean):
        e = clean.find(". ", end - 80, end + 80)
        if e >= 0:
            end = e + 1
    snippet = clean[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(clean):
        snippet = snippet + "…"
    return snippet


def _compiled_terms(tid: str) -> list[CompiledTerm]:
    terms = _TOPIC_BY_ID[tid][4]
    out = []
    for raw in terms:
        t = _compile_term(raw)
        if t:
            out.append(t)
    return out


def _passage_score(g: KnowledgeGraph, tid: str, cid: str) -> float:
    p = g.passages[cid]
    hits = g.topic_hits[tid].get(cid, 0)
    density = hits / math.sqrt(max(p.words, 1))
    book = g.books[p.book_id]
    prior = CATEGORY_PRIOR.get(book.category, 0.8)
    # Prefer passages that are *about* the topic (several hits) but not
    # enumerations of it (very high hit counts in short text).
    return min(density, 2.5) * prior * (1.0 + 0.15 * min(hits, 6))


def passage_payload(g: KnowledgeGraph, retriever: Any, tid: str | None, cid: str,
                    terms: list[CompiledTerm] | None = None) -> dict[str, Any]:
    p = g.passages[cid]
    book = g.books[p.book_id]
    chunk = retriever._chunks_by_id.get(cid)
    text = chunk.text if chunk else ""
    section = book.sections[p.section] if p.section is not None and p.section < len(book.sections) else None
    others = [
        {"id": t, "label": _TOPIC_BY_ID[t][1], "group": _TOPIC_BY_ID[t][2], "hits": k}
        for t, k in g.chunk_topics.get(cid, [])
        if t != tid
    ][:8]
    return {
        "chunk_id": cid,
        "book_id": book.id,
        "book_title": book.title,
        "doc_id": book.doc_id,
        "block_ids": p.block_ids,
        "section": section.title if section else None,
        "section_index": p.section,
        "printed_page": p.printed_page,
        "words": p.words,
        "hits": g.topic_hits[tid].get(cid, 0) if tid else 0,
        "excerpt": _snippet(text, terms if terms is not None else (_compiled_terms(tid) if tid else [])),
        "topics": others,
    }


def graph_map(g: KnowledgeGraph, max_topic_edges_per_node: int = 6,
              max_books_per_topic: int = 12) -> dict[str, Any]:
    """The whole-corpus overview: every topic, every book, pruned edges."""
    topics = [_topic_node(t[0], g) for t in TOPICS]

    # Keep the strongest N topic edges per node (union).
    keep: set[tuple[str, str]] = set()
    per_node: Counter = Counter()
    for e in g.topic_edges:  # already sorted by weight desc
        a, b = e["source"], e["target"]
        if per_node[a] < max_topic_edges_per_node or per_node[b] < max_topic_edges_per_node:
            keep.add((a, b))
            per_node[a] += 1
            per_node[b] += 1
    topic_edges = [e for e in g.topic_edges if (e["source"], e["target"]) in keep]

    # Books: top topics for each, and top books for each topic.
    by_topic: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_book: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in g.book_edges:
        by_topic[e["topic"]].append(e)
        by_book[e["book"]].append(e)
    book_edges: list[dict[str, Any]] = []
    for tid, edges in by_topic.items():
        edges.sort(key=lambda e: (-e["count"], -e["density"]))
        book_edges.extend(edges[:max_books_per_topic])
    books = []
    for book in sorted(g.books.values(), key=lambda b: b.title.lower()):
        tops = sorted(by_book.get(book.id, []), key=lambda e: -e["density"])[:6]
        node = _book_node(book, g)
        node["top_topics"] = [e["topic"] for e in tops]
        books.append(node)

    return {
        "version": g.version,
        "built_at": g.built_at,
        "stats": {
            "topics": len(topics),
            "books": len(books),
            "passages": len(g.passages),
            "chunks": g.document_count,
        },
        "groups": [{"id": gid, "label": label} for gid, label in GROUPS],
        "categories": [{"id": k, "label": v} for k, v in CATEGORY_LABELS.items() if k != "uncategorized"],
        "topics": topics,
        "books": books,
        "topic_edges": topic_edges,
        "book_edges": book_edges,
    }


def related_topics(g: KnowledgeGraph, tid: str, limit: int = 10) -> list[dict[str, Any]]:
    out = []
    for e in g.topic_edges:
        if e["source"] == tid:
            other = e["target"]
        elif e["target"] == tid:
            other = e["source"]
        else:
            continue
        node = _topic_node(other, g)
        node["weight"] = e["weight"]
        node["shared"] = e["shared"]
        out.append(node)
        if len(out) >= limit:
            break
    return out


def topic_detail(g: KnowledgeGraph, retriever: Any, tid: str,
                 max_books: int = 14, passages_per_book: int = 3) -> dict[str, Any] | None:
    if tid not in _TOPIC_BY_ID:
        return None
    terms = _compiled_terms(tid)
    hits = g.topic_hits.get(tid, {})
    scored = sorted(hits, key=lambda cid: -_passage_score(g, tid, cid))

    per_book: dict[str, list[str]] = defaultdict(list)
    for cid in scored:
        bid = g.passages[cid].book_id
        if len(per_book[bid]) < passages_per_book:
            per_book[bid].append(cid)

    books_out = []
    counts = g.topic_book_counts.get(tid, Counter())
    ranked_books = sorted(
        counts.items(),
        key=lambda kv: -(kv[1] * CATEGORY_PRIOR.get(g.books[kv[0]].category, 0.8)),
    )
    for book_id, count in ranked_books[:max_books]:
        book = g.books[book_id]
        node = _book_node(book, g)
        node["count"] = count
        node["density"] = round(100.0 * count / max(book.chunk_count, 1), 2)
        sec_counts = [
            (s, n) for (b, s), n in g.topic_section_counts.get(tid, Counter()).items() if b == book_id
        ]
        sec_counts.sort(key=lambda x: -x[1])
        node["sections"] = [
            {"index": s, "title": book.sections[s].title, "count": n,
             "printed_page": book.sections[s].printed_page, "block_id": book.sections[s].block_id}
            for s, n in sec_counts[:5] if s < len(book.sections)
        ]
        node["passages"] = [passage_payload(g, retriever, tid, cid, terms) for cid in per_book.get(book_id, [])]
        books_out.append(node)

    return {
        "topic": _topic_node(tid, g),
        "related": related_topics(g, tid),
        "books": books_out,
        "total_books": len(counts),
    }


def topic_passages(g: KnowledgeGraph, retriever: Any, tid: str, book_id: str | None,
                   sort: str = "score", offset: int = 0, limit: int = 20,
                   section: int | None = None) -> dict[str, Any] | None:
    if tid not in _TOPIC_BY_ID:
        return None
    terms = _compiled_terms(tid)
    hits = g.topic_hits.get(tid, {})
    cids = [cid for cid in hits if (book_id is None or g.passages[cid].book_id == book_id)
            and (section is None or g.passages[cid].section == section)]
    if sort == "position":
        cids.sort(key=lambda cid: (g.passages[cid].book_id, g.passages[cid].position))
    else:
        cids.sort(key=lambda cid: -_passage_score(g, tid, cid))
    total = len(cids)
    page = cids[offset: offset + limit]
    return {
        "topic": _topic_node(tid, g),
        "book": _book_node(g.books[book_id], g) if book_id and book_id in g.books else None,
        "sort": sort,
        "offset": offset,
        "total": total,
        "passages": [passage_payload(g, retriever, tid, cid, terms) for cid in page],
    }


def book_detail(g: KnowledgeGraph, book_id: str, max_topics: int = 24) -> dict[str, Any] | None:
    book = g.books.get(book_id)
    if book is None:
        return None
    topics = []
    for e in g.book_edges:
        if e["book"] != book_id:
            continue
        node = _topic_node(e["topic"], g)
        node["count"] = e["count"]
        node["density"] = e["density"]
        topics.append(node)
    topics.sort(key=lambda t: -t["density"])
    # Sections with their dominant topics.
    sec_topics: dict[int, Counter] = defaultdict(Counter)
    for tid, sc in g.topic_section_counts.items():
        for (b, s), n in sc.items():
            if b == book_id:
                sec_topics[s][tid] += n
    sections = []
    for s in book.sections:
        tops = sec_topics.get(s.index, Counter()).most_common(4)
        sections.append({
            "index": s.index, "title": s.title, "printed_page": s.printed_page, "block_id": s.block_id,
            "blocks": s.end - s.start,
            "topics": [{"id": t, "label": _TOPIC_BY_ID[t][1], "group": _TOPIC_BY_ID[t][2], "count": n}
                       for t, n in tops],
        })
    return {"book": _book_node(book, g), "topics": topics[:max_topics], "sections": sections}


def search(g: KnowledgeGraph, retriever: Any, query: str, top_k: int = 10) -> dict[str, Any]:
    """Free-text entry point: matching topics + semantically retrieved passages tagged with topics."""
    q = (query or "").strip()
    ql = q.lower()
    topics = []
    if ql:
        for tid, label, group, blurb, terms in TOPICS:
            score = 0.0
            if ql == label.lower():
                score = 3.0
            elif ql in label.lower() or label.lower() in ql:
                score = 2.0
            else:
                for raw in terms:
                    t = raw.rstrip("*").lower()
                    if len(t) >= 4 and (t in ql or (ql in t and len(ql) >= 4)):
                        score = max(score, 1.0)
            if score:
                node = _topic_node(tid, g)
                node["score"] = score
                topics.append(node)
        topics.sort(key=lambda t: (-t["score"], -t["mentions"]))

    passages: list[dict[str, Any]] = []
    topic_votes: Counter = Counter()
    if ql and retriever is not None:
        try:
            results = retriever.retrieve(q, top_k=top_k)
        except Exception:
            results = []
        for r in results:
            # RetrievalResult may match at any scale; map it onto the graph's
            # medium-scale passage covering the same spot in the book.
            cid = _locate_passage(g, retriever, r)
            if cid is None:
                continue
            payload = passage_payload(g, retriever, None, cid, [])
            payload["excerpt"] = re.sub(r"\s+", " ", (getattr(r, "excerpt", "") or payload["excerpt"])).strip()
            payload["similarity"] = round(float(getattr(r, "similarity", 0.0)), 3)
            passages.append(payload)
            for t in payload["topics"][:4]:
                topic_votes[t["id"]] += 1
    suggested = [dict(_topic_node(t, g), votes=n) for t, n in topic_votes.most_common(8)
                 if t not in {x["id"] for x in topics}]
    return {"query": q, "topics": topics[:8], "suggested_topics": suggested, "passages": passages}


def _locate_passage(g: KnowledgeGraph, retriever: Any, result: Any) -> str | None:
    """Map a RetrievalResult (any scale) onto the graph's passage for that spot."""
    chunks = retriever._chunks_by_id
    # 1. The result's own id / parents, if exposed.
    for attr in ("matched_chunk_id", "parent_id", "chunk_id", "context_parent_id", "topic_parent_id"):
        cid = getattr(result, attr, None)
        if cid and cid in g.passages:
            return cid
    # 2. Same book + overlapping block ids.
    doc_id = getattr(result, "doc_id", None)
    block_ids = getattr(result, "block_ids", None) or []
    if doc_id and block_ids:
        wanted = set(block_ids)
        best = None
        for cid, p in g.passages.items():
            if g.books[p.book_id].doc_id != doc_id:
                continue
            if wanted.intersection(p.block_ids):
                best = cid
                break
        if best:
            return best
    # 3. Text-prefix match within the same source.
    text = (getattr(result, "text", "") or "")[:80]
    source = getattr(result, "source", "")
    if text:
        for cid, p in g.passages.items():
            c = chunks.get(cid)
            if c is not None and c.source == source and text in c.text:
                return cid
    return None


def _find_block_by_text(blocks: list[dict[str, Any]], anchor_text: str) -> int | None:
    """Locate a block by a prefix of the passage text (fallback when block ids
    come from an older extraction than the current manifest)."""
    needle = re.sub(r"\s+", " ", (anchor_text or "")).strip().lstrip("…. ").lower()
    if len(needle) < 20:
        return None
    for length in (80, 50, 32):
        probe = needle[:length]
        if len(probe) < 20:
            continue
        for i, b in enumerate(blocks):
            text = re.sub(r"\s+", " ", b.get("text") or "").lower()
            if probe in text:
                return i
    return None


def doc_window(documents_dir: str, doc_id: str, block_ids: list[str], radius: int = 10,
               max_blocks: int = 80, anchor_text: str | None = None) -> dict[str, Any] | None:
    """A JSON reading window around the given blocks (for the in-app passage reader)."""
    path = os.path.join(documents_dir, ".manifests", f"{doc_id}.json")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    blocks = [b for b in manifest.get("blocks", [])
              if b.get("type") not in ("page_header", "page_footer", "garbage", "toc", "index")]
    if not blocks:
        return None
    wanted = set(block_ids)
    idxs = [i for i, b in enumerate(blocks) if b.get("id") in wanted]
    if not idxs and anchor_text:
        hit = _find_block_by_text(blocks, anchor_text)
        if hit is not None:
            idxs = [hit]
            wanted = {blocks[hit].get("id")}
    if idxs:
        start = max(0, min(idxs) - radius)
        end = min(len(blocks), max(idxs) + radius + 1)
    else:
        start, end = 0, min(len(blocks), 2 * radius + 1)
    if end - start > max_blocks:
        end = start + max_blocks
    # Nearest *real* chapter heading above the window for context (skips
    # drop-caps, contents lines and other mis-tagged headings).
    heading = None
    for i in range(min(idxs) if idxs else start, -1, -1):
        if blocks[i].get("type") == "heading":
            cleaned = GraphBuilder._clean_heading(blocks[i].get("text") or "")
            if cleaned:
                heading = cleaned
                break
    out_blocks = []
    for b in blocks[start:end]:
        out_blocks.append({
            "id": b.get("id"), "type": b.get("type"), "text": b.get("text", ""),
            "printed_page": b.get("printed_page"),
            "highlight": b.get("id") in wanted,
        })
    override = BOOK_OVERRIDES.get(doc_id, {})
    return {
        "doc_id": doc_id,
        "title": override.get("title", manifest.get("title") or doc_id),
        "author": override.get("author", manifest.get("author") or ""),
        # False when none of the requested block ids exist in this manifest
        # (an index built against a different extraction) — the client then
        # shows its excerpt instead of pretending the book starts here.
        "found": bool(idxs) or not wanted,
        "heading": heading,
        "start": start,
        "end": end,
        "total": len(blocks),
        "prev_block": blocks[start - 1].get("id") if start > 0 else None,
        "next_block": blocks[end].get("id") if end < len(blocks) else None,
        "blocks": out_blocks,
    }


# ── Legacy per-query graph (kept for older mobile builds) ─────────────────


CORE_RECOVERY_NODES = [
    {"id": "step_1", "label": "Step 1: Powerlessness & Honesty", "type": "step", "category": "surrender"},
    {"id": "step_2", "label": "Step 2: Hope & Higher Power", "type": "step", "category": "hope"},
    {"id": "step_3", "label": "Step 3: Surrender & Trust", "type": "step", "category": "surrender"},
    {"id": "step_4", "label": "Step 4: Fourth-Step Inventory", "type": "step", "category": "inventory"},
    {"id": "step_5", "label": "Step 5: Confession & Integrity", "type": "step", "category": "inventory"},
    {"id": "step_6", "label": "Step 6: Willingness to Change", "type": "step", "category": "defects"},
    {"id": "step_7", "label": "Step 7: Humility & Seventh Step Prayer", "type": "step", "category": "defects"},
    {"id": "step_8", "label": "Step 8: List of Amends", "type": "step", "category": "amends"},
    {"id": "step_9", "label": "Step 9: Direct Restitution & Amends", "type": "step", "category": "amends"},
    {"id": "step_10", "label": "Step 10: Daily Spot-Check Inventory", "type": "step", "category": "maintenance"},
    {"id": "step_11", "label": "Step 11: Prayer & Morning Meditation", "type": "step", "category": "maintenance"},
    {"id": "step_12", "label": "Step 12: Service & Spiritual Awakening", "type": "step", "category": "service"},
]

RECOVERY_TERMS = [
    "willingness", "amends", "resentment", "surrender", "rigorous honesty",
    "higher power", "inventory", "acceptance", "fellowship", "sponsorship",
    "serenity", "fear", "defects of character", "spiritual awakening", "prayer",
    "meditation", "daily reflections", "big book", "twelve steps", "restitution",
]


def build_knowledge_graph(query: str, retriever: Any | None = None) -> dict[str, Any]:
    """Legacy node-and-edge graph centred on `query` (pre-2026-09 mobile builds)."""
    q = (query or "The Twelve Steps").strip()
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()

    central_id = f"term_{q.lower().replace(' ', '_')}"
    nodes.append({"id": central_id, "label": q, "type": "query", "category": "central"})
    node_ids.add(central_id)

    results = retriever.retrieve(q, top_k=6) if retriever else []

    for idx, res in enumerate(results):
        source_clean = os.path.splitext(os.path.basename(res.source))[0].replace("_", " ")
        if " - " in source_clean:
            source_clean = source_clean.split(" - ", 1)[0]
        if source_clean.lower() == "trimmed-big-book":
            source_clean = "Alcoholics Anonymous"

        passage_id = f"passage_{hash(res.source + str(idx)) & 0xFFFFFF}"
        excerpt_clean = re.sub(r"\s+", " ", res.excerpt[:80]).strip()

        if passage_id not in node_ids:
            nodes.append({
                "id": passage_id,
                "label": f"{source_clean}: {excerpt_clean}...",
                "type": "passage",
                "source": source_clean,
                "category": "literature",
                "excerpt": res.excerpt[:250],
            })
            node_ids.add(passage_id)

        edges.append({"source": central_id, "target": passage_id, "label": f"cite ({int(res.similarity * 100)}%)"})

        excerpt_lower = res.excerpt.lower()
        matched_terms = [t for t in RECOVERY_TERMS if t in excerpt_lower and t != q.lower()][:3]
        for term in matched_terms:
            t_id = f"term_{term.replace(' ', '_')}"
            if t_id not in node_ids:
                nodes.append({"id": t_id, "label": term.title(), "type": "term", "category": "concept"})
                node_ids.add(t_id)
            edges.append({"source": passage_id, "target": t_id, "label": "contains term"})

    q_lower = q.lower()
    for step_node in CORE_RECOVERY_NODES:
        if any(term in q_lower for term in [step_node["id"].replace("_", " "), step_node["label"].lower(), "step", "inventory"]):
            if step_node["id"] not in node_ids:
                nodes.append(step_node)
                node_ids.add(step_node["id"])
            edges.append({"source": central_id, "target": step_node["id"], "label": "relates to"})

    prompts = [
        f"How do I apply {q} in daily recovery?",
        f"What does the Big Book say about {q}?",
        f"What does the 12&12 teach about {q}?",
    ]
    for prompt in prompts:
        p_id = f"prompt_{hash(prompt) & 0xFFFFFF}"
        if p_id not in node_ids:
            nodes.append({"id": p_id, "label": prompt, "type": "prompt", "category": "followup"})
            node_ids.add(p_id)
        edges.append({"source": central_id, "target": p_id, "label": "explore"})

    return {"query": q, "nodes": nodes, "edges": edges}
