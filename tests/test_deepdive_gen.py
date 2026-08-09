"""Unit tests for the deep-dive GENERATION layer (src.rag.deepdive_gen).

These tests exercise ``generate_deepdive`` directly against a FAKE engine
(no network, no real InferenceEngine, no vLLM/Ollama). They build a small real
manifest JSON on disk (via tmp_path) so the assembly layer
(``src.rag.deepdive.assemble_deepdive``) can read it offline, then drive the
generation with a canned-response engine.

Like ``test_deepdive_api.py``, this repo's .venv does not ship fastapi/
starlette (pydantic_core binary isn't built), so these tests target the
plain-Python ``generate_deepdive`` function rather than the HTTP layer. The
route is a thin wrapper that translates ``DeepdiveGenerationError`` to a 502,
which is asserted explicitly here (test_engine_failure_raises_generation_error).
"""

from __future__ import annotations

import json

import pytest

from src.rag import deepdive_gen
from src.rag.deepdive_gen import DeepdiveGenerationError, generate_deepdive


# --- Fake engine -------------------------------------------------------------


class FakeEngine:
    """Records every generate() call and returns a canned string."""

    def __init__(self, canned: str = "canned deep-dive text", fail: bool = False):
        self.canned = canned
        self.fail = fail
        self.calls: list[dict] = []

    def generate(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        if self.fail:
            raise RuntimeError("connection refused to vLLM")
        return self.canned


# --- Manifest helpers --------------------------------------------------------


def _make_manifest(path, doc_id="twelve-steps-and-twelve-traditions", title="Twelve Steps and Twelve Traditions"):
    """Write a small two-section manifest JSON on disk and return its path."""
    path = path / f"{doc_id}.json"
    manifest = {
        "doc_id": doc_id,
        "title": title,
        "blocks": [
            {"type": "heading", "level": 2, "text": "Step One", "id": "h1"},
            {"type": "paragraph", "text": "We admitted we were powerless over alcohol.", "id": "b1"},
            {"type": "paragraph", "text": "This is the text of step one." * 5, "id": "b2"},
            {"type": "heading", "level": 2, "text": "Step Two", "id": "h2"},
            {"type": "paragraph", "text": "Came to believe that a Power greater than ourselves could restore us to sanity.", "id": "b3"},
        ],
    }
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return str(path)


# --- Tests -------------------------------------------------------------------


def test_specific_section_deepdive_returns_canned_text_and_grounds_prompt(tmp_path):
    manifest = _make_manifest(tmp_path)
    engine = FakeEngine(canned="Here is your deep dive on Step One.")

    result = generate_deepdive(engine, manifest, section="step one")

    # (a) specific-section deep dive returns the canned engine text
    assert result["text"] == "Here is your deep dive on Step One."
    assert result["mode"] == "section"
    assert result["section_title"] == "Step One"
    assert result["word_count"] > 0

    # The prompt the engine received must contain the section's content.
    assert len(engine.calls) == 1
    prompt = engine.calls[0]["prompt"]
    assert "Step One" in prompt
    assert "We admitted we were powerless" in prompt  # grounded on full text
    assert "Step Two" not in prompt  # only the requested section, not the whole doc


def test_specific_section_passes_full_text_into_prompt(tmp_path):
    manifest = _make_manifest(tmp_path)
    engine = FakeEngine()

    generate_deepdive(engine, manifest, section="step two")

    prompt = engine.calls[0]["prompt"]
    # long-context path grounds on the section's full content_text
    assert "Came to believe that a Power greater than ourselves" in prompt
    assert "Step One" not in prompt


def test_all_sections_summary_list_works(tmp_path):
    manifest = _make_manifest(tmp_path)
    engine = FakeEngine(canned="Ordered overview of the whole book.")

    result = generate_deepdive(engine, manifest, summary_only=True)

    assert result["text"] == "Ordered overview of the whole book."
    assert result["mode"] == "overview"
    assert result["section_title"] is None
    assert result["word_count"] > 0

    # The overview prompt must reference both section titles in order.
    prompt = engine.calls[0]["prompt"]
    assert "Step One" in prompt
    assert "Step Two" in prompt
    assert "1." in prompt and "2." in prompt


def test_engine_failure_raises_generation_error_for_route_502(tmp_path):
    """A failing engine must raise DeepdiveGenerationError (route -> HTTP 502)."""
    manifest = _make_manifest(tmp_path)
    engine = FakeEngine(fail=True)

    with pytest.raises(DeepdiveGenerationError) as excinfo:
        generate_deepdive(engine, manifest, section="step one")

    assert "Engine failed" in str(excinfo.value)


def test_empty_engine_output_raises_generation_error(tmp_path):
    """An engine that returns empty text must be treated as a generation failure."""
    manifest = _make_manifest(tmp_path)
    engine = FakeEngine(canned="   ")

    with pytest.raises(DeepdiveGenerationError):
        generate_deepdive(engine, manifest, section="step one")


def test_prompt_includes_safety_and_program_first_guardrails(tmp_path):
    """(d) The prompt must carry program-first guardrails (supplement/sponsor)."""
    manifest = _make_manifest(tmp_path)
    engine = FakeEngine()

    generate_deepdive(engine, manifest, section="step one")
    prompt = engine.calls[0]["prompt"]
    assert "supplement" in prompt.lower()
    assert "sponsor" in prompt.lower()

    # tone drives the safety-bearing system message, and the deep-dive system
    # message layers on leadership guidance.
    sys_msg = engine.calls[0].get("system_message", "")
    assert "deep-dive" in sys_msg.lower()
    assert "non-judgmental" in sys_msg.lower()  # inherited from the tone's safety block


def test_no_matching_section_raises_generation_error(tmp_path):
    """An unknown section surfaces as a generation error the route 502s on."""
    manifest = _make_manifest(tmp_path)
    engine = FakeEngine()

    with pytest.raises(DeepdiveGenerationError):
        generate_deepdive(engine, manifest, section="step ninety-nine")

    assert engine.calls == []  # never even reached the engine
