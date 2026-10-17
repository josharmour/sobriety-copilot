"""The literature as research tools: catalog, chapter outlines, reading, exact search.

Everything reads the canonical manifests (``documents/.manifests/*.json``), so
quotes, page numbers and block ids match what the in-app reader shows. Chunks
in the vector index are only used for semantic search, and every hit is mapped
back onto manifest blocks.
"""

from __future__ import annotations

import difflib
import glob
import json
import math
import os
import re
import threading
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from typing import Any

from src.rag.graph import BOOK_OVERRIDES, CATEGORY_LABELS, EXCLUDED_DOC_IDS
from src.rag.outline import CONTENT_TYPES, OutlineEntry, build_outline, clean_heading, title_key

# Names people actually use for the books, beyond their titles.
ALIASES: dict[str, list[str]] = {
    "alcoholics-anonymous": ["Big Book", "the Big Book", "BB"],
    "twelve-steps-and-twelve-traditions": ["12 and 12", "12&12", "Twelve and Twelve", "12 & 12"],
    "narcotics-anonymous": ["Basic Text", "NA Basic Text"],
    "as-bill-sees-it": ["ABSI"],
    "plain-language-big-book": ["Plain Language Big Book"],
    "it-works-how-and-why": ["It Works How and Why"],
    "twenty-four-hours-a-day": ["24 Hours a Day", "Twenty-Four Hours"],
    "dr-bob-and-the-good-oldtimers": ["Dr. Bob and the Good Oldtimers"],
}
# Lower ranks list first in the catalog the model sees.
_CATEGORY_ORDER = {"conference_approved": 0, "books_about_aa": 1, "other_anonymous": 2,
                   "related_nonfiction": 3, "temp_downloads": 4}
_BOOK_CACHE_SIZE = 40
_WORD_RE = re.compile(r"[A-Za-z0-9’']+")
_EMBEDDED_HEADER = re.compile(r"\s(?:\d{1,4}\s)?([A-Z][A-Z’'.,&\- ]{4,}[A-Z.])\s(?:[ivxlc]{1,7}|\d{1,4})(?=\s)")
# PDF ligatures split a word: "sacrifi ce", "confi dence", "diffi culties".
_LIGATURE_SPLIT = re.compile(r"\b([A-Za-z]*(?:ffi|ffl|fi|fl|ff)) ([a-z]{2,})\b")
# Real words that end in fi/fl/ff, which must not swallow the next word.
_REAL_WORDS_ENDING_FI = {"sufi", "wifi", "hifi", "scifi", "if", "of", "off", "staff", "stuff", "cliff", "stiff",
                         "sheriff", "scoff", "gruff", "whiff", "puff", "bluff", "chef", "jeff", "riff", "tariff",
                         "cuff", "buff", "fluff", "huff", "snuff", "plaintiff", "payoff", "eff", "diff", "toff"}
# A drop cap the extractor split off as a "heading": "R", "“T".
_DROP_CAP = re.compile(r"^[“\"‘]?[A-Z]$")


@dataclass
class Block:
    id: str
    kind: str          # "p" (readable text) or "h" (heading)
    text: str
    page: Any
    section: int | None


@dataclass
class BookInfo:
    doc_id: str
    title: str
    author: str
    category: str
    source_file: str
    words: int
    sections: int
    aliases: list[str] = field(default_factory=list)
    copyright_year: int | None = None  # first year in this copy's copyright notice

    @property
    def category_label(self) -> str:
        return CATEGORY_LABELS.get(self.category, "Other")


@dataclass
class BookText:
    info: BookInfo
    blocks: list[Block]
    outline: list[OutlineEntry]
    # outline index -> (first, last) index into ``blocks``
    spans: list[tuple[int, int]]
    by_id: dict[str, int]


def _page(v: Any) -> Any:
    return None if v in (None, "None", "") else v


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("’", "'")).strip().lower()


def _display(doc_id: str, manifest: dict[str, Any]) -> tuple[str, str]:
    over = BOOK_OVERRIDES.get(doc_id, {})
    src = os.path.splitext(os.path.basename(manifest.get("source_file") or ""))[0]
    title, author = src, ""
    if " - " in src:
        title, author = (s.strip() for s in src.split(" - ", 1))
    title = over.get("title") or manifest.get("title") or title or doc_id
    author = over.get("author") or author or manifest.get("author") or ""
    return title, author


