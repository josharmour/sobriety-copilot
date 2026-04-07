"""Document processing for PDF, TXT, MD, and EPUB files."""

import os
from dataclasses import dataclass
from typing import Protocol

import pdfplumber
from bs4 import BeautifulSoup
from ebooklib import epub


@dataclass
class ProcessedDocument:
    text: str
    source: str
    source_path: str


class DocumentHandler(Protocol):
    def can_handle(self, path: str) -> bool: ...
    def extract(self, path: str) -> str: ...


class PDFHandler:
    def can_handle(self, path: str) -> bool:
        return path.lower().endswith(".pdf")

    def extract(self, path: str) -> str:
        pages = []
        try:
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        pages.append(text)
        except Exception:
            from PyPDF2 import PdfReader

            reader = PdfReader(path)
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
        return "\n\n".join(pages)


class EPUBHandler:
    def can_handle(self, path: str) -> bool:
        return path.lower().endswith(".epub")

    def extract(self, path: str) -> str:
        book = epub.read_epub(path, options={"ignore_ncx": True})
        sections = []
        for item in book.get_items_of_type(9):  # ITEM_DOCUMENT
            soup = BeautifulSoup(item.get_content(), "lxml")
            text = soup.get_text(separator="\n", strip=True)
            if text:
                sections.append(text)
        return "\n\n".join(sections)


class TextHandler:
    EXTENSIONS = (".txt", ".md")

    def can_handle(self, path: str) -> bool:
        return any(path.lower().endswith(ext) for ext in self.EXTENSIONS)

    def extract(self, path: str) -> str:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()


HANDLERS: list[DocumentHandler] = [PDFHandler(), EPUBHandler(), TextHandler()]

# Skip Synology extended attribute sidecar files
SKIP_SUFFIXES = ("@SynoEAStream",)


class DocumentProcessor:
    def __init__(self, directory: str):
        self.directory = directory

    def process_all(self) -> list[ProcessedDocument]:
        documents = []
        for dirpath, _, filenames in os.walk(self.directory):
            for filename in sorted(filenames):
                if any(filename.endswith(s) for s in SKIP_SUFFIXES):
                    continue
                filepath = os.path.join(dirpath, filename)
                if not os.path.isfile(filepath):
                    continue
                for handler in HANDLERS:
                    if handler.can_handle(filepath):
                        try:
                            text = handler.extract(filepath)
                            if text.strip():
                                documents.append(
                                    ProcessedDocument(
                                        text=text,
                                        source=filename,
                                        source_path=filepath,
                                    )
                                )
                                print(f"Processed: {filename}")
                        except Exception as e:
                            print(f"Warning: failed to process {filename}: {e}")
                        break
        return documents
