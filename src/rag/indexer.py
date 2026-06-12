"""Index documents into ChromaDB for RAG retrieval."""

from __future__ import annotations

import hashlib
import os
import time
from collections import Counter, defaultdict
from collections.abc import Callable

from .chroma_client import create_chroma_client
from .document_processor import DocumentProcessor
from .embeddings import EMBEDDING_PROVIDER, embed_documents
from .semantic_chunker import SemanticChunker

DEFAULT_COLLECTION = "recovery_literature"
BATCH_SIZE = int(os.environ.get("CHROMA_BATCH_SIZE", "256"))
SCALE_ORDER = ("small", "medium", "large", "topic")
CONTEXT_PARENT_PREFERENCE = {
    "small": ("medium", "large", "topic"),
    "medium": ("large", "topic"),
    "large": ("topic",),
    "topic": (),
}
TOPIC_PARENT_PREFERENCE = {
    "small": ("topic", "large", "medium"),
    "medium": ("topic", "large"),
    "large": ("topic",),
    "topic": (),
}


def _log(message: str) -> None:
    print(message, flush=True)


class RAGIndexer:
    def __init__(
        self,
        db_path: str = "rag_db",
        collection_name: str = DEFAULT_COLLECTION,
        progress_callback: Callable[[dict], None] | None = None,
    ):
        self.client = create_chroma_client(db_path)
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        self.chunker = SemanticChunker()
        self.progress_callback = progress_callback

    def _add_batch_with_retry(
        self,
        ids: list[str],
        texts: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> None:
        try:
            self.collection.add(
                ids=ids,
                documents=texts,
                embeddings=embeddings,
                metadatas=metadatas,
            )
            return
        except Exception:
            if len(ids) <= 1:
                raise

        midpoint = max(1, len(ids) // 2)
        self._add_batch_with_retry(
            ids[:midpoint],
            texts[:midpoint],
            embeddings[:midpoint],
            metadatas[:midpoint],
        )
        self._add_batch_with_retry(
            ids[midpoint:],
            texts[midpoint:],
            embeddings[midpoint:],
            metadatas[midpoint:],
        )

    def _emit(self, **payload) -> None:
        message = payload.get("message")
        if message:
            _log(message)
        if self.progress_callback is not None:
            self.progress_callback(payload)

    def _get_category(self, source_path: str, directory: str) -> str:
        rel = os.path.relpath(source_path, directory)
        parts = rel.split(os.sep)
        return parts[0] if len(parts) > 1 else "uncategorized"

    def _get_relative_path(self, source_path: str, directory: str) -> str:
        return os.path.relpath(source_path, directory).replace(os.sep, "/")

    def _document_key(self, source_path: str, directory: str) -> str:
        rel_path = self._get_relative_path(source_path, directory)
        return hashlib.sha1(rel_path.encode("utf-8")).hexdigest()[:16]

    def _find_covering_parent(
        self,
        record: dict,
        records_by_scale: dict[str, list[dict]],
        preferred_scales: tuple[str, ...],
    ) -> dict:
        for scale in preferred_scales:
            for candidate in records_by_scale.get(scale, []):
                if (
                    candidate["start_paragraph"] <= record["start_paragraph"]
                    and candidate["end_paragraph"] >= record["end_paragraph"]
                ):
                    return candidate
        return record

    def _build_records_for_document(self, doc, directory: str) -> list[dict]:
        category = self._get_category(doc.source_path, directory)
        relative_path = self._get_relative_path(doc.source_path, directory)
        document_key = self._document_key(doc.source_path, directory)
        chunks = self.chunker.chunk(doc.text)
        scale_counts: Counter[str] = Counter()
        records = []

        for chunk in chunks:
            scale = chunk["scale"]
            chunk_index = scale_counts[scale]
            scale_counts[scale] += 1
            chunk_id = f"{document_key}_{scale}_chunk_{chunk_index}"
            records.append(
                {
                    "id": chunk_id,
                    "text": chunk["text"],
                    "metadata": {
                        "source": doc.source,
                        "relative_path": relative_path,
                        "source_path": doc.source_path,
                        "chunk_index": chunk_index,
                        "scale": scale,
                        "category": category,
                        "document_key": document_key,
                        "start_paragraph": chunk["start_paragraph"],
                        "end_paragraph": chunk["end_paragraph"],
                    },
                    "scale": scale,
                    "start_paragraph": chunk["start_paragraph"],
                    "end_paragraph": chunk["end_paragraph"],
                }
            )

        records_by_scale: dict[str, list[dict]] = defaultdict(list)
        for record in records:
            records_by_scale[record["scale"]].append(record)

        for record in records:
            scale = record["scale"]
            context_parent = self._find_covering_parent(
                record,
                records_by_scale,
                CONTEXT_PARENT_PREFERENCE.get(scale, ()),
            )
            topic_parent = self._find_covering_parent(
                record,
                records_by_scale,
                TOPIC_PARENT_PREFERENCE.get(scale, ()),
            )

            record["metadata"]["parent_id"] = context_parent["id"]
            record["metadata"]["parent_scale"] = context_parent["scale"]
            record["metadata"]["context_parent_id"] = context_parent["id"]
            record["metadata"]["context_parent_scale"] = context_parent["scale"]
            record["metadata"]["topic_parent_id"] = topic_parent["id"]
            record["metadata"]["topic_parent_scale"] = topic_parent["scale"]

        return records

    def index_directory(self, directory: str) -> int:
        """Process and index all documents in a directory. Returns chunk count."""
        start_time = time.time()
        self._emit(stage="reading", progress=5, message="[1/4] Reading documents...")

        def on_read_progress(payload: dict) -> None:
            files_total = max(int(payload.get("files_total", 0)), 1)
            files_processed = int(payload.get("files_processed", 0))
            filename = payload.get("current_file", "")
            status = payload.get("status", "processed")
            current_file_progress = int(payload.get("current_file_progress", 0))
            current_file_total = max(int(payload.get("current_file_total", 0)), 0)
            current_file_fraction = (
                current_file_progress / current_file_total if current_file_total > 0 else 0.0
            )
            progress_ratio = min(files_processed + current_file_fraction, files_total) / files_total
            progress = 5 + int(progress_ratio * 10)
            status_word = {
                "processed": "Processed",
                "empty": "Read",
                "error": "Skipped",
                "extracting": "Reading",
            }.get(status, "Processed")
            display_index = files_processed if status != "extracting" else min(files_processed + 1, files_total)
            message = f"[1/4] {status_word} {display_index}/{files_total}: {filename}"
            if status == "extracting" and current_file_total > 0:
                unit = payload.get("current_file_unit", "steps")
                message += f" ({current_file_progress}/{current_file_total} {unit})"
            if status == "error" and payload.get("error"):
                message += f" ({payload['error']})"
            self._emit(
                stage="reading",
                progress=min(progress, 14),
                files_processed=files_processed,
                files_total=files_total,
                current_file=filename,
                current_file_progress=current_file_progress,
                current_file_total=current_file_total,
                current_file_unit=payload.get("current_file_unit"),
                message=message,
            )

        processor = DocumentProcessor(directory, progress_callback=on_read_progress)
        documents = processor.process_all()
        self._emit(
            stage="reading",
            progress=15,
            documents_total=len(documents),
            message=f"[1/4] Found {len(documents)} documents ({time.time() - start_time:.0f}s)",
        )

        self._emit(stage="chunking", progress=20, message="[2/4] Chunking documents...")
        all_records = []
        scale_summary: Counter[str] = Counter()

        for index, doc in enumerate(documents, 1):
            records = self._build_records_for_document(doc, directory)
            all_records.extend(records)
            for record in records:
                scale_summary[record["scale"]] += 1

            if index % 10 == 0 or index == len(documents):
                progress = 20 + int((index / max(len(documents), 1)) * 25)
                self._emit(
                    stage="chunking",
                    progress=min(progress, 45),
                    documents_processed=index,
                    documents_total=len(documents),
                    chunks_so_far=len(all_records),
                    message=(
                        f"[2/4] Chunked {index}/{len(documents)} documents "
                        f"({len(all_records)} chunks so far)"
                    ),
                )

        if not all_records:
            self._emit(stage="complete", progress=100, message="No indexable text found")
            return 0

        self._emit(
            stage="chunking",
            progress=50,
            chunks_total=len(all_records),
            message=(
                f"[2/4] Total: {len(all_records)} chunks - "
                f"small: {scale_summary.get('small', 0)}, "
                f"medium: {scale_summary.get('medium', 0)}, "
                f"large: {scale_summary.get('large', 0)}, "
                f"topic: {scale_summary.get('topic', 0)} "
                f"({time.time() - start_time:.0f}s)"
            ),
        )

        self._emit(
            stage="embedding",
            progress=55,
            chunks_total=len(all_records),
            message=(
                f"[3/4] Embedding {len(all_records)} chunks "
                f"using {EMBEDDING_PROVIDER}..."
            ),
        )
        embed_start = time.time()
        texts = [record["text"] for record in all_records]
        embeddings = embed_documents(texts, batch_size=32).tolist()
        self._emit(
            stage="embedding",
            progress=70,
            message=f"[3/4] Embedding complete ({time.time() - embed_start:.0f}s)",
        )

        self._emit(stage="writing", progress=75, message="[4/4] Writing to ChromaDB...")
        ids = [record["id"] for record in all_records]
        metadatas = [record["metadata"] for record in all_records]

        for index in range(0, len(all_records), BATCH_SIZE):
            end = min(index + BATCH_SIZE, len(all_records))
            self._add_batch_with_retry(
                ids=ids[index:end],
                texts=texts[index:end],
                embeddings=embeddings[index:end],
                metadatas=metadatas[index:end],
            )
            progress = 75 + int((end / len(all_records)) * 20)
            self._emit(
                stage="writing",
                progress=min(progress, 95),
                chunks_written=end,
                chunks_total=len(all_records),
                message=f"[4/4] Inserted {end}/{len(all_records)} chunks",
            )

        elapsed = time.time() - start_time
        self._emit(
            stage="complete",
            progress=100,
            indexed_chunks=len(all_records),
            message=(
                f"Done! Indexed {len(all_records)} chunks from "
                f"{len(documents)} documents in {elapsed:.0f}s"
            ),
        )
        return len(all_records)

    def clear(self) -> None:
        """Remove all documents from the collection."""
        try:
            self.client.delete_collection(self.collection.name)
        except Exception:
            pass
        self.collection = self.client.get_or_create_collection(
            name=self.collection.name,
            metadata={"hnsw:space": "cosine"},
        )
