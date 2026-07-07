"""Retrieve relevant chunks from ChromaDB and build RAG prompts."""

from __future__ import annotations

import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from .chroma_client import create_chroma_client
from .embeddings import embed_query
from .indexer import DEFAULT_COLLECTION
from . import reranker

TOKEN_RE = re.compile(r"[A-Za-z0-9']+")


def _display_title(source: str) -> str:
    """Human-facing work title from a source filename.

    Strips any directory, the file extension, and a trailing " - <author/
    fellowship>" suffix so the model sees the bare title it should name
    (e.g. "Step Working Guides - NA.pdf" -> "Step Working Guides"). Mirrors
    the frontend cleanSourceTitle() so inline-link matching lines up.
    """
    title = os.path.splitext(os.path.basename(source or ""))[0].replace("_", " ").strip()
    if " - " in title:
        title = title.split(" - ", 1)[0].strip()
    return title

# Stopwords to drop from query-side BM25 scoring. Document-side tokenization is
# unchanged so chunks still index every word, but query-side filtering means
# noise like "how", "do", "I", "with" doesn't get to boost generic chunks.
QUERY_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being", "am",
    "of", "in", "on", "at", "to", "for", "with", "by", "from", "as", "into",
    "about", "that", "i", "me", "my", "mine", "we", "us", "our", "you", "your",
    "yours", "he", "she", "they", "it", "its", "this", "these", "those",
    "what", "how", "why", "when", "where", "who", "do", "does", "did", "done",
    "can", "could", "would", "should", "may", "might", "will", "have", "has",
    "had", "having", "and", "or", "but", "if", "than", "then", "so", "not",
    "just", "very", "really", "much", "more", "most", "some", "any", "like",
    "go", "get", "got", "make", "made", "let", "help", "know", "tell", "say",
    "said", "deal", "doing", "being", "want", "need", "thing", "things", "way",
})
SEMANTIC_WEIGHT = float(os.environ.get("SEMANTIC_WEIGHT", "0.7"))
KEYWORD_WEIGHT = float(os.environ.get("KEYWORD_WEIGHT", "0.3"))
QUERY_CANDIDATE_MULTIPLIER = int(os.environ.get("RAG_CANDIDATE_MULTIPLIER", "8"))
CACHE_BATCH_SIZE = int(os.environ.get("RAG_CACHE_BATCH_SIZE", "2000"))
SCALE_DIVERSITY_MIN_RATIO = float(os.environ.get("RAG_SCALE_DIVERSITY_MIN_RATIO", "0.5"))
MAX_RESULTS_PER_SOURCE = int(os.environ.get("RAG_MAX_PER_SOURCE", "2"))
SCALE_BOOST = {
    "small": 1.0,
    "medium": 0.97,
    "large": 0.95,
    "topic": 0.96,
}
CATEGORY_BOOST = {
    "conference_approved": float(os.environ.get("BOOST_CONFERENCE_APPROVED", "1.40")),
    "books_about_aa": float(os.environ.get("BOOST_BOOKS_ABOUT_AA", "1.05")),
    "related_nonfiction": float(os.environ.get("BOOST_RELATED_NONFICTION", "0.85")),
    "other_anonymous": float(os.environ.get("BOOST_OTHER_ANONYMOUS", "0.80")),
    "uncategorized": float(os.environ.get("BOOST_UNCATEGORIZED", "0.75")),
}
BUCKET_ORDER = ("small", "medium", "large")

# When the user names a specific work ("what does the Big Book say…"), chunks
# from that work get a large multiplicative boost — both in hybrid selection
# (so they survive into the reranker's candidate pool) and in the final rerank
# (so the cross-encoder can't silently demote the book actually asked about).
# A relaxed per-source cap lets several passages from that one book through.
TITLE_REFERENCE_BOOST = float(os.environ.get("BOOST_TITLE_REFERENCE", "3.0"))

# Bare enumerations of the Steps/Traditions (TOC-style list pages) contain the
# literal text of every step, so they out-score substantive discussion for any
# "Step N" query while explaining nothing. Chunks carrying at least
# RAG_ENUMERATION_MIN_MARKERS list markers get their score multiplied down.
ENUMERATION_PENALTY = float(os.environ.get("RAG_ENUMERATION_PENALTY", "0.45"))
ENUMERATION_MIN_MARKERS = int(os.environ.get("RAG_ENUMERATION_MIN_MARKERS", "5"))

