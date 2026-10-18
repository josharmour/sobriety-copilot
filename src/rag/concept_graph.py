"""Concept graph: thousands of concepts across the whole library, each with all its peers.

The concept list, map positions and prominence come from
``src/rag/data/graph_concepts.json`` (built offline by
``scripts/build_concepts.py``). At startup the server only has to find where
each concept occurs:

* every book is cut into passages (``concept_text.passages_for_book``);
* one pass of ``ConceptMatcher`` per passage gives a passages × concepts
  incidence matrix;
* peers are concepts that share passages more than chance predicts (NPMI),
  ranked — not capped at ten;
* "where two concepts meet" is the intersection of their passage lists, so any
  pair can be opened as readable passages.

Books and chapters are reachable from every concept and lead back to concepts,
so navigation never dead-ends. Built in a background thread and pickled; the
endpoints answer 202 + progress while it builds.
"""

from __future__ import annotations

import json
import os
import pickle
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from src.rag.concept_text import ConceptMatcher, passages_for_book, tokens
from src.rag.graph import CATEGORY_LABELS, CATEGORY_PRIOR
from src.rag.graph_taxonomy import TOPICS

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "graph_concepts.json")
MAX_PEERS = 800          # peers kept per concept (the UI pages through them)
MIN_SHARED = 2           # passages two concepts must share to be peers
CACHE_FORMAT = 3
_TOPIC_BY_ID = {t[0]: t for t in TOPICS}


@dataclass
class ConceptGraphData:
    version: Any
    signature: str
    nodes: list[dict[str, Any]]
    index: dict[str, int]
    groups: list[dict[str, str]]
    # passages
    p_doc: np.ndarray            # int32 index into books
    p_section: np.ndarray        # int32, -1 = none
    p_blocks: list[list[str]]
    p_page: list[Any]
    p_page_end: list[Any]
    p_words: np.ndarray
    books: list[str]             # doc ids
    # incidence: node -> sorted passage ids, and hit counts
    postings: list[np.ndarray]
    hits: list[np.ndarray]
    # peers: node -> (peer idx, npmi, shared) sorted by strength
    peer_idx: list[np.ndarray]
    peer_w: list[np.ndarray]
    peer_n: list[np.ndarray]
    built_at: float = 0.0
    build_seconds: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


def _signature(library: Any) -> str:
    mtimes = []
    for f in sorted(os.listdir(library.manifest_dir)):
        if f.endswith(".json"):
            mtimes.append(f"{f}:{int(os.path.getmtime(os.path.join(library.manifest_dir, f)))}")
    data_m = int(os.path.getmtime(DATA_PATH)) if os.path.exists(DATA_PATH) else 0
    return f"v{CACHE_FORMAT}|{data_m}|{len(mtimes)}|{hash(tuple(mtimes)) & 0xffffffff:x}"