class Library:
    """Lazy, thread-safe access to every book's text and outline."""

    def __init__(self, documents_dir: str):
        self.documents_dir = documents_dir
        self.manifest_dir = os.path.join(documents_dir, ".manifests")
        self._lock = threading.Lock()
        self._catalog: dict[str, BookInfo] | None = None
        self._books: OrderedDict[str, BookText] = OrderedDict()

    # ── catalog ──────────────────────────────────────────────────────────

    def catalog(self) -> dict[str, BookInfo]:
        with self._lock:
            if self._catalog is None:
                self._catalog = self._build_catalog()
            return self._catalog

    def _build_catalog(self) -> dict[str, BookInfo]:
        infos: dict[str, BookInfo] = {}
        for path in sorted(glob.glob(os.path.join(self.manifest_dir, "*.json"))):
            doc_id = os.path.splitext(os.path.basename(path))[0]
            if doc_id in EXCLUDED_DOC_IDS:
                continue
            book = self._load(doc_id)
            if book is None or not book.info.words:
                continue
            infos[doc_id] = book.info
        # A temp_downloads copy of a book that also lives in a real category is a duplicate.
        titles = Counter(title_key(i.title) for i in infos.values())
        for doc_id, info in list(infos.items()):
            if info.category == "temp_downloads" and titles[title_key(info.title)] > 1:
                del infos[doc_id]
        return dict(sorted(infos.items(), key=lambda kv: (_CATEGORY_ORDER.get(kv[1].category, 9), kv[1].title.lower())))

    def catalog_text(self, categories: list[str] | None = None) -> str:
        """One line per book for the model: id, title, author, size, aliases."""
        lines = []
        cats = set(categories or [])
        for info in self.catalog().values():
            if cats and info.category not in cats:
                continue
            alias = f" (also: {', '.join(info.aliases)})" if info.aliases else ""
            by = f" by {info.author}" if info.author else ""
            year = f"© {info.copyright_year} in this copy; " if info.copyright_year else ""
            lines.append(f"- {info.doc_id}: {info.title}{by}{alias} [{info.category_label}; {year}"
                         f"{info.words:,} words; {info.sections} sections]")
        return "\n".join(lines)

    # ── books ────────────────────────────────────────────────────────────

    def book(self, doc_id: str) -> BookText | None:
        with self._lock:
            hit = self._books.get(doc_id)
            if hit is not None:
                self._books.move_to_end(doc_id)
                return hit
        loaded = self._load(doc_id)
        if loaded is None:
            return None
        with self._lock:
            self._books[doc_id] = loaded
            while len(self._books) > _BOOK_CACHE_SIZE:
                self._books.popitem(last=False)
        return loaded

    def _load(self, doc_id: str) -> BookText | None:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", doc_id or ""):
            return None
        path = os.path.join(self.manifest_dir, f"{doc_id}.json")
        if not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            return None
        raw = manifest.get("blocks") or []
        outline = build_outline(raw)
        title, author = _display(doc_id, manifest)
        # Running headers the extractor left inside paragraphs: "which comes at
        # once by THE DOCTOR’S OPINION xxix taking a few drinks".
        header_keys = {title_key(e.title) for e in outline} | {title_key(title), title_key(manifest.get("title") or "")}

        def strip_headers(text: str) -> str:
            def drop(m: re.Match) -> str:
                return " " if title_key(m.group(1)) in header_keys else m.group(0)
            return _EMBEDDED_HEADER.sub(drop, text)
        starts = [e.start for e in outline]
        blocks: list[Block] = []
        spans: list[list[int]] = [[-1, -1] for _ in outline]
        sec = -1
        words = 0
        drop_cap = ""
        for i, b in enumerate(raw):
            while sec + 1 < len(starts) and i >= starts[sec + 1]:
                sec += 1
            t = b.get("type")
            text = re.sub(r"\s+", " ", b.get("text") or "").strip()
            if not text:
                continue
            if t == "heading" and _DROP_CAP.match(text):
                drop_cap = text  # the big first letter of the next paragraph
                continue
            if t in CONTENT_TYPES:
                kind = "p"
                text = re.sub(r"\s{2,}", " ", strip_headers(_LIGATURE_SPLIT.sub(_join_ligature, text)))
                if drop_cap and text[:1].isupper():
                    text = drop_cap + text  # "ARELY HAVE we…" → "RARELY HAVE we…"
                drop_cap = ""
                words += len(text.split())
            elif t == "heading":
                cleaned = clean_heading(text)
                if cleaned is None or cleaned[1]:
                    continue
                kind = "h"
            else:
                continue
            s = sec if sec >= 0 else None
            if s is not None:
                if spans[s][0] < 0:
                    spans[s][0] = len(blocks)
                spans[s][1] = len(blocks)
            blocks.append(Block(id=b.get("id") or f"i{i}", kind=kind, text=text, page=_page(b.get("printed_page")), section=s))
        info = BookInfo(doc_id=doc_id, title=title, author=author,
                        category=manifest.get("category") or "uncategorized",
                        source_file=manifest.get("source_file") or "", words=words,
                        sections=len(outline), aliases=ALIASES.get(doc_id, []),
                        copyright_year=_copyright_year(raw))
        return BookText(info=info, blocks=blocks, outline=outline,
                        spans=[(a, z) for a, z in spans], by_id={b.id: n for n, b in enumerate(blocks)})

    # ── resolution ───────────────────────────────────────────────────────

    def resolve_book(self, name: str) -> str | None:
        """Map a doc id, title or common name ("Big Book", "12&12") onto a doc id."""
        cat = self.catalog()
        q = (name or "").strip()
        if not q:
            return None
        if q in cat:
            return q
        key = title_key(q)
        if key.startswith("the") and len(key) > 6:
            key_nothe = key[3:]
        else:
            key_nothe = key
        names: dict[str, str] = {}
        for doc_id, info in cat.items():
            for n in [info.title, doc_id, *info.aliases]:
                k = title_key(n)
                names.setdefault(k, doc_id)
                if k.startswith("the"):
                    names.setdefault(k[3:], doc_id)
        for k in (key, key_nothe):
            if k in names:
                return names[k]
        # A unique prefix/containment match ("twelve steps and twelve" → 12&12).
        partial = {d for k, d in names.items() if len(key) >= 5 and (k.startswith(key) or key in k)}
        if len(partial) == 1:
            return partial.pop()
        close = difflib.get_close_matches(key, list(names), n=1, cutoff=0.82)
        return names[close[0]] if close else None

    def resolve_section(self, book: BookText, ref: Any) -> int | None:
        if ref is None or ref == "":
            return None
        if isinstance(ref, int) or (isinstance(ref, str) and ref.strip().isdigit()):
            n = int(ref)
            return n if 0 <= n < len(book.outline) else None
        key = title_key(str(ref))
        titles = [title_key(e.title) for e in book.outline]
        for n, t in enumerate(titles):
            if t == key:
                return n
        hits = [n for n, t in enumerate(titles) if key and (key in t or t.startswith(key))]
        if hits:
            return hits[0]
        close = difflib.get_close_matches(key, titles, n=1, cutoff=0.75)
        return titles.index(close[0]) if close else None

    # ── tools ────────────────────────────────────────────────────────────

    def section_pages(self, book: BookText, n: int) -> str:
        a, z = book.spans[n]
        if a < 0:
            return ""
        pages = [b.page for b in book.blocks[a:z + 1] if b.page is not None]
        if not pages:
            return ""
        return f"p. {pages[0]}" if pages[0] == pages[-1] else f"pp. {pages[0]}–{pages[-1]}"

    def section_words(self, book: BookText, n: int) -> int:
        a, z = book.spans[n]
        if a < 0:
            return 0
        return sum(len(b.text.split()) for b in book.blocks[a:z + 1] if b.kind == "p")

    def outline_text(self, book: BookText) -> str:
        lines = [f"{book.info.title} — {len(book.outline)} sections, {book.info.words:,} words"]
        for n, e in enumerate(book.outline):
            pages = self.section_pages(book, n)
            lines.append(f"[{n}] {e.title}" + (f" ({pages}" if pages else " (") + f", {self.section_words(book, n):,} words)")
        return "\n".join(lines)

    def read(self, book: BookText, n: int, max_words: int, part: int = 1) -> tuple[str, list[Block], int]:
        """Section text with a ``[p.67 b00629]`` marker per paragraph. Returns (text, blocks, parts)."""
        a, z = book.spans[n]
        blocks = book.blocks[a:z + 1] if a >= 0 else []
        chunks: list[list[Block]] = [[]]
        count = 0
        for b in blocks:
            w = len(b.text.split())
            if chunks[-1] and count + w > max_words:
                chunks.append([])
                count = 0
            chunks[-1].append(b)
            count += w
        parts = len(chunks)
        part = min(max(part, 1), parts)
        shown = chunks[part - 1]
        lines = []
        for b in shown:
            if b.kind == "h":
                lines.append(f"\n## {b.text}")
            else:
                page = f"p.{b.page} " if b.page is not None else ""
                lines.append(f"[{page}{b.id}] {b.text}")
        return "\n".join(lines).strip(), shown, parts

    def find(self, terms: list[str], doc_ids: list[str], section: int | None = None,
             max_quotes: int = 30) -> dict[str, Any]:
        """Exact, case-insensitive word/phrase matches; ``pray*`` matches pray/prayer/praying…"""
        patterns = []
        for t in terms[:8]:
            t = (t or "").strip()
            words = _WORD_RE.findall(t.rstrip("*").replace("’", "'"))
            if not words:
                continue
            body = r"\W+".join(re.escape(w) for w in words)
            tail = r"\w*" if t.endswith("*") else r"\b"
            patterns.append((t, re.compile(r"\b" + body.replace("'", "['’]") + tail, re.IGNORECASE)))
        totals: Counter = Counter()
        by_scope: dict[str, Counter] = {}
        quotes: list[dict[str, Any]] = []
        for doc_id in doc_ids:
            book = self.book(doc_id)
            if book is None:
                continue
            for b in book.blocks:
                if b.kind != "p" or (section is not None and b.section != section):
                    continue
                for label, rx in patterns:
                    hits = list(rx.finditer(b.text))
                    if not hits:
                        continue
                    totals[label] += len(hits)
                    scope = (book.outline[b.section].title if b.section is not None else "(front matter)") \
                        if len(doc_ids) == 1 else book.info.title
                    by_scope.setdefault(scope, Counter())[label] += len(hits)
                    if len(quotes) < max_quotes:
                        for m in hits[:2]:
                            quotes.append({"doc_id": doc_id, "block": b, "term": label,
                                           "quote": _sentence_around(b.text, m.start(), m.end())})
        return {"totals": dict(totals), "by_scope": {k: dict(v) for k, v in by_scope.items()},
                "quotes": quotes, "terms": [p[0] for p in patterns]}

    def keyword_search(self, query: str, doc_ids: list[str], limit: int) -> list[tuple[str, Block, float]]:
        """Fallback search when the vector index is unavailable: tf-idf over paragraphs."""
        q = [w.lower() for w in _WORD_RE.findall(query) if len(w) > 2]
        if not q:
            return []
        scored: list[tuple[float, str, Block]] = []
        df: Counter = Counter()
        paras: list[tuple[str, Block, Counter]] = []
        for doc_id in doc_ids:
            book = self.book(doc_id)
            if book is None:
                continue
            for b in book.blocks:
                if b.kind != "p" or len(b.text) < 80:
                    continue
                tf = Counter(w.lower() for w in _WORD_RE.findall(b.text))
                if not any(t in tf for t in q):
                    continue
                paras.append((doc_id, b, tf))
                for t in set(q):
                    if t in tf:
                        df[t] += 1
        n = max(len(paras), 1)
        for doc_id, b, tf in paras:
            s = sum((1 + math.log(tf[t])) * math.log(1 + n / df[t]) for t in set(q) if tf.get(t))
            scored.append((s / math.sqrt(len(b.text.split()) / 60 + 1), doc_id, b))
        scored.sort(key=lambda x: -x[0])
        return [(d, b, s) for s, d, b in scored[:limit]]


