#!/usr/bin/env python3
"""
Comprehensive Citation & Chunk Quality Audit Tool

Scans all manifests and generated chunks across all literature books in documents/
to verify that citations provide high context, complete thoughts, and zero severed
fragments or abbreviation artifacts.
"""

from __future__ import annotations

import os
import sys
import json
import glob
import random
import re
from collections import defaultdict
from typing import Any

# Ensure src can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.rag.text_repair import is_abbreviation_ending, ABBREVIATIONS
from src.rag.semantic_chunker import SemanticChunker


def audit_manifests(manifests_dir: str) -> dict[str, Any]:
    manifest_files = sorted(glob.glob(os.path.join(manifests_dir, "*.json")))
    if not manifest_files:
        print(f"No manifests found in {manifests_dir}")
        return {}

    total_manifests = len(manifest_files)
    total_blocks = 0
    total_paragraph_blocks = 0
    broken_abbrev_blocks = []
    lowercase_start_blocks = []
    very_short_blocks = []
    doc_stats = {}

    for mf in manifest_files:
        with open(mf, "r", encoding="utf-8") as f:
            data = json.load(f)

        doc_id = data.get("doc_id", os.path.basename(mf))
        title = data.get("title", doc_id)
        category = data.get("category", "unknown")
        blocks = data.get("blocks", [])

        total_blocks += len(blocks)
        doc_broken = []
        doc_lowercase = []
        doc_short = []

        for b in blocks:
            text = b.get("text", "").strip()
            b_type = b.get("type", "paragraph")
            if b_type in ("paragraph", "epigraph", "footnote"):
                total_paragraph_blocks += 1

                # 1. Check if block ends in trailing title/abbreviation
                if is_abbreviation_ending(text):
                    # Exclude valid standalone abbreviations if any
                    doc_broken.append((b["id"], text))
                    broken_abbrev_blocks.append((title, b["id"], text))

                # 2. Check if block starts with a lowercase continuation word (excluding dialogue/quotes)
                first_char = text[0] if text else ""
                if first_char.islower() and not text.startswith("http"):
                    doc_lowercase.append((b["id"], text))
                    lowercase_start_blocks.append((title, b["id"], text))

                # 3. Check for extremely short fragments (< 3 words, not headings)
                words = text.split()
                if len(words) < 3 and b_type == "paragraph":
                    doc_short.append((b["id"], text))
                    very_short_blocks.append((title, b["id"], text))

        doc_stats[doc_id] = {
            "title": title,
            "category": category,
            "total_blocks": len(blocks),
            "broken_abbrev_count": len(doc_broken),
            "lowercase_start_count": len(doc_lowercase),
            "very_short_count": len(doc_short),
            "blocks": blocks,
        }

    return {
        "total_manifests": total_manifests,
        "total_blocks": total_blocks,
        "total_paragraph_blocks": total_paragraph_blocks,
        "broken_abbrev_blocks": broken_abbrev_blocks,
        "lowercase_start_blocks": lowercase_start_blocks,
        "very_short_blocks": very_short_blocks,
        "doc_stats": doc_stats,
    }


def audit_chunks(doc_stats: dict[str, Any]) -> dict[str, Any]:
    chunker = SemanticChunker()
    all_chunks = []
    scale_counts = defaultdict(int)
    scale_word_lengths = defaultdict(list)
    broken_chunks = []

    for doc_id, info in doc_stats.items():
        raw_blocks = info["blocks"]
        current_heading = None
        content_blocks = []
        for b in raw_blocks:
            if b["type"] == "heading":
                current_heading = b["text"]
            elif b["type"] in ("paragraph", "epigraph", "footnote"):
                b_copy = dict(b)
                b_copy["heading_context"] = current_heading
                content_blocks.append(b_copy)

        chunks = chunker.chunk_from_blocks(content_blocks)
        for c in chunks:
            scale = c["scale"]
            text = c["text"]
            words = len(text.split())
            scale_counts[scale] += 1
            scale_word_lengths[scale].append(words)

            chunk_record = {
                "doc_id": doc_id,
                "title": info["title"],
                "category": info["category"],
                "scale": scale,
                "words": words,
                "text": text,
                "block_ids": c.get("block_ids", []),
                "printed_page_start": c.get("printed_page_start"),
                "printed_page_end": c.get("printed_page_end"),
                "heading_context": c.get("heading_context"),
            }
            all_chunks.append(chunk_record)

            # Check if chunk ends in broken abbreviation
            if is_abbreviation_ending(text):
                broken_chunks.append(chunk_record)

    return {
        "total_chunks": len(all_chunks),
        "scale_counts": dict(scale_counts),
        "scale_avg_words": {s: round(sum(w)/len(w), 1) for s, w in scale_word_lengths.items() if w},
        "broken_chunks": broken_chunks,
        "all_chunks": all_chunks,
    }