# Header-only chunks (short text after stripping page headers) are structural
# noise -- they match semantically because their heading happens to live near
# the query in embedding space, but carry no substantive content. Chunks that
# are almost all header get their score penalized so real passages outrank them.
HEADER_PENALTY = float(os.environ.get("RAG_HEADER_PENALTY", "0.35"))
HEADER_MIN_SUBSTANTIVE_WORDS = int(os.environ.get("RAG_HEADER_MIN_WORDS", "15"))

_ENUMERATION_MARKER = re.compile(
    r"(?:Step|Tradition)\s+(?:One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|Eleven|Twelve)\s*(?:[:.)]|\d{1,3}\b)"
    r"|\b(?:[1-9]|1[0-2])\s*[.)]\s*(?:We\s+admitted|Came\s+to\s+believe|Made\s+a\s+(?:decision|list)"
    r"|Made\s+direct\s+amends|Were\s+entirely\s+ready|Humbly\s+asked|Continued\s+to\s+take"
    r"|Sought\s+through\s+prayer|Having\s+had\s+a\s+spiritual|Admitted\s+to\s+God|Became\s+willing)",
    re.IGNORECASE,
)
# A literal CONTENTS heading is near-certain evidence of a table-of-contents
# page (counts as several markers on its own).
_CONTENTS_RE = re.compile(r"\bCONTENTS\b")
REFERENCED_MAX_PER_SOURCE = int(os.environ.get("RAG_REFERENCED_MAX_PER_SOURCE", "4"))

# Running-header regex (matches PDF repeating headers / page numbers at start
# of text lines). Copied from server.py so retriever can do its own stripping.
_PAGE_HEADER_RE = re.compile(
    r"^(?:"
    r"[A-Z][A-Z\s\-\.',&]+\d+|"
    r"\d+\s+[A-Z][A-Z\s\-\.',&]+|"
    r"[\-•]\s*\w+\s+\d+\s*[\-•]"
    r")\s*\n",
)

# Query phrases that name a specific work -> source-filename substrings (lower).
# Substrings are deliberately specific so "big book" boosts the Big Book itself
# ("Alcoholics Anonymous - AA.pdf") but not books *about* it ("…Comes of Age").
WORK_ALIASES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("big book", "the big book"),
     ("alcoholics anonymous - aa", "plain language big book", "trimmed-big-book")),
    (("twelve and twelve", "twelve & twelve", "12 and 12", "12 & 12", "12&12",
      "twelve steps and twelve traditions"),
     ("twelve steps and twelve traditions - aa",)),
    (("as bill sees it",), ("as bill sees it",)),
    (("daily reflections",), ("daily reflections - aa",)),
    (("living sober",), ("living sober - aa",)),
    (("came to believe",), ("came to believe - aa",)),
    (("twenty-four hours a day", "twenty four hours a day", "24 hours a day"),
     ("twenty-four hours a day",)),
    (("just for today",), ("just for today - na",)),
    (("basic text", "narcotics anonymous", "na big book"),
     ("narcotics anonymous - na",)),
    (("it works how and why", "it works: how and why"), ("it works how and why",)),
    (("living clean",), ("living clean",)),
    (("step working guide",), ("step working guides - na",)),
)


def _referenced_source_substrings(query: str) -> set[str]:
    """Source-filename substrings for any work the query names by title."""
    q = (query or "").lower()
    matched: set[str] = set()
    for phrases, sources in WORK_ALIASES:
        if any(phrase in q for phrase in phrases):
            matched.update(sources)
    return matched


def _source_is_referenced(source: str, referenced: set[str]) -> bool:
    if not referenced:
        return False
    s = (source or "").lower()
    return any(sub in s for sub in referenced)


@dataclass
class CachedChunk:
    id: str
    text: str
    source: str
    chunk_index: int
    source_path: str = ""
    relative_path: str = ""
    scale: str = "medium"
    category: str = "uncategorized"
    parent_id: str = ""
    parent_scale: str = "medium"
    context_parent_id: str = ""
    context_parent_scale: str = "medium"
    topic_parent_id: str = ""
    topic_parent_scale: str = "medium"
    doc_id: str | None = None
    block_ids: str | None = None
    printed_page_start: int | str | None = None
    printed_page_end: int | str | None = None


@dataclass
class RetrievalResult:
    text: str
    excerpt: str
    similarity: float
    source: str
    chunk_index: int
    source_path: str = ""
    relative_path: str = ""
    scale: str = "medium"
    match_scale: str = "medium"
    parent_id: str = ""
    matched_chunk_id: str = ""
    category: str = "uncategorized"
    doc_id: str | None = None
    block_ids: list[str] | None = None
    printed_page_start: int | str | None = None
    printed_page_end: int | str | None = None


