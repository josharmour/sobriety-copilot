"""Text helpers shared by the concept-graph build script and the server.

* ``passages_for_book`` cuts a book into reading-sized passages (a few
  paragraphs, never across a chapter boundary) — the unit in which two concepts
  "occur together".
* ``ConceptMatcher`` finds which of thousands of concepts occur in a passage in
  one pass over its tokens: single words and word-prefixes (``resent*``) are
  dict lookups, phrases are checked from their first word.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")

STOPWORDS = frozenset("""
a about above after again against all almost also am among an and any are as at back be because been before
being below between both but by can could did do does doing done down during each either else enough etc
ever every for from further had has have having he her here hers herself him himself his how however i if
in into is it its itself just least less let like made many may me might mine more most much must my myself
neither no nor not now of off often on once one only onto or other ou our ours ourselves out over own per
perhaps quite rather same see seem she should since so some such than that the their theirs them themselves
then there these they this those though through thus till to too toward towards under until up upon us
very via was we well were what whatever when where whether which while who whom whose why will with within
without would yet you your yours yourself yourselves 's s t don didn doesn isn wasn weren aren couldn
wouldn shouldn won can't i'm i've i'd i'll you're you've we're we've they're they've it's that's there's
what's he's she's let's
""".split())

PASSAGE_MIN_WORDS = 120
PASSAGE_MAX_WORDS = 260


def tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower().replace("’", "'").replace("‘", "'"))


@dataclass
class Passage:
    doc_id: str
    section: int | None
    block_ids: list[str]
    page: Any
    page_end: Any
    text: str
    words: int = 0


def passages_for_book(book: Any) -> list[Passage]:
    """Group a ``research.library.BookText``'s paragraphs into passages within each section."""
    out: list[Passage] = []
    cur: list[Any] = []
    words = 0

    def flush() -> None:
        nonlocal cur, words
        if cur:
            pages = [b.page for b in cur if b.page is not None]
            out.append(Passage(doc_id=book.info.doc_id, section=cur[0].section, block_ids=[b.id for b in cur],
                               page=pages[0] if pages else None, page_end=pages[-1] if pages else None,
                               text=" ".join(b.text for b in cur), words=words))
        cur, words = [], 0

    for b in book.blocks:
        if b.kind != "p":
            continue
        if cur and (b.section != cur[0].section or words >= PASSAGE_MIN_WORDS):
            flush()
        w = len(b.text.split())
        if cur and words + w > PASSAGE_MAX_WORDS:
            flush()
        cur.append(b)
        words += w
    flush()
    return [p for p in out if p.words >= 25]


def _variants(form: str) -> list[str]:
    """A form plus its simple plural/singular, so "resentment" also finds "resentments"."""
    f = form.strip().lower().replace("’", "'")
    if not f or f.endswith("*"):
        return [f] if f else []
    out = [f]
    last = f.split()[-1]
    head = f[: len(f) - len(last)]
    if last.endswith("ies") and len(last) > 4:
        out.append(head + last[:-3] + "y")
    elif last.endswith("s") and not last.endswith("ss") and len(last) > 3:
        out.append(head + last[:-1])
    elif last.endswith("y") and len(last) > 3 and last[-2] not in "aeiou":
        out.append(head + last[:-1] + "ies")
    elif not last.endswith("s") and last.isalpha() and len(last) > 2:
        out.append(head + last + "s")
    return out


@dataclass
class ConceptMatcher:
    concepts: list[tuple[str, Iterable[str]]]
    index: dict[str, int] = field(init=False)
    _single: dict[str, set] = field(init=False)
    _prefix: dict[int, dict[str, set]] = field(init=False)
    _phrases: dict[str, list[tuple[tuple[str, ...], bool, str]]] = field(init=False)

    def __post_init__(self) -> None:
        self.index = {}
        self._single = defaultdict(set)
        self._prefix = defaultdict(lambda: defaultdict(set))
        self._phrases = defaultdict(list)
        for cid, forms in self.concepts:
            self.index.setdefault(cid, len(self.index))
            for raw in forms:
                for form in _variants(raw):
                    wildcard = form.endswith("*")
                    toks = tokens(form.rstrip("*"))
                    if not toks:
                        continue
                    if len(toks) == 1 and not wildcard:
                        self._single[toks[0]].add(cid)
                    elif len(toks) == 1:
                        if len(toks[0]) >= 3:
                            self._prefix[len(toks[0])][toks[0]].add(cid)
                    else:
                        self._phrases[toks[0]].append((tuple(toks[1:]), wildcard, cid))
        self._prefix_lens = sorted(self._prefix)

    def match_counts(self, text: str) -> dict[str, int]:
        toks = tokens(text)
        hits: dict[str, int] = defaultdict(int)
        n = len(toks)
        for i, t in enumerate(toks):
            for cid in self._single.get(t, ()):
                hits[cid] += 1
            for L in self._prefix_lens:
                if len(t) >= L:
                    for cid in self._prefix[L].get(t[:L], ()):
                        hits[cid] += 1
            for rest, wildcard, cid in self._phrases.get(t, ()):
                k = len(rest)
                if i + k >= n:
                    continue
                if toks[i + 1:i + k] == list(rest[:-1]) and (
                        toks[i + k] == rest[-1] or (wildcard and toks[i + k].startswith(rest[-1]))):
                    hits[cid] += 1
        return dict(hits)

    def match(self, text: str) -> set[str]:
        return set(self.match_counts(text))
