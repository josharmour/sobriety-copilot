"""Redis-backed indexing job metadata store."""

from __future__ import annotations

import json
import os
import time
from typing import Any

from celery.result import AsyncResult
from redis import Redis

from .celery_app import REDIS_URL, celery_app

TASK_TTL_SECONDS = int(os.environ.get("INDEX_TASK_TTL_SECONDS", "604800"))
TASK_LIST_LIMIT = int(os.environ.get("INDEX_TASK_LIST_LIMIT", "50"))
REDIS_SOCKET_TIMEOUT = float(os.environ.get("REDIS_SOCKET_TIMEOUT", "1.5"))
REDIS_SOCKET_CONNECT_TIMEOUT = float(os.environ.get("REDIS_SOCKET_CONNECT_TIMEOUT", "1.5"))
TASK_ORPHANED_SECONDS = int(os.environ.get("INDEX_TASK_ORPHANED_SECONDS", "180"))
INDEX_TASK_PREFIX = "sobriety:index:task:"
INDEX_TASK_LIST_KEY = "sobriety:index:tasks"
INDEX_ACTIVE_TASK_KEY = "sobriety:index:active"
INDEX_VERSION_KEY = "sobriety:index:version"
INDEX_ACTIVE_COLLECTION_KEY = "sobriety:index:active_collection"
INDEX_PREVIOUS_COLLECTION_KEY = "sobriety:index:previous_collection"
TERMINAL_STATUSES = {"completed", "failed"}
ORPHANABLE_ASYNC_STATES = {"PENDING", "RECEIVED", "STARTED", "PROGRESS"}

_redis_client: Redis | None = None


class ActiveIndexJobError(RuntimeError):
    """Raised when a non-terminal indexing job already owns the active slot."""

    def __init__(self, job: dict[str, Any]):
        self.job = job
        super().__init__(job.get("id", "active indexing job"))


def get_redis_client() -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_timeout=REDIS_SOCKET_TIMEOUT,
            socket_connect_timeout=REDIS_SOCKET_CONNECT_TIMEOUT,
        )
    return _redis_client


def _task_key(task_id: str) -> str:
    return f"{INDEX_TASK_PREFIX}{task_id}"


def _default_payload(task_id: str, directory: str) -> dict[str, Any]:
    return {
        "id": task_id,
        "directory": directory,
        "status": "queued",
        "stage": "queued",
        "progress": 0,
        "message": f"Queued indexing job for {directory}",
        "indexed_chunks": None,
        "error": None,
        "created_at": round(time.time(), 3),
        "started_at": None,
        "completed_at": None,
    }


def _load_payload(task_id: str) -> dict[str, Any] | None:
    raw = get_redis_client().get(_task_key(task_id))
    if not raw:
        return None
    return json.loads(raw)


