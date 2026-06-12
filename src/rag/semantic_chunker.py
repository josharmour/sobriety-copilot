"""Multi-scale semantic chunking for recovery literature.

Produces chunks at four granularities so retrieval can match
single-line prayers, medium passages, chapter-length sections,
and overlapping multi-page topic windows.
"""

from __future__ import annotations

import re

PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"\u201C])")

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
        sentences = SENTENCE_SPLIT_RE.split(text)
        return [sentence.strip() for sentence in sentences if sentence.strip()]

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
