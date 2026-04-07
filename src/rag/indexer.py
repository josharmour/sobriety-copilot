"""Index documents into ChromaDB for RAG retrieval."""

import os
import sys
import time

import chromadb
from chromadb.config import Settings

from .document_processor import DocumentProcessor
from .embeddings import embed_documents
from .semantic_chunker import SemanticChunker

DEFAULT_COLLECTION = "recovery_literature"
BATCH_SIZE = 5000


def _log(msg):
    print(msg, flush=True)


class RAGIndexer:
    def __init__(
        self,
        db_path: str = "rag_db",
        collection_name: str = DEFAULT_COLLECTION,
    ):
        self.client = chromadb.PersistentClient(
            path=db_path,
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        self.chunker = SemanticChunker()

    def _get_category(self, source_path: str, directory: str) -> str:
        """Extract the category folder name from a document's path."""
        rel = os.path.relpath(source_path, directory)
        parts = rel.split(os.sep)
        return parts[0] if len(parts) > 1 else "uncategorized"

    def index_directory(self, directory: str) -> int:
        """Process and index all documents in a directory. Returns chunk count."""
        start_time = time.time()

        _log("[1/4] Reading documents...")
        processor = DocumentProcessor(directory)
        documents = processor.process_all()
        _log(f"[1/4] Found {len(documents)} documents ({time.time() - start_time:.0f}s)")

        _log("[2/4] Chunking documents...")
        all_texts = []
        all_metadata = []
        all_ids = []

        for i, doc in enumerate(documents, 1):
            category = self._get_category(doc.source_path, directory)
            chunks = self.chunker.chunk(doc.text)
            scale_counts = {"small": 0, "medium": 0, "large": 0}
            for chunk in chunks:
                scale = chunk["scale"]
                idx = scale_counts[scale]
                scale_counts[scale] += 1

                chunk_id = f"{doc.source}_{scale}_chunk_{idx}"
                all_texts.append(chunk["text"])
                all_metadata.append({
                    "source": doc.source,
                    "chunk_index": idx,
                    "source_path": doc.source_path,
                    "scale": scale,
                    "category": category,
                })
                all_ids.append(chunk_id)

            if i % 10 == 0 or i == len(documents):
                _log(f"[2/4] Chunked {i}/{len(documents)} documents ({len(all_texts)} chunks so far)")

        if not all_texts:
            return 0

        # Count by scale
        scale_summary = {}
        for m in all_metadata:
            scale_summary[m["scale"]] = scale_summary.get(m["scale"], 0) + 1
        _log(f"[2/4] Total: {len(all_texts)} chunks — "
             f"small: {scale_summary.get('small', 0)}, "
             f"medium: {scale_summary.get('medium', 0)}, "
             f"large: {scale_summary.get('large', 0)} "
             f"({time.time() - start_time:.0f}s)")

        _log(f"[3/4] Embedding {len(all_texts)} chunks (this takes a while on CPU)...")
        embed_start = time.time()
        embeddings = embed_documents(all_texts, batch_size=32).tolist()
        _log(f"[3/4] Embedding complete ({time.time() - embed_start:.0f}s)")

        _log(f"[4/4] Writing to ChromaDB...")
        for i in range(0, len(all_texts), BATCH_SIZE):
            end = min(i + BATCH_SIZE, len(all_texts))
            self.collection.add(
                ids=all_ids[i:end],
                documents=all_texts[i:end],
                embeddings=embeddings[i:end],
                metadatas=all_metadata[i:end],
            )
            _log(f"[4/4] Inserted {end}/{len(all_texts)} chunks")

        elapsed = time.time() - start_time
        _log(f"Done! Indexed {len(all_texts)} chunks from {len(documents)} documents in {elapsed:.0f}s")
        return len(all_texts)

    def clear(self):
        """Remove all documents from the collection."""
        self.client.delete_collection(self.collection.name)
        self.collection = self.client.get_or_create_collection(
            name=self.collection.name,
            metadata={"hnsw:space": "cosine"},
        )
