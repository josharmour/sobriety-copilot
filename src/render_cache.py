"""Persistent render-cache helpers for PDF and EPUB source documents."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable
from typing import Any

import pdfplumber
from bs4 import BeautifulSoup
from ebooklib import epub

RENDER_CACHE_DIR = os.environ.get(
    "RENDER_CACHE_DIR",
    os.path.join(os.path.expanduser("~"), ".cache", "sobriety-copilot", "render_cache"),
)
RENDER_CACHE_VERSION = 1
TOKEN_RE = re.compile(r"[A-Za-z0-9']+")

ProgressCallback = Callable[[dict[str, Any]], None]


def normalize_render_text(text: str) -> str:
    return " ".join(TOKEN_RE.findall((text or "").lower()))


def _should_emit_step(current: int, total: int, interval: int) -> bool:
    return current == 1 or current == total or current % max(interval, 1) == 0


def extract_pdf_render_payload(
    path: str,
    progress_callback: ProgressCallback | None = None,
    interval: int = 25,
) -> dict[str, Any]:
    page_text: list[str] = []

    try:
        with pdfplumber.open(path) as pdf:
            total_pages = len(pdf.pages)
            for index, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ""
                page_text.append(text)
                if progress_callback and _should_emit_step(index, total_pages, interval=interval):
                    progress_callback(
                        {
                            "stage": "extracting",
                            "current": index,
                            "total": total_pages,
                            "unit": "pages",
                        }
                    )
    except Exception:
        from PyPDF2 import PdfReader

        reader = PdfReader(path)
        total_pages = len(reader.pages)
        for index, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            page_text.append(text)
            if progress_callback and _should_emit_step(index, total_pages, interval=interval):
                progress_callback(
                    {
                        "stage": "extracting",
                        "current": index,
                        "total": total_pages,
                        "unit": "pages",
                    }
                )

    return {
        "kind": "pdf",
        "page_text": page_text,
        "normalized_page_text": [normalize_render_text(text) for text in page_text],
        "total_pages": len(page_text),
    }


def extract_epub_render_payload(
    path: str,
    progress_callback: ProgressCallback | None = None,
    interval: int = 10,
) -> dict[str, Any]:
    book = epub.read_epub(path, options={"ignore_ncx": True})
    sections_html: list[str] = []
    section_text: list[str] = []
    items = list(book.get_items_of_type(9))
    total_items = len(items)

    for index, item in enumerate(items, 1):
        soup = BeautifulSoup(item.get_content(), "xml")
        body = soup.find("body")
        if body:
            sections_html.append(str(body.decode_contents()))
            section_text.append(body.get_text(" ", strip=True))

        if progress_callback and _should_emit_step(index, total_items, interval=interval):
            progress_callback(
                {
                    "stage": "extracting",
                    "current": index,
                    "total": total_items,
                    "unit": "sections",
                }
            )

    return {
        "kind": "epub",
        "sections_html": sections_html,
        "section_text": section_text,
        "normalized_section_text": [normalize_render_text(text) for text in section_text],
    }


def _render_cache_file(source_path: str) -> str:
    normalized_source = os.path.abspath(source_path)
    digest = hashlib.sha1(normalized_source.encode("utf-8")).hexdigest()
    return os.path.join(RENDER_CACHE_DIR, digest[:2], f"{digest}.json")


def _source_signature(source_path: str) -> tuple[str, int, int]:
    normalized_source = os.path.abspath(source_path)
    stat = os.stat(normalized_source)
    return normalized_source, stat.st_mtime_ns, stat.st_size


def load_render_cache(source_path: str) -> dict[str, Any] | None:
    normalized_source, source_mtime_ns, source_size = _source_signature(source_path)
    cache_path = _render_cache_file(normalized_source)
    if not os.path.isfile(cache_path):
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return None

    if payload.get("cache_version") != RENDER_CACHE_VERSION:
        return None
    if payload.get("source_path") != normalized_source:
        return None
    if payload.get("source_mtime_ns") != source_mtime_ns:
        return None
    if payload.get("source_size") != source_size:
        return None
    return payload


def write_render_cache(source_path: str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized_source, source_mtime_ns, source_size = _source_signature(source_path)
    cache_path = _render_cache_file(normalized_source)
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)

    record = {
        "cache_version": RENDER_CACHE_VERSION,
        "source_path": normalized_source,
        "source_mtime_ns": source_mtime_ns,
        "source_size": source_size,
        **payload,
    }

    fd, temp_path = tempfile.mkstemp(
        dir=os.path.dirname(cache_path),
        prefix=".render-cache-",
        suffix=".json",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False)
        os.replace(temp_path, cache_path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    return record
