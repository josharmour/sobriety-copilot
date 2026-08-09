"""Manifest-based section loader for recovery literature.

Reads a canonical recovery-literature manifest JSON (as produced by
``src.rag.manifest_builder``) and splits its flat ``blocks`` list into
structural sections at heading boundaries.

This module is intentionally dependency-free: it imports only the standard
library. It does NOT import ``src.rag.retriever``, ``src.rag.indexer``,
chromadb, or Ollama, so it can be imported and unit-tested without any heavy
or network deps.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Block types that carry readable content (words). Heading blocks are the
# section delimiters, so they are excluded from a section's word_count and
# content_text.
_CONTENT_TYPES = {"paragraph", "list", "epigraph"}

# Spelled-out step numbers, for the 12&12 step helper.
_STEP_WORD_NUMS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}


def _parse_manifest(path_or_dict: str | dict[str, Any]) -> dict[str, Any]:
    """Accept either a manifest dict or a path to a JSON manifest file."""
    if isinstance(path_or_dict, dict):
        return path_or_dict
    with open(path_or_dict, encoding="utf-8") as fh:
        return json.load(fh)


def _word_count(text: str) -> int:
    """Count whitespace-separated tokens in a block's text."""
    return len(text.split())


def _make_section(sections_so_far: list[dict[str, Any]], heading: dict[str, Any], index: int) -> dict[str, Any]:
    """Open a new section anchored at a heading block."""
    order = len(sections_so_far) + 1
    return {
        "id": f"section_{order:03d}",
        "title": heading.get("text", ""),
        "order": order,
        "heading_level": heading.get("level"),
        "block_ids": [heading.get("id")],
        "block_indices": [index],
        "para_start": index,
        "para_end": index,
        "printed_page": heading.get("printed_page"),
        "word_count": 0,
        "content_text": "",
    }


def _finalize(section: dict[str, Any]) -> dict[str, Any]:
    """Compute content_text and word_count from a section's content blocks.

    Consumed from ``section['_content']``; the internal accumulator is
    removed so the returned structure is clean and JSON-serializable.
    """
    content = section.pop("_content", [])
    texts = [b.get("text", "") for b in content]
    section["content_text"] = "\n".join(t for t in texts if t)
    section["word_count"] = sum(_word_count(t) for t in texts)
    return section


def split_blocks(
    blocks: list[dict[str, Any]],
    heading_level: int | None = None,
    keep_trailing_text: bool = True,
) -> list[dict[str, Any]]:
    """Split a flat block list into sections at each heading block.

    A section is the heading block plus every content block that follows it
    up to (but not including) the next heading. Content blocks appearing
    before the first heading (front matter) are skipped unless
    ``keep_trailing_text`` is set and they are the trailing un-headed tail.

    ``heading_level`` optionally restricts section boundaries to headings of
    exactly that level; headings of other levels are then treated as content.
    """
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    pending: list[dict[str, Any]] = []  # un-headed leading blocks (front matter)

    for index, block in enumerate(blocks):
        btype = block.get("type")
        is_heading = btype == "heading" and (
            heading_level is None or block.get("level") == heading_level
        )
        if is_heading:
            if current is not None:
                sections.append(_finalize(current))
            current = _make_section(sections, block, index)
            pending = []
        elif current is not None:
            current.setdefault("_content", []).append(block)
            current["block_ids"].append(block.get("id"))
            current["block_indices"].append(index)
            current["para_end"] = index
        else:
            pending.append(block)

    if current is not None:
        sections.append(_finalize(current))
    elif keep_trailing_text and pending:
        # No headings at all in the document: expose everything as a single
        # un-headed section so content is never silently dropped.
        unheaded = {
            "id": "section_001",
            "title": "",
            "order": 1,
            "heading_level": None,
            "block_ids": [b.get("id") for b in pending],
            "block_indices": list(range(len(pending))),
            "para_start": 0,
            "para_end": len(pending) - 1,
            "printed_page": None,
            "_content": pending,
            "word_count": 0,
            "content_text": "",
        }
        return [_finalize(unheaded)]

    return sections


def load(path_or_dict: str | dict[str, Any], heading_level: int | None = None) -> dict[str, Any]:
    """Load a manifest and return its structural sections.

    Returns a dict with ``doc_id``, ``title``, ``author``, ``category`` and an
    ordered ``sections`` list produced by the generic heading-based split.
    """
    manifest = _parse_manifest(path_or_dict)
    sections = split_blocks(manifest.get("blocks", []), heading_level=heading_level)
    return {
        "doc_id": manifest.get("doc_id"),
        "title": manifest.get("title"),
        "author": manifest.get("author"),
        "category": manifest.get("category"),
        "sections": sections,
    }


def _step_number(title: str) -> int | None:
    """Parse the numeric step from a heading title like 'Step One' or 'Step 9'.

    Returns None if the title is not a Step heading.
    """
    match = re.match(r"^\s*step\s+([a-z]+|\d+)\b", title, re.IGNORECASE)
    if not match:
        return None
    token = match.group(1).lower()
    if token.isdigit():
        return int(token)
    return _STEP_WORD_NUMS.get(token)


def identify_sections_steps(
    manifest: dict[str, Any] | str,
    heading_level: int = 2,
    expected: int | None = 12,
) -> list[dict[str, Any]]:
    """Step-specific helper for the Twelve Steps & Twelve Traditions.

    Collects the Step-heading sections in document order, asserts they form an
    unbroken run numbered 1..N, and returns them ordered by step number.

    Raises ``AssertionError`` if a Step heading is missing or out of order, or
    (when ``expected`` is given, default 12 for the 12&12) the run is not the
    full expected length.
    """
    doc = load(manifest, heading_level=heading_level)
    step_sections: list[dict[str, Any]] = []
    seen: set[int] = set()

    for section in doc["sections"]:
        num = _step_number(section.get("title", ""))
        if num is None:
            continue
        assert num not in seen, f"duplicate Step heading: {section['title']!r}"
        seen.add(num)
        step_sections.append(section)

    step_sections.sort(key=lambda s: _step_number(s.get("title", "")) or 0)

    if not step_sections:
        raise AssertionError("no Step headings found in manifest")
    nums = [_step_number(s.get("title", "")) for s in step_sections]
    expected_nums = list(range(1, len(nums) + 1))
    if nums != expected_nums:
        raise AssertionError(
            f"Step headings are not contiguous from 1: got {nums}, expected {expected_nums}"
        )
    if expected is not None and len(step_sections) != expected:
        raise AssertionError(
            f"expected {expected} Step sections, found {len(step_sections)}"
        )
    return step_sections
