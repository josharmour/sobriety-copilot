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

# Location of the manifest corpus. Production runs in Docker where the
# documents tree (incl. .manifests) is mounted at /app/documents; the SMB path
# below is the local (macOS dev) fallback. Override via the MANIFESTS_DIR env
# var (set in docker-compose app-env for the container).
CONTAINER_MANIFESTS_DIR = "/app/documents/.manifests"
LOCAL_MANIFESTS_DIR = "/Users/joshu/repos/sobriety-copilot/documents/.manifests"


def manifests_dir() -> str:
    """Return the configured manifests directory.

    Resolution order: MANIFESTS_DIR env var → container path (if it exists on
    disk) → local macOS SMB path. The container path is checked because the
    Docker image has no MANIFESTS_DIR baked in, and the default must point at
    real manifests in production as well as on a dev machine.
    """
    env = os.environ.get("MANIFESTS_DIR", "").strip()
    if env:
        return env
    if os.path.isdir(CONTAINER_MANIFESTS_DIR):
        return CONTAINER_MANIFESTS_DIR
    return LOCAL_MANIFESTS_DIR

_STEP_WORD_NUMS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
# An exact Step heading is exactly 'Step <num>' (e.g. 'Step One', 'Step 9').
# This deliberately EXCLUDES verbose sub-headings like
# 'Step Five. As we took inventory, ...' that some manifests carry as their
# own level-2 heading, so the canonical 12 steps are selected cleanly.
_STEP_HEADING_RE = re.compile(r"^Step\s+([A-Za-z]+|\d+)$", re.IGNORECASE)


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
    block_ids: list[str] | None = None,
    printed_page: int | str | None = None,
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

    ``block_ids`` / ``printed_page`` (from a retrieved chunk) scope the deep
    dive to the *actual* section the passage belongs to when ``section`` is not
    given — see ``resolve_section_for_blocks``. So a citation from "Step Four"
    deep-dives Step Four, not a whole-book overview.

    Returns a dict:
        {doc_id, title, requested_section, sections: [{title, order,
          word_count, preview, full_text?}]}   # full_text only when requested
    """
    doc = sections_load(manifest_path, heading_level=2)
    sections = doc.get("sections", [])

    if step_only:
        step_sections = [
            s for s in sections
            if _is_step_heading(s.get("title", ""))
        ]
        step_sections.sort(key=lambda s: _step_number(s.get("title", "")) or 0)
        # Only restrict to Step sections when this document actually HAS them
        # (the 12&12). Books like "As Bill Sees It" or "Daily Reflections" have
        # no Step headings — falling back to their real sections lets a deep
        # dive work there too instead of returning nothing.
        if step_sections:
            sections = step_sections

    requested = _match_requested(sections, section) if section else None

    # No explicit section but a retrieved passage's block_ids/page is given:
    # scope to that passage's containing section.
    if requested is None and not section and (block_ids or printed_page is not None):
        resolved = resolve_section_for_blocks(sections, block_ids, printed_page)
        if resolved is not None:
            requested = resolved

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


def resolve_section_for_blocks(
    sections: list[dict[str, Any]],
    block_ids: list[str] | None = None,
    printed_page: int | str | None = None,
) -> dict[str, Any] | None:
    """Find the section containing a given passage, by block_ids or page.

    The retrieval layer attaches ``block_ids`` and ``printed_page_start/end``
    to each returned chunk. This maps that passage back to the structural
    section it belongs to, so a deep-dive can be scoped to the *actual* section
    a citation came from instead of always defaulting to the whole document.

    Matching order:
    1. Best block_id overlap — the section whose block_ids is a superset of (or
       shares the most with) the passage's block_ids.
    2. Printed page range — a section whose heading printed_page (or page span)
       equals/contains the passage's printed page.
    3. Fallback: the first section (so a deep-dive still works when no section
       can be confidently resolved).

    Returns None only when there are no sections at all.
    """
    if not sections:
        return None

    block_ids = [b for b in (block_ids or []) if b]
    page = printed_page

    # 1) block_id overlap (most precise when block_ids present)
    if block_ids:
        best = None
        best_overlap = -1
        for s in sections:
            sbid = set(s.get("block_ids") or [])
            overlap = sum(1 for b in block_ids if b in sbid)
            if overlap > best_overlap:
                best_overlap = overlap
                best = s
        if best_overlap > 0:
            return best

    # 2) printed page containment (falls back for docs w/o block_ids)
    if page is not None:
        try:
            pnum = int(page)
        except (TypeError, ValueError):
            pnum = None
        if pnum is not None:
            for s in sections:
                sp = s.get("printed_page")
                if sp is not None:
                    try:
                        if int(sp) == pnum:
                            return s
                    except (TypeError, ValueError):
                        pass

    # 3) Fallback to first section
    return sections[0]