def load_concepts() -> dict[str, Any] | None:
    if not os.path.exists(DATA_PATH):
        return None
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def build(library: Any, progress=lambda msg, pct: None) -> ConceptGraphData:
    from scipy import sparse

    t0 = time.monotonic()
    data = load_concepts()
    if data is None:
        raise RuntimeError(f"concept data missing: {DATA_PATH}")
    nodes = data["nodes"]
    index = {n["id"]: i for i, n in enumerate(nodes)}
    forms = []
    for n in nodes:
        if n["id"].startswith("t:"):
            t = _TOPIC_BY_ID.get(n["id"][2:])
            forms.append((n["id"], t[4] if t else [n["label"]]))
        else:
            forms.append((n["id"], n.get("forms") or [n["label"]]))
    matcher = ConceptMatcher(forms)

    progress("reading the library", 2)
    books = list(library.catalog())
    p_doc, p_section, p_blocks, p_page, p_page_end, p_words = [], [], [], [], [], []
    rows, cols, vals = [], [], []
    chapters: dict[tuple[int, int], tuple[str, str]] = {}
    for bi, doc_id in enumerate(books):
        book = library.book(doc_id)
        if book is None:
            continue
        for s, e in enumerate(book.outline):
            chapters[(bi, s)] = (e.title, library.section_pages(book, s))
        for p in passages_for_book(book):
            pid = len(p_doc)
            p_doc.append(bi)
            p_section.append(-1 if p.section is None else p.section)
            p_blocks.append(p.block_ids)
            p_page.append(p.page)
            p_page_end.append(p.page_end)
            p_words.append(p.words)
            for cid, k in matcher.match_counts(p.text).items():
                j = index.get(cid)
                if j is not None:
                    rows.append(pid)
                    cols.append(j)
                    vals.append(k)
        progress(f"reading {book.info.title}", 2 + int(80 * (bi + 1) / len(books)))
    n_pass, n_nodes = len(p_doc), len(nodes)
    X = sparse.csr_matrix((np.asarray(vals, dtype=np.float32), (rows, cols)), shape=(n_pass, n_nodes))
    Xc = X.tocsc()
    postings = [Xc.indices[Xc.indptr[j]:Xc.indptr[j + 1]].astype(np.int32) for j in range(n_nodes)]
    hits = [Xc.data[Xc.indptr[j]:Xc.indptr[j + 1]].astype(np.int16) for j in range(n_nodes)]

    progress("linking concepts", 85)
    B = X.copy()
    B.data[:] = 1.0
    df = np.asarray(B.sum(axis=0)).ravel()
    C = (B.T @ B).tocoo()
    mask = (C.row != C.col) & (C.data >= MIN_SHARED)
    r, c, n = C.row[mask], C.col[mask], C.data[mask].astype(np.float64)
    p_ab = n / n_pass
    npmi = np.log(p_ab / ((df[r] / n_pass) * (df[c] / n_pass))) / -np.log(p_ab)
    keep = npmi > 0.02
    r, c, n, npmi = r[keep], c[keep], n[keep], npmi[keep]
    # Rank peers by association, nudged toward pairs with real support.
    strength = npmi * (1 + 0.15 * np.log1p(n))
    order = np.lexsort((-strength, r))
    r, c, n, npmi = r[order], c[order], n[order], npmi[order]
    starts = np.searchsorted(r, np.arange(n_nodes + 1))
    peer_idx, peer_w, peer_n = [], [], []
    for j in range(n_nodes):
        a, z = starts[j], min(starts[j + 1], starts[j] + MAX_PEERS)
        peer_idx.append(c[a:z].astype(np.int32))
        peer_w.append(npmi[a:z].astype(np.float32))
        peer_n.append(n[a:z].astype(np.int32))

    progress("done", 100)
    return ConceptGraphData(
        version=data.get("version"), signature=_signature(library), nodes=nodes, index=index,
        groups=data.get("groups", []),
        p_doc=np.asarray(p_doc, dtype=np.int32), p_section=np.asarray(p_section, dtype=np.int32),
        p_blocks=p_blocks, p_page=p_page, p_page_end=p_page_end, p_words=np.asarray(p_words, dtype=np.int32),
        books=books, postings=postings, hits=hits, peer_idx=peer_idx, peer_w=peer_w, peer_n=peer_n,
        built_at=time.time(), build_seconds=round(time.monotonic() - t0, 1),
        extra={"df": df.astype(np.int32), "chapters": chapters},
    )


# ── lifecycle ─────────────────────────────────────────────────────────────


