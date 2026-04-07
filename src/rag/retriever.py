"""Retrieve relevant chunks from ChromaDB and build RAG prompts."""

from dataclasses import dataclass

import chromadb
from chromadb.config import Settings

from .embeddings import embed_query
from .indexer import DEFAULT_COLLECTION


@dataclass
class RetrievalResult:
    text: str
    similarity: float
    source: str
    chunk_index: int
    source_path: str = ""
    scale: str = "medium"


class RAGRetriever:
    def __init__(
        self,
        db_path: str = "rag_db",
        collection_name: str = DEFAULT_COLLECTION,
    ):
        client = chromadb.PersistentClient(
            path=db_path,
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def retrieve(
        self,
        query: str,
        top_k: int = 8,
        categories: list[str] | None = None,
    ) -> list[RetrievalResult]:
        if self.collection.count() == 0:
            return []

        query_embedding = embed_query(query)
        where = None
        if categories:
            where = {"category": {"$in": categories}}
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, self.collection.count()),
            where=where,
        )

        retrieval_results = []
        for i in range(len(results["documents"][0])):
            distance = results["distances"][0][i]
            similarity = 1.0 - distance
            meta = results["metadatas"][0][i]
            retrieval_results.append(
                RetrievalResult(
                    text=results["documents"][0][i],
                    similarity=similarity,
                    source=meta["source"],
                    chunk_index=meta["chunk_index"],
                    source_path=meta.get("source_path", ""),
                    scale=meta.get("scale", "medium"),
                )
            )
        return retrieval_results

    def format_context(
        self, results: list[RetrievalResult], max_total_chars: int = 12000
    ) -> str:
        sections = []
        chars_used = 0
        for i, r in enumerate(results, 1):
            remaining = max_total_chars - chars_used
            if remaining <= 0:
                break
            text = r.text[:remaining] if len(r.text) > remaining else r.text
            header = f"[Source {i}: {r.source} ({r.scale})]"
            section = f"{header}\n{text}"
            sections.append(section)
            chars_used += len(section)
        return "\n\n---\n\n".join(sections)