@dataclass
class RankedCandidate:
    context_id: str
    bucket: str
    score: float
    result: RetrievalResult


class RAGRetriever:
    def __init__(
        self,
        db_path: str = "rag_db",
        collection_name: str = DEFAULT_COLLECTION,
    ):
        client = create_chroma_client(db_path)
        self.collection = client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        self._chunks_by_id: dict[str, CachedChunk] = {}
        self._postings: dict[str, list[tuple[str, int]]] = {}
        self._doc_lengths: dict[str, int] = {}
        self._avg_doc_length = 0.0
        self._document_count = 0
        self._cache_initialized = False
        self._enum_penalty: dict[str, float] = {}

    def _tokenize(self, text: str) -> list[str]:
        return [token.lower() for token in TOKEN_RE.findall(text)]

    def refresh_cache(self) -> None:
        import pickle

        self._chunks_by_id = {}
        self._postings = defaultdict(list)
        self._doc_lengths = {}
        self._enum_penalty = {}
        self._avg_doc_length = 0.0
        self._document_count = self.collection.count()
        self._cache_initialized = True

        if self._document_count == 0:
            return

        cache_dir = "/home/app/memory"
        if not os.path.exists(cache_dir):
            cache_dir = os.path.dirname(os.environ.get("USER_MEMORY_DB_PATH", "/tmp"))
        cache_file = os.path.join(cache_dir, f"bm25_cache_{self.collection.name}.pkl")

        try:
            if os.path.exists(cache_file):
                with open(cache_file, "rb") as f:
                    cache_data = pickle.load(f)
                if cache_data.get("document_count") == self._document_count:
                    self._chunks_by_id = cache_data["chunks_by_id"]
                    self._postings = defaultdict(list, cache_data["postings"])
                    self._doc_lengths = cache_data["doc_lengths"]
                    self._enum_penalty = cache_data.get("enum_penalty", {})
                    self._avg_doc_length = cache_data["avg_doc_length"]
                    print(f"[BM25-CACHE] Loaded {self._document_count} chunks from {cache_file} instantly.", flush=True)
                    return
        except Exception as e:
            print(f"[BM25-CACHE-ERR] Failed to load cache from {cache_file}: {e}", flush=True)

        total_tokens = 0
        for offset in range(0, self._document_count, CACHE_BATCH_SIZE):
            batch = self.collection.get(
                limit=min(CACHE_BATCH_SIZE, self._document_count - offset),
                offset=offset,
                include=["documents", "metadatas"],
            )
            ids = batch.get("ids", [])
            documents = batch.get("documents", [])
            metadatas = batch.get("metadatas", [])

            for chunk_id, document, metadata in zip(ids, documents, metadatas):
                chunk = CachedChunk(
                    id=chunk_id,
                    text=document,
                    source=metadata.get("source", ""),
                    chunk_index=metadata.get("chunk_index", 0),
                    source_path=metadata.get("source_path", ""),
                    relative_path=metadata.get("relative_path", ""),
                    scale=metadata.get("scale", "medium"),
                    category=metadata.get("category", "uncategorized"),
                    parent_id=metadata.get("parent_id", chunk_id),
                    parent_scale=metadata.get("parent_scale", metadata.get("scale", "medium")),
                    context_parent_id=metadata.get("context_parent_id", metadata.get("parent_id", chunk_id)),
                    context_parent_scale=metadata.get(
                        "context_parent_scale",
                        metadata.get("parent_scale", metadata.get("scale", "medium")),
                    ),
                    topic_parent_id=metadata.get("topic_parent_id", metadata.get("parent_id", chunk_id)),
                    topic_parent_scale=metadata.get(
                        "topic_parent_scale",
                        metadata.get("parent_scale", metadata.get("scale", "medium")),
                    ),
                    doc_id=metadata.get("doc_id"),
                    block_ids=metadata.get("block_ids"),
                    printed_page_start=metadata.get("printed_page_start"),
                    printed_page_end=metadata.get("printed_page_end"),
                )
                self._chunks_by_id[chunk_id] = chunk

                tokens = self._tokenize(document)
                token_counts = Counter(tokens)
                self._doc_lengths[chunk_id] = len(tokens)
                total_tokens += len(tokens)
                for token, count in token_counts.items():
                    self._postings[token].append((chunk_id, count))

        if self._chunks_by_id:
            self._avg_doc_length = total_tokens / len(self._chunks_by_id)

            try:
                os.makedirs(os.path.dirname(cache_file), exist_ok=True)
                cache_data = {
                    "document_count": self._document_count,
                    "chunks_by_id": self._chunks_by_id,
                    "postings": dict(self._postings),
                    "doc_lengths": self._doc_lengths,
                    "enum_penalty": self._enum_penalty,
                    "avg_doc_length": self._avg_doc_length,
                }
                with open(cache_file, "wb") as f:
                    pickle.dump(cache_data, f, protocol=pickle.HIGHEST_PROTOCOL)
                print(f"[BM25-CACHE] Saved {self._document_count} chunks to {cache_file}", flush=True)
            except Exception as e:
                print(f"[BM25-CACHE-ERR] Failed to save cache to {cache_file}: {e}", flush=True)

    def _keyword_scores(
        self,
        query: str,
        categories: list[str] | None,
    ) -> dict[str, float]:
        if not self._chunks_by_id:
            return {}

        query_terms = [
            t for t in self._tokenize(query)
            if len(t) > 2 and t not in QUERY_STOPWORDS
        ]
        if not query_terms:
            return {}

        scores: defaultdict[str, float] = defaultdict(float)
        k1 = 1.5
        b = 0.75
        category_filter = set(categories or [])

        for token in query_terms:
            postings = self._postings.get(token)
            if not postings:
                continue
            document_frequency = len(postings)
            idf = math.log(1 + (self._document_count - document_frequency + 0.5) / (document_frequency + 0.5))
            for chunk_id, term_frequency in postings:
                chunk = self._chunks_by_id.get(chunk_id)
                if chunk is None:
                    continue
                if category_filter and chunk.category not in category_filter:
                    continue
                document_length = max(self._doc_lengths.get(chunk_id, 0), 1)
                denominator = term_frequency + k1 * (
                    1 - b + b * (document_length / max(self._avg_doc_length, 1.0))
                )
                scores[chunk_id] += idf * ((term_frequency * (k1 + 1)) / denominator)

        return dict(scores)

    def _enumeration_penalty(self, chunk_id: str, chunk: CachedChunk) -> float:
        cached = self._enum_penalty.get(chunk_id)
        if cached is None:
            text = chunk.text or ""
            markers = len(_ENUMERATION_MARKER.findall(text))
            if _CONTENTS_RE.search(text):
                markers += 3
            cached = ENUMERATION_PENALTY if markers >= ENUMERATION_MIN_MARKERS else 1.0
            self._enum_penalty[chunk_id] = cached
        return cached

    def _is_header_only(self, chunk: CachedChunk) -> bool:
        """True if the chunk is too short / header-like to be substantive."""
        text = chunk.text or ""
        stripped = self._strip_page_headers(text)
        words = len(re.findall(r"[A-Za-z0-9]+", stripped))
        if words < HEADER_MIN_SUBSTANTIVE_WORDS and chunk.scale == "small":
            return True
        return False

    def _strip_page_headers(self, text: str) -> str:
        """Remove PDF running headers / page numbers from the start of text."""
        for _ in range(3):
            m = _PAGE_HEADER_RE.match(text)
            if not m:
                break
            text = text[m.end():]
        return text.strip()

    def _resolve_chunk(self, chunk_id: str | None, fallback: CachedChunk) -> CachedChunk:
        if chunk_id and chunk_id in self._chunks_by_id:
            return self._chunks_by_id[chunk_id]
        return fallback

    def _compact_context_chunk(self, chunk: CachedChunk) -> CachedChunk:
        return self._resolve_chunk(chunk.context_parent_id or chunk.parent_id, chunk)

    def _broad_context_chunk(self, chunk: CachedChunk) -> CachedChunk:
        return self._resolve_chunk(
            chunk.topic_parent_id or chunk.context_parent_id or chunk.parent_id,
            chunk,
        )

    def _bucket_for_scale(self, scale: str) -> str:
        if scale == "topic":
            return "topic"
        if scale == "large":
            return "large"
        return "small" if scale == "small" else "medium"

    def _candidate_for_chunk(self, chunk: CachedChunk, score: float) -> RankedCandidate:
        bucket = self._bucket_for_scale(chunk.scale)
        context_chunk = self._compact_context_chunk(chunk) if bucket != "broad" else self._broad_context_chunk(chunk)
        context_id = context_chunk.id
        
        import json
        block_ids_list = None
        if chunk.block_ids:
            try:
                block_ids_list = json.loads(chunk.block_ids)
            except Exception:
                pass
                
        return RankedCandidate(
            context_id=context_id,
            bucket=bucket,
            score=score,
            result=RetrievalResult(
                text=context_chunk.text,
                excerpt=chunk.text,
                similarity=score,
                source=chunk.source,
                chunk_index=chunk.chunk_index,
                source_path=chunk.source_path,
                relative_path=chunk.relative_path,
                scale=context_chunk.scale,
                match_scale=chunk.scale,
                parent_id=context_id,
                matched_chunk_id=chunk.id,
                category=chunk.category,
                doc_id=chunk.doc_id,
                block_ids=block_ids_list,
                printed_page_start=chunk.printed_page_start,
                printed_page_end=chunk.printed_page_end,
            ),
        )

    def retrieve(
        self,
        query: str,
        top_k: int = 8,
        categories: list[str] | None = None,
        embedding_query: str | None = None,
        model_mode: str | None = None,
        enable_reranker: bool | None = None,
    ) -> list[RetrievalResult]:
        """Retrieve top-k chunks for a query.

        `embedding_query` overrides what gets sent to the embedding model for
        semantic search (e.g., a HyDE-generated hypothetical passage). The
        BM25 keyword scoring always uses the raw `query`, so literal matches
        aren't lost.
        """
        collection_count = self.collection.count()
        if collection_count == 0:
            return []
        if not self._cache_initialized or self._document_count != collection_count:
            self.refresh_cache()

        where = None
        if categories:
            where = {"category": {"$in": categories}}

        referenced_sources = _referenced_source_substrings(query)

        query_embedding = embed_query(embedding_query or query)
        candidate_count = min(max(top_k * QUERY_CANDIDATE_MULTIPLIER, top_k), collection_count)
        semantic_results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=candidate_count,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        semantic_scores: dict[str, float] = {}
        for chunk_id, distance in zip(
            semantic_results.get("ids", [[]])[0],
            semantic_results.get("distances", [[]])[0],
        ):
            similarity = max(0.0, 1.0 - float(distance))
            semantic_scores[chunk_id] = similarity

        missing_ids = [chunk_id for chunk_id in semantic_scores if chunk_id not in self._chunks_by_id]
        if missing_ids:
            self.refresh_cache()

        keyword_scores = self._keyword_scores(query, categories)
        max_semantic = max(semantic_scores.values(), default=1.0)
        max_keyword = max(keyword_scores.values(), default=1.0)

        combined_scores = {}
        for chunk_id in set(semantic_scores) | set(keyword_scores):
            chunk = self._chunks_by_id.get(chunk_id)
            if chunk is None:
                continue
            semantic_score = semantic_scores.get(chunk_id, 0.0) / max(max_semantic, 1e-6)
            keyword_score = keyword_scores.get(chunk_id, 0.0) / max(max_keyword, 1e-6)
            category_boost = CATEGORY_BOOST.get(chunk.category, 1.0)
            title_boost = (
                TITLE_REFERENCE_BOOST
                if _source_is_referenced(chunk.source, referenced_sources)
                else 1.0
            )
            hybrid_score = (
                (SEMANTIC_WEIGHT * semantic_score) + (KEYWORD_WEIGHT * keyword_score)
            ) * SCALE_BOOST.get(chunk.scale, 1.0) * category_boost * title_boost \
                * self._enumeration_penalty(chunk_id, chunk)
            if self._is_header_only(chunk):
                hybrid_score *= HEADER_PENALTY
            combined_scores[chunk_id] = hybrid_score

        ranked_ids = sorted(combined_scores, key=combined_scores.get, reverse=True)
        candidates = [
            self._candidate_for_chunk(self._chunks_by_id[chunk_id], combined_scores[chunk_id])
            for chunk_id in ranked_ids
            if chunk_id in self._chunks_by_id
        ]
        if not candidates:
            return []

        top_score = candidates[0].score
        bucket_candidates: dict[str, list[RankedCandidate]] = defaultdict(list)
        for candidate in candidates:
            if candidate.score >= top_score * SCALE_DIVERSITY_MIN_RATIO:
                bucket_candidates[candidate.bucket].append(candidate)

        retrieval_results = []
        seen_context_ids = set()
        source_counts: dict[str, int] = defaultdict(int)
        bucket_indexes = {bucket: 0 for bucket in BUCKET_ORDER}

        # Respect payload override if provided; otherwise use the environment default.
        if enable_reranker is not None:
            use_reranker = enable_reranker
        else:
            use_reranker = reranker.is_enabled()

        oversample = reranker.oversample_factor() if use_reranker else 1
        target_k = top_k * oversample

        def _source_cap(source: str) -> int:
            if _source_is_referenced(source, referenced_sources):
                return REFERENCED_MAX_PER_SOURCE
            return MAX_RESULTS_PER_SOURCE

        def _can_add(candidate: RankedCandidate) -> bool:
            if candidate.context_id in seen_context_ids:
                return False
            if source_counts[candidate.result.source] >= _source_cap(candidate.result.source):
                return False
            return True

        def _add(candidate: RankedCandidate) -> None:
            seen_context_ids.add(candidate.context_id)
            source_counts[candidate.result.source] += 1
            retrieval_results.append(candidate.result)

        while len(retrieval_results) < target_k:
            made_progress = False
            for bucket in BUCKET_ORDER:
                queue = bucket_candidates.get(bucket, [])
                while bucket_indexes[bucket] < len(queue):
                    candidate = queue[bucket_indexes[bucket]]
                    bucket_indexes[bucket] += 1
                    if not _can_add(candidate):
                        continue
                    _add(candidate)
                    made_progress = True
                    break
                if len(retrieval_results) >= target_k:
                    break
            if not made_progress:
                break

        for candidate in candidates:
            if len(retrieval_results) >= target_k:
                break
            if not _can_add(candidate):
                continue
            _add(candidate)

        if use_reranker and len(retrieval_results) > 1:
            # Re-apply the priors the cross-encoder is blind to: category
            # (conference-approved literature) and any work the query named.
            rerank_boosts = [
                CATEGORY_BOOST.get(r.category, 1.0)
                * (
                    TITLE_REFERENCE_BOOST
                    if _source_is_referenced(r.source, referenced_sources)
                    else 1.0
                )
                for r in retrieval_results
            ]
            retrieval_results = reranker.rerank(
                query, retrieval_results, top_k=top_k, boosts=rerank_boosts
            )
        elif len(retrieval_results) > top_k:
            retrieval_results = retrieval_results[:top_k]

        return retrieval_results

    def format_context(
        self,
        results: list[RetrievalResult],
        max_total_chars: int = 12000,
    ) -> str:
        sections = []
        chars_used = 0

        for index, result in enumerate(results, 1):
            remaining = max_total_chars - chars_used
            if remaining <= 0:
                break

            header = f'[Source {index}: "{_display_title(result.source)}" | match={result.match_scale}, context={result.scale}]'
            if result.excerpt and result.excerpt != result.text:
                section = (
                    f"{header}\n"
                    f"Matched excerpt:\n{result.excerpt}\n\n"
                    f"Broader context:\n{result.text}"
                )
            else:
                section = f"{header}\n{result.text}"

            if len(section) > remaining:
                section = section[:remaining]

            sections.append(section)
            chars_used += len(section)

        return "\n\n---\n\n".join(sections)

    def query_anchored_excerpt(self, text: str, query: str, context_chars: int = 250) -> str:
        """Instance version that delegates to the module-level function."""
        return _query_anchored_excerpt(text, query, context_chars)


