"""Chapter outline of a book manifest.

A manifest is a flat list of blocks (``heading``, ``paragraph``, ``toc`` …).
Turning that into chapters is harder than splitting at every heading, because
the extractor also tags as headings:

* decorative drop caps — the big "W" that opens "War fever ran high…";
* running page headers — "22 STEP ONE", "THE DOCTOR'S OPINION xxv", or the
  book's own title repeated on every other page;
* title-page lines and table-of-contents entries.

The old graph builder counted a heading's content up to the very next heading,
so a chapter title followed by its drop cap had "no content" and was dropped:
the Big Book lost Bill's Story through A Vision for You, and the 12&12 lost
every Step except One and Four. Here noise headings are skipped when measuring a
section, running headers never start one, and a heading only opens a section if
real paragraphs follow it.

Stdlib only, so the graph builder, the research tools and tests can all use it.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

CONTENT_TYPES = frozenset({"paragraph", "list", "epigraph"})
MIN_CONTENT_BLOCKS = 3
# A heading text seen this many times in one book is a running header (the
# book title or a recurring label like "Thought for the Day"), not a chapter.
RUNNING_HEADER_REPEATS = 5
# Longer "chapters" (a heading-less book, a 600-paragraph section) are cut
# into page ranges so every section can be read in one sitting.
MAX_SECTION_CONTENT_BLOCKS = 150
_CONTENTS_LINE_RE = re.compile(r"(\s|\.)(\d{1,4}|[ivxlc]{1,7})$")

_DROP_CAP_RE = re.compile(r"^[\W\d]*[A-Za-z]?[\W\d]*$")
# "6 BUILDING A NEW LIFE 476" — a contents line with chapter and page numbers.
_TOC_LINE_RE = re.compile(r"^\d{1,3}\s+.+\s\d{1,4}$")
_NOISE_HEADING_RE = re.compile(
    r"copyright|©|isbn|printed in|all rights reserved|library of congress|www\.|\.com\b|"
    r"^contents$|^chapter page$|^page$|^index$|world services|\binc\.|medical association",
    re.IGNORECASE,
)
# Headings whose number is part of the name, not a page number.
_NUMBERED_NAME_RE = re.compile(
    r"^(chapter|step|tradition|concept|part|day|lesson|week|section|appendix)\s+([0-9]{1,3}|[ivxlc]{1,6})\b",
    re.IGNORECASE,
)
_LEADING_PAGE_RE = re.compile(r"^\d{1,4}\s+(?=[A-Za-z“\"'])")
_TRAILING_PAGE_RE = re.compile(r"(?<=[A-Za-z.!?’'\"”*)])\s+\d{1,4}$")
# Front-matter pages are numbered in lowercase roman ("THE DOCTOR'S OPINION xxv");
# only trusted after an all-caps header so "Mentally ill" survives.
_TRAILING_ROMAN_RE = re.compile(r"(?<=[A-Z.!?’'\"”*])\s+[ivxlc]{1,7}$")
_SMALL_WORDS = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on", "or", "the", "to", "vs", "with"}


def title_case(text: str) -> str:
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


def clean_heading(raw: str) -> tuple[str, bool] | None:
    """Normalise a manifest heading into ``(title, is_running_header)``, or None if it's noise."""
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
    running = False
    if not _NUMBERED_NAME_RE.match(text):
        # Page numbers glued to a heading mark a running header: "22 STEP ONE",
        # "STEP ONE 22", "THE DOCTOR'S OPINION xxv".
        stripped = _LEADING_PAGE_RE.sub("", text)
        stripped = _TRAILING_PAGE_RE.sub("", stripped)
        unroman = _TRAILING_ROMAN_RE.sub("", stripped)
        if unroman != stripped and unroman.isupper():
            stripped = unroman
        if stripped != text:
            running = True
            text = stripped
    text = text.rstrip("*†·• ").strip()
    if len(text) < 3 or not re.search(r"[A-Za-z]{2}", text):
        return None
    if text.isupper():
        text = title_case(text)
    if len(text) > 80:
        text = text[:77].rstrip() + "…"
    return text, running


def title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower().replace("’", "'"))


@dataclass
class OutlineEntry:
    title: str
    start: int            # block index of the heading (inclusive)
    end: int              # block index where the next section starts (exclusive)
    printed_page: Any = None
    block_id: str = ""
    content_blocks: int = 0


