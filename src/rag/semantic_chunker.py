"""Multi-scale semantic chunking for recovery literature.

Produces chunks at three granularities so retrieval can match
short prayers, medium passages, and full chapter-length sections.
"""

import re

PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"\u201C])")

# Scale boundaries (word counts)
SMALL_MIN = 10
SMALL_MAX = 80
MEDIUM_MIN = 80
MEDIUM_MAX = 400
LARGE_MAX = 1500


class SemanticChunker:
    def __init__(self, similarity_threshold: float = 0.55):
        self.similarity_threshold = similarity_threshold

    def _split_paragraphs(self, text: str) -> list[str]:
        paragraphs = PARAGRAPH_SPLIT_RE.split(text)
        return [p.strip() for p in paragraphs if p.strip()]

    def _split_sentences(self, text: str) -> list[str]:
        sentences = SENTENCE_SPLIT_RE.split(text)
        return [s.strip() for s in sentences if s.strip()]

    def _word_count(self, text: str) -> int:
        return len(text.split())

    def _split_long_paragraph(self, text: str) -> list[str]:
        """Split a paragraph over MEDIUM_MAX words at sentence boundaries."""
        sentences = self._split_sentences(text)
        if len(sentences) <= 1:
            words = text.split()
            chunks = []
            for i in range(0, len(words), MEDIUM_MAX):
                chunk = " ".join(words[i : i + MEDIUM_MAX])
                if self._word_count(chunk) >= SMALL_MIN:
                    chunks.append(chunk)
                elif chunks:
                    chunks[-1] += " " + chunk
            return chunks

        # Greedily accumulate sentences into medium-sized chunks
        chunks = []
        acc = []
        acc_words = 0
        for s in sentences:
            wc = self._word_count(s)
            if acc_words + wc > MEDIUM_MAX and acc:
                chunks.append(" ".join(acc))
                acc = []
                acc_words = 0
            acc.append(s)
            acc_words += wc

        if acc:
            merged = " ".join(acc)
            if chunks and self._word_count(merged) < SMALL_MIN:
                chunks[-1] += " " + merged
            else:
                chunks.append(merged)

        return chunks

    def chunk(self, text: str) -> list[dict]:
        """Chunk text at three scales: small, medium, large.

        Returns list of {"text": str, "scale": "small"|"medium"|"large"}.
        """
        paragraphs = self._split_paragraphs(text)
        if not paragraphs:
            return []

        # --- Small-scale chunks ---
        small_chunks = []
        for p in paragraphs:
            wc = self._word_count(p)
            if SMALL_MIN <= wc <= SMALL_MAX:
                small_chunks.append({"text": p, "scale": "small"})

        # --- Medium-scale chunks ---
        medium_chunks = []
        accumulator = []
        acc_words = 0

        for p in paragraphs:
            wc = self._word_count(p)

            if wc > MEDIUM_MAX:
                # Flush accumulator first
                if accumulator and acc_words >= MEDIUM_MIN:
                    medium_chunks.append({
                        "text": " ".join(accumulator),
                        "scale": "medium",
                    })
                elif accumulator and medium_chunks:
                    medium_chunks[-1]["text"] += " " + " ".join(accumulator)
                accumulator = []
                acc_words = 0

                # Split the long paragraph at semantic boundaries
                sub_chunks = self._split_long_paragraph(p)
                for sc in sub_chunks:
                    medium_chunks.append({"text": sc, "scale": "medium"})

            elif wc >= MEDIUM_MIN:
                # Flush accumulator
                if accumulator and acc_words >= MEDIUM_MIN:
                    medium_chunks.append({
                        "text": " ".join(accumulator),
                        "scale": "medium",
                    })
                elif accumulator and medium_chunks:
                    medium_chunks[-1]["text"] += " " + " ".join(accumulator)
                accumulator = []
                acc_words = 0

                medium_chunks.append({"text": p, "scale": "medium"})

            else:
                # Short paragraph — accumulate
                accumulator.append(p)
                acc_words += wc
                if acc_words >= MEDIUM_MIN:
                    medium_chunks.append({
                        "text": " ".join(accumulator),
                        "scale": "medium",
                    })
                    accumulator = []
                    acc_words = 0

        # Flush remaining accumulator
        if accumulator:
            merged = " ".join(accumulator)
            if self._word_count(merged) >= MEDIUM_MIN:
                medium_chunks.append({"text": merged, "scale": "medium"})
            elif medium_chunks:
                medium_chunks[-1]["text"] += " " + merged
            elif self._word_count(merged) >= SMALL_MIN:
                # Not enough for medium, but valid as small
                small_chunks.append({"text": merged, "scale": "small"})

        # --- Large-scale chunks ---
        large_chunks = []
        acc_text = []
        acc_words = 0

        for p in paragraphs:
            wc = self._word_count(p)
            if acc_words + wc > LARGE_MAX and acc_text:
                large_chunks.append({
                    "text": "\n\n".join(acc_text),
                    "scale": "large",
                })
                acc_text = []
                acc_words = 0

            acc_text.append(p)
            acc_words += wc

        if acc_text:
            merged = "\n\n".join(acc_text)
            if self._word_count(merged) > MEDIUM_MAX:
                large_chunks.append({"text": merged, "scale": "large"})
            # If it's not larger than medium range, skip — already covered

        return small_chunks + medium_chunks + large_chunks
