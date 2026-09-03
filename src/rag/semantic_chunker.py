"""Multi-scale semantic chunking for recovery literature.

Produces chunks at four granularities so retrieval can match
single-line prayers, medium passages, chapter-length sections,
and overlapping multi-page topic windows.
"""

from __future__ import annotations

import re

from .text_repair import is_abbreviation_ending, is_terminal_sentence_ending

PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")

# Scale boundaries (word counts)
SMALL_MIN = 4
SMALL_MAX = 100
MEDIUM_MIN = 80
MEDIUM_MAX = 400
LARGE_MAX = 1500
TOPIC_MIN = 600
TOPIC_TARGET = 1400
TOPIC_MAX = 2800
TOPIC_STRIDE_WORDS = 700


class SemanticChunker:
    def __init__(self, similarity_threshold: float = 0.55):
        self.similarity_threshold = similarity_threshold

    def _split_paragraphs(self, text: str) -> list[str]:
        paragraphs = PARAGRAPH_SPLIT_RE.split(text)
        return [paragraph.strip() for paragraph in paragraphs if paragraph.strip()]

    def _split_sentences(self, text: str) -> list[str]:
        if not text:
            return []
        pattern = r"([.!?][\x22\x27\u201d\u201c\u2019\u2018)]?)\s+([A-Z\x22\u201c\u2018])"
        sentences = []
        start = 0
        for match in re.finditer(pattern, text):
            split_pos = match.start(1) + len(match.group(1))
            prefix = text[start:split_pos]
            words = prefix.strip().split()
            if words:
                last_word = words[-1]
                if is_abbreviation_ending(last_word):
                    continue
            sentences.append(text[start:split_pos].strip())
            start = match.start(2)

        remainder = text[start:].strip()
        if remainder:
            sentences.append(remainder)
        return [s for s in sentences if s]

    def _word_count(self, text: str) -> int:
        return len(text.split())

    def _make_chunk(
        self,
        text: str,
        scale: str,
        start_paragraph: int,
        end_paragraph: int,
    ) -> dict:
        return {
            "text": text,
            "scale": scale,
            "start_paragraph": start_paragraph,
            "end_paragraph": end_paragraph,
        }

    def _split_long_paragraph(self, text: str) -> list[str]:
        """Split a paragraph over MEDIUM_MAX words at sentence boundaries."""
        sentences = self._split_sentences(text)
        if len(sentences) <= 1:
            words = text.split()
            chunks = []
            for index in range(0, len(words), MEDIUM_MAX):
                chunk = " ".join(words[index : index + MEDIUM_MAX])
                if self._word_count(chunk) >= SMALL_MIN:
                    chunks.append(chunk)
                elif chunks:
                    chunks[-1] += " " + chunk
            return chunks

        chunks = []
        accumulator = []
        accumulator_words = 0
        for sentence in sentences:
            word_count = self._word_count(sentence)
            if accumulator_words + word_count > MEDIUM_MAX and accumulator:
                chunks.append(" ".join(accumulator))
                accumulator = []
                accumulator_words = 0
            accumulator.append(sentence)
            accumulator_words += word_count

        if accumulator:
            merged = " ".join(accumulator)
            if chunks and self._word_count(merged) < SMALL_MIN:
                chunks[-1] += " " + merged
            else:
                chunks.append(merged)

        return chunks

    def _build_topic_chunks(self, paragraph_entries: list[dict]) -> list[dict]:
        total_words = sum(entry["words"] for entry in paragraph_entries)
        if total_words <= MEDIUM_MAX:
            return []

        topic_chunks = []
        start_index = 0
        paragraph_count = len(paragraph_entries)

        while start_index < paragraph_count:
            accumulator = []
            accumulator_words = 0
            end_index = start_index

            while end_index < paragraph_count:
                entry = paragraph_entries[end_index]
                if accumulator and accumulator_words >= TOPIC_TARGET and accumulator_words + entry["words"] > TOPIC_MAX:
                    break

                accumulator.append(entry["text"])
                accumulator_words += entry["words"]
                end_index += 1

                if accumulator_words >= TOPIC_TARGET:
                    next_words = paragraph_entries[end_index]["words"] if end_index < paragraph_count else 0
                    if accumulator_words + next_words > TOPIC_MAX:
                        break

            if accumulator_words >= TOPIC_MIN or (not topic_chunks and accumulator_words > MEDIUM_MAX):
                sub_entries = paragraph_entries[start_index:end_index]
                if sub_entries and "block_id" in sub_entries[0]:
                    topic_chunks.append(
                        self._make_chunk_from_entries(
                            sub_entries,
                            "topic"
                        )
                    )
                else:
                    topic_chunks.append(
                        self._make_chunk(
                            "\n\n".join(accumulator),
                            "topic",
                            paragraph_entries[start_index]["index"],
                            paragraph_entries[end_index - 1]["index"],
                        )
                    )

            if end_index >= paragraph_count:
                break

            stride_words = 0
            next_start = start_index
            while next_start < end_index and stride_words < TOPIC_STRIDE_WORDS:
                stride_words += paragraph_entries[next_start]["words"]
                next_start += 1

            if next_start <= start_index:
                next_start = start_index + 1
            start_index = next_start

        return topic_chunks

    def chunk(self, text: str) -> list[dict]:
        """Chunk text across small, medium, large, and topic scales."""
        paragraphs = self._split_paragraphs(text)
        if not paragraphs:
            return []

        paragraph_entries = [
            {"index": index, "text": paragraph, "words": self._word_count(paragraph)}
            for index, paragraph in enumerate(paragraphs)
        ]

        small_chunks = []
        for entry in paragraph_entries:
            if SMALL_MIN <= entry["words"] <= SMALL_MAX:
                small_chunks.append(
                    self._make_chunk(
                        entry["text"],
                        "small",
                        entry["index"],
                        entry["index"],
                    )
                )

        medium_chunks = []
        accumulator = []
        accumulator_words = 0
        accumulator_start = None

        def flush_medium_accumulator() -> None:
            nonlocal accumulator, accumulator_words, accumulator_start
            if not accumulator:
                return

            merged = " ".join(accumulator)
            if self._word_count(merged) >= MEDIUM_MIN:
                medium_chunks.append(
                    self._make_chunk(
                        merged,
                        "medium",
                        accumulator_start,
                        accumulator_start + len(accumulator) - 1,
                    )
                )
            elif medium_chunks:
                medium_chunks[-1]["text"] += " " + merged
                medium_chunks[-1]["end_paragraph"] = accumulator_start + len(accumulator) - 1
            elif self._word_count(merged) >= SMALL_MIN:
                small_chunks.append(
                    self._make_chunk(
                        merged,
                        "small",
                        accumulator_start,
                        accumulator_start + len(accumulator) - 1,
                    )
                )

            accumulator = []
            accumulator_words = 0
            accumulator_start = None

        for entry in paragraph_entries:
            word_count = entry["words"]

            if word_count > MEDIUM_MAX:
                flush_medium_accumulator()
                for chunk in self._split_long_paragraph(entry["text"]):
                    medium_chunks.append(
                        self._make_chunk(
                            chunk,
                            "medium",
                            entry["index"],
                            entry["index"],
                        )
                    )
                continue

            if word_count >= MEDIUM_MIN:
                flush_medium_accumulator()
                medium_chunks.append(
                    self._make_chunk(
                        entry["text"],
                        "medium",
                        entry["index"],
                        entry["index"],
                    )
                )
                continue

            if accumulator_start is None:
                accumulator_start = entry["index"]
            accumulator.append(entry["text"])
            accumulator_words += word_count

            if accumulator_words >= MEDIUM_MIN:
                flush_medium_accumulator()

        flush_medium_accumulator()

        large_chunks = []
        accumulator_text = []
        accumulator_words = 0
        accumulator_start = None

        for entry in paragraph_entries:
            if accumulator_start is None:
                accumulator_start = entry["index"]

            if accumulator_words + entry["words"] > LARGE_MAX and accumulator_text:
                large_chunks.append(
                    self._make_chunk(
                        "\n\n".join(accumulator_text),
                        "large",
                        accumulator_start,
                        accumulator_start + len(accumulator_text) - 1,
                    )
                )
                accumulator_text = []
                accumulator_words = 0
                accumulator_start = entry["index"]

            accumulator_text.append(entry["text"])
            accumulator_words += entry["words"]

        if accumulator_text:
            merged = "\n\n".join(accumulator_text)
            if self._word_count(merged) > MEDIUM_MAX:
                large_chunks.append(
                    self._make_chunk(
                        merged,
                        "large",
                        accumulator_start,
                        accumulator_start + len(accumulator_text) - 1,
                    )
                )

        topic_chunks = self._build_topic_chunks(paragraph_entries)

        return small_chunks + medium_chunks + large_chunks + topic_chunks

    def _make_chunk_from_entries(
        self,
        entries: list[dict],
        scale: str,
    ) -> dict:
        if scale in ("large", "topic"):
            text = "\n\n".join(e["text"] for e in entries)
        else:
            text = " ".join(e["text"] for e in entries)
            
        pages = [e["printed_page"] for e in entries if e.get("printed_page") is not None]
        printed_page_start = pages[0] if pages else None
        printed_page_end = pages[-1] if pages else None
        
        # Take the heading context from the first entry if available
        heading_context = entries[0].get("heading_context")
        
        return {
            "text": text,
            "scale": scale,
            "start_paragraph": entries[0]["index"],
            "end_paragraph": entries[-1]["index"],
            "block_ids": [e["block_id"] for e in entries],
            "printed_page_start": printed_page_start,
            "printed_page_end": printed_page_end,
            "heading_context": heading_context,
        }

    def _split_long_paragraph_entries(self, entry: dict) -> list[dict]:
        """Split a long paragraph entry into virtual sub-entries for chunking."""
        sentences = self._split_sentences(entry["text"])
        if len(sentences) <= 1:
            words = entry["text"].split()
            sub_entries = []
            for index in range(0, len(words), MEDIUM_MAX):
                chunk_text = " ".join(words[index : index + MEDIUM_MAX])
                if self._word_count(chunk_text) >= SMALL_MIN:
                    sub_entries.append(chunk_text)
                elif sub_entries:
                    sub_entries[-1] += " " + chunk_text
            return [
                {
                    "index": entry["index"],
                    "text": txt,
                    "words": self._word_count(txt),
                    "block_id": entry["block_id"],
                    "printed_page": entry["printed_page"],
                    "physical_page": entry["physical_page"],
                    "heading_context": entry.get("heading_context")
                }
                for txt in sub_entries
            ]

        sub_entries = []
        accumulator = []
        accumulator_words = 0
        for sentence in sentences:
            word_count = self._word_count(sentence)
            if accumulator_words + word_count > MEDIUM_MAX and accumulator:
                sub_entries.append(" ".join(accumulator))
                accumulator = []
                accumulator_words = 0
            accumulator.append(sentence)
            accumulator_words += word_count

        if accumulator:
            merged = " ".join(accumulator)
            if sub_entries and self._word_count(merged) < SMALL_MIN:
                sub_entries[-1] += " " + merged
            else:
                sub_entries.append(merged)

        return [
            {
                "index": entry["index"],
                "text": txt,
                "words": self._word_count(txt),
                "block_id": entry["block_id"],
                "printed_page": entry["printed_page"],
                "physical_page": entry["physical_page"],
                "heading_context": entry.get("heading_context")
            }
            for txt in sub_entries
        ]

    def chunk_from_blocks(self, blocks: list[dict]) -> list[dict]:
        """Chunk manifest content blocks across small, medium, large, and topic scales."""
        if not blocks:
            return []

        paragraph_entries = [
            {
                "index": index,
                "text": b["text"],
                "words": self._word_count(b["text"]),
                "block_id": b["id"],
                "printed_page": b.get("printed_page"),
                "physical_page": b.get("physical_page"),
                "heading_context": b.get("heading_context"),
            }
            for index, b in enumerate(blocks)
        ]

        small_chunks = []
        for entry in paragraph_entries:
            text = entry["text"].strip()
            # Only create small chunks if the block is a complete, self-contained thought
            if SMALL_MIN <= entry["words"] <= SMALL_MAX:
                if entry["words"] >= 8 and (text[0].isupper() or text[0] in ('"', '“', '‘', "'", '1', '2', '3', '4', '5', '6', '7', '8', '9')) and is_terminal_sentence_ending(text):
                    small_chunks.append(
                        self._make_chunk_from_entries(
                            [entry],
                            "small"
                        )
                    )

        medium_chunks = []
        accumulator = []
        accumulator_words = 0
        accumulator_start = None

        def flush_medium_accumulator() -> None:
            nonlocal accumulator, accumulator_words, accumulator_start
            if not accumulator:
                return

            merged_words = sum(e["words"] for e in accumulator)
            if merged_words >= MEDIUM_MIN:
                medium_chunks.append(
                    self._make_chunk_from_entries(
                        accumulator,
                        "medium"
                    )
                )
            elif medium_chunks:
                last_chunk = medium_chunks[-1]
                last_chunk["text"] += " " + " ".join(e["text"] for e in accumulator)
                last_chunk["end_paragraph"] = accumulator[-1]["index"]
                last_chunk["block_ids"].extend(e["block_id"] for e in accumulator)
                pages = [e["printed_page"] for e in accumulator if e.get("printed_page") is not None]
                if pages:
                    last_chunk["printed_page_end"] = pages[-1]
            elif merged_words >= SMALL_MIN:
                small_chunks.append(
                    self._make_chunk_from_entries(
                        accumulator,
                        "small"
                    )
                )

            accumulator = []
            accumulator_words = 0
            accumulator_start = None

        for entry in paragraph_entries:
            word_count = entry["words"]

            if word_count > MEDIUM_MAX:
                flush_medium_accumulator()
                for sub_entry in self._split_long_paragraph_entries(entry):
                    medium_chunks.append(
                        self._make_chunk_from_entries(
                            [sub_entry],
                            "medium"
                        )
                    )
                continue

            if word_count >= MEDIUM_MIN:
                flush_medium_accumulator()
                medium_chunks.append(
                    self._make_chunk_from_entries(
                        [entry],
                        "medium"
                    )
                )
                continue

            if accumulator_start is None:
                accumulator_start = entry["index"]
            accumulator.append(entry)
            accumulator_words += word_count

            if accumulator_words >= MEDIUM_MIN:
                flush_medium_accumulator()

        flush_medium_accumulator()

        large_chunks = []
        accumulator_text = []
        accumulator_words = 0
        accumulator_start = None

        for entry in paragraph_entries:
            if accumulator_start is None:
                accumulator_start = entry["index"]

            if accumulator_words + entry["words"] > LARGE_MAX and accumulator_text:
                large_chunks.append(
                    self._make_chunk_from_entries(
                        accumulator_text,
                        "large"
                    )
                )
                accumulator_text = []
                accumulator_words = 0
                accumulator_start = entry["index"]

            accumulator_text.append(entry)
            accumulator_words += entry["words"]

        if accumulator_text:
            merged_words = sum(e["words"] for e in accumulator_text)
            if merged_words > MEDIUM_MAX:
                large_chunks.append(
                    self._make_chunk_from_entries(
                        accumulator_text,
                        "large"
                    )
                )

        topic_chunks = self._build_topic_chunks(paragraph_entries)

        return small_chunks + medium_chunks + large_chunks + topic_chunks
