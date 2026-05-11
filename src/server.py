"""FastAPI server with chat and indexing endpoints."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from threading import Lock
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from src.render_cache import (
    extract_epub_render_payload,
    extract_pdf_render_payload,
    load_render_cache,
    normalize_render_text,
    write_render_cache,
)

from src.inference.engine import InferenceEngine
from src.meetings.service import search_meetings, warmup_feeds as warmup_meeting_feeds
from src.prompts.templates import NO_CONTEXT_TEMPLATE, USER_MESSAGE_TEMPLATE, system_message_for_tone
from src.rag.chroma_client import find_largest_collection_with_prefix
from src.rag.embeddings import warmup as warmup_embeddings
from src.rag.indexer import DEFAULT_COLLECTION
from src.rag.reranker import warmup as warmup_reranker
from src.rag.retriever import RAGRetriever
from src.tasks.indexing import index_documents_task, perform_shadow_index
from src.tasks.job_store import (
    INDEX_ACTIVE_COLLECTION_KEY,
    ActiveIndexJobError,
    clear_active_index_task,
    get_active_collection_name,
    get_index_version,
    get_recent_index_task_ids,
    get_redis_client,
    get_task_status_payload,
    ping_job_store,
    record_index_task,
    set_index_version,
    swap_active_collection_name,
    update_index_task,
)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATIC_DIR = os.path.join(BASE_DIR, "static")
INDEX_HTML_PATH = os.path.join(STATIC_DIR, "index.html")

BASE_URL = os.environ.get("LLM_BASE_URL", "http://172.20.48.1:11434/v1")
MODEL = os.environ.get("LLM_MODEL", "gemma4:e2b")
API_KEY = os.environ.get("LLM_API_KEY", "ollama")
DOCUMENTS_DIR = os.environ.get("DOCUMENTS_DIR", "documents")
RAG_DB_PATH = os.environ.get("RAG_DB_PATH", "rag_db")
RAG_COLLECTION = os.environ.get("RAG_COLLECTION", DEFAULT_COLLECTION)

engine = InferenceEngine(base_url=BASE_URL, model=MODEL, api_key=API_KEY)
retriever: RAGRetriever | None = None
retriever_version = "0"
retriever_collection_name = RAG_COLLECTION
TERMINAL_JOB_STATUSES = {"completed", "failed"}
SUGGESTION_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")
QUESTION_START_RE = re.compile(
    r"^(what|how|why|where|when|who|can|could|would|should|is|are|do|does|did|will)\b",
    re.IGNORECASE,
)
MONTH_DAY_RE = re.compile(
    r"^(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}$",
    re.IGNORECASE,
)
LEADING_DATE_RE = re.compile(
    r"^(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}\s+",
    re.IGNORECASE,
)
LEADING_SECTION_NUMBER_RE = re.compile(r"^(?:\d+\s+){1,3}")
SUGGESTION_PROMPT_TEMPLATES = (
    "What does recovery literature say about {subject}?",
    "Can you explain {subject}?",
    "Can you show me passages about {subject}?",
    "Where should I start reading about {subject}?",
    "How does recovery literature describe {subject}?",
)
ACTION_SUGGESTION_PROMPT_TEMPLATES = (
    "What does recovery literature say about how to {subject}?",
    "Can you explain how to {subject}?",
    "Can you show me passages about how to {subject}?",
    "Where should I start reading about how to {subject}?",
    "How does recovery literature handle {subject}?",
)
ACTION_PHRASE_VERBS = {
    "accept",
    "change",
    "deal",
    "face",
    "find",
    "forgive",
    "handle",
    "let",
    "make",
    "manage",
    "practice",
    "pray",
    "read",
    "work",
    "write",
}
SUGGESTION_RETRIEVE_TOP_K = int(os.environ.get("SUGGESTION_RETRIEVE_TOP_K", "24"))
SUGGESTION_LIMIT = int(os.environ.get("SUGGESTION_LIMIT", "5"))
RENDER_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")
RENDER_CACHE_MAX_DOCUMENTS = int(os.environ.get("RENDER_CACHE_MAX_DOCUMENTS", "8"))
render_document_cache: OrderedDict[tuple[str, int, int], dict[str, Any]] = OrderedDict()
render_document_cache_lock = Lock()


class ChatRequest(BaseModel):
    message: str
    history: list[dict[str, Any]] = Field(default_factory=list)
    categories: list[str] | None = None
    tone: str | None = None
    show_thinking: bool = False


class IndexRequest(BaseModel):
    directory: str | None = None
    wait: bool = False


class BugReport(BaseModel):
    description: str
    conversation: list[dict[str, Any]] = Field(default_factory=list)
    url: str = ""


def _normalize_render_text(text: str) -> str:
    return normalize_render_text(text)


def _get_render_cache_key(full_path: str) -> tuple[str, int, int]:
    stat = os.stat(full_path)
    return (os.path.abspath(full_path), stat.st_mtime_ns, stat.st_size)


def _get_cached_render_document(full_path: str) -> dict[str, Any] | None:
    cache_key = _get_render_cache_key(full_path)
    with render_document_cache_lock:
        cached = render_document_cache.get(cache_key)
        if cached is None:
            return None
        render_document_cache.move_to_end(cache_key)
        return cached


def _store_cached_render_document(full_path: str, payload: dict[str, Any]) -> dict[str, Any]:
    cache_key = _get_render_cache_key(full_path)
    cache_path = cache_key[0]
    with render_document_cache_lock:
        stale_keys = [key for key in render_document_cache if key[0] == cache_path and key != cache_key]
        for stale_key in stale_keys:
            del render_document_cache[stale_key]
        render_document_cache[cache_key] = payload
        render_document_cache.move_to_end(cache_key)
        while len(render_document_cache) > RENDER_CACHE_MAX_DOCUMENTS:
            render_document_cache.popitem(last=False)
    return payload


def _load_pdf_render_document(full_path: str) -> dict[str, Any]:
    return extract_pdf_render_payload(full_path)


def _load_epub_render_document(full_path: str) -> dict[str, Any]:
    return extract_epub_render_payload(full_path)


def _get_render_document(full_path: str) -> dict[str, Any]:
    cached = _get_cached_render_document(full_path)
    if cached is not None:
        return cached

    cached_file = load_render_cache(full_path)
    if cached_file is not None:
        return _store_cached_render_document(full_path, cached_file)

    lower = full_path.lower()
    if lower.endswith(".pdf"):
        payload = _load_pdf_render_document(full_path)
    elif lower.endswith(".epub"):
        payload = _load_epub_render_document(full_path)
    else:
        raise HTTPException(status_code=400, detail="Unsupported format")

    try:
        payload = write_render_cache(full_path, payload)
    except Exception:
        pass

    return _store_cached_render_document(full_path, payload)


def _ordered_term_hits(text: str, terms: list[str]) -> int:
    if not text or not terms:
        return 0

    cursor = 0
    hits = 0
    for term in terms:
        index = text.find(term, cursor)
        if index == -1:
            break
        hits += 1
        cursor = index + len(term)
    return hits


def _find_best_render_match(candidates: list[str], highlight: str, *, normalized: bool = False) -> int | None:
    terms = []
    seen_terms = set()
    for token in RENDER_TOKEN_RE.findall((highlight or "").lower()):
        if len(token) < 2 or token in seen_terms:
            continue
        terms.append(token)
        seen_terms.add(token)
        if len(terms) >= 12:
            break

    if not terms:
        return None

    short_phrase = " ".join(terms[: min(len(terms), 8)])
    long_phrase = " ".join(terms)
    best_index = None
    best_score = 0

    for index, candidate in enumerate(candidates):
        candidate_text = candidate if normalized else _normalize_render_text(candidate)
        if not candidate_text:
            continue

        score = 0
        if long_phrase and long_phrase in candidate_text:
            score += 250
        if short_phrase and short_phrase in candidate_text:
            score += 160

        token_hits = sum(1 for term in terms if term in candidate_text)
        ordered_hits = _ordered_term_hits(candidate_text, terms[:8])
        early_window = candidate_text[: min(len(candidate_text), 900)]
        early_hits = sum(1 for term in terms[:6] if term in early_window)

        score += token_hits * 14
        score += ordered_hits * 20
        score += early_hits * 6

        if score > best_score:
            best_score = score
            best_index = index

    minimum_score = max(36, min(len(terms), 4) * 14)
    if best_score < minimum_score:
        return None
    return best_index


def _locate_highlight_span(highlight: str, content: str) -> tuple[int, int] | None:
    """Find where a snippet appears in the rendered (HTML-escaped) page text.

    The rendered content has whitespace, <br> tags, page-divider markup, and
    HTML-escaped punctuation interleaved with the words. The retrieval-time
    snippet has none of that. So we ignore everything but alphanumeric tokens
    and require them to appear in order, with arbitrary non-alphanumeric
    content between them. Among all valid matches we prefer the SHORTEST
    span — that's almost always the actual paragraph (a heading + paragraph
    coincidence has a much wider span).
    """
    # Pure alphanumeric tokens — ignoring apostrophes lets us match the same
    # word even when the document uses curly quotes vs the chunk's straight ones.
    tokens = [t for t in re.findall(r"[A-Za-z0-9]+", highlight or "") if len(t) >= 3]
    # Cap at 10; more is usually noise that hurts match rate.
    tokens = tokens[:10]
    if len(tokens) < 2:
        return None

    def _try(n: int, gap: int) -> tuple[int, int] | None:
        # Take the first N significant tokens, allow up to `gap` chars (of any
        # kind: words, whitespace, HTML tags, page-break markup) between
        # consecutive ones, lazily-matched so we get the tightest window.
        if n < 2:
            return None
        sep = r"[\s\S]{1," + str(gap) + r"}?"
        pat = re.compile(
            r"\b" + sep.join(re.escape(t) for t in tokens[:n]) + r"\b",
            flags=re.IGNORECASE,
        )
        best: tuple[int, int] | None = None
        for m in pat.finditer(content):
            span = (m.start(), m.end())
            if best is None or (span[1] - span[0]) < (best[1] - best[0]):
                best = span
        return best

    # Try progressively looser configurations. Most snippets resolve at the
    # first or second attempt; the long-tail keeps us from leaving the user
    # at the top of the page. Smaller gap first → tighter (more accurate)
    # match wins when both succeed.
    for n, gap in ((10, 50), (8, 60), (6, 80), (4, 120), (3, 160)):
        if n > len(tokens):
            continue
        hit = _try(n, gap)
        if hit:
            return hit
    return None


def _get_active_collection_name_safe() -> str:
    try:
        stored = get_redis_client().get(INDEX_ACTIVE_COLLECTION_KEY)
    except Exception:
        stored = None
    if stored:
        return stored

    recovered = find_largest_collection_with_prefix(
        f"{RAG_COLLECTION}__shadow__",
        db_path=RAG_DB_PATH,
    )
    if recovered:
        try:
            swap_active_collection_name(recovered, RAG_COLLECTION)
            set_index_version()
        except Exception:
            pass
        return recovered

    return RAG_COLLECTION


def _build_retriever(collection_name: str | None = None) -> RAGRetriever:
    return RAGRetriever(
        db_path=RAG_DB_PATH,
        collection_name=collection_name or _get_active_collection_name_safe(),
    )


def _get_shared_index_version() -> str:
    try:
        return get_index_version()
    except Exception:
        return retriever_version


def _refresh_retriever(force: bool = False) -> None:
    global retriever, retriever_collection_name, retriever_version
    shared_version = _get_shared_index_version()
    shared_collection_name = _get_active_collection_name_safe()
    if (
        force
        or retriever is None
        or retriever_version != shared_version
        or retriever_collection_name != shared_collection_name
    ):
        retriever = _build_retriever(shared_collection_name)
        retriever_version = shared_version
        retriever_collection_name = shared_collection_name


def _get_retriever() -> RAGRetriever:
    _refresh_retriever()
    assert retriever is not None
    return retriever


def _safe_get_retriever() -> RAGRetriever:
    try:
        return _get_retriever()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"retriever unavailable: {exc}") from exc


def _normalize_categories(categories: list[str] | None) -> list[str] | None:
    if not categories:
        return None
    cleaned = [category.strip() for category in categories if category and category.strip()]
    return cleaned or None


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _suggestion_tokens(text: str) -> list[str]:
    return [
        token.lower()
        for token in SUGGESTION_TOKEN_RE.findall(text)
        if any(char.isalpha() for char in token) and len(token) > 1
    ]


def _looks_like_noise_topic(text: str) -> bool:
    cleaned = _normalize_whitespace(text).strip(" \"'`.,:;!?()[]{}-")
    if len(cleaned) < 4:
        return True
    if MONTH_DAY_RE.fullmatch(cleaned):
        return True

    raw_tokens = [token for token in SUGGESTION_TOKEN_RE.findall(cleaned) if any(char.isalpha() for char in token)]
    if sum(len(token) == 1 for token in raw_tokens) >= 2:
        return True

    tokens = _suggestion_tokens(cleaned)
    if not tokens:
        return True
    if len(tokens) <= 2 and all(len(token) <= 2 for token in tokens):
        return True
    if len(set(tokens)) == 1 and len(tokens) > 1:
        return True

    alpha_chars = sum(char.isalpha() for char in cleaned)
    if alpha_chars < 4:
        return True
    if alpha_chars / max(len(cleaned), 1) < 0.55:
        return True

    return False


def _source_title(source: str) -> str:
    title = os.path.splitext(os.path.basename(source or ""))[0].replace("_", " ").strip()
    if " - " in title:
        title = title.split(" - ", 1)[0].strip()
    return title


def _smart_title(text: str) -> str:
    words = []
    for word in text.split():
        if word.isupper() and len(word) > 3:
            words.append(word.title())
        else:
            words.append(word)
    return " ".join(words)


def _clean_suggestion_subject(text: str) -> str | None:
    if not text:
        return None

    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    cleaned = lines[0] if lines else _normalize_whitespace(str(text))
    cleaned = cleaned.strip(" \"'`.,:;!?()[]{}-")
    cleaned = LEADING_DATE_RE.sub("", cleaned)
    cleaned = LEADING_SECTION_NUMBER_RE.sub("", cleaned)
    if not cleaned:
        return None

    if len(cleaned) > 90:
        for separator in (". ", " - ", " — ", ": ", "; "):
            if separator in cleaned[:90]:
                cleaned = cleaned.split(separator, 1)[0].strip()
                break

    if len(cleaned) > 72:
        shortened = cleaned[:72].rsplit(" ", 1)[0].strip()
        cleaned = shortened or cleaned[:72].strip()

    cleaned = cleaned.strip(" \"'`.,:;!?()[]{}-")
    if cleaned.isupper():
        cleaned = _smart_title(cleaned)
    if _looks_like_noise_topic(cleaned):
        return None
    return cleaned


def _subject_match_score(query: str, subject: str) -> float:
    query_tokens = _suggestion_tokens(query)
    subject_tokens = _suggestion_tokens(subject)
    if not query_tokens or not subject_tokens:
        return 0.0

    matched = 0
    for query_token in query_tokens:
        if any(
            subject_token == query_token
            or subject_token.startswith(query_token)
            or query_token.startswith(subject_token)
            for subject_token in subject_tokens
        ):
            matched += 1

    return matched / len(query_tokens)


def _questionize_query(query: str) -> str | None:
    cleaned = _normalize_whitespace(query).rstrip("?.!")
    tokens = _suggestion_tokens(cleaned)
    if len(tokens) < 4 or not QUESTION_START_RE.match(cleaned):
        return None
    cleaned = re.sub(r"\bi\b", "I", cleaned)
    return cleaned[:1].upper() + cleaned[1:] + "?"


def _query_topic(query: str) -> str | None:
    cleaned = _clean_suggestion_subject(query)
    if not cleaned:
        return None
    lowered = cleaned.lower()
    for prefix in (
        "how do i ",
        "how can i ",
        "why do i ",
        "why am i ",
        "what is ",
        "what are ",
        "can you explain ",
        "can you show me ",
        "where should i start reading about ",
        "help me understand ",
        "tell me about ",
    ):
        if lowered.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
            lowered = cleaned.lower()
            break
    tokens = _suggestion_tokens(cleaned)
    if len(tokens) >= 2 and len(tokens[-1]) < 3:
        return None
    if QUESTION_START_RE.match(cleaned):
        return None
    return cleaned


def _templates_for_subject(subject: str) -> tuple[str, ...]:
    subject_tokens = _suggestion_tokens(subject)
    if subject_tokens and subject_tokens[0] in ACTION_PHRASE_VERBS:
        return ACTION_SUGGESTION_PROMPT_TEMPLATES
    return SUGGESTION_PROMPT_TEMPLATES


def _finalize_prompt(prompt: str) -> str | None:
    normalized = _normalize_whitespace(prompt).rstrip("?.!")
    if not normalized:
        return None
    return normalized[:1].upper() + normalized[1:] + "?"


def _prompt_subject_for_candidate(query_topic: str | None, subject: str) -> str:
    if not query_topic:
        return subject

    if (
        _subject_match_score(query_topic, subject) >= 0.85
        and len(subject) <= max(len(query_topic) + 18, int(len(query_topic) * 2))
    ):
        return subject

    return query_topic


def _build_source_candidates(query: str, results) -> list[dict[str, Any]]:
    query_topic = _query_topic(query)
    candidates_by_source: dict[str, dict[str, Any]] = {}

    for result in results:
        raw_candidates = [
            (result.excerpt, "excerpt"),
            (result.text if result.text != result.excerpt else "", "context"),
            (_source_title(result.source), "title"),
        ]

        best_for_result: dict[str, Any] | None = None
        for raw, kind in raw_candidates:
            subject = _clean_suggestion_subject(raw)
            if not subject:
                continue

            prompt_subject = _prompt_subject_for_candidate(query_topic, subject)
            subject_match = _subject_match_score(query_topic or query, subject)
            prompt_match = _subject_match_score(query_topic or query, prompt_subject)
            score = float(result.similarity) + max(subject_match, prompt_match) * 0.4
            if kind == "excerpt":
                score += 0.05
            elif kind == "title":
                score -= 0.05
            if len(_suggestion_tokens(subject)) > 8:
                score -= 0.04

            candidate = {
                "source": result.source,
                "subject": prompt_subject,
                "score": score,
                "similarity": float(result.similarity),
            }
            if (
                best_for_result is None
                or candidate["score"] > best_for_result["score"]
                or (
                    candidate["score"] == best_for_result["score"]
                    and len(candidate["subject"]) < len(best_for_result["subject"])
                )
            ):
                best_for_result = candidate

        if best_for_result is None:
            continue

        current = candidates_by_source.get(result.source)
        if (
            current is None
            or best_for_result["score"] > current["score"]
            or (
                best_for_result["score"] == current["score"]
                and len(best_for_result["subject"]) < len(current["subject"])
            )
        ):
            candidates_by_source[result.source] = best_for_result

    return sorted(
        candidates_by_source.values(),
        key=lambda candidate: (candidate["score"], candidate["similarity"]),
        reverse=True,
    )


def _build_suggestions(query: str, results) -> list[dict[str, str]]:
    direct_question = _questionize_query(query)
    source_candidates = _build_source_candidates(query, results)
    suggestions: list[dict[str, str]] = []
    seen_prompts: set[str] = set()
    used_sources: set[str] = set()

    if direct_question:
        source = source_candidates[0]["source"] if source_candidates else "Suggested prompt"
        prompt = _finalize_prompt(direct_question)
        if prompt:
            suggestions.append({"text": prompt, "source": source})
            seen_prompts.add(prompt.lower())
            used_sources.add(source)

    distinct_candidates = [candidate for candidate in source_candidates if candidate["source"] not in used_sources]
    for index, candidate in enumerate(distinct_candidates):
        if len(suggestions) >= SUGGESTION_LIMIT:
            break
        templates = _templates_for_subject(candidate["subject"])
        template = templates[index % len(templates)]
        prompt = _finalize_prompt(template.format(subject=candidate["subject"]))
        if not prompt or prompt.lower() in seen_prompts:
            for fallback_template in templates:
                prompt = _finalize_prompt(fallback_template.format(subject=candidate["subject"]))
                if prompt and prompt.lower() not in seen_prompts:
                    break
            else:
                continue

        suggestions.append({"text": prompt, "source": candidate["source"]})
        seen_prompts.add(prompt.lower())
        used_sources.add(candidate["source"])

    if len(suggestions) < SUGGESTION_LIMIT:
        for candidate in source_candidates:
            templates = _templates_for_subject(candidate["subject"])
            for template in templates:
                prompt = _finalize_prompt(template.format(subject=candidate["subject"]))
                if not prompt or prompt.lower() in seen_prompts:
                    continue
                suggestions.append({"text": prompt, "source": candidate["source"]})
                seen_prompts.add(prompt.lower())
                if len(suggestions) >= SUGGESTION_LIMIT:
                    return suggestions

    return suggestions


def _get_abs_documents_dir() -> str:
    return os.path.abspath(DOCUMENTS_DIR)


def _resolve_document_path(filepath: str) -> str:
    abs_docs = _get_abs_documents_dir()
    full_path = os.path.abspath(os.path.join(abs_docs, filepath))
    if not full_path.startswith(abs_docs + os.sep) and full_path != abs_docs:
        raise HTTPException(status_code=404, detail="Not found")
    return full_path


MAX_EXCERPT_CHARS = 1500

# Matches PDF running headers like "CHAPTER TITLE 123\n" or "123 BOOK TITLE\n"
_PAGE_HEADER_RE = re.compile(
    r"^(?:"
    r"[A-Z][A-Z\s\-\.,'&]+\d+|"      # TITLE 123
    r"\d+\s+[A-Z][A-Z\s\-\.,'&]+|"   # 123 TITLE
    r"[•\-]\s*\w+\s+\d+\s*[•\-]"     # bullet-style headers
    r")\s*\n",
)


def _strip_page_headers(text: str) -> str:
    """Remove PDF running headers / page numbers from the start of text."""
    # Strip up to 3 header lines (page can have header + subheader)
    for _ in range(3):
        m = _PAGE_HEADER_RE.match(text)
        if not m:
            break
        text = text[m.end():]
    return text.strip()


def _build_chat_sources(results) -> list[dict[str, Any]]:
    sources = []
    for result in results:
        rel_path = result.relative_path or (
            os.path.relpath(result.source_path, DOCUMENTS_DIR) if result.source_path else result.source
        )
        excerpt = _strip_page_headers(result.excerpt)
        if len(excerpt) > MAX_EXCERPT_CHARS:
            excerpt = excerpt[:MAX_EXCERPT_CHARS].rsplit(" ", 1)[0] + "..."
        sources.append({
            "source": result.source,
            "similarity": round(result.similarity, 3),
            "url": f"/api/documents/{rel_path}",
            "excerpt": excerpt,
            "match_scale": result.match_scale,
            "context_scale": result.scale,
        })
    return sources


def _error_content(detail: Any) -> dict[str, Any]:
    if isinstance(detail, dict):
        return detail
    return {"error": str(detail)}


def _get_active_index_job() -> dict[str, Any] | None:
    try:
        return get_task_status_payload()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"job store unavailable: {exc}") from exc


def _assert_no_active_index_job() -> None:
    active_job = _get_active_index_job()
    if active_job and active_job.get("status") not in TERMINAL_JOB_STATUSES:
        raise HTTPException(
            status_code=409,
            detail={"error": "an indexing job is already running", "job": active_job},
        )


async def _warmup_models() -> None:
    # Sequential so a small GPU isn't asked to load both models at once.
    # The cross-encoder is CPU-only and small (~80MB), so it's safe to warm
    # alongside the others; the lifespan task still runs in the background.
    for fn in (engine.warmup, warmup_embeddings, warmup_reranker):
        try:
            await asyncio.to_thread(fn)
        except Exception:
            pass


async def _warmup_meetings() -> None:
    try:
        await warmup_meeting_feeds()
    except Exception:
        pass


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        _refresh_retriever(force=True)
    except Exception:
        pass
    asyncio.create_task(_warmup_models())
    asyncio.create_task(_warmup_meetings())
    yield


app = FastAPI(title="Sobriety Copilot", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.exception_handler(HTTPException)
async def http_exception_handler(_, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content=_error_content(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": "invalid request", "details": exc.errors()},
    )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(INDEX_HTML_PATH)


@app.get("/service-worker.js")
def service_worker() -> FileResponse:
    # Served from root so its default scope covers the whole app.
    return FileResponse(
        os.path.join(STATIC_DIR, "service-worker.js"),
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


@app.get("/manifest.json")
def manifest() -> FileResponse:
    return FileResponse(
        os.path.join(STATIC_DIR, "manifest.json"),
        media_type="application/manifest+json",
    )


_hyde_cache: dict[str, tuple[float, str]] = {}
_HYDE_CACHE_TTL = 24 * 60 * 60  # 24h
_HYDE_CACHE_MAX = 500


def _hyde_cache_key(question: str) -> str:
    import hashlib
    norm = " ".join(question.lower().split())
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()


def _hyde_cache_get(key: str) -> str | None:
    entry = _hyde_cache.get(key)
    if not entry:
        return None
    ts, passage = entry
    if time.time() - ts > _HYDE_CACHE_TTL:
        _hyde_cache.pop(key, None)
        return None
    return passage


def _hyde_cache_put(key: str, passage: str) -> None:
    if len(_hyde_cache) >= _HYDE_CACHE_MAX:
        oldest = min(_hyde_cache, key=lambda k: _hyde_cache[k][0])
        _hyde_cache.pop(oldest, None)
    _hyde_cache[key] = (time.time(), passage)


HYDE_SYSTEM_MESSAGE = (
    "You write short paragraphs in the voice of A.A. recovery literature "
    "(the Big Book, the 12 Steps and 12 Traditions, As Bill Sees It, daily "
    "reflections, and A.A. history books such as Alcoholics Anonymous Comes "
    "of Age, Dr. Bob and the Good Oldtimers, Pass It On). Plain prose. No "
    "formatting, no lists, no preamble."
)

HYDE_PROMPT = (
    "Write 2 to 4 sentences (about 50-110 words) on the topic below, as if "
    "lifted from A.A. literature. Match the style of the examples.\n\n"
    "Example A — thematic recovery question:\n"
    "  Topic: how do I deal with anger?\n"
    "  Passage: Anger is a luxury we cannot afford. Resentments, the "
    "literature reminds us, are the number one offender; they kill more "
    "alcoholics than anything else. The Fourth Step inventory and the work "
    "that follows with a sponsor are how we lay our anger down — by looking "
    "honestly at our part, by praying for the people we resent, and by "
    "asking that whatever poison we hold be taken from us.\n\n"
    "Example B — biographical / historical question:\n"
    "  Topic: who are the first few members of A.A.?\n"
    "  Passage: A.A. began with Bill Wilson, a New York stockbroker who got "
    "sober in December 1934, and Dr. Bob Smith, an Akron surgeon who took "
    "his last drink on June 10, 1935, after meeting Bill at the home of "
    "Henrietta Seiberling. Their third member was a hospitalized Akron "
    "lawyer named Bill D., who became known as A.A. Number Three. Anne "
    "Smith, Dr. Bob's wife, and the early Akron and New York groups carried "
    "the message in those first years.\n\n"
    "Example C — specific event / date:\n"
    "  Topic: when was the Big Book published?\n"
    "  Passage: The book Alcoholics Anonymous, which the fellowship came to "
    "call the Big Book, was first published in April 1939, after Bill "
    "Wilson and the early members in Akron and New York worked together on "
    "the manuscript. The first printing of 4,650 copies was financed in part "
    "by stock subscriptions and the labor of the early fellowship.\n\n"
    "Rules: Use only well-known A.A. history facts; do not invent names or "
    "dates. Match the right style for the topic — vocabulary-rich for "
    "thematic questions, name-rich for biographical/historical questions. "
    "No preamble, no commentary, no formatting.\n\n"
    "Topic: {question}\n\nPassage:"
)


def _hyde_for_query(question: str) -> str | None:
    """Generate a hypothetical recovery-literature passage for the query.

    Used as the embedding for semantic retrieval (HyDE). Cached by query hash
    so repeated questions hit instantly, with a 24h TTL.
    """
    if not question or len(question) > 600:
        return None
    key = _hyde_cache_key(question)
    cached = _hyde_cache_get(key)
    if cached:
        return cached
    try:
        # Budget enough headroom for thinking-model variants (e.g., gemma4:e2b)
        # that burn tokens on internal reasoning before emitting content.
        # ~400 thinking + ~150 useful output, with safety margin.
        passage = engine.generate(
            prompt=HYDE_PROMPT.format(question=question.strip()),
            history=[],
            max_tokens=900,
            system_message=HYDE_SYSTEM_MESSAGE,
        )
        passage = (passage or "").strip()
    except Exception as exc:
        print(f"[HYDE-ERR] {type(exc).__name__}: {exc}", flush=True)
        return None
    if not passage:
        print("[HYDE-EMPTY] LLM returned no usable text", flush=True)
        return None
    # If we got a "Thinking Process: ..." dump, try to keep just the prose tail.
    if "passage:" in passage.lower():
        passage = passage.split(":", 1)[-1].strip() if "Passage:" in passage else passage
    _hyde_cache_put(key, passage)
    return passage


def _build_retrieval_query(message: str, history: list[dict[str, Any]]) -> str:
    """Build a retrieval query that incorporates conversation context.

    For follow-up messages we append key phrases from the last few turns so the
    retriever can resolve references like "tell me more" or "what about that".

    For first-turn messages we use the user's wording verbatim. The corpus is
    already entirely recovery literature, so adding a generic recovery hint
    only dilutes the embedding and pulls back unrelated material.
    """
    if not history:
        return message
    parts = [message]
    for turn in history[-4:]:
        content = (turn.get("content") or "")[:200].strip()
        if content:
            parts.append(content)
    return " ".join(parts)


_explain_cache: dict[str, dict[str, str]] = {}
_EXPLAIN_CACHE_MAX = 1000

EXPLAIN_SYSTEM_MESSAGE = (
    "You are a research assistant helping a person see why a passage from "
    "recovery literature was retrieved for their question. Be honest about "
    "loose connections; don't pretend a tangential passage is directly on-topic. "
    "Output ONLY the two labelled lines requested. No preamble, no commentary."
)

EXPLAIN_PROMPT = (
    "User's question: {query}\n\n"
    "Retrieved passage:\n\"\"\"\n{excerpt}\n\"\"\"\n\n"
    "Output exactly these two lines, in this order, with no other text:\n"
    "RELEVANCE: <one short sentence, max 18 words, explaining how this passage "
    "relates to the user's question. If the connection is loose, say so plainly.>\n"
    "KEY: <the single most directly relevant phrase from the passage, copied "
    "verbatim, max 15 words. Empty if nothing in the passage is directly on point.>"
)


def _explain_cache_key(query: str, excerpt: str) -> str:
    import hashlib
    norm = (query.strip().lower() + "||" + excerpt.strip()[:600]).encode("utf-8")
    return hashlib.sha1(norm).hexdigest()


def _explain_cache_put(key: str, value: dict[str, str]) -> None:
    if len(_explain_cache) >= _EXPLAIN_CACHE_MAX:
        first = next(iter(_explain_cache))
        _explain_cache.pop(first, None)
    _explain_cache[key] = value


class ExplainSnippetRequest(BaseModel):
    query: str
    excerpt: str
    source: str | None = None


class ExplainBatchRequest(BaseModel):
    query: str
    excerpts: list[str]


BATCH_EXPLAIN_SYSTEM_MESSAGE = (
    "You are a research assistant helping a person see why several passages "
    "from recovery literature were retrieved for their question. Be honest "
    "about loose connections; if a passage is tangential, say so plainly. "
    "Output ONLY the labelled lines requested, one block per passage, in "
    "order. No preamble, no commentary."
)

BATCH_EXPLAIN_PROMPT = (
    "User's question: {query}\n\n"
    "{passages}\n"
    "For each passage above, output exactly two lines, in order, with no other "
    "text or surrounding commentary:\n\n"
    "  PASSAGE N\n"
    "  RELEVANCE: <one short sentence, max 18 words, explaining how this "
    "passage relates to the user's question. If the connection is loose, say "
    "so plainly.>\n"
    "  KEY: <the single most directly relevant phrase from the passage, "
    "verbatim, max 15 words. Empty if nothing is directly on point.>"
)


def _parse_batch_explanations(text: str, n: int) -> list[dict[str, str]]:
    """Parse the batched LLM output into per-passage {why,key} dicts."""
    results: list[dict[str, str]] = [{"why": "", "key": ""} for _ in range(n)]
    if not text:
        return results
    current = -1
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        upper = line.upper()
        if upper.startswith("PASSAGE"):
            # Try to extract a 1-based number after "PASSAGE"
            tail = line[7:].strip().lstrip("#").lstrip(":").strip()
            head = "".join(ch for ch in tail if ch.isdigit())
            if head.isdigit():
                idx = int(head) - 1
                if 0 <= idx < n:
                    current = idx
            continue
        if upper.startswith("RELEVANCE:") and 0 <= current < n:
            results[current]["why"] = line.split(":", 1)[1].strip()
        elif upper.startswith("KEY:") and 0 <= current < n:
            results[current]["key"] = line.split(":", 1)[1].strip().strip('"\'')
    return results


@app.post("/api/explain-snippets-batch")
def explain_snippets_batch(payload: ExplainBatchRequest):
    q = (payload.query or "").strip()
    excerpts = [e.strip() for e in (payload.excerpts or [])][:8]  # cap at 8
    if not q or not excerpts:
        return {"results": []}

    # Per-excerpt cache lookup to avoid re-asking the LLM for already-known pairs.
    cached: list[dict[str, str] | None] = []
    pending_indices: list[int] = []
    pending_excerpts: list[str] = []
    keys: list[str] = []
    for i, ex in enumerate(excerpts):
        key = _explain_cache_key(q, ex)
        keys.append(key)
        hit = _explain_cache.get(key)
        if hit is not None:
            cached.append(hit)
        else:
            cached.append(None)
            pending_indices.append(i)
            pending_excerpts.append(ex)

    if pending_excerpts:
        passages = "\n\n".join(
            f"PASSAGE {n + 1}\n\"\"\"\n{ex[:1200]}\n\"\"\""
            for n, ex in enumerate(pending_excerpts)
        )
        try:
            # Generous token budget — thinking model needs headroom for its
            # internal reasoning before producing the labelled output.
            out = engine.generate(
                prompt=BATCH_EXPLAIN_PROMPT.format(query=q[:400], passages=passages),
                history=[],
                max_tokens=900 + 220 * len(pending_excerpts),
                system_message=BATCH_EXPLAIN_SYSTEM_MESSAGE,
            )
        except Exception as exc:
            return {"results": [c or {"why": "", "key": "", "error": str(exc)} for c in cached]}

        parsed = _parse_batch_explanations(out or "", len(pending_excerpts))
        for slot, parsed_item in zip(pending_indices, parsed):
            cached[slot] = parsed_item
            _explain_cache_put(keys[slot], parsed_item)

    return {"results": [c or {"why": "", "key": ""} for c in cached]}


@app.post("/api/explain-snippet")
def explain_snippet(payload: ExplainSnippetRequest):
    q = (payload.query or "").strip()
    ex = (payload.excerpt or "").strip()
    if not q or not ex:
        return {"why": "", "key": ""}

    key = _explain_cache_key(q, ex)
    cached = _explain_cache.get(key)
    if cached is not None:
        return cached

    try:
        out = engine.generate(
            prompt=EXPLAIN_PROMPT.format(query=q[:400], excerpt=ex[:1500]),
            history=[],
            max_tokens=600,
            system_message=EXPLAIN_SYSTEM_MESSAGE,
        )
    except Exception as exc:
        return {"why": "", "key": "", "error": str(exc)}

    why = ""
    key_phrase = ""
    for line in (out or "").splitlines():
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith("RELEVANCE:"):
            why = stripped.split(":", 1)[1].strip()
        elif upper.startswith("KEY:"):
            key_phrase = stripped.split(":", 1)[1].strip().strip('"\'')

    # Some thinking-models prepend their chain-of-thought; strip framing if found.
    if not why and out:
        # Last non-empty line as fallback
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        if lines:
            why = lines[-1][:200]

    result = {"why": why, "key": key_phrase}
    _explain_cache_put(key, result)
    return result


@app.post("/api/chat")
def chat(payload: ChatRequest):
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="missing 'message' field")

    retriever_instance = _safe_get_retriever()
    query = payload.message
    history = payload.history
    categories = _normalize_categories(payload.categories)

    # Use conversation-aware query for retrieval so follow-ups resolve correctly.
    retrieval_query = _build_retrieval_query(query, history)

    # HyDE — fold a hypothetical literature-style passage into the embedding
    # query. We keep the user's raw words too so factual/biographical questions
    # ("where did Bill first drink?") don't lose their proper nouns to HyDE's
    # thematic abstraction.
    #
    # We run HyDE on every turn — including follow-ups — because users often
    # pivot to a new topic without it being a "fresh" first turn. History still
    # benefits the BM25 keyword scorer via `retrieval_query`, which carries
    # recent turns; the embedding query stays focused on the current question.
    hyde_passage = _hyde_for_query(query)
    if hyde_passage:
        embedding_query = f"{query}\n\n{hyde_passage}"
    else:
        embedding_query = retrieval_query

    results = retriever_instance.retrieve(
        retrieval_query,
        categories=categories,
        embedding_query=embedding_query,
    )

    # Diagnostic — flushed to stdout (Docker captures it). Strip if/when noisy.
    try:
        print("=" * 70, flush=True)
        print(f"[CHAT] tone={payload.tone or 'brief'!s:9} history_len={len(history)} cats={categories}", flush=True)
        print(f"[QUERY]  {query!r}", flush=True)
        if hyde_passage:
            print(f"[HYDE]   {hyde_passage[:400]!r}{'…' if len(hyde_passage) > 400 else ''}", flush=True)
        else:
            print("[HYDE]   (none — used raw query for embedding)", flush=True)
        print(f"[RETRIEVED] {len(results)} chunks. Top:", flush=True)
        for i, r in enumerate(results[:5], 1):
            ex = (r.excerpt or r.text or "").replace("\n", " ")[:200]
            print(f"  {i}. [{r.match_scale}/{r.scale} sim={r.similarity:.3f}] {r.source}: {ex}…", flush=True)
        print("=" * 70, flush=True)
    except Exception as _diag_exc:
        print(f"[CHAT-DIAG-ERR] {_diag_exc}", flush=True)

    if results:
        context = retriever_instance.format_context(results)
        prompt = USER_MESSAGE_TEMPLATE.format(context=context, question=query)
    else:
        prompt = NO_CONTEXT_TEMPLATE.format(question=query)

    sources = _build_chat_sources(results)
    sys_msg = system_message_for_tone(payload.tone)
    want_thinking = bool(payload.show_thinking)

    def generate():
        first_event = {"sources": sources}
        if hyde_passage:
            first_event["expanded_query"] = hyde_passage
        yield f"data: {json.dumps(first_event)}\n\n"
        try:
            for kind, text in engine.stream_typed(prompt, history=history, system_message=sys_msg):
                if kind == "thinking":
                    if want_thinking:
                        yield f"data: {json.dumps({'thinking': text})}\n\n"
                    else:
                        # SSE comment — invisible to EventSource but keeps the
                        # connection alive across proxies (Cloudflare free
                        # tunnels close idle streams around 100s; thinking
                        # models can reason longer than that before any token).
                        yield ": keepalive\n\n"
                else:
                    yield f"data: {json.dumps({'token': text})}\n\n"
            yield "data: {\"done\": true}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


BUG_REPORT_KEY = "sobriety_copilot:bugs"
BUG_REPORT_TTL = 60 * 60 * 24 * 30  # 30 days


@app.post("/api/bugs")
def submit_bug(report: BugReport):
    if not report.description.strip():
        raise HTTPException(status_code=400, detail="description is required")
    from src.tasks.job_store import get_redis_client
    entry = {
        "id": str(uuid4()),
        "description": report.description,
        "conversation": report.conversation[-6:],
        "url": report.url,
        "timestamp": time.time(),
    }
    r = get_redis_client()
    r.lpush(BUG_REPORT_KEY, json.dumps(entry))
    r.ltrim(BUG_REPORT_KEY, 0, 99)
    return {"ok": True, "id": entry["id"]}


@app.get("/api/bugs")
def list_bugs():
    from src.tasks.job_store import get_redis_client
    r = get_redis_client()
    raw = r.lrange(BUG_REPORT_KEY, 0, 99)
    return [json.loads(item) for item in raw]


@app.get("/api/suggest")
def suggest(
    q: str = Query(default=""),
    categories: str = Query(default=""),
):
    query = q.strip()
    if not query or len(query) < 2:
        return []

    category_list = _normalize_categories(categories.split(",")) if categories else None
    results = _safe_get_retriever().retrieve(
        query,
        top_k=SUGGESTION_RETRIEVE_TOP_K,
        categories=category_list,
    )
    return _build_suggestions(query, results)


_geocode_cache: dict[str, dict[str, Any] | None] = {}


@app.get("/api/geocode")
async def geocode(q: str = Query(..., min_length=2, max_length=120)):
    """Resolve a ZIP, city, or place name to lat/lng via OpenStreetMap Nominatim.

    Proxied so the user's IP isn't exposed to the upstream and so we can
    enforce a polite User-Agent + cache repeated lookups.
    """
    import httpx

    key = q.strip().lower()
    if key in _geocode_cache:
        cached = _geocode_cache[key]
        if cached is None:
            raise HTTPException(status_code=404, detail="No match for that location")
        return cached

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={
                    "q": q,
                    "format": "json",
                    "limit": "1",
                    "addressdetails": "1",
                    "countrycodes": "us,ca",
                },
                headers={"User-Agent": "sobriety-copilot/1.0 (+https://github.com)"},
                timeout=8.0,
                follow_redirects=True,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"geocoding upstream error: {exc}") from exc

    if not data:
        _geocode_cache[key] = None
        raise HTTPException(status_code=404, detail="No match for that location")

    hit = data[0]
    addr = hit.get("address", {}) or {}
    label_parts = [
        addr.get("postcode"),
        addr.get("city") or addr.get("town") or addr.get("village") or addr.get("hamlet"),
        addr.get("state"),
    ]
    label = ", ".join([p for p in label_parts if p]) or hit.get("display_name", "")
    payload = {
        "lat": float(hit["lat"]),
        "lng": float(hit["lon"]),
        "label": label,
    }
    _geocode_cache[key] = payload
    return payload


@app.get("/api/meetings")
async def meetings(
    lat: float = Query(...),
    lng: float = Query(...),
    radius_mi: float = Query(25.0, ge=1.0, le=200.0),
    max: int = Query(30, ge=1, le=100),
    day: int | None = Query(None, ge=0, le=6),
    attendance: str | None = Query(None, pattern="^(inperson|online|all)$"),
    fellowship: str | None = Query(None, pattern="^(aa|na|all|AA|NA|ALL)$"),
):
    return await search_meetings(
        lat=lat, lng=lng,
        radius_mi=radius_mi, max_results=max,
        day=day, attendance=attendance, fellowship=fellowship,
    )


@app.get("/api/categories")
def categories():
    abs_docs = _get_abs_documents_dir()
    cats = []
    if not os.path.isdir(abs_docs):
        return cats
    for entry in sorted(os.listdir(abs_docs)):
        if os.path.isdir(os.path.join(abs_docs, entry)) and not entry.startswith("."):
            label = entry.replace("_", " ").title()
            cats.append({"id": entry, "label": label})
    return cats


@app.get("/api/health")
def health():
    active_collection = _get_active_collection_name_safe()
    payload = {
        "status": "ok",
        "framework": "fastapi",
        "model": MODEL,
        "documents_dir": _get_abs_documents_dir(),
        "rag_collection": RAG_COLLECTION,
        "active_collection": active_collection,
        "cached_chunks": 0,
        "active_index_job": None,
        "chroma_mode": "http" if os.environ.get("CHROMA_HOST") else "embedded",
        "embedding_provider": os.environ.get("EMBEDDING_PROVIDER", "ollama"),
        "embedding_model": os.environ.get("EMBEDDING_MODEL", "nomic-embed-text"),
        "index_backend": "celery",
        "job_backend": "redis",
        "redis_status": "ok" if ping_job_store() else "down",
    }

    try:
        active_job = get_task_status_payload()
        if active_job is not None:
            payload["active_index_job"] = active_job
    except Exception as exc:
        payload["status"] = "degraded"
        payload["redis_status"] = "down"
        payload["redis_error"] = str(exc)

    try:
        retriever_instance = _get_retriever()
        payload["cached_chunks"] = len(retriever_instance._chunks_by_id)
        payload["indexed_chunks"] = retriever_instance.collection.count()
    except Exception as exc:
        payload["status"] = "degraded"
        payload["indexed_chunks"] = None
        payload["chroma_error"] = str(exc)

    return payload


@app.get("/api/documents/{filepath:path}")
def serve_document(filepath: str):
    # Intentionally disabled — we don't want to expose the original PDF/EPUB
    # file as a download bypass that would let users read entire books in
    # place of buying their own copy. The page-capped /api/render/ endpoint
    # is the only legitimate way to view source content.
    raise HTTPException(
        status_code=404,
        detail="Full source documents are not served. Use the snippet preview.",
    )


@app.get("/api/render/{filepath:path}")
def render_document(
    filepath: str,
    highlight: str = Query(default=""),
):
    import html as html_mod
    import re

    full_path = _resolve_document_path(filepath)
    lower = full_path.lower()

    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="Not found")
    if not (lower.endswith(".epub") or lower.endswith(".pdf")):
        raise HTTPException(status_code=400, detail="Unsupported format")

    context_pages = 3

    if lower.endswith(".epub"):
        render_payload = _get_render_document(full_path)
        all_sections = render_payload["sections_html"]
        normalized_sections = render_payload["normalized_section_text"]

        if highlight:
            match_idx = _find_best_render_match(normalized_sections, highlight, normalized=True)
            if match_idx is not None:
                start = max(0, match_idx - context_pages)
                end = min(len(all_sections), match_idx + context_pages + 1)
                all_sections = all_sections[start:end]

        content = '<hr style="border:none;border-top:1px solid #e5e7eb;margin:2rem 0;">'.join(all_sections)

    else:
        render_payload = _get_render_document(full_path)
        page_text = render_payload["page_text"]
        normalized_page_text = render_payload["normalized_page_text"]
        total = render_payload["total_pages"]
        match_page = _find_best_render_match(normalized_page_text, highlight, normalized=True) if highlight else None
        if match_page is not None:
            start = max(0, match_page - context_pages)
            end = min(total, match_page + context_pages + 1)
        else:
            start = 0
            end = min(total, 2 * context_pages + 1)

        pages = []
        for index in range(start, end):
            text = page_text[index]
            if text:
                escaped_text = html_mod.escape(text).replace("\n", "<br>")
                pages.append(
                    f'<div style="margin-bottom:1rem;padding-bottom:1rem;border-bottom:1px solid #e5e7eb;">'
                    f'<div style="font-size:0.7rem;color:#9ca3af;margin-bottom:0.5rem;">Page {index + 1} of {total}</div>'
                    f'<div>{escaped_text}</div></div>'
                )
        content = "\n".join(pages)

    if highlight:
        match_span = _locate_highlight_span(highlight, content)
        if match_span is not None:
            start, end = match_span
            # If the matched span starts with a run of ALL-CAPS title words
            # (Daily Reflections, A.A. Service Manual, etc embed the page
            # title at the top of each chunk), advance past them so the
            # highlight opens on the body prose instead of the page-top
            # banner. Only skip when there's substantial body text after.
            # Trailing separator tolerates whitespace and the <br> tags
            # injected when rendering line breaks from PDF text.
            span_text = content[start:end]
            title_prefix = re.match(
                r"^[A-Z][A-Z0-9]+(?:\s+[A-Z][A-Z0-9]+){0,7}",
                span_text,
            )
            if title_prefix:
                pos = title_prefix.end()
                sep = re.match(r"\s*(?:<br\s*/?>\s*)*", span_text[pos:])
                if sep:
                    pos += sep.end()
                if pos < len(span_text) - 20:
                    start += pos
            snippet = content[start:end]
            highlighted = f'<span id="hl" style="background:#d4f5e9;padding:2px 4px;border-radius:3px;">{snippet}</span>'
            content = content[:start] + highlighted + content[end:]

    purchase_notice = (
        '<div class="purchase-notice">'
        '<div class="notice-headline">Please purchase this book at your local meeting</div>'
        '<div class="notice-sub">Only a few pages of context are shown here. '
        'The full text supports the work of A.A. and the publisher.</div>'
        '</div>'
    )
    framed_content = purchase_notice + content + purchase_notice

    page = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
body {{
  font-family: Georgia, "Times New Roman", serif;
  max-width: 720px;
  margin: 0 auto;
  padding: 2rem 1.5rem;
  line-height: 1.8;
  color: #1a1a2e;
  font-size: 1rem;
  background: #fff;
}}
h1,h2,h3,h4 {{ font-family: -apple-system, sans-serif; color: #264653; margin-top: 1.5em; }}
p {{ margin: 0.75em 0; }}
#hl {{ scroll-margin-top: 100px; }}
.purchase-notice {{
  background: linear-gradient(135deg, #fff7ed 0%, #fde68a 100%);
  color: #7c2d12;
  border: 2px solid #f59e0b;
  border-radius: 0.75rem;
  padding: 1.75rem 1.5rem;
  margin: 2rem 0;
  text-align: center;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}}
.purchase-notice .notice-headline {{
  font-size: 1.25rem;
  font-weight: 700;
  margin-bottom: 0.5rem;
  letter-spacing: -0.01em;
}}
.purchase-notice .notice-sub {{
  font-size: 0.875rem;
  font-weight: 400;
  opacity: 0.85;
  line-height: 1.5;
}}
@media (prefers-color-scheme: dark) {{
  body {{ background: #161b22; color: #e8eaed; }}
  h1,h2,h3,h4 {{ color: #4ec3b1; }}
  #hl {{ background: #1f4a3e !important; }}
  .purchase-notice {{
    background: linear-gradient(135deg, #2d1b0e 0%, #432818 100%);
    color: #fef3c7;
    border-color: #d97706;
  }}
}}
</style></head>
<body>{framed_content}
<script>
  function scrollToHl() {{
    const hl = document.getElementById('hl');
    if (!hl) return;
    hl.scrollIntoView({{ behavior: 'auto', block: 'center' }});
  }}
  // Stagger several attempts: layout pass, paint, and post-paint windows.
  // This beats races against (a) iframe layout not yet committed, (b) the
  // user's prior touch/inertia-scroll gesture still being applied, and (c)
  // browser focus/scroll-restoration heuristics on srcdoc reloads.
  function startScrollAttempts() {{
    requestAnimationFrame(() => requestAnimationFrame(scrollToHl));
    [0, 60, 180, 400].forEach(d => setTimeout(scrollToHl, d));
  }}
  if (document.readyState === 'complete') startScrollAttempts();
  else window.addEventListener('load', startScrollAttempts);
</script>
</body></html>"""
    return HTMLResponse(page)