def _save_payload(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    payload["id"] = task_id
    payload["updated_at"] = round(time.time(), 3)
    get_redis_client().set(_task_key(task_id), json.dumps(payload), ex=TASK_TTL_SECONDS)
    return payload


def ping_job_store() -> bool:
    try:
        return bool(get_redis_client().ping())
    except Exception:
        return False


def record_index_task(task_id: str, directory: str) -> dict[str, Any]:
    redis_client = get_redis_client()
    active_task_id = redis_client.get(INDEX_ACTIVE_TASK_KEY)
    if active_task_id:
        existing = get_task_status_payload(active_task_id)
        if existing and existing.get("status") not in TERMINAL_STATUSES:
            raise ActiveIndexJobError(existing)
        clear_active_index_task(active_task_id)

    if not redis_client.set(INDEX_ACTIVE_TASK_KEY, task_id, nx=True, ex=TASK_TTL_SECONDS):
        active_task_id = redis_client.get(INDEX_ACTIVE_TASK_KEY)
        existing = get_task_status_payload(active_task_id) if active_task_id else None
        if existing and existing.get("status") not in TERMINAL_STATUSES:
            raise ActiveIndexJobError(existing)
        if active_task_id:
            clear_active_index_task(active_task_id)
        if not redis_client.set(INDEX_ACTIVE_TASK_KEY, task_id, nx=True, ex=TASK_TTL_SECONDS):
            active_task_id = redis_client.get(INDEX_ACTIVE_TASK_KEY)
            existing = get_task_status_payload(active_task_id) if active_task_id else None
            raise ActiveIndexJobError(existing or {"id": active_task_id, "status": "running"})

    payload = _default_payload(task_id, directory)
    redis_client.lrem(INDEX_TASK_LIST_KEY, 0, task_id)
    redis_client.lpush(INDEX_TASK_LIST_KEY, task_id)
    redis_client.ltrim(INDEX_TASK_LIST_KEY, 0, TASK_LIST_LIMIT - 1)
    return _save_payload(task_id, payload)


def update_index_task(task_id: str, **updates: Any) -> dict[str, Any]:
    payload = _load_payload(task_id) or {"id": task_id}
    payload.update(updates)
    saved = _save_payload(task_id, payload)
    redis_client = get_redis_client()
    if redis_client.get(INDEX_ACTIVE_TASK_KEY) == task_id:
        redis_client.expire(INDEX_ACTIVE_TASK_KEY, TASK_TTL_SECONDS)
    return saved


def get_index_task(task_id: str) -> dict[str, Any] | None:
    return _load_payload(task_id)


def get_recent_index_task_ids(limit: int = 10) -> list[str]:
    return get_redis_client().lrange(INDEX_TASK_LIST_KEY, 0, limit - 1)


def get_active_index_task_id() -> str | None:
    return get_redis_client().get(INDEX_ACTIVE_TASK_KEY)


def clear_active_index_task(task_id: str) -> None:
    redis_client = get_redis_client()
    current = redis_client.get(INDEX_ACTIVE_TASK_KEY)
    if current == task_id:
        redis_client.delete(INDEX_ACTIVE_TASK_KEY)


def set_index_version(value: str | None = None) -> str:
    version = value or str(time.time())
    get_redis_client().set(INDEX_VERSION_KEY, version)
    return version


def get_index_version() -> str:
    return get_redis_client().get(INDEX_VERSION_KEY) or "0"


def get_active_collection_name(default: str) -> str:
    return get_redis_client().get(INDEX_ACTIVE_COLLECTION_KEY) or default


def get_previous_collection_name() -> str | None:
    return get_redis_client().get(INDEX_PREVIOUS_COLLECTION_KEY)


def swap_active_collection_name(
    new_collection: str,
    default_collection: str,
) -> tuple[str, str | None]:
    redis_client = get_redis_client()
    current_collection = redis_client.get(INDEX_ACTIVE_COLLECTION_KEY) or default_collection
    previous_collection = redis_client.get(INDEX_PREVIOUS_COLLECTION_KEY)

    pipeline = redis_client.pipeline()
    pipeline.set(INDEX_ACTIVE_COLLECTION_KEY, new_collection)
    if current_collection and current_collection != new_collection:
        pipeline.set(INDEX_PREVIOUS_COLLECTION_KEY, current_collection)
    elif not current_collection:
        pipeline.delete(INDEX_PREVIOUS_COLLECTION_KEY)
    pipeline.execute()

    stale_collection = None
    if previous_collection and previous_collection not in {current_collection, new_collection}:
        stale_collection = previous_collection

    return current_collection, stale_collection


def _iter_worker_task_ids(payload: dict[str, Any] | None) -> set[str]:
    task_ids: set[str] = set()
    if not payload:
        return task_ids
    for entries in payload.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            task_id = entry.get("id")
            if isinstance(task_id, str):
                task_ids.add(task_id)
            request = entry.get("request")
            if isinstance(request, dict):
                request_id = request.get("id")
                if isinstance(request_id, str):
                    task_ids.add(request_id)
    return task_ids


def task_seen_by_workers(task_id: str) -> bool | None:
    inspect = celery_app.control.inspect(timeout=1.0)
    responses: list[dict[str, Any]] = []

    for method_name in ("active", "reserved", "scheduled"):
        method = getattr(inspect, method_name)
        try:
            payload = method()
        except Exception:
            continue
        if payload:
            responses.append(payload)
            if task_id in _iter_worker_task_ids(payload):
                return True

    if responses:
        return False
    return None


def _mark_task_orphaned(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    failed = update_index_task(
        task_id,
        status="failed",
        stage="failed",
        progress=100,
        error="indexing task was interrupted or lost after a worker restart",
        message="Indexing failed: indexing task was interrupted or lost after a worker restart",
        completed_at=round(time.time(), 3),
    )
    clear_active_index_task(task_id)
    return failed


def _stored_payload_is_orphaned(task_id: str, payload: dict[str, Any], async_state: str) -> bool:
    if payload.get("status") in TERMINAL_STATUSES:
        return False
    if async_state not in ORPHANABLE_ASYNC_STATES:
        return False

    updated_at = float(
        payload.get("updated_at")
        or payload.get("started_at")
        or payload.get("created_at")
        or 0
    )
    if updated_at <= 0:
        return False
    if (time.time() - updated_at) < TASK_ORPHANED_SECONDS:
        return False

    worker_status = task_seen_by_workers(task_id)
    return worker_status is False


def _normalize_from_async_result(task_id: str, result: AsyncResult) -> dict[str, Any] | None:
    if result.state == "PENDING":
        return None

    if isinstance(result.info, dict):
        payload = dict(result.info)
        payload.setdefault("id", task_id)
        return payload

    if result.state == "FAILURE":
        return {
            "id": task_id,
            "status": "failed",
            "stage": "failed",
            "progress": 100,
            "message": f"Indexing failed: {result.info}",
            "error": str(result.info),
        }

    if result.state == "REVOKED":
        return {
            "id": task_id,
            "status": "failed",
            "stage": "failed",
            "progress": 100,
            "message": "Indexing cancelled",
            "error": "cancelled",
        }

    if result.state == "SUCCESS" and isinstance(result.result, dict):
        payload = dict(result.result)
        payload.setdefault("id", task_id)
        return payload

    return {"id": task_id, "status": result.state.lower(), "stage": result.state.lower()}


def get_task_status_payload(task_id: str | None = None) -> dict[str, Any] | None:
    resolved_task_id = task_id or get_active_index_task_id()
    if not resolved_task_id:
        return None

    stored = get_index_task(resolved_task_id)
    async_result = AsyncResult(resolved_task_id, app=celery_app)
    async_payload = _normalize_from_async_result(resolved_task_id, async_result)

    if async_payload and async_payload.get("status") in TERMINAL_STATUSES:
        stored = update_index_task(resolved_task_id, **async_payload)
        clear_active_index_task(resolved_task_id)
        return stored

    if stored:
        if _stored_payload_is_orphaned(resolved_task_id, stored, async_result.state):
            return _mark_task_orphaned(resolved_task_id, stored)
        if stored.get("status") in TERMINAL_STATUSES:
            clear_active_index_task(resolved_task_id)
        return stored

    return async_payload
