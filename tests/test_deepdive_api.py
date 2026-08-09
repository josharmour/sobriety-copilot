"""Unit tests for the deep-dive section assembly logic.

These tests exercise ``src.rag.deepdive`` (the core assembly logic that the
thin ``/api/deepdive`` FastAPI route wraps) directly against the REAL
Twelve Steps & Twelve Traditions manifest on the SMB path. They are fully
offline: no LLM, no network, no FastAPI TestClient.

Note on FastAPI/TestClient: this repo's ``.venv`` does not ship fastapi/
starlette/pytest (the host-wide pytest env does), so these tests target the
plain-Python ``assemble_deepdive``/``resolve_manifest_path`` helpers rather
than the HTTP layer. The route itself is a thin wrapper over these same
functions and is exercised implicitly here.
"""

from __future__ import annotations

import os

import pytest

from src.rag import deepdive

# Real manifest on the SMB-mounted (read-only) corpus. Never git-tracked.
REAL_MANIFEST = (
    "/Users/joshu/repos/sobriety-copilot/documents/.manifests/"
    "twelve-steps-and-twelve-traditions.json"
)

REAL_DIR = os.path.dirname(REAL_MANIFEST)


@pytest.mark.skipif(
    not os.path.isfile(REAL_MANIFEST), reason="real manifest not present on SMB path"
)
def test_resolve_manifest_path_direct():
    path = deepdive.resolve_manifest_path(
        "twelve-steps-and-twelve-traditions", explicit_dir=REAL_DIR
    )
    assert path == REAL_MANIFEST


@pytest.mark.skipif(
    not os.path.isdir(REAL_DIR), reason="real manifest dir not present on SMB path"
)
def test_resolve_manifest_path_unknown_returns_none():
    assert deepdive.resolve_manifest_path("definitely-not-a-book", explicit_dir=REAL_DIR) is None


@pytest.mark.skipif(
    not os.path.isfile(REAL_MANIFEST), reason="real manifest not present on SMB path"
)
def test_all_twelve_steps_present_in_order():
    payload = deepdive.assemble_deepdive(REAL_MANIFEST)
    titles = [s["title"] for s in payload["sections"]]
    expected = [f"Step {w}" for w in (
        "One", "Two", "Three", "Four", "Five", "Six", "Seven",
        "Eight", "Nine", "Ten", "Eleven", "Twelve",
    )]
    assert titles == expected
    assert len(payload["sections"]) == 12


@pytest.mark.skipif(
    not os.path.isfile(REAL_MANIFEST), reason="real manifest not present on SMB path"
)
def test_step_one_section_substantial():
    payload = deepdive.assemble_deepdive(REAL_MANIFEST, section="step one")
    assert payload["requested_section"] == "Step One"
    assert len(payload["sections"]) == 1
    sec = payload["sections"][0]
    assert sec["title"] == "Step One"
    assert sec["word_count"] > 500
    assert sec["full_text"]  # non-empty full text for long-context grounding


@pytest.mark.skipif(
    not os.path.isfile(REAL_MANIFEST), reason="real manifest not present on SMB path"
)
def test_request_single_step_by_number():
    payload = deepdive.assemble_deepdive(REAL_MANIFEST, section="5")
    assert payload["requested_section"] == "Step Five"
    sec = payload["sections"][0]
    assert sec["full_text"]  # full text present when a section is requested


@pytest.mark.skipif(
    not os.path.isfile(REAL_MANIFEST), reason="real manifest not present on SMB path"
)
def test_listing_has_no_full_text():
    payload = deepdive.assemble_deepdive(REAL_MANIFEST)
    for sec in payload["sections"]:
        assert "full_text" not in sec  # avoid shipping entire book by default
        assert sec["preview"]  # 500-char preview present


@pytest.mark.skipif(
    not os.path.isfile(REAL_MANIFEST), reason="real manifest not present on SMB path"
)
def test_step_twelve_is_largest_step():
    payload = deepdive.assemble_deepdive(REAL_MANIFEST)
    wc = {s["title"]: s["word_count"] for s in payload["sections"]}
    assert wc["Step Twelve"] == max(wc.values())


@pytest.mark.skipif(
    not os.path.isfile(REAL_MANIFEST), reason="real manifest not present on SMB path"
)
def test_unknown_section_returns_empty():
    payload = deepdive.assemble_deepdive(REAL_MANIFEST, section="step ninety-nine")
    assert payload["sections"] == []


@pytest.mark.skipif(
    not os.path.isfile(REAL_MANIFEST), reason="real manifest not present on SMB path"
)
def test_missing_manifest_raises():
    with pytest.raises(FileNotFoundError):
        deepdive.assemble_deepdive("/nonexistent/manifest.json")
