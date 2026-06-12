"""Celery application configuration."""

from __future__ import annotations

import os

from celery import Celery

REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
INDEX_QUEUE = os.environ.get("INDEX_QUEUE_NAME", "indexing")
VISIBILITY_TIMEOUT = int(os.environ.get("CELERY_VISIBILITY_TIMEOUT", "43200"))

celery_app = Celery(
    "sobriety_copilot",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["src.tasks.indexing"],
)

celery_app.conf.update(
    task_default_queue=INDEX_QUEUE,
    task_routes={"src.tasks.indexing.index_documents_task": {"queue": INDEX_QUEUE}},
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=int(os.environ.get("CELERY_RESULT_EXPIRES", "86400")),
    broker_connection_retry_on_startup=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_transport_options={"visibility_timeout": VISIBILITY_TIMEOUT},
    result_backend_transport_options={"visibility_timeout": VISIBILITY_TIMEOUT},
)