class ConceptGraphService:
    def __init__(self, library: Any, cache_dir: str):
        self.library = library
        self.cache_path = os.path.join(cache_dir, "concept_graph.pkl")
        self._graph: ConceptGraphData | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._progress = {"message": "", "pct": 0}
        self._error: str | None = None

    def status(self) -> dict[str, Any]:
        g = self._graph
        return {"ready": g is not None, "building": bool(self._thread and self._thread.is_alive()),
                "progress": dict(self._progress), "error": self._error,
                "nodes": len(g.nodes) if g else 0, "passages": int(len(g.p_doc)) if g else 0,
                "build_seconds": g.build_seconds if g else None}

    def get(self) -> ConceptGraphData | None:
        if self._graph is not None:
            return self._graph
        self.ensure_building()
        return self._graph

    def ensure_building(self) -> None:
        with self._lock:
            if self._graph is not None or (self._thread and self._thread.is_alive()):
                return
            self._thread = threading.Thread(target=self._build, name="concept-graph", daemon=True)
            self._thread.start()

    def _set(self, message: str, pct: int) -> None:
        self._progress = {"message": message, "pct": pct}

    def _build(self) -> None:
        try:
            sig = _signature(self.library)
            if os.path.exists(self.cache_path):
                try:
                    with open(self.cache_path, "rb") as f:
                        cached = pickle.load(f)
                    if getattr(cached, "signature", None) == sig:
                        self._graph = cached
                        print(f"[CGRAPH] loaded cache ({len(cached.nodes)} nodes)", flush=True)
                        return
                except Exception as exc:
                    print(f"[CGRAPH] cache load failed: {exc}", flush=True)
            g = build(self.library, self._set)
            self._graph = g
            print(f"[CGRAPH] built {len(g.nodes)} nodes over {len(g.p_doc)} passages in {g.build_seconds}s", flush=True)
            try:
                os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
                tmp = self.cache_path + ".tmp"
                with open(tmp, "wb") as f:
                    pickle.dump(g, f, protocol=pickle.HIGHEST_PROTOCOL)
                os.replace(tmp, self.cache_path)
            except Exception as exc:
                print(f"[CGRAPH] cache write failed: {exc}", flush=True)
        except Exception as exc:
            self._error = f"{type(exc).__name__}: {exc}"
            print(f"[CGRAPH] build failed: {self._error}", flush=True)


# ── source filter ─────────────────────────────────────────────────────────
#
# The app's "source material" setting (the same category ids /api/chat takes).
# The graph itself — map positions, prominence, NPMI peer strengths — stays the
# whole-library one; a scope only hides the passages, books, chapters and
# concepts outside the chosen categories, and recounts what remains.


class Scope:
    def __init__(self, g: ConceptGraphData, library: Any, categories: frozenset[str] | None):
        self.full = categories is None
        if self.full:
            self.book_ok = np.ones(len(g.books), dtype=bool)
            self.postings, self.hits = g.postings, g.hits
        else:
            cat = library.catalog()
            self.book_ok = np.asarray([b in cat and cat[b].category in categories for b in g.books], dtype=bool)
            mask = self.book_ok[g.p_doc] if len(g.p_doc) else np.zeros(0, dtype=bool)
            self.postings = [p[mask[p]] for p in g.postings]
            self.hits = [h[mask[p]] for p, h in zip(g.postings, g.hits)]
        self.n_passages = int(np.count_nonzero(self.book_ok[g.p_doc])) if len(g.p_doc) else 0
        self._peers: dict[int, list[tuple[int, float, int]]] = {}
        self.map_rows: tuple[list, dict] | None = None

    def peers(self, g: ConceptGraphData, j: int) -> list[tuple[int, float, int]]:
        """(peer, npmi, passages shared in scope), strongest first; peers that never meet in scope are dropped."""
        if self.full:
            return list(zip(g.peer_idx[j].tolist(), g.peer_w[j].tolist(), g.peer_n[j].tolist()))
        out = self._peers.get(j)
        if out is None:
            sel = np.zeros(len(g.p_doc), dtype=bool)
            sel[self.postings[j]] = True
            out = []
            for k, w in zip(g.peer_idx[j].tolist(), g.peer_w[j].tolist()):
                shared = int(np.count_nonzero(sel[self.postings[k]]))
                if shared:
                    out.append((k, w, shared))
            self._peers[j] = out
        return out


_SCOPES: dict[tuple, Scope] = {}


def scope_for(g: ConceptGraphData, library: Any, categories: list[str] | None = None) -> Scope:
    """The scope for a category list; None, empty, or every category the library has means the whole library."""
    cats = frozenset(c for c in (categories or []) if c) or None
    if cats is not None and {info.category for info in library.catalog().values()} <= cats:
        cats = None
    key = (id(g), g.built_at, cats)
    sc = _SCOPES.get(key)
    if sc is None:
        if len(_SCOPES) >= 64:
            _SCOPES.clear()
        sc = _SCOPES[key] = Scope(g, library, cats)
    return sc


# ── queries ───────────────────────────────────────────────────────────────


