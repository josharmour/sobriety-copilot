"""Celery tasks for background indexing."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

from src.rag.chroma_client import create_chroma_client
from .celery_app import celery_app
from .job_store import (
    clear_active_index_task,
    set_index_version,
    swap_active_collection_name,
    update_index_task,
)
from src.rag.indexer import RAGIndexer

SHADOW_COLLECTION_DELIMITER = "__shadow__"
COLLECTION_TOKEN_RE = re.compile(r"[^a-zA-Z0-9]+")


def _base_collection_name(collection_name: str) -> str:
    if SHADOW_COLLECTION_DELIMITER in collection_name:
        return collection_name.split(SHADOW_COLLECTION_DELIMITER, 1)[0]
    return collection_name


def build_shadow_collection_name(base_collection_name: str, task_id: str) -> str:
    root_name = _base_collection_name(base_collection_name)
    token = COLLECTION_TOKEN_RE.sub("", task_id).lower()[:20] or str(int(time.time()))
    return f"{root_name}{SHADOW_COLLECTION_DELIMITER}{token}"


def is_managed_shadow_collection(collection_name: str, base_collection_name: str) -> bool:
    root_name = _base_collection_name(base_collection_name)
    return collection_name.startswith(f"{root_name}{SHADOW_COLLECTION_DELIMITER}")


def delete_collection_if_exists(db_path: str, collection_name: str | None) -> None:
    if not collection_name:
        return
    client = create_chroma_client(db_path)
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass


def perform_shadow_index(
    *,
    directory: str,
    db_path: str,
    base_collection_name: str,
    task_id: str,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    target_collection = build_shadow_collection_name(base_collection_name, task_id)
    swapped = False

    try:
        indexer = RAGIndexer(
            db_path=db_path,
            collection_name=target_collection,
            progress_callback=progress_callback,
        )
        indexer.clear()
        count = indexer.index_directory(directory)

        previous_collection, stale_collection = swap_active_collection_name(
            new_collection=target_collection,
            default_collection=_base_collection_name(base_collection_name),
        )
        swapped = True
        version = set_index_version()

        cleaned_up_collection = None
        cleanup_error = None
        if stale_collection and is_managed_shadow_collection(stale_collection, base_collection_name):
            try:
                delete_collection_if_exists(db_path, stale_collection)
                cleaned_up_collection = stale_collection
            except Exception as exc:
                cleanup_error = str(exc)

        return {
            "indexed_chunks": count,
            "active_collection": target_collection,
            "previous_collection": previous_collection,
            "stale_collection": stale_collection,
            "cleaned_up_collection": cleaned_up_collection,
            "cleanup_error": cleanup_error,
            "index_version": version,
        }
    except Exception:
        if not swapped:
            delete_collection_if_exists(db_path, target_collection)
        raise


@celery_app.task(bind=True, name="src.tasks.indexing.index_documents_task")
def index_documents_task(
    self,
    directory: str,
    db_path: str,
    collection_name: str,
) -> dict[str, Any]:
    task_id = self.request.id or ""
    started_at = round(time.time(), 3)
    update_index_task(
        task_id,
        status="running",
        stage="starting",
        progress=1,
        started_at=started_at,
        message=f"Started indexing job for {directory}",
    )

    def on_progress(payload: dict[str, Any]) -> None:
        current = update_index_task(
            task_id,
            status="running",
            **payload,
        )
        self.update_state(state="PROGRESS", meta=current)

    try:
        build_result = perform_shadow_index(
            directory=directory,
            db_path=db_path,
            base_collection_name=collection_name,
            task_id=task_id,
            progress_callback=on_progress,
        )
        completed_at = round(time.time(), 3)
        count = int(build_result["indexed_chunks"])
        message = f"Indexed {count} chunks and activated the new search collection"
        if build_result.get("cleanup_error"):
            message += f" (cleanup warning: {build_result['cleanup_error']})"
        result = update_index_task(
            task_id,
            status="completed",
            stage="complete",
            progress=100,
            indexed_chunks=count,
            active_collection=build_result["active_collection"],
            previous_collection=build_result.get("previous_collection"),
            cleaned_up_collection=build_result.get("cleaned_up_collection"),
            message=message,
            completed_at=completed_at,
            index_version=build_result["index_version"],
        )
        clear_active_index_task(task_id)
        return result
    except Exception as exc:
        completed_at = round(time.time(), 3)
        failure = update_index_task(
            task_id,
            status="failed",
            stage="failed",
            error=str(exc),
            message=f"Indexing failed: {exc}",
            completed_at=completed_at,
        )
        clear_active_index_task(task_id)
        self.update_state(state="FAILURE", meta=failure)
        raise
