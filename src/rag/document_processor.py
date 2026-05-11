"""Document processing for PDF, TXT, MD, and EPUB files."""

from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass
from typing import Callable
from typing import Protocol
from src.render_cache import (
    extract_epub_render_payload,
    extract_pdf_render_payload,
    write_render_cache,
)

# Matches lines that look like running headers:
# "CHAPTER TITLE 123", "123 BOOK TITLE", "Page 123", roman numerals, etc.
_HEADER_LINE_RE = re.compile(
    r"^(?:"
    r"[A-Z][A-Z\s\-\.,'&:;!?\"]+\d+|"       # TITLE 123
    r"\d+\s+[A-Z][A-Z\s\-\.,'&:;!?\"]+|"     # 123 TITLE
    r"[Pp]age\s+\d+|"                          # Page 123
    r"[ivxlcdm]+\s*$"                           # roman numerals alone
    r")$"
)


def _detect_running_headers(pages: list[str], threshold: int = 3) -> set[str]:
    """Detect repeated header patterns across pages.

    A line that appears (with only the page number varying) on many pages
    is likely a running header.  We normalize by replacing digits with #
    and count how many pages share each pattern.
    """
    pattern_counts: Counter[str] = Counter()
    for page in pages:
        lines = page.split("\n")
        seen_on_page: set[str] = set()
        # Check first 3 and last 2 lines of each page
        candidate_lines = lines[:3] + lines[-2:]
        for line in candidate_lines:
            stripped = line.strip()
            if not stripped or len(stripped) > 80:
                continue
            normalized = re.sub(r"\d+", "#", stripped)
            if normalized not in seen_on_page:
                seen_on_page.add(normalized)
                pattern_counts[normalized] += 1

    # Patterns appearing on many pages are running headers
    return {p for p, count in pattern_counts.items() if count >= threshold}


_ALWAYS_STRIP_RE = re.compile(
    r"^(?:"
    r"[Pp]age\s+\d+|"           # "Page 65"
    r"\d+$"                      # standalone page number
    r")$"
)


def _strip_page_headers(page_text: str, header_patterns: set[str]) -> str:
    """Remove running header/footer lines from a single page's text."""
    lines = page_text.split("\n")
    cleaned = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            cleaned.append(line)
            continue
        # Only check first 3 and last 2 lines
        if i < 3 or i >= len(lines) - 2:
            if _ALWAYS_STRIP_RE.match(stripped):
                continue
            normalized = re.sub(r"\d+", "#", stripped)
            if normalized in header_patterns:
                continue
        cleaned.append(line)
    return "\n".join(cleaned)


def clean_extracted_pages(pages: list[str]) -> list[str]:
    """Remove running headers/footers from extracted PDF page text."""
    header_patterns = _detect_running_headers(pages)
    return [_strip_page_headers(page, header_patterns) for page in pages]


@dataclass
class ProcessedDocument:
    text: str
    source: str
    source_path: str


@dataclass
class ExtractedDocument:
    text: str
    render_payload: dict | None = None


ProgressCallback = Callable[[dict], None]


class DocumentHandler(Protocol):
    def can_handle(self, path: str) -> bool: ...
    def extract(self, path: str, progress_callback: ProgressCallback | None = None) -> ExtractedDocument: ...


class PDFHandler:
    def can_handle(self, path: str) -> bool:
        return path.lower().endswith(".pdf")

    def extract(self, path: str, progress_callback: ProgressCallback | None = None) -> ExtractedDocument:
        render_payload = extract_pdf_render_payload(path, progress_callback=progress_callback, interval=25)
        pages = render_payload["page_text"]
        cleaned_pages = clean_extracted_pages(pages)
        text = "\n\n".join(page for page in cleaned_pages if page.strip())
        return ExtractedDocument(text=text, render_payload=render_payload)


class EPUBHandler:
    def can_handle(self, path: str) -> bool:
        return path.lower().endswith(".epub")

    def extract(self, path: str, progress_callback: ProgressCallback | None = None) -> ExtractedDocument:
        render_payload = extract_epub_render_payload(path, progress_callback=progress_callback, interval=10)
        text = "\n\n".join(section for section in render_payload["section_text"] if section.strip())
        return ExtractedDocument(text=text, render_payload=render_payload)


class TextHandler:
    EXTENSIONS = (".txt", ".md")

    def can_handle(self, path: str) -> bool:
        return any(path.lower().endswith(ext) for ext in self.EXTENSIONS)

    def extract(self, path: str, progress_callback: ProgressCallback | None = None) -> ExtractedDocument:
        with open(path, "r", encoding="utf-8") as f:
            return ExtractedDocument(text=f.read())


HANDLERS: list[DocumentHandler] = [PDFHandler(), EPUBHandler(), TextHandler()]

# Skip Synology extended attribute sidecar files
SKIP_SUFFIXES = ("@SynoEAStream",)


class DocumentProcessor:
    def __init__(
        self,
        directory: str,
        progress_callback: Callable[[dict], None] | None = None,
    ):
        self.directory = directory
        self.progress_callback = progress_callback

    def _emit(self, **payload) -> None:
        if self.progress_callback is not None:
            self.progress_callback(payload)

    def _iter_supported_files(self) -> list[str]:
        supported_files = []
        for dirpath, _, filenames in os.walk(self.directory):
            for filename in sorted(filenames):
                if any(filename.endswith(s) for s in SKIP_SUFFIXES):
                    continue
                filepath = os.path.join(dirpath, filename)
                if not os.path.isfile(filepath):
                    continue
                if any(handler.can_handle(filepath) for handler in HANDLERS):
                    supported_files.append(filepath)
        return supported_files

    def process_all(self) -> list[ProcessedDocument]:
        documents = []
        supported_files = self._iter_supported_files()
        total_files = len(supported_files)

        for index, filepath in enumerate(supported_files, 1):
            filename = os.path.basename(filepath)
            for handler in HANDLERS:
                if handler.can_handle(filepath):
                    try:
                        def on_file_progress(payload: dict) -> None:
                            self._emit(
                                files_processed=index - 1,
                                files_total=total_files,
                                current_file=filename,
                                current_file_stage=payload.get("stage", "extracting"),
                                current_file_progress=payload.get("current", 0),
                                current_file_total=payload.get("total", 0),
                                current_file_unit=payload.get("unit", "steps"),
                                status="extracting",
                            )

                        extracted = handler.extract(filepath, progress_callback=on_file_progress)
                        text = extracted.text
                        if text.strip():
                            if extracted.render_payload:
                                try:
                                    write_render_cache(filepath, extracted.render_payload)
                                except Exception as cache_exc:
                                    print(f"Warning: failed to write render cache for {filename}: {cache_exc}")
                            documents.append(
                                ProcessedDocument(
                                    text=text,
                                    source=filename,
                                    source_path=filepath,
                                )
                            )
                            print(f"Processed: {filename}")
                            self._emit(
                                files_processed=index,
                                files_total=total_files,
                                current_file=filename,
                                extracted_chars=len(text),
                                status="processed",
                            )
                        else:
                            self._emit(
                                files_processed=index,
                                files_total=total_files,
                                current_file=filename,
                                extracted_chars=0,
                                status="empty",
                            )
                    except Exception as e:
                        print(f"Warning: failed to process {filename}: {e}")
                        self._emit(
                            files_processed=index,
                            files_total=total_files,
                            current_file=filename,
                            status="error",
                            error=str(e),
                        )
                    break
        return documents