def _node_brief(g: ConceptGraphData, j: int, sc: Scope | None = None) -> dict[str, Any]:
    n = g.nodes[j]
    return {"id": n["id"], "label": n["label"], "type": n.get("type"), "group": n.get("group"),
            "passages": int(len((sc.postings if sc else g.postings)[j]))}


def map_payload(g: ConceptGraphData, library: Any, sc: Scope | None = None) -> dict[str, Any]:
    """Every node with its map position and size, plus each node's three strongest peers.

    Under a source filter, concepts that never occur in the chosen books are left
    off the map (``top_peers`` index the rows actually sent).
    """
    sc = sc or scope_for(g, library)
    if sc.map_rows is None:
        keep = [j for j in range(len(g.nodes)) if sc.full or len(sc.postings[j])]
        row_of = {j: i for i, j in enumerate(keep)}
        rows = []
        for j in keep:
            n = g.nodes[j]
            if sc.full:
                top = [int(k) for k in g.peer_idx[j][:3]]
            else:
                top = []
                for k, _w, _c in sc.peers(g, j):
                    top.append(row_of[k])
                    if len(top) == 3:
                        break
            rows.append([n["id"], n["label"], n.get("type") or "concept", n.get("group") or "other",
                         n.get("x", 0.5), n.get("y", 0.5), n.get("prominence", 0.0), int(len(sc.postings[j])), top])
        cat = library.catalog()
        books = [b for b, ok in zip(g.books, sc.book_ok) if ok]
        stats = {"nodes": len(rows), "passages": sc.n_passages, "books": len(books),
                 "chapters": int(sum(cat[b].sections for b in books if b in cat))}
        sc.map_rows = (rows, stats)
    rows, stats = sc.map_rows
    return {
        "version": g.version,
        "built_at": g.built_at,
        "fields": ["id", "label", "type", "group", "x", "y", "prominence", "passages", "top_peers"],
        "nodes": rows,
        "groups": g.groups,
        "stats": dict(stats),
    }


def _book_meta(library: Any, doc_id: str) -> dict[str, Any]:
    info = library.catalog().get(doc_id)
    if info is None:
        return {"id": doc_id, "title": doc_id}
    return {"id": doc_id, "title": info.title, "author": info.author, "category": info.category,
            "category_label": CATEGORY_LABELS.get(info.category, "Other"), "year": info.copyright_year}


def _chapter_title(g: ConceptGraphData, doc_id: str, section: int) -> tuple[str, str]:
    try:
        return g.extra["chapters"].get((g.books.index(doc_id), section), ("", ""))
    except ValueError:
        return "", ""


def _passages_payload(g: ConceptGraphData, library: Any, pids: list[int], highlight: list[str]) -> list[dict]:
    out = []
    for pid in pids:
        doc_id = g.books[int(g.p_doc[pid])]
        book = library.book(doc_id)
        if book is None:
            continue
        blocks = [book.blocks[book.by_id[b]] for b in g.p_blocks[pid] if b in book.by_id]
        text = " ".join(b.text for b in blocks)
        sec = int(g.p_section[pid])
        title, _pages = _chapter_title(g, doc_id, sec)
        page, page_end = g.p_page[pid], g.p_page_end[pid]
        out.append({
            "passage": int(pid), "doc_id": doc_id, "book_title": book.info.title,
            "section": sec if sec >= 0 else None, "section_title": title or None,
            "block_ids": g.p_blocks[pid], "page": page,
            "pages": (f"p. {page}" if page == page_end else f"pp. {page}–{page_end}") if page is not None else None,
            "excerpt": _excerpt(text, highlight),
        })
    return out


def _forms(g: ConceptGraphData, j: int) -> list[str]:
    n = g.nodes[j]
    if n["id"].startswith("t:"):
        t = _TOPIC_BY_ID.get(n["id"][2:])
        return [x for x in (t[4] if t else [])]
    return n.get("forms") or [n["label"]]