def build_outline(blocks: list[dict[str, Any]], min_content_blocks: int = MIN_CONTENT_BLOCKS,
                  max_content_blocks: int | None = MAX_SECTION_CONTENT_BLOCKS) -> list[OutlineEntry]:
    """Split a manifest's blocks into chapter-level sections, in reading order.

    Chapters come from headings, plus table-of-contents titles found at the
    start of paragraphs (some extractions glue "2 Staying away from the first
    drink" onto the chapter's first paragraph). Sections longer than
    ``max_content_blocks`` are cut into page ranges so no "chapter" is half a
    book.
    """
    starts = {e.start: e for e in _heading_outline(blocks, min_content_blocks)}
    for e in _toc_outline(blocks):
        if not any(abs(e.start - s) <= 2 for s in starts):
            starts[e.start] = e
    content_before = _content_prefix(blocks)
    ordered = [starts[k] for k in sorted(starts)]
    # A contents-page entry ("Dr Bob's Nightmare", a blurb, a page number) that
    # reappears later as the real chapter is not a chapter itself.
    later_keys: Counter = Counter(title_key(e.title) for e in ordered)
    for e in ordered:
        later_keys[title_key(e.title)] -= 1
        nxt = next((s for s in sorted(starts) if s > e.start), len(blocks))
        if later_keys[title_key(e.title)] > 0 and content_before[nxt] - content_before[e.start + 1] < 20:
            del starts[e.start]
    entries: list[OutlineEntry] = []
    for k in sorted(starts):
        # A TOC title matched right next to a heading leaves an empty section.
        if entries and content_before[k] - content_before[entries[-1].start + 1] <= 0:
            entries.pop()
        entries.append(starts[k])
    for k, e in enumerate(entries):
        e.end = entries[k + 1].start if k + 1 < len(entries) else len(blocks)
        e.content_blocks = content_before[e.end] - content_before[e.start + 1]
    if max_content_blocks:
        entries = _split_oversized(blocks, entries, max_content_blocks, content_before)
    return entries


def _content_prefix(blocks: list[dict[str, Any]]) -> list[int]:
    out = [0] * (len(blocks) + 1)
    for i, b in enumerate(blocks):
        out[i + 1] = out[i] + (1 if b.get("type") in CONTENT_TYPES else 0)
    return out


def _heading_outline(blocks: list[dict[str, Any]], min_content_blocks: int) -> list[OutlineEntry]:
    heads: list[tuple[int, str, str]] = []  # (block index, title, key)
    running_keys: set[str] = set()
    for i, b in enumerate(blocks):
        if b.get("type") != "heading":
            continue
        cleaned = clean_heading(b.get("text") or "")
        if cleaned is None:
            continue
        title, running = cleaned
        key = title_key(title)
        if not key:
            continue
        if running:
            running_keys.add(key)
        heads.append((i, title, key))

    repeats = Counter(k for _, _, k in heads)
    content_before = _content_prefix(blocks)

    def content_between(a: int, z: int) -> int:
        return content_before[z] - content_before[a]

    # Candidate starts: real headings, not running headers of a known chapter,
    # not labels repeated all through the book.
    cands = []
    for i, title, key in heads:
        if repeats[key] >= RUNNING_HEADER_REPEATS:
            continue
        is_running_copy = key in running_keys and any(k == key and j < i for j, _, k in heads)
        if is_running_copy:
            continue
        cands.append((i, title, key))

    entries: list[OutlineEntry] = []
    for n, (i, title, key) in enumerate(cands):
        # Measure up to the next candidate with a different title.
        nxt = len(blocks)
        for j, _, k in cands[n + 1:]:
            if k != key:
                nxt = j
                break
        if content_between(i + 1, nxt) < min_content_blocks:
            continue
        if _is_contents_listing(blocks[i + 1:nxt]):
            continue
        if entries and title_key(entries[-1].title) == key:
            continue  # same chapter title again (a header that slipped through)
        b = blocks[i]
        entries.append(OutlineEntry(title=title, start=i, end=len(blocks),
                                    printed_page=b.get("printed_page"), block_id=b.get("id") or ""))
    return entries


def _is_contents_listing(blocks: list[dict[str, Any]]) -> bool:
    """A run of blocks that is mostly table-of-contents lines ("Gratitude in Action 193")."""
    body = [b for b in blocks if b.get("type") in CONTENT_TYPES or b.get("type") == "heading"]
    if not body:
        return False
    listing = sum(1 for b in body if _CONTENTS_LINE_RE.search((b.get("text") or "").strip()))
    words = sum(len((b.get("text") or "").split()) for b in body)
    return listing / len(body) >= 0.5 and words / len(body) < 25


# ── Table-of-contents titles glued onto paragraphs ────────────────────────

_TOC_DOTS_RE = re.compile(r"([A-Z“\"][^.\n]{2,80}?)\s*(?:\.\s*){3,}(?:\d{1,4}|[ivxlc]{1,7})\b")
_TOC_NUMBERED_RE = re.compile(r"(?:^|\s)(\d{1,2})\s+([A-Z“\"].{2,90}?)(?=\s+\d{1,2}\s+[A-Z“\"]|\s*$)")


