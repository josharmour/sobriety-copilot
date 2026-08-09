"""Deep-dive GENERATION layer for recovery literature.

Turns the structure-aware section assembly from ``src.rag.deepdive`` into
grounded prose deep-dives via the local LLM engine.

This module is deliberately thin and fully offline-unit-testable: it accepts an
engine object (``InferenceEngine`` or any duck-typed object exposing
``.generate(prompt, ...) -> str``) and never constructs or reaches a network
itself. Tests pass a fake engine whose ``generate`` returns canned text.

Wave 3 (this module) builds on Wave 1-2:
- ``src.rag.deepdive.assemble_deepdive`` assembles section text (no LLM).
- This module adds ``generate_deepdive``, which grounds an ``engine.generate``
  call on that section text so a deep-dive is actually useful (grounded, not
  generic).
"""

from __future__ import annotations

from typing import Any

from src.prompts.templates import (
    DEEPDIVE_OVERVIEW_TEMPLATE,
    DEEPDIVE_SYSTEM_MESSAGE,
    DEEPDIVE_TEMPLATE,
    system_message_for_tone,
)
from src.rag.deepdive import assemble_deepdive


class DeepdiveGenerationError(RuntimeError):
    """Raised when the LLM engine fails to produce a deep-dive.

    A route wrapper can catch this and translate it to a 502, keeping the
    generation failure distinct from a 404 (doc/section not found) or a 500
    (assembly bug).
    """


def _render_listing(sections: list[dict[str, Any]]) -> str:
    """Render the ordered section listing used by the overview prompt."""
    lines = []
    for sec in sections:
        preview = (sec.get("preview") or "").replace("\n", " ").strip()
        lines.append(
            f"{sec.get('order')}. {sec.get('title') or '(untitled)'} "
            f"[{sec.get('word_count', 0)} words] — {preview[:200]}"
        )
    return "\n".join(lines)


def _compose_full_deepdive_prompt(
    doc_title: str | None, section: dict[str, Any]
) -> str:
    """Build the long-context user prompt for one section's full deep-dive."""
    return DEEPDIVE_TEMPLATE.format(
        doc_title=doc_title or "",
        title=section.get("title") or "",
        word_count=section.get("word_count", 0),
        section_text=section.get("full_text") or section.get("preview") or "",
    )


def _compose_overview_prompt(
    doc_title: str | None, sections: list[dict[str, Any]]
) -> str:
    """Build the ordered-overview prompt for all sections (summary_only)."""
    return DEEPDIVE_OVERVIEW_TEMPLATE.format(
        doc_title=doc_title or "",
        count=len(sections),
        listing=_render_listing(sections),
    )


def generate_deepdive(
    engine,
    manifest_path: str,
    section: str | None = None,
    tone: str = "warm",
    summary_only: bool = False,
    max_tokens: int = 2048,
    block_ids: list[str] | None = None,
    printed_page: int | str | None = None,
) -> dict[str, Any]:
    """Generate a grounded deep-dive for an assembled literature section.

    Args:
        engine: Any object exposing ``.generate(prompt, system_message=,
            enable_thinking=, max_tokens=) -> str``. In production this is
            ``src.inference.engine.InferenceEngine``; in tests it is a fake
            whose ``generate`` returns canned text.
        manifest_path: Path to the manifest JSON (see
            ``src.rag.deepdive.resolve_manifest_path``).
        section: Optional specific section to deep-dive (a step number, 'step
            one', or a section title). When None, either produce an ordered
            overview (``summary_only=True``), a full deep-dive, or — when
            ``block_ids``/``printed_page`` are provided — a deep-dive of the
            passage's actual containing section.
        tone: Tone variant used to pick the safety-bearing system message
            (warm/factual/reflective/brief).
        summary_only: When section is None, if True produce an ordered overview
            of every section instead of a full deep-dive.
        max_tokens: Max tokens requested from the engine.
        block_ids: Comma-passed block_ids of the retrieved passage; scopes the
            deep dive to that passage's section when ``section`` is omitted.
        printed_page: Printed page of the retrieved passage; same scoping.

    Returns:
        A dict:
            {
              "doc_id", "doc_title",
              "section_title",      # the section actually deep-dived, or None
              "word_count",         # section word_count used, or total for overview
              "mode": "section" | "overview" | "full",
              "text": "<generated deep-dive prose>",
            }

    Raises:
        DeepdiveGenerationError: when the assembly yields nothing usable or the
            engine fails to return text (so a route can map to HTTP 502).
    """
    payload = assemble_deepdive(
        manifest_path,
        section=section,
        block_ids=block_ids,
        printed_page=printed_page,
    )

    # Determine whether a *single, specific* section was selected — either by an
    # explicit `section`, or by scoping to a retrieved passage's containing
    # section via block_ids/printed_page (section-aware deep dive).
    scoped_to_section = section is not None or bool(block_ids) or printed_page is not None

    if scoped_to_section:
        # Long-context path: one specific section, grounded on its full text.
        out_sections = payload.get("sections") or []
        if not out_sections:
            raise DeepdiveGenerationError(
                f"No section matched request: {section!r}"
            )
        target = out_sections[0]
        mode = "section"
        if not (target.get("full_text") or target.get("preview")):
            raise DeepdiveGenerationError(
                f"Section {target.get('title')!r} has no text to ground on"
            )
        prompt = _compose_full_deepdive_prompt(payload.get("title"), target)
        result_title = target.get("title")
        word_count = target.get("word_count", 0)
    else:
        sections = payload.get("sections") or []
        if not sections:
            raise DeepdiveGenerationError("No sections available to summarize")
        if summary_only:
            mode = "overview"
            prompt = _compose_overview_prompt(payload.get("title"), sections)
            result_title = None
            word_count = sum(s.get("word_count", 0) for s in sections)
        else:
            # Full deep-dive over all sections: ground on their previews (the
            # full text of an entire book is too large for one context window).
            mode = "full"
            prompt = _compose_overview_prompt(payload.get("title"), sections)
            result_title = None
            word_count = sum(s.get("word_count", 0) for s in sections)

    # Leadership message layered on top of the tone's existing safety block.
    system_message = DEEPDIVE_SYSTEM_MESSAGE + system_message_for_tone(tone)

    try:
        text = engine.generate(
            prompt,
            system_message=system_message,
            enable_thinking=False,
            max_tokens=max_tokens,
        )
    except Exception as exc:  # network/API failures surface here
        raise DeepdiveGenerationError(f"Engine failed to generate deep-dive: {exc}") from exc

    if not text or not text.strip():
        raise DeepdiveGenerationError("Engine returned an empty deep-dive")

    return {
        "doc_id": payload.get("doc_id"),
        "doc_title": payload.get("title"),
        "section_title": result_title,
        "word_count": word_count,
        "mode": mode,
        "text": text.strip(),
    }