def _excerpt(text: str, forms: list[str], max_chars: int = 460) -> str:
    low = text.lower().replace("’", "'")
    anchor = -1
    for f in forms:
        f = f.lower().rstrip("*")
        if len(f) < 3:
            continue
        m = re.search(r"\b" + re.escape(f), low)
        if m and (anchor < 0 or m.start() < anchor):
            anchor = m.start()
    if len(text) <= max_chars:
        return text
    start = max(0, (anchor if anchor >= 0 else 0) - max_chars // 3)
    start = text.rfind(" ", 0, start) + 1 if start > 0 else 0
    end = min(len(text), start + max_chars)
    end = text.rfind(" ", start, end) if end < len(text) else end
    return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")


def _rank_passages(g: ConceptGraphData, library: Any, pids: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Passages most *about* the concept first, conference-approved literature preferred."""
    cat = library.catalog()
    prior = np.asarray([CATEGORY_PRIOR.get(cat[b].category, 0.8) if b in cat else 0.8 for b in g.books])
    words = np.maximum(g.p_words[pids], 1)
    score = np.minimum(weights / np.sqrt(words / 60), 3.0) * prior[g.p_doc[pids]]
    return pids[np.argsort(-score, kind="stable")]


def node_payload(g: ConceptGraphData, library: Any, node_id: str, peers: int = 300,
                 passages: int = 12, sc: Scope | None = None) -> dict[str, Any] | None:
    j = g.index.get(node_id)
    if j is None:
        return None
    sc = sc or scope_for(g, library)
    pids = sc.postings[j]
    n = g.nodes[j]
    # Books and chapters where it occurs.
    book_counts = np.bincount(g.p_doc[pids], minlength=len(g.books)) if len(pids) else np.zeros(len(g.books), int)
    books = [dict(_book_meta(library, g.books[b]), count=int(book_counts[b]))
             for b in np.argsort(-book_counts) if book_counts[b] > 0]
    sec_keys: dict[tuple[int, int], int] = {}
    for d, s in zip(g.p_doc[pids], g.p_section[pids]):
        if s >= 0:
            sec_keys[(int(d), int(s))] = sec_keys.get((int(d), int(s)), 0) + 1
    chapters = []
    for (d, s), cnt in sorted(sec_keys.items(), key=lambda kv: -kv[1])[:150]:
        title, pages = _chapter_title(g, g.books[d], s)
        if title:
            chapters.append({"doc_id": g.books[d], "book_title": library.catalog()[g.books[d]].title,
                             "section": s, "title": title, "pages": pages, "count": cnt})
    ranked = _rank_passages(g, library, pids, sc.hits[j].astype(np.float64))[:passages]
    all_peers = sc.peers(g, j)
    return {
        "node": dict(_node_brief(g, j, sc), prominence=n.get("prominence"), hub=n.get("hub"),
                     forms=_forms(g, j)[:12]),
        "peers_total": len(all_peers),
        "peers": [dict(_node_brief(g, k, sc), weight=round(float(w), 3), shared=int(c))
                  for k, w, c in all_peers[:peers]],
        "books": books,
        "chapters": chapters,
        "passages": _passages_payload(g, library, [int(p) for p in ranked], _forms(g, j)),
    }


def meet_payload(g: ConceptGraphData, library: Any, a: str, b: str, offset: int = 0, limit: int = 12,
                 sc: Scope | None = None) -> dict | None:
    """Passages where two concepts occur together — the junction between them."""
    ja, jb = g.index.get(a), g.index.get(b)
    if ja is None or jb is None:
        return None
    sc = sc or scope_for(g, library)
    both = np.intersect1d(sc.postings[ja], sc.postings[jb], assume_unique=True)
    wa = dict(zip(sc.postings[ja].tolist(), sc.hits[ja].tolist()))
    wb = dict(zip(sc.postings[jb].tolist(), sc.hits[jb].tolist()))
    weights = np.asarray([min(wa[p], wb[p]) for p in both.tolist()], dtype=np.float64)
    ranked = _rank_passages(g, library, both, weights) if len(both) else both
    page = [int(p) for p in ranked[offset:offset + limit]]
    return {"a": _node_brief(g, ja, sc), "b": _node_brief(g, jb, sc), "total": int(len(both)), "offset": offset,
            "passages": _passages_payload(g, library, page, _forms(g, ja) + _forms(g, jb))}


def _concepts_in(g: ConceptGraphData, sc: Scope, mask_pids: np.ndarray, limit: int) -> list[dict]:
    """Concepts over-represented in a set of passages (a book or a chapter), relative to the scope."""
    if not len(mask_pids):
        return []
    sel = np.zeros(len(g.p_doc), dtype=bool)
    sel[mask_pids] = True
    n_sel, n_all = len(mask_pids), max(sc.n_passages, 1)
    scored = []
    for j, post in enumerate(sc.postings):
        if not len(post):
            continue
        k = int(sel[post].sum())
        if k < 1:
            continue
        lift = (k / n_sel) / (len(post) / n_all)
        scored.append((k * np.log1p(lift), j, k))
    scored.sort(key=lambda x: -x[0])
    return [dict(_node_brief(g, j, sc), count=k) for _s, j, k in scored[:limit]]


def _scoped_book(g: ConceptGraphData, sc: Scope, doc_id: str) -> int | None:
    """The book's index, or None when it is unknown or outside the scope."""
    if doc_id not in g.books:
        return None
    bi = g.books.index(doc_id)
    return bi if sc.book_ok[bi] else None


def book_payload(g: ConceptGraphData, library: Any, doc_id: str, limit: int = 300,
                 sc: Scope | None = None) -> dict | None:
    sc = sc or scope_for(g, library)
    bi = _scoped_book(g, sc, doc_id)
    if bi is None:
        return None
    pids = np.where(g.p_doc == bi)[0]
    secs = np.bincount(g.p_section[pids][g.p_section[pids] >= 0]) if len(pids) else np.zeros(0, int)
    chapters = [{"section": s, "title": t, "pages": pg, "passages": int(secs[s]) if s < len(secs) else 0}
                for (b, s), (t, pg) in sorted(g.extra["chapters"].items()) if b == bi]
    return {"book": _book_meta(library, doc_id), "concepts": _concepts_in(g, sc, pids, limit), "chapters": chapters}


def chapter_payload(g: ConceptGraphData, library: Any, doc_id: str, section: int, limit: int = 200,
                    sc: Scope | None = None) -> dict | None:
    sc = sc or scope_for(g, library)
    bi = _scoped_book(g, sc, doc_id)
    if bi is None:
        return None
    pids = np.where((g.p_doc == bi) & (g.p_section == section))[0]
    title, pages = _chapter_title(g, doc_id, section)
    if not title:
        return None
    return {"book": _book_meta(library, doc_id), "section": section, "title": title, "pages": pages,
            "concepts": _concepts_in(g, sc, pids, limit),
            "passages": _passages_payload(g, library, [int(p) for p in pids[:40]], [])}


def search_payload(g: ConceptGraphData, library: Any, q: str, limit: int = 20,
                   sc: Scope | None = None) -> dict[str, Any]:
    ql = (q or "").strip().lower()
    if not ql:
        return {"query": q, "nodes": [], "books": [], "chapters": []}
    sc = sc or scope_for(g, library)
    in_scope = {b for b, ok in zip(g.books, sc.book_ok) if ok}
    qt = " ".join(tokens(ql))
    scored = []
    for j, n in enumerate(g.nodes):
        if not sc.full and not len(sc.postings[j]):
            continue
        lab = n["label"].lower()
        forms = [f.lower() for f in (n.get("forms") or [])]
        if lab == ql or qt in forms:
            s = 3.0
        elif lab.startswith(ql):
            s = 2.0
        elif ql in lab or any(qt and qt in f for f in forms):
            s = 1.0
        else:
            continue
        scored.append((s, n.get("prominence", 0), j))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    books, chapters = [], []
    for doc_id, info in library.catalog().items():
        if ql in info.title.lower() and (sc.full or doc_id in in_scope):
            books.append(_book_meta(library, doc_id))
    cat = library.catalog()
    for (bi, s), (title, pages) in g.extra["chapters"].items():
        if ql in title.lower() and len(chapters) < limit and sc.book_ok[bi]:
            doc_id = g.books[bi]
            chapters.append({"doc_id": doc_id, "book_title": cat[doc_id].title if doc_id in cat else doc_id,
                             "section": s, "title": title, "pages": pages})
    return {"query": q, "nodes": [_node_brief(g, j, sc) for _s, _p, j in scored[:limit]],
            "books": books[:10], "chapters": chapters[:limit]}
