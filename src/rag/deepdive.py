"""Deep-dive section assembly for recovery literature.

Assembles whole literature sections (Steps) from the REAL manifests so a
later generation layer can ground itself on complete, in-context source text
rather than retrieved snippets.

This module is intentionally lightweight and dependency-free: it only depends
on the standard library and ``src.rag.sections`` (the Wave-1, committed
section loader). It does NOT call the LLM, does not touch the network, and is
offline-unit-testable against a real manifest file on disk.
"""

from __future__ import annotations

import os
import re
from typing import Any

from src.rag.sections import load as sections_load

# Default location of the manifest corpus (the SMB-mounted, read-only store).
# Overridable via the MANIFESTS_DIR env var so tests can point elsewhere.
DEFAULT_MANIFESTS_DIR = "/Users/joshu/repos/sobriety-copilot/documents/.manifests"

_STEP_WORD_NUMS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
# An exact Step heading is exactly 'Step <num>' (e.g. 'Step One', 'Step 9').
# This deliberately EXCLUDES verbose sub-headings like
# 'Step Five. As we took inventory, ...' that some manifests carry as their
# own level-2 heading, so the canonical 12 steps are selected cleanly.
_STEP_HEADING_RE = re.compile(r"^Step\s+([A-Za-z]+|\d+)$", re.IGNORECASE)


def manifests_dir() -> str:
    """Return the configured manifests directory (default: the SMB store)."""
    return os.environ.get("MANIFESTS_DIR", DEFAULT_MANIFESTS_DIR)


def _is_step_heading(title: str) -> bool:
    m = _STEP_HEADING_RE.match(title.strip())
    if not m:
        return False
    token = m.group(1).lower()
    return token.isdigit() or token in _STEP_WORD_NUMS


def _step_number(title: str) -> int | None:
    m = _STEP_HEADING_RE.match(title.strip())
    if not m:
        return None
    token = m.group(1).lower()
    if token.isdigit():
        return int(token)
    return _STEP_WORD_NUMS.get(token)


def resolve_manifest_path(
    doc_id: str,
    explicit_dir: str | None = None,
) -> str | None:
    """Resolve a ``doc_id`` to a manifest file path.

    ``doc_id`` may already be a plain filename stem (e.g.
    ``twelve-steps-and-twelve-traditions``) in which case it maps directly to
    ``<dir>/<doc_id>.json``. Otherwise we fall back to matching any manifest
    whose ``source_file`` relative path contains ``doc_id`` as a substring, so
    bare book names (e.g. ``living-sober``) resolve even if their manifest
    doc_id differs.

    Returns None when nothing matches.
    """
    mdir = explicit_dir or manifests_dir()
    if not os.path.isdir(mdir):
        return None

    direct = os.path.join(
        mdir, f"{doc_id}.json" if not doc_id.endswith(".json") else doc_id
    )
    if os.path.isfile(direct):
        return direct

    # Fallback: substring match against source filename.
    stem = doc_id.lower().replace(".json", "")
    try:
        names = [n for n in os.listdir(mdir) if n.endswith(".json")]
    except OSError:
        return None
    for name in sorted(names):
        if stem in name.lower():
            return os.path.join(mdir, name)
    return None


def _section_listing(section: dict[str, Any]) -> dict[str, Any]:
    """Return the lightweight listing view of a section (no full text)."""
    text = section.get("content_text") or ""
    return {
        "title": section.get("title"),
        "order": section.get("order"),
        "word_count": section.get("word_count"),
        "preview": text[:500],
    }


def assemble_deepdive(
    manifest_path: str,
    section: str | None = None,
    *,
    step_only: bool = True,
) -> dict[str, Any]:
    """Assemble a deep-dive payload from a real manifest file.

    Uses ``src.rag.sections.load`` to split the manifest into structural
    sections, then filters to the canonical Step sections (when
    ``step_only=True``) and returns each with its full ``content_text`` so a
    downstream generation layer can use ``full_text`` as the long-context
    grounding source.

    When ``section`` is given (a step number, 'step one', or a section title),
    only that one section's full text is returned; otherwise all sections are
    returned with title + word_count + a 500-char preview.

    Returns a dict:
        {doc_id, title, requested_section, sections: [{title, order,
          word_count, preview, full_text?}]}   # full_text only when requested
    """
    doc = sections_load(manifest_path, heading_level=2)
    sections = doc.get("sections", [])

    if step_only:
        sections = [
            s for s in sections
            if _is_step_heading(s.get("title", ""))
        ]
        sections.sort(key=lambda s: _step_number(s.get("title", "")) or 0)

    requested = _match_requested(sections, section) if section else None

    if requested is not None:
        listing = _section_listing(requested)
        listing["full_text"] = requested.get("content_text") or ""
        out_sections = [listing]
    elif section is not None:
        # A specific section was requested but nothing matched — surface as
        # empty so the route can respond 404.
        out_sections = []
    else:
        out_sections = [_section_listing(s) for s in sections]

    return {
        "doc_id": doc.get("doc_id"),
        "title": doc.get("title"),
        "requested_section": requested.get("title") if requested is not None else None,
        "sections": out_sections,
    }


def _match_requested(
    sections: list[dict[str, Any]], section: str
) -> dict[str, Any] | None:
    """Resolve a requested section spec against the section list.

    Accepts a step number ('5', 'step five'), or an exact/loose title match
    ('Step Five', 'step 5', 'tradition one'). Returns None if no match.
    """
    spec = section.strip().lower()

    # Numeric or 'step N' resolution against step headings.
    for s in sections:
        title = s.get("title", "")
        num = _step_number(title)
        if num is not None:
            if spec in {str(num), f"step {num}", f"step {num:02d}"}:
                return s
        if spec == title.lower():
            return s

    # Loose substring title match (covers 'tradition one', unique titles).
    matches = [s for s in sections if spec in s.get("title", "").lower()]
    if len(matches) == 1:
        return matches[0]
    return None