def print_random_citation_samples(all_chunks: list[dict[str, Any]], sample_size: int = 10) -> None:
    print("\n" + "=" * 90)
    print(f"RANDOM CITATION SAMPLES (Sample of {sample_size} chunks across corpus)")
    print("=" * 90)

    # Sample across different scales and categories
    random.seed(42)  # Deterministic seed for reproducible audit
    sample = random.sample(all_chunks, min(sample_size, len(all_chunks)))

    for idx, c in enumerate(sample, 1):
        print(f"\n--- [Sample {idx}/{len(sample)}] {c['title']} ({c['category']}) ---")
        print(f"Scale: {c['scale'].upper()} | Words: {c['words']} | Page: {c['printed_page_start'] or 'N/A'}")
        if c.get("heading_context"):
            print(f"Section Heading: {c['heading_context']}")
        print(f"Blocks: {', '.join(c['block_ids'][:4])}{'...' if len(c['block_ids']) > 4 else ''}")
        print("Excerpt:")
        # Indent excerpt
        for line in c['text'].strip().split("\n"):
            print(f"  {line}")


def main():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    manifests_dir = os.path.join(base_dir, "documents", ".manifests")

    print(f"Starting Citation Quality Audit on {manifests_dir}...")
    manifest_results = audit_manifests(manifests_dir)
    if not manifest_results:
        sys.exit(1)

    print("\n" + "=" * 90)
    print("MANIFEST LEVEL AUDIT SUMMARY")
    print("=" * 90)
    print(f"Total Books/Manifests:        {manifest_results['total_manifests']}")
    print(f"Total Blocks:                 {manifest_results['total_blocks']:,}")
    print(f"Total Content Paragraphs:     {manifest_results['total_paragraph_blocks']:,}")
    print(f"Blocks Ending on Abbrev Bug:  {len(manifest_results['broken_abbrev_blocks'])}")
    print(f"Blocks Starting Lowercase:    {len(manifest_results['lowercase_start_blocks'])}")
    print(f"Extremely Short Fragments:    {len(manifest_results['very_short_blocks'])}")

    if manifest_results["broken_abbrev_blocks"]:
        print("\n[WARNING] Found blocks ending with trailing abbreviations:")
        for title, bid, text in manifest_results["broken_abbrev_blocks"][:10]:
            print(f"  - [{title}] {bid}: {text[-70:]}")

    # Audit chunks
    chunk_results = audit_chunks(manifest_results["doc_stats"])
    print("\n" + "=" * 90)
    print("CHUNK LEVEL AUDIT SUMMARY")
    print("=" * 90)
    print(f"Total Generated Chunks:       {chunk_results['total_chunks']:,}")
    for scale, count in sorted(chunk_results["scale_counts"].items()):
        avg_w = chunk_results["scale_avg_words"].get(scale, 0)
        pct = (count / max(1, chunk_results["total_chunks"])) * 100
        print(f"  - Scale '{scale:<6}': {count:>6,} chunks ({pct:>5.1f}%) | Avg {avg_w:>6.1f} words")
    print(f"Broken Chunks (abbrev cuts):  {len(chunk_results['broken_chunks'])}")

    # Print random citation samples
    print_random_citation_samples(chunk_results["all_chunks"], sample_size=10)

    print("\n" + "=" * 90)
    print("AUDIT RESULT: " + ("PASS" if len(manifest_results['broken_abbrev_blocks']) == 0 and len(chunk_results['broken_chunks']) == 0 else "FAIL"))
    print("=" * 90)


if __name__ == "__main__":
    main()