@app.post("/api/index")
def index_documents(
    payload: IndexRequest | None = None,
    wait: bool = Query(default=False),
):
    data = payload or IndexRequest()
    directory = os.path.abspath(data.directory or DOCUMENTS_DIR)
    wait_for_completion = data.wait or wait

    if not os.path.isdir(directory):
        raise HTTPException(status_code=400, detail=f"directory not found: {directory}")

    _assert_no_active_index_job()

    if wait_for_completion:
        try:
            build_result = perform_shadow_index(
                directory=directory,
                db_path=RAG_DB_PATH,
                base_collection_name=RAG_COLLECTION,
                task_id=f"sync{uuid4().hex}",
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"indexing failed: {exc}") from exc

        _refresh_retriever(force=True)
        return {
            "status": "completed",
            "indexed_chunks": build_result["indexed_chunks"],
            "active_collection": build_result["active_collection"],
        }

    task_id = str(uuid4())
    try:
        job = record_index_task(task_id, directory)
    except ActiveIndexJobError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "an indexing job is already running", "job": exc.job},
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"job store unavailable: {exc}") from exc

    try:
        index_documents_task.apply_async(
            kwargs={
                "directory": directory,
                "db_path": RAG_DB_PATH,
                "collection_name": RAG_COLLECTION,
            },
            task_id=task_id,
        )
    except Exception as exc:
        completed_at = round(time.time(), 3)
        update_index_task(
            task_id,
            status="failed",
            stage="failed",
            error=str(exc),
            message=f"Failed to queue indexing job: {exc}",
            completed_at=completed_at,
        )
        clear_active_index_task(task_id)
        raise HTTPException(status_code=500, detail=f"failed to queue indexing job: {exc}") from exc

    return {
        "status": "queued",
        "task_id": task_id,
        "job": job,
        "status_url": f"/api/index/{task_id}",
    }


@app.get("/api/index")
def list_index_jobs():
    active_job = _get_active_index_job()
    jobs = []
    try:
        for task_id in get_recent_index_task_ids():
            payload = get_task_status_payload(task_id)
            if payload is not None:
                jobs.append(payload)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"job store unavailable: {exc}") from exc
    return {
        "active_job": active_job,
        "jobs": jobs,
    }


@app.get("/api/index/{task_id}")
def get_index_job(task_id: str):
    try:
        payload = get_task_status_payload(task_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"job store unavailable: {exc}") from exc
    if payload is None:
        raise HTTPException(status_code=404, detail=f"index job not found: {task_id}")
    return payload


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.server:app", host="0.0.0.0", port=5000, reload=False)
