"""Unit tests for the manifest-based section loader in src.rag.sections.

This module imports ONLY the stdlib and ``src.rag.sections`` — no chromadb,
Ollama, retriever, or indexer — so it runs in a plain pytest invocation
without heavy/network deps.
"""
import pytest

from src.rag.sections import load, split_blocks, identify_sections_steps


# -- Inline fixture: a small book with 3 heading-delimited chapters -----------
# Exercises the step helper via 'Step One'/'Step Two'/'Step Three'.
FIXTURE_MANIFEST = {
    "schema_version": 1,
    "doc_id": "twelve-steps-and-twelve-traditions",
    "source_file": "/fake/twelve-steps-and-twelve-traditions.pdf",
    "title": "Twelve Steps and Twelve Traditions",
    "author": "Alcoholics Anonymous",
    "category": "12-step",
    "blocks": [
        # Front matter before the first heading (should not form its own
        # section, just skipped).
        {"id": "b00001", "type": "paragraph", "text": "FOREWORD"},
        # --- Chapter 1 -----------------------------------------------------
        {
            "id": "b00002",
            "type": "heading",
            "text": "Step One: We admitted we were powerless",
            "level": 2,
            "printed_page": 21,
        },
        {"id": "b00003", "type": "paragraph", "text": "Who cares to admit complete defeat?"},
        {"id": "b00004", "type": "list", "text": "first admission"},
        {"id": "b00005", "type": "epigraph", "text": "That the great fact is just this."},
        # --- Chapter 2 -----------------------------------------------------
        {
            "id": "b00006",
            "type": "heading",
            "text": "Step Two: Came to believe",
            "level": 2,
            "printed_page": 29,
        },
        {"id": "b00007", "type": "paragraph", "text": "We soon saw that the process was made clear."},
        # --- Chapter 3 -----------------------------------------------------
        {
            "id": "b00008",
            "type": "heading",
            "text": "Step Three: Made a decision",
            "level": 2,
            "printed_page": 34,
        },
        {"id": "b00009", "type": "paragraph", "text": "The first requirement is that we be convinced."},
        {"id": "b00010", "type": "paragraph", "text": "Then we go ahead and decide."},
    ],
    "lint": {},
}


def test_section_count():
    doc = load(FIXTURE_MANIFEST)
    # 3 headings => 3 sections (front-matter paragraph before first heading
    # is skipped, not made into its own section).
    assert len(doc["sections"]) == 3


def test_title_and_meta_extraction():
    doc = load(FIXTURE_MANIFEST)
    assert doc["doc_id"] == "twelve-steps-and-twelve-traditions"
    assert doc["title"] == "Twelve Steps and Twelve Traditions"
    assert doc["author"] == "Alcoholics Anonymous"


def test_ordering_and_fields():
    doc = load(FIXTURE_MANIFEST)
    sections = doc["sections"]
    assert [s["order"] for s in sections] == [1, 2, 3]
    assert sections[0]["title"].startswith("Step One")
    assert sections[1]["title"].startswith("Step Two")
    assert sections[2]["title"].startswith("Step Three")
    # heading_level captured from the block metadata
    assert all(s["heading_level"] == 2 for s in sections)
    # block indices are contiguous and non-overlapping
    assert sections[0]["block_indices"] == [1, 2, 3, 4]
    assert sections[0]["para_start"] == 1
    assert sections[0]["para_end"] == 4


def test_block_ids_recorded():
    doc = load(FIXTURE_MANIFEST)
    assert doc["sections"][0]["block_ids"] == [
        "b00002", "b00003", "b00004", "b00005",
    ]


def test_word_count_per_section():
    doc = load(FIXTURE_MANIFEST)
    s1, s2, s3 = doc["sections"]
    # Step One: 3 content blocks -> "Who cares to admit complete defeat?" (6)
    #           + "first admission" (2) + "That the great fact is just this." (7)
    assert s1["word_count"] == 15
    # Step Two: 1 content block -> 9 words
    assert s2["word_count"] == 9
    # Step Three: "The first requirement is that we be convinced." (8)
    #             + "Then we go ahead and decide." (6)
    assert s3["word_count"] == 14


def test_content_text_contains_correct_blocks():
    doc = load(FIXTURE_MANIFEST)
    s1 = doc["sections"][0]
    assert "Who cares to admit complete defeat?" in s1["content_text"]
    assert "first admission" in s1["content_text"]
    assert "great fact is just this." in s1["content_text"]
    # Heading text itself is NOT part of content_text (delimiter only), and
    # chapter 2's content is not in chapter 1.
    assert "Step One" not in s1["content_text"]
    assert "process was made clear" not in s1["content_text"]


def test_printed_page_from_heading_metadata():
    doc = load(FIXTURE_MANIFEST)
    assert doc["sections"][0]["printed_page"] == 21
    assert doc["sections"][2]["printed_page"] == 34


def test_split_blocks_returns_sections():
    sections = split_blocks(FIXTURE_MANIFEST["blocks"])
    assert len(sections) == 3
    assert sections[1]["title"].startswith("Step Two")


def test_identify_sections_steps_order():
    steps = identify_sections_steps(FIXTURE_MANIFEST, expected=3)
    assert [s["title"] for s in steps] == [
        s["title"] for s in load(FIXTURE_MANIFEST)["sections"]
    ]
    assert [s["order"] for s in steps] == [1, 2, 3]
    # notes below: order is document order, already ascending by step number


def test_step_number_parses_spelled_and_digit_forms():
    from src.rag.sections import _step_number
    assert _step_number("Step One: We admitted") == 1
    assert _step_number("Step Nine: Made direct amends") == 9
    assert _step_number("Step 12: Service") == 12
    assert _step_number("Tradition Seven") is None
    assert _step_number("Chapter One") is None


def test_identify_sections_steps_raises_on_missing_steps():
    # A book that skips from Step One straight to Step Three is not an
    # unbroken run, so the helper must reject it.
    broken = {
        "doc_id": "broken",
        "title": "Broken",
        "blocks": [
            {"id": "b1", "type": "heading", "level": 2, "text": "Step One"},
            {"id": "b2", "type": "paragraph", "text": "alpha"},
            {"id": "b3", "type": "heading", "level": 2, "text": "Step Three"},
            {"id": "b4", "type": "paragraph", "text": "beta"},
        ],
    }
    with pytest.raises(AssertionError):
        identify_sections_steps(broken, expected=3)


def test_load_accepts_json_file_path(tmp_path):
    import json
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(FIXTURE_MANIFEST), encoding="utf-8")
    doc = load(str(path))
    assert doc["title"] == "Twelve Steps and Twelve Traditions"
    assert len(doc["sections"]) == 3


def test_no_headings_returns_single_unheaded_section():
    blocks = [
        {"id": "b1", "type": "paragraph", "text": "hello world"},
        {"id": "b2", "type": "paragraph", "text": "foo bar baz"},
    ]
    doc = load({"doc_id": "x", "title": "X", "blocks": blocks})
    assert len(doc["sections"]) == 1
    assert doc["sections"][0]["title"] == ""
    assert doc["sections"][0]["word_count"] == 5