def _toc_titles(blocks: list[dict[str, Any]]) -> tuple[list[str], int]:
    """Chapter titles listed in the book's contents pages, and the block index where they end."""
    titles: list[str] = []
    last = -1
    for i, b in enumerate(blocks[: max(200, len(blocks) // 8)]):
        text = re.sub(r"\s+", " ", b.get("text") or "").strip()
        found = [m.group(1).strip() for m in _TOC_DOTS_RE.finditer(text)]
        if not found and re.match(r"(?i)^(table of )?contents\b", text):
            nums = list(_TOC_NUMBERED_RE.finditer(text))
            # Only a real numbered list: 1, 2, 3 …
            if len(nums) >= 3 and [int(m.group(1)) for m in nums[:3]] == [1, 2, 3]:
                found = [m.group(2).strip() for m in nums]
        if found:
            titles.extend(found)
            last = i
    return titles, last


def _toc_outline(blocks: list[dict[str, Any]]) -> list[OutlineEntry]:
    titles, toc_end = _toc_titles(blocks)
    if len(titles) < 3:
        return []
    keys = [title_key(t)[:40] for t in titles]
    entries: list[OutlineEntry] = []
    pos = toc_end + 1
    for title, key in zip(titles, keys):
        if len(key) < 6:
            continue
        for i in range(pos, len(blocks)):
            b = blocks[i]
            if b.get("type") not in CONTENT_TYPES and b.get("type") != "heading":
                continue
            head = title_key(re.sub(r"^\d{1,3}\s+", "", (b.get("text") or "")[:160]))
            if head.startswith(key):
                clean = re.sub(r"\s+", " ", title).strip(" .")
                entries.append(OutlineEntry(title=title_case(clean) if clean.isupper() else clean[:1].upper() + clean[1:],
                                            start=i, end=len(blocks),
                                            printed_page=b.get("printed_page"), block_id=b.get("id") or ""))
                pos = i + 1
                break
    return entries if len(entries) >= 3 else []


def _split_oversized(blocks: list[dict[str, Any]], entries: list[OutlineEntry], limit: int,
                     content_before: list[int]) -> list[OutlineEntry]:
    """Cut sections longer than ``limit`` content blocks into page-range parts."""
    if not entries and content_before[-1] > limit:
        entries = [OutlineEntry(title="", start=0, end=len(blocks), content_blocks=content_before[-1])]
    out: list[OutlineEntry] = []
    for e in entries:
        if e.content_blocks <= limit:
            out.append(e)
            continue
        n_parts = -(-e.content_blocks // limit)
        target = e.content_blocks / n_parts
        cuts = [e.start]
        seen = 0
        for i in range(e.start + 1, e.end):
            if blocks[i].get("type") in CONTENT_TYPES:
                seen += 1
                # Cut at a page turn once the part is big enough.
                if seen >= target * len(cuts) and len(cuts) < n_parts:
                    prev = blocks[i - 1].get("printed_page") or blocks[i - 1].get("physical_page")
                    here = blocks[i].get("printed_page") or blocks[i].get("physical_page")
                    if prev != here or seen >= target * len(cuts) + target / 3:
                        cuts.append(i)
        cuts.append(e.end)
        for k in range(len(cuts) - 1):
            a, z = cuts[k], cuts[k + 1]
            first = next((b for b in blocks[a:z] if b.get("printed_page") not in (None, "None")), None)
            last = next((b for b in reversed(blocks[a:z]) if b.get("printed_page") not in (None, "None")), None)
            pages = ""
            if first is not None and last is not None:
                p1, p2 = first.get("printed_page"), last.get("printed_page")
                pages = f"p. {p1}" if p1 == p2 else f"pp. {p1}–{p2}"
            base = e.title or "Text"
            title = f"{base} ({pages})" if pages else f"{base} (part {k + 1} of {len(cuts) - 1})"
            out.append(OutlineEntry(title=title, start=a, end=z,
                                    printed_page=blocks[a].get("printed_page"),
                                    block_id=blocks[a].get("id") or "",
                                    content_blocks=content_before[z] - content_before[a + 1 if k == 0 and e.title else a]))
    return out


def section_text(blocks: list[dict[str, Any]], start: int, end: int) -> list[dict[str, Any]]:
    """The readable blocks of a section, in order (headings kept so the reader sees structure)."""
    out = []
    for b in blocks[start:end]:
        t = b.get("type")
        if t in CONTENT_TYPES:
            out.append(b)
        elif t == "heading":
            cleaned = clean_heading(b.get("text") or "")
            if cleaned is not None and not cleaned[1]:
                out.append(b)
    return out