def _query_anchored_excerpt(text: str, query: str, context_chars: int = 250) -> str:
    """Extract ~context_chars around the best query-term hit within text.

    Standalone module-level version so server.py can use it
    without coupling to a RAGRetriever instance.
    Falls back to the first 500 chars if no query tokens match.
    """
    if not text or not query:
        if text:
            return text[:min(len(text), 500)]
        return text

    _stopwords = QUERY_STOPWORDS
    query_terms = [
        t for t in re.findall(r"[A-Za-z0-9]+", query.lower())
        if len(t) > 2 and t not in _stopwords
    ]
    if not query_terms:
        return text[:min(len(text), 500)]

    lower = text.lower()
    best_pos = 0
    best_score = 0
    window = context_chars // 2
    for pos in range(0, len(lower), 50):
        end = min(pos + window, len(lower))
        score = sum(1 for t in query_terms if t in lower[pos:end])
        if score > best_score:
            best_score = score
            best_pos = pos

    if best_score == 0:
        return text[:min(len(text), 500)]

    start = max(0, best_pos - 30)
    end = min(len(text), start + context_chars)
    excerpt = text[start:end].strip()
    if start > 0:
        excerpt = "... " + excerpt
    if end < len(text):
        excerpt = excerpt + " ..."
    return excerpt

