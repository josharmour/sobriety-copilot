"""Shared Chroma client configuration."""

from __future__ import annotations

import os

import chromadb
from chromadb.config import Settings


def create_chroma_client(db_path: str | None = None):
    """Create either an embedded or HTTP Chroma client from environment."""
    settings = Settings(anonymized_telemetry=False)
    chroma_host = os.environ.get("CHROMA_HOST", "").strip()

    if chroma_host:
        chroma_port = int(os.environ.get("CHROMA_PORT", "8000"))
        chroma_ssl = os.environ.get("CHROMA_SSL", "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        return chromadb.HttpClient(
            host=chroma_host,
            port=chroma_port,
            ssl=chroma_ssl,
            settings=settings,
        )

    resolved_path = db_path or os.environ.get("RAG_DB_PATH", "rag_db")
    return chromadb.PersistentClient(path=resolved_path, settings=settings)


def find_largest_collection_with_prefix(prefix: str, db_path: str | None = None) -> str | None:
    """Return the name of the non-empty collection with prefix and the largest count.

    Used as a recovery fallback when the Redis active-collection pointer is missing
    (e.g. after wiping the broker volume) — the indexer's shadow-swap pattern leaves
    real data in `<base>__shadow__<hash>` collections, so the largest matching one
    is the most-recent successful index.
    """
    try:
        client = create_chroma_client(db_path)
        best_name: str | None = None
        best_count = 0
        for collection in client.list_collections():
            name = getattr(collection, "name", "")
            if not name.startswith(prefix):
                continue
            try:
                count = collection.count()
            except Exception:
                continue
            if count > best_count:
                best_count = count
                best_name = name
        return best_name
    except Exception:
        return None
