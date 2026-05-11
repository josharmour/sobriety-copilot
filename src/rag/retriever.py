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

    def _tokenize(self, text: str) -> list[str]:
        return [token.lower() for token in TOKEN_RE.findall(text)]

    def refresh_cache(self) -> None:
        self._chunks_by_id = {}
        self._postings = defaultdict(list)
        self._doc_lengths = {}
        self._avg_doc_length = 0.0
        self._document_count = self.collection.count()
        self._cache_initialized = True

        if self._document_count == 0:
            return

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
            ),
        )

    def retrieve(
        self,
        query: str,
        top_k: int = 8,
        categories: list[str] | None = None,
        embedding_query: str | None = None,
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
            hybrid_score = (
                (SEMANTIC_WEIGHT * semantic_score) + (KEYWORD_WEIGHT * keyword_score)
            ) * SCALE_BOOST.get(chunk.scale, 1.0) * category_boost
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

        # Oversample the diversity-filtered pool when a reranker will trim it
        # back: give the cross-encoder real choices instead of a fixed top_k.
        target_k = top_k * reranker.oversample_factor()

        def _can_add(candidate: RankedCandidate) -> bool:
            if candidate.context_id in seen_context_ids:
                return False
            if source_counts[candidate.result.source] >= MAX_RESULTS_PER_SOURCE:
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

        if reranker.is_enabled() and len(retrieval_results) > 1:
            retrieval_results = reranker.rerank(query, retrieval_results, top_k=top_k)
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

            header = f"[Source {index}: {result.source} | match={result.match_scale}, context={result.scale}]"
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
