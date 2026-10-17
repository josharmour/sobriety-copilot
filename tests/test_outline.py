"""Chapter outline (src/rag/outline.py): synthetic cases + the real manifests."""

import json
import os

import pytest

from src.rag.outline import build_outline, clean_heading

MANIFESTS = os.path.join(os.path.dirname(__file__), "..", "documents", ".manifests")


def _h(i, text, page=None):
    return {"id": f"b{i:03d}", "type": "heading", "text": text, "printed_page": page}


def _p(i, text="Some paragraph text about the program.", page=None):
    return {"id": f"b{i:03d}", "type": "paragraph", "text": text, "printed_page": page}


def test_drop_cap_after_chapter_title_does_not_hide_the_chapter():
    blocks = [_h(0, "BILL’S STORY", 1), _h(1, "W"), *[_p(i, page=1) for i in range(2, 8)],
              _h(8, "THERE IS A SOLUTION", 17), _h(9, "“T"), *[_p(i, page=17) for i in range(10, 15)]]
    titles = [e.title for e in build_outline(blocks)]
    assert titles == ["Bill’s Story", "There Is a Solution"]


def test_running_headers_do_not_split_a_chapter():
    blocks = [_h(0, "Step One", 21), _h(1, "W"), *[_p(i, page=21) for i in range(2, 6)],
              _h(6, "22 STEP ONE", 22), *[_p(i, page=22) for i in range(7, 11)],
              _h(11, "Step Two", 25), *[_p(i, page=25) for i in range(12, 16)]]
    out = build_outline(blocks)
    assert [e.title for e in out] == ["Step One", "Step Two"]
    assert out[0].content_blocks == 8


def test_contents_listing_is_not_a_chapter():
    listing = [_p(i, f"Story number {i} {170 + i}") for i in range(1, 6)]
    blocks = [_h(0, "Pioneers of A.A."), *listing,
              _h(6, "Doctor Bob’s Nightmare", 171), *[_p(i) for i in range(7, 12)]]
    assert [e.title for e in build_outline(blocks)] == ["Doctor Bob’s Nightmare"]


def test_toc_titles_glued_to_paragraphs_become_chapters():
    toc = {"id": "t0", "type": "toc",
           "text": "Contents 1 Using this booklet 2 Staying away from the first drink 3 Using the 24-hour plan"}
    blocks = [toc,
              _p(1, "1 Using this booklet This is not a plan for recovery."), *[_p(i) for i in range(2, 6)],
              _p(6, "2 Staying away from the first drink Expressions commonly heard."), *[_p(i) for i in range(7, 10)],
              _p(10, "3 Using the 24-hour plan In AA we concentrate on today."), *[_p(i) for i in range(11, 14)]]
    titles = [e.title for e in build_outline(blocks)]
    assert titles == ["Using this booklet", "Staying away from the first drink", "Using the 24-hour plan"]


def test_oversized_sections_are_cut_into_page_ranges():
    blocks = [_h(0, "One Long Chapter", 1)] + [_p(i, page=1 + i // 10) for i in range(1, 301)]
    out = build_outline(blocks, max_content_blocks=100)
    assert len(out) == 3
    assert all(e.content_blocks <= 110 for e in out)
    assert out[0].title.startswith("One Long Chapter (pp. ")


def test_clean_heading_flags_running_headers():
    assert clean_heading("22 STEP ONE") == ("Step One", True)
    assert clean_heading("THE DOCTOR’S OPINION xxv") == ("The Doctor’s Opinion", True)
    assert clean_heading("Chapter 5") == ("Chapter 5", False)
    assert clean_heading("Mentally ill") == ("Mentally ill", False)
    assert clean_heading("W") is None


def _real(doc_id):
    path = os.path.join(MANIFESTS, f"{doc_id}.json")
    if not os.path.isfile(path):
        pytest.skip(f"manifest {doc_id} not present")
    with open(path, encoding="utf-8") as f:
        return [e.title for e in build_outline(json.load(f)["blocks"])]


def test_big_book_has_every_chapter():
    titles = _real("alcoholics-anonymous")
    chapters = ["The Doctor’s Opinion", "Bill’s Story", "There Is a Solution", "More About Alcoholism",
                "We Agnostics", "How It Works", "Into Action", "Working with Others", "To Wives",
                "The Family Afterward", "To Employers", "A Vision for You"]
    idx = [titles.index(c) for c in chapters]
    assert idx == sorted(idx), "chapters out of order"


def test_twelve_and_twelve_has_every_step_and_tradition():
    titles = _real("twelve-steps-and-twelve-traditions")
    words = ["One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve"]
    for w in words:
        assert f"Step {w}" in titles
        assert f"Tradition {w}" in titles


def test_living_sober_chapters_come_from_its_contents_page():
    titles = _real("living-sober")
    assert "Staying away from the first drink" in titles
    assert "Trying the Twelve Steps" in titles
    assert len(titles) >= 30