_COPYRIGHT_RE = re.compile(r"(?:copyright|©)[^.]{0,120}", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(1[89]\d\d|20[0-2]\d)\b")


def _copyright_year(raw: list[dict[str, Any]]) -> int | None:
    """The first year of the first copyright notice in the front matter (this copy's edition)."""
    for b in raw[:250]:
        for m in _COPYRIGHT_RE.finditer(b.get("text") or ""):
            years = _YEAR_RE.findall(m.group(0))
            if years:
                return int(years[0])
    return None


def _join_ligature(m: re.Match) -> str:
    left, right = m.group(1), m.group(2)
    return m.group(0) if left.lower() in _REAL_WORDS_ENDING_FI else left + right


def _sentence_around(text: str, a: int, z: int, max_chars: int = 320) -> str:
    start = max(text.rfind(". ", 0, a), text.rfind("? ", 0, a), text.rfind("! ", 0, a), text.rfind("“", 0, a) - 1)
    start = 0 if start < 0 else start + 2
    ends = [i for i in (text.find(". ", z), text.find("? ", z), text.find("! ", z), text.find("”", z)) if i >= 0]
    end = min(ends) + 1 if ends else len(text)
    if end - start > max_chars:
        start = max(start, a - max_chars // 2)
        end = min(end, start + max_chars)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet
