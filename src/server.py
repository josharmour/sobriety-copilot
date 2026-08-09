"""FastAPI server with chat and indexing endpoints."""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from threading import Lock
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Query
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
from src.meetings.online import search_online_meetings, warmup_online_feeds
from src.meetings.service import search_meetings, warmup_feeds as warmup_meeting_feeds
from src.prompts.templates import NO_CONTEXT_TEMPLATE, USER_MESSAGE_TEMPLATE, system_message_for_tone
from src.rag.chroma_client import find_largest_collection_with_prefix
from src.rag.embeddings import warmup as warmup_embeddings
from src.rag.indexer import DEFAULT_COLLECTION
from src.rag.memory import UserMemoryManager, format_state_note
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

BASE_URL = os.environ.get("LLM_BASE_URL", "http://10.0.0.10:8002/v1")
MODEL = os.environ.get("LLM_MODEL", "dsv4")
LLM_MODEL_FT = os.environ.get("LLM_MODEL_FT", "") or None  # None when unset/empty
API_KEY = os.environ.get("LLM_API_KEY", "")
DOCUMENTS_DIR = os.environ.get("DOCUMENTS_DIR", "documents")
RAG_DB_PATH = os.environ.get("RAG_DB_PATH", "rag_db")
RAG_COLLECTION = os.environ.get("RAG_COLLECTION", DEFAULT_COLLECTION)

engine = InferenceEngine(base_url=BASE_URL, model=MODEL, api_key=API_KEY)
# Secondary engine for fine-tuned model A/B testing. Created only when
# LLM_MODEL_FT is set (non-empty). The per-request model_variant="ft" flag
# routes to this engine; unset env = no-op, flag rejected cleanly.
engine_ft: InferenceEngine | None = (
    InferenceEngine(base_url=BASE_URL, model=LLM_MODEL_FT, api_key=API_KEY)
    if LLM_MODEL_FT
    else None
)

# Latency circuit-breaker: the primary generator (gemma on plex) is fast when
# uncontended but can slow under bursty load. When one request's time-to-first-
# token exceeds SLOW_TTFT_MS, we trip a shared (Redis) breaker so subsequent
# requests route to the faster fallback (dsv4) for SLOW_COOLDOWN_S, then revert.
# No single user has to sit through the slow path repeatedly, and it self-heals.
LLM_MODEL_FALLBACK = os.environ.get("LLM_MODEL_FALLBACK", "") or None
SLOW_TTFT_MS = int(os.environ.get("SLOW_TTFT_MS", "5000"))
SLOW_COOLDOWN_S = int(os.environ.get("SLOW_COOLDOWN_S", "120"))
_BREAKER_KEY = "sc:generator:slow_until"
engine_fallback: InferenceEngine | None = (
    InferenceEngine(base_url=BASE_URL, model=LLM_MODEL_FALLBACK, api_key=API_KEY)
    if LLM_MODEL_FALLBACK
    else None
)
memory_manager = UserMemoryManager()
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

# Iterative grounding (diffusion backend): max diffusion blocks per answer and
# how many newly retrieved chunks may be folded into the context between blocks.
GROUND_MAX_BLOCKS = int(os.environ.get("GROUND_MAX_BLOCKS", "16"))
GROUND_NEW_CHUNKS_PER_BLOCK = int(os.environ.get("GROUND_NEW_CHUNKS_PER_BLOCK", "2"))
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
    diffusion_view: bool = False
    user_id: str | None = None
    # Ambient context supplied by the client (e.g. the local-only sobriety
    # tracker's day count). Folded into the system prompt, never persisted.
    client_context: str | None = None
    # Photo attachments as data URLs. Forwarded to the LLM as OpenAI
    # image_url content parts when LLM_SUPPORTS_IMAGES=1; otherwise dropped
    # (the app was already sending these; they were silently ignored).
    images: list[str] | None = None
    # A/B flag for fine-tuned server model routing. Accepted values:
    #   None / absent  → default model (LLM_MODEL)
    #   "ft"           → fine-tuned model (LLM_MODEL_FT); 400 if unset
    model_variant: str | None = None


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
    all_tokens = [t for t in re.findall(r"[A-Za-z0-9]+", highlight or "") if len(t) >= 3]
    # Anchor the match on the first 10; more is usually noise that hurts match rate.
    tokens = all_tokens[:10]
    if len(tokens) < 2:
        return None

    # Rendered PDFs split words across lines ("hu- man", "unhappi-<br>ness",
    # ligature losses like "suffi ciency"), so a token must be allowed to break
    # INSIDE itself: between any two letters permit an optional hyphen/soft-
    # hyphen followed by a short run of whitespace or markup.
    _brk = r"(?:[-­]?(?:<[^>]{0,80}>|\s){1,8})?"

    def _tok(t: str) -> str:
        return _brk.join(re.escape(ch) for ch in t)

    def _try(n: int, gap: int) -> list[tuple[int, int]]:
        # Take the first N significant tokens, allow up to `gap` chars (of any
        # kind: words, whitespace, HTML tags, page-break markup) between
        # consecutive ones, lazily-matched so we get the tightest window.
        # Returns ALL matches: a 10-word phrase can recur (epigraphs, quotes
        # repeated in TOCs), and only the forward walk below can tell which
        # occurrence is the actual passage.
        if n < 2:
            return []
        sep = r"[\s\S]{1," + str(gap) + r"}?"
        pat = re.compile(
            r"\b" + sep.join(_tok(t) for t in tokens[:n]) + r"\b",
            flags=re.IGNORECASE,
        )
        return [(m.start(), m.end()) for m in pat.finditer(content)][:8]

    # Try progressively looser configurations. Most snippets resolve at the
    # first or second attempt; the long-tail keeps us from leaving the user
    # at the top of the page.
    candidates: list[tuple[int, int]] = []
    for n, gap in ((10, 50), (8, 60), (6, 80), (4, 120), (3, 160)):
        if n > len(tokens):
            continue
        candidates = _try(n, gap)
        if candidates:
            break
    if not candidates:
        return None

    def _walk(head: tuple[int, int]) -> tuple[int, int]:
        """Extend a head match through the rest of the excerpt.

        Walk forward in 8-token strides, each matched within a bounded window
        after the last verified point. A stride that fails to match (the two
        extraction pipelines diverge: footnotes, section breaks, inserted
        captions) is SKIPPED — up to 2 consecutive misses with a widened
        window — so a divergent patch in the middle doesn't truncate the
        highlight. Returns (verified_token_count, end_offset).
        """
        sep = r"[\s\S]{1,80}?"
        pos = end = head[1]
        verified = min(10, len(all_tokens))
        misses = 0
        window = 4000
        i = 10  # the head consumed the first ~10 significant tokens
        while i < len(all_tokens):
            stride = all_tokens[i:i + 8]
            if len(stride) < 3:
                break  # too few leftover tokens to match reliably
            # no trailing \b: a length-capped excerpt may end mid-word
            pat = re.compile(
                r"\b" + sep.join(_tok(t) for t in stride),
                flags=re.IGNORECASE,
            )
            m = pat.search(content, pos, pos + window)
            if m:
                end = m.end()
                pos = end
                verified += len(stride)
                misses = 0
                window = 4000
            else:
                misses += 1
                if misses > 2:
                    break
                window = 9000  # widen past the divergent patch, keep position
            i += 8
        return verified, end

    # Pick the head occurrence whose forward walk verifies the most of the
    # excerpt — that's the real passage; a coincidental phrase match goes
    # nowhere on the very next stride.
    best_head = candidates[0]
    best_verified, best_end = _walk(best_head)
    for cand in candidates[1:]:
        if best_verified >= len(all_tokens):
            break
        verified, cand_end = _walk(cand)
        if verified > best_verified:
            best_head, best_verified, best_end = cand, verified, cand_end
    return (best_head[0], best_end)


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


_FOLLOWUP_SYS = (
    "You generate short follow-up questions for a recovery-support chat. "
    "Given the exchange, output 3 brief, natural questions the person might ask "
    "next to go deeper. Each on its own line, phrased in the person's own first "
    "person voice (e.g. \"How do I...\", \"What if I...\"). No numbering, no "
    "bullets, no preamble, under 12 words each."
)


def _generate_followups(query: str, answer: str) -> list[str]:
    """Generate up to 3 'Keep exploring' follow-up questions from the exchange.

    Cheap, capped LLM call. Returns [] on any shortfall so the caller can skip
    emitting the event entirely.
    """
    if not answer:
        return []
    prompt = (
        f"The person asked:\n{query}\n\n"
        f"The assistant replied:\n{answer[:1500]}\n\n"
        "Three follow-up questions the person might ask next:"
    )
    # Thinking OFF (via extra_body) so the model emits the questions directly
    # instead of burning the budget on reasoning that then leaks into content.
    # A tight budget is plenty for three short questions.
    response = engine.client.chat.completions.create(
        model=engine.model,
        messages=[
            {"role": "system", "content": _FOLLOWUP_SYS},
            {"role": "user", "content": prompt},
        ],
        max_tokens=200,
        temperature=0.7,
        extra_body=engine._extra_body(enable_thinking=False),
    )
    message = response.choices[0].message
    raw = message.content or getattr(message, "reasoning", "") or ""
    out: list[str] = []
    for line in (raw or "").splitlines():
        # Strip leading bullets / numbering / quotes that models sometimes add.
        cleaned = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip().strip('"').strip()
        if len(cleaned) < 5 or "?" not in cleaned:
            continue
        out.append(cleaned)
        if len(out) >= 3:
            break
    return out


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


def _unwrap_excerpt(text: str) -> str:
    """Collapse PDF-layout line wraps so excerpts reflow naturally in the UI.

    Extracted page text keeps a newline at every printed line, so excerpts
    break at fixed columns. Rejoin hyphenated wraps, turn single newlines
    into spaces, and keep blank lines as real paragraph breaks.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = re.sub(r"\n{2,}", "\x00", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    text = text.replace("\x00", "\n\n")
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _build_chat_sources(results) -> list[dict[str, Any]]:
    sources = []
    for result in results:
        rel_path = result.relative_path or (
            os.path.relpath(result.source_path, DOCUMENTS_DIR) if result.source_path else result.source
        )
        excerpt = _unwrap_excerpt(_strip_page_headers(result.excerpt))
        if len(excerpt) > MAX_EXCERPT_CHARS:
            excerpt = excerpt[:MAX_EXCERPT_CHARS].rsplit(" ", 1)[0] + "..."
        sources.append({
            "source": result.source,
            "similarity": round(result.similarity, 3),
            "url": f"/api/documents/{rel_path}",
            "excerpt": excerpt,
            "match_scale": result.match_scale,
            "context_scale": result.scale,
            # Conceptual-citation tag surfaced on the chip. Defaults to [] so
            # the frontend contract is stable even when the concept layer has
            # not run (e.g. results built before the field was populated).
            "concepts": list(getattr(result, "concepts", []) or []),
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


def _warmup_retriever() -> None:
    """Build the BM25 keyword cache and exercise the full retrieval path now.

    refresh_cache() loads + tokenizes the entire corpus (~45s for ~29k chunks)
    and is otherwise built lazily on the first user query — so without this the
    first question after a restart pays ~45s on top of the embedding-model load
    and the client times out. Runs after the embedding model is warm, since
    retrieve() needs it.
    """
    _get_retriever().retrieve("recovery serenity acceptance", top_k=4)


async def _warmup_models() -> None:
    # Sequential so a small GPU isn't asked to load both models at once.
    # The cross-encoder is CPU-only and small (~80MB), so it's safe to warm
    # alongside the others; the lifespan task still runs in the background.
    for fn in (engine.warmup, warmup_embeddings, warmup_reranker):
        try:
            await asyncio.to_thread(fn)
        except Exception:
            pass
    # Warm the BM25 cache last: it depends on the embedding model being loaded.
    try:
        await asyncio.to_thread(_warmup_retriever)
    except Exception:
        pass


async def _warmup_meetings() -> None:
    try:
        await warmup_meeting_feeds()
    except Exception:
        pass
    try:
        await warmup_online_feeds()
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
    enable_hyde = os.environ.get("ENABLE_HYDE", "1").strip().lower() not in ("0", "false", "no", "off")
    if not enable_hyde:
        return None
    if not question or len(question) > 600:
        return None
    key = _hyde_cache_key(question)
    cached = _hyde_cache_get(key)
    if cached:
        return cached
    try:
        # Thinking OFF: HyDE only needs the hypothetical passage, and leaving
        # reasoning on let the model's chain-of-thought leak into the passage
        # (and from there into the retrieval embedding). With no reasoning the
        # passage comes back directly, so a tight budget is enough.
        passage = engine.generate(
            prompt=HYDE_PROMPT.format(question=question.strip()),
            history=[],
            max_tokens=400,
            system_message=HYDE_SYSTEM_MESSAGE,
            enable_thinking=False,
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
    import time as _chat_time
    _chat_t0 = _chat_time.monotonic()
    
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="missing 'message' field")

    user_id = (payload.user_id or "default_user").strip() or "default_user"
    user_state = memory_manager.get_user_state(user_id)
    user_state_note = format_state_note(user_state)

    retriever_instance = _safe_get_retriever()
    query = payload.message
    history = payload.history
    categories = _normalize_categories(payload.categories)

    # A/B model variant routing -------------------------------------------------
    selected_model_variant = "default"
    active_engine: InferenceEngine = engine
    variant = (payload.model_variant or "").strip().lower()
    if variant and variant != "default":
        if variant != "ft":
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported model_variant {variant!r}. Accepted: 'ft' or absent.",
            )
        if not LLM_MODEL_FT:
            raise HTTPException(
                status_code=400,
                detail="model_variant='ft' requested but LLM_MODEL_FT is not configured. Set LLM_MODEL_FT env var to enable.",
            )
        active_engine = engine_ft  # type: ignore[assignment]
        selected_model_variant = "ft"
    # ---------------------------------------------------------------------------

    # Latency circuit-breaker: if the primary generator recently went slow, a
    # shared Redis flag routes requests to the faster fallback (dsv4) until the
    # cooldown expires — so no user queues behind a slow gemma. Only applies to
    # the default variant; explicit A/B requests are honored as asked.
    breaker_active = False
    if selected_model_variant == "default" and engine_fallback is not None:
        try:
            if get_redis_client().get(_BREAKER_KEY):
                active_engine = engine_fallback
                selected_model_variant = "fallback"
                breaker_active = True
        except Exception:
            pass

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
        print(f"[CHAT] tone={payload.tone or 'brief'!s:9} history_len={len(history)} cats={categories} model_variant={selected_model_variant}", flush=True)
        if selected_model_variant == "ft":
            print(f"[ABFLAG] variant=ft model={active_engine.model} base_url={BASE_URL}", flush=True)
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
    if user_state_note:
        sys_msg = f"{sys_msg}\n\n{user_state_note}" if sys_msg else user_state_note
    client_note = (payload.client_context or "").strip()
    if client_note:
        client_note = client_note.replace("\n", " ")[:300]
        note_line = (
            "Personal context from their device for this reply only "
            f"(mention only if it fits what they're asking): {client_note}"
        )
        sys_msg = f"{sys_msg}\n\n{note_line}" if sys_msg else note_line
    want_thinking = bool(payload.show_thinking)
    want_diffusion = bool(payload.diffusion_view)

    def generate():
        # Immediate SSE priming comment — forces proxies (nginx, Cloudflare) to
        # commit the TCP connection and start streaming *before* the first data
        # event.  The header bytes hit the wire right away; any downstream
        # buffering heuristic that waits for N bytes is defeated.
        yield ": primed\n\n"

        # Wall-clock timing instrumentation
        _t_retrieval_done = _chat_time.monotonic()
        _t_retrieval_ms = int((_t_retrieval_done - _chat_t0) * 1000)
        yield f"data: {json.dumps({'server_timing_ms': {'chat': _t_retrieval_ms}})}\n\n"

        first_event = {"sources": sources}
        if hyde_passage:
            first_event["expanded_query"] = hyde_passage
        yield f"data: {json.dumps(first_event)}\n\n"

        response_buffer: list[str] = []
        try:
            # Iterative grounding: generate ONE diffusion block per call; between
            # blocks, re-retrieve using the draft so far and fold new chunks into
            # the context. Strictly additive — chunks are never evicted, so
            # grounding the model already drew on cannot vanish mid-answer.
            merged_results = list(results)
            seen_chunks = {(r.source, (r.excerpt or r.text or "")[:80]) for r in results}
            cur_prompt = prompt
            # Multimodal: attach photos as OpenAI content parts when the
            # backend model supports vision (LLM_SUPPORTS_IMAGES=1).
            user_content = None
            if LLM_SUPPORTS_IMAGES and payload.images:
                user_content = [{"type": "text", "text": prompt}] + [
                    {"type": "image_url", "image_url": {"url": img}}
                    for img in payload.images[:4]
                    if isinstance(img, str) and img.startswith("data:image/")
                ]
            raw_answer = ""   # verbatim committed text (incl. thought tags) fed back as continue_text
            agg_tokens = 0
            gen_t0 = time.monotonic()
            _first_tok_t: float | None = None
            for block_i in range(GROUND_MAX_BLOCKS):
                block_raw = ""
                block_tokens = 0
                finish = None
                for kind, text in active_engine.stream_typed(
                    cur_prompt,
                    history=history,
                    system_message=sys_msg,
                    continue_text=raw_answer or None,
                    n_blocks=1,
                    user_content=user_content if block_i == 0 else None,
                ):
                    if kind == "diffusion":
                        # Per-denoising-step snapshot of the WHOLE answer so far
                        # (replace semantics). Only forwarded when the client
                        # opted into the animated diffusion view; the committed
                        # `token` events below remain the canonical answer text.
                        if want_diffusion and isinstance(text, dict):
                            frame = dict(text)
                            frame["block"] = block_i
                            yield f"data: {json.dumps({'diffusion': frame})}\n\n"
                    elif kind == "stats":
                        # backend stats are per-call; aggregate across blocks so
                        # the client sees answer-level throughput
                        if isinstance(text, dict):
                            block_tokens = int(text.get("completion_tokens") or 0)
                            elapsed = max(time.monotonic() - gen_t0, 1e-6)
                            agg = {
                                "completion_tokens": agg_tokens + block_tokens,
                                "elapsed_ms": round(elapsed * 1000),
                                "tok_per_sec": round((agg_tokens + block_tokens) / elapsed, 1),
                            }
                            yield f"data: {json.dumps({'stats': agg})}\n\n"
                    elif kind == "raw":
                        block_raw = text or ""
                    elif kind == "finish":
                        finish = text
                    elif kind == "thinking":
                        if want_thinking:
                            yield f"data: {json.dumps({'thinking': text})}\n\n"
                        else:
                            # SSE comment — invisible to EventSource but keeps the
                            # connection alive across proxies (Cloudflare free
                            # tunnels close idle streams around 100s; thinking
                            # models can reason longer than that before any token).
                            yield ": keepalive\n\n"
                    else:
                        if _first_tok_t is None:
                            _first_tok_t = time.monotonic()
                            # Trip the breaker if the PRIMARY generator was slow to
                            # first token, so subsequent requests use the fallback.
                            if (not breaker_active and engine_fallback is not None
                                    and (_first_tok_t - gen_t0) * 1000 > SLOW_TTFT_MS):
                                try:
                                    get_redis_client().set(
                                        _BREAKER_KEY, "1", ex=SLOW_COOLDOWN_S
                                    )
                                    print(
                                        f"[BREAKER] gen TTFT "
                                        f"{(_first_tok_t - gen_t0) * 1000:.0f}ms > "
                                        f"{SLOW_TTFT_MS}ms -> routing to "
                                        f"{LLM_MODEL_FALLBACK} for {SLOW_COOLDOWN_S}s",
                                        flush=True,
                                    )
                                except Exception:
                                    pass
                        response_buffer.append(text)
                        yield f"data: {json.dumps({'token': text})}\n\n"
                raw_answer += block_raw
                agg_tokens += block_tokens
                if finish != "length":
                    break  # answer complete (EOG) — "length" means more blocks needed
                draft = "".join(response_buffer).strip()
                if not draft:
                    continue  # still inside the thought channel; nothing to ground on yet
                _re_t0 = _chat_time.monotonic()
                try:
                    regrounded = retriever_instance.retrieve(
                        retrieval_query,
                        categories=categories,
                        embedding_query=f"{query}\n\n{draft[-900:]}",
                    )
                except Exception as rg_exc:
                    print(f"[REGROUND-ERR] {type(rg_exc).__name__}: {rg_exc}", flush=True)
                    continue
                _re_elapsed = _chat_time.monotonic() - _re_t0
                print(f"[REGROUND] block {block_i}: retrieve in {_re_elapsed:.2f}s, "
                      f"returned {len(regrounded)} chunks", flush=True)
                fresh = []
                for r in regrounded:
                    chunk_key = (r.source, (r.excerpt or r.text or "")[:80])
                    if chunk_key not in seen_chunks:
                        seen_chunks.add(chunk_key)
                        fresh.append(r)
                if not fresh:
                    continue
                fresh.sort(key=lambda r: r.similarity, reverse=True)
                merged_results.extend(fresh[:GROUND_NEW_CHUNKS_PER_BLOCK])
                cur_prompt = USER_MESSAGE_TEMPLATE.format(
                    context=retriever_instance.format_context(merged_results),
                    question=query,
                )
                print(
                    f"[REGROUND] after block {block_i}: +{len(fresh[:GROUND_NEW_CHUNKS_PER_BLOCK])} chunks"
                    f" -> {len(merged_results)} total: "
                    + ", ".join(r.source for r in fresh[:GROUND_NEW_CHUNKS_PER_BLOCK]),
                    flush=True,
                )
                # cumulative source list — clients replace their copy wholesale
                yield f"data: {json.dumps({'sources': _build_chat_sources(merged_results)})}\n\n"
            # "Keep exploring" follow-up questions, generated from the answer.
            # Best-effort: never let a failure here break the stream.
            try:
                answer_text = "".join(response_buffer).strip()
                followups = _generate_followups(query, answer_text)
                if followups:
                    yield f"data: {json.dumps({'followups': followups})}\n\n"
            except Exception as fu_exc:
                print(f"[FOLLOWUPS-ERR] {type(fu_exc).__name__}: {fu_exc}", flush=True)
            yield "data: {\"done\": true}\n\n"
            # Total wall-clock time from request start
            _t_total_ms = int((_chat_time.monotonic() - _chat_t0) * 1000)
            print(f"[CHAT-DONE] {_t_total_ms}ms total", flush=True)
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        finally:
            try:
                if STORE_CHAT_HISTORY:
                    response_text = "".join(response_buffer).strip()
                    memory_manager.save_interaction(user_id, query, response_text)
                else:
                    # Privacy default: no message bodies server-side — the
                    # deployed privacy policy promises chat history stays on
                    # the device. Keep only the last-seen timestamp.
                    memory_manager.touch(user_id)
            except Exception as mem_exc:
                print(f"[MEM-ERR] {type(mem_exc).__name__}: {mem_exc}", flush=True)

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

# Opt-in server-side transcript storage (debugging only). Default OFF: the
# deployed privacy policy promises chat history lives on-device only.
STORE_CHAT_HISTORY = os.environ.get("STORE_CHAT_HISTORY", "0") == "1"

# Forward photo attachments to the LLM as vision content parts. Off by
# default — flip after confirming the deployed model accepts image input.
LLM_SUPPORTS_IMAGES = os.environ.get("LLM_SUPPORTS_IMAGES", "0") == "1"


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
def list_bugs(x_admin_token: str | None = Header(default=None)):
    # Reports carry conversation snippets — admin-only, fail closed when the
    # token isn't configured.
    expected = os.environ.get("BUG_ADMIN_TOKEN", "")
    if not expected or not x_admin_token or not hmac.compare_digest(
        x_admin_token, expected
    ):
        raise HTTPException(status_code=403, detail="forbidden")
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


@app.get("/api/graph")
def graph(q: str = Query(default="The Twelve Steps")):
    from src.rag.graph import build_knowledge_graph
    retriever_instance = _safe_get_retriever()
    return build_knowledge_graph(q, retriever=retriever_instance)


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

    params = {
        "q": q,
        "format": "json",
        "limit": "1",
        "addressdetails": "1",
    }
    # Optional comma-separated country filter. Default is worldwide — the NA
    # aggregator covers meetings well beyond the US/CA.
    countrycodes = os.environ.get("GEOCODE_COUNTRYCODES", "").strip()
    if countrycodes:
        params["countrycodes"] = countrycodes

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params=params,
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
    fellowship: str | None = Query(None, max_length=40),
):
    return await search_meetings(
        lat=lat, lng=lng,
        radius_mi=radius_mi, max_results=max,
        day=day, attendance=attendance, fellowship=fellowship,
    )


@app.get("/api/meetings/online")
async def meetings_online(
    fellowship: str | None = Query(None, max_length=40),
    max: int = Query(50, ge=1, le=200),
    day: int | None = Query(None, ge=0, le=6),
):
    """Location-agnostic online-meeting directory (OIAA + Virtual NA).

    Sorted live-now first, then soonest-to-start; every result carries a
    conference_url or conference_phone.
    """
    return await search_online_meetings(
        fellowship=fellowship, max_results=max, day=day,
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
        "model_ft": LLM_MODEL_FT,
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


@app.get("/api/doc/{doc_id}")
def render_manifest_doc(
    doc_id: str,
    blocks: str = Query(default=""),
    debug: str = Query(default=""),
):
    import json
    
    manifest_path = os.path.join(DOCUMENTS_DIR, ".manifests", f"{doc_id}.json")
    if not os.path.isfile(manifest_path):
        raise HTTPException(status_code=404, detail="Document manifest not found")
        
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read manifest: {e}")
        
    raw_blocks = manifest.get("blocks", [])
    if not raw_blocks:
        raise HTTPException(status_code=400, detail="Manifest has no blocks")
        
    requested_blocks = [b.strip() for b in blocks.split(",") if b.strip()]
    requested_set = set(requested_blocks)
    
    # Find block indices of requested blocks
    block_indices = []
    for idx, b in enumerate(raw_blocks):
        if b["id"] in requested_set:
            block_indices.append(idx)
            
    # Determine which blocks to show (context window)
    if not block_indices:
        # Default: show the first 5 pages or first 30 blocks
        show_indices = []
        for idx, b in enumerate(raw_blocks):
            phys_page = b.get("physical_page")
            if phys_page is not None and phys_page <= 5:
                show_indices.append(idx)
            elif phys_page is None and idx < 30:
                show_indices.append(idx)
        if not show_indices:
            show_indices = list(range(min(len(raw_blocks), 30)))
    else:
        # Find physical page range or index range
        has_phys = any(raw_blocks[idx].get("physical_page") is not None for idx in block_indices)
        if has_phys:
            pages = [raw_blocks[idx]["physical_page"] for idx in block_indices if raw_blocks[idx].get("physical_page") is not None]
            min_page = min(pages)
            max_page = max(pages)
            
            show_indices = []
            for idx, b in enumerate(raw_blocks):
                phys = b.get("physical_page")
                if phys is not None and (min_page - 3 <= phys <= max_page + 3):
                    show_indices.append(idx)
        else:
            min_idx = min(block_indices)
            max_idx = max(block_indices)
            start_idx = max(0, min_idx - 20)
            end_idx = min(len(raw_blocks), max_idx + 21)
            show_indices = list(range(start_idx, end_idx))
            
    # Now build the HTML blocks
    rendered_blocks = []
    last_printed_page = None
    first_highlight_id_set = False
    
    for idx in show_indices:
        b = raw_blocks[idx]
        b_type = b.get("type", "paragraph")
        
        # Skip headers, footers, garbage
        if b_type in ("page_header", "page_footer", "garbage"):
            continue
            
        # Page marker
        printed_page = b.get("printed_page")
        if printed_page is not None and printed_page != last_printed_page:
            rendered_blocks.append(f'<div class="page-marker">p. {printed_page}</div>')
            last_printed_page = printed_page
            
        # Highlight logic
        is_highlighted = b["id"] in requested_set
        hl_attr = ""
        hl_class = ""
        if is_highlighted:
            hl_class = " hl-block"
            if not first_highlight_id_set:
                hl_attr = ' id="hl"'
                first_highlight_id_set = True
                
        # Render tag
        b_id = b["id"]
        text = b.get("text", "")
        import html as html_mod
        escaped_text = html_mod.escape(text)
        
        if b_type == "heading":
            level = b.get("level", 2)
            if level not in (2, 3, 4):
                level = 2
            rendered_blocks.append(f'<h{level}{hl_attr} class="doc-heading{hl_class}">{escaped_text}</h{level}>')
        elif b_type == "epigraph":
            rendered_blocks.append(f'<blockquote{hl_attr} class="epigraph{hl_class}">{escaped_text}</blockquote>')
        elif b_type == "footnote":
            rendered_blocks.append(f'<p{hl_attr} class="footnote{hl_class}" id="{b_id}"><sup>*</sup> {escaped_text}</p>')
        elif b_type == "list":
            rendered_blocks.append(f'<p{hl_attr} class="list-item{hl_class}" id="{b_id}">• {escaped_text}</p>')
        elif b_type == "toc":
            rendered_blocks.append(f'<p{hl_attr} class="toc-item{hl_class}" id="{b_id}">{escaped_text}</p>')
        else:
            rendered_blocks.append(f'<p{hl_attr} class="paragraph{hl_class}" id="{b_id}">{escaped_text}</p>')
            
    content = "\n".join(rendered_blocks)
    
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
.page-marker {{
  text-align: center;
  color: #888;
  font-size: 0.8rem;
  margin: 2rem 0;
  border-top: 1px dashed #ccc;
  border-bottom: 1px dashed #ccc;
  padding: 0.2rem 0;
  font-family: -apple-system, BlinkMacSystemFont, sans-serif;
}}
.hl-block {{
  background-color: #d4f5e9 !important;
  padding: 4px 8px;
  border-radius: 4px;
}}
.epigraph {{
  font-style: italic;
  margin: 1rem 2rem;
  color: #555;
}}
.footnote {{
  font-size: 0.875rem;
  color: #666;
}}
.list-item {{
  margin-left: 1.5rem;
}}
@media (prefers-color-scheme: dark) {{
  body {{ background: #161b22; color: #e8eaed; }}
  h1,h2,h3,h4 {{ color: #4ec3b1; }}
  #hl {{ background: #1f4a3e !important; }}
  .hl-block {{ background-color: #1f4a3e !important; }}
  .purchase-notice {{
    background: linear-gradient(135deg, #2d1b0e 0%, #432818 100%);
    color: #fef3c7;
    border-color: #d97706;
  }}
  .page-marker {{ border-color: #444; color: #777; }}
  .epigraph {{ color: #aaa; }}
  .footnote {{ color: #aaa; }}
}}
</style></head>
<body>{framed_content}
<script>
  function scrollToHl() {{
    const hl = document.getElementById('hl');
    if (!hl) return;
    hl.scrollIntoView({{ behavior: 'auto', block: 'center' }});
  }}
  function startScrollAttempts() {{
    requestAnimationFrame(() => requestAnimationFrame(scrollToHl));
    [0, 60, 180, 400].forEach(d => setTimeout(scrollToHl, d));
  }}
  if (document.readyState === 'complete') startScrollAttempts();
  else window.addEventListener('load', startScrollAttempts);
</script>
</body></html>"""
    return HTMLResponse(page)


@app.get("/api/private/embedder/{part}")
def private_embedder(part: str):
    """Serve the EmbeddingGemma files for Private Mode semantic search.

    Self-hosted mirror (Gemma Terms permit redistribution) so users need no
    HuggingFace account. Files live in packs/embedder/ (read-only mount),
    dropped there out-of-band — they are deliberately not in git.
    """
    names = {
        "model": "embeddinggemma.tflite",
        "tokenizer": "embeddinggemma-tokenizer.model",
    }
    if part not in names:
        raise HTTPException(status_code=404, detail="unknown part")
    path = os.path.join(BASE_DIR, "packs", "embedder", names[part])
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="embedder not hosted")
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=names[part],
    )


@app.get("/api/packs/latest")
def get_latest_pack():
    import glob
    import hashlib
    import zipfile
    
    packs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packs")
    if not os.path.isdir(packs_dir):
        packs_dir = "packs"
        
    pack_files = glob.glob(os.path.join(packs_dir, "library-v*.scpack"))
    if not pack_files:
        raise HTTPException(status_code=404, detail="No content packs found")
        
    # Find latest pack file by version number
    latest_file = None
    latest_version = -1
    for pf in pack_files:
        basename = os.path.basename(pf)
        try:
            ver_part = basename.replace("library-v", "").replace(".scpack", "")
            ver = int(ver_part)
            if ver > latest_version:
                latest_version = ver
                latest_file = pf
        except ValueError:
            continue
            
    if not latest_file:
        raise HTTPException(status_code=404, detail="No valid content packs found")
        
    # Read pack.json metadata from zip
    try:
        with zipfile.ZipFile(latest_file, "r") as zipf:
            pack_json_data = zipf.read("pack.json")
            pack_meta = json.loads(pack_json_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read pack metadata: {e}")
        
    # Compute sha256 of the zip file
    sha256_hash = hashlib.sha256()
    try:
        with open(latest_file, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        file_sha256 = sha256_hash.hexdigest()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to hash pack file: {e}")
        
    return {
        "pack_version": pack_meta.get("pack_version", latest_version),
        "schema_version": pack_meta.get("schema_version", 1),
        "created_utc": pack_meta.get("created_utc", int(os.path.getmtime(latest_file))),
        "doc_count": pack_meta.get("doc_count", 0),
        "sha256": file_sha256,
        "download_url": f"/api/packs/download/v{latest_version}"
    }

@app.get("/api/packs/download/v{version}")
def download_pack(version: int):
    packs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packs")
    if not os.path.isdir(packs_dir):
        packs_dir = "packs"
        
    pack_file = os.path.join(packs_dir, f"library-v{version}.scpack")
    if not os.path.isfile(pack_file):
        raise HTTPException(status_code=404, detail=f"Content pack version {version} not found")
        
    return FileResponse(
        pack_file,
        media_type="application/zip",
        filename=f"library-v{version}.scpack"
    )


@app.get("/api/render/{filepath:path}")
def render_document(
    filepath: str,
    highlight: str = Query(default=""),
    debug: str = Query(default=""),
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
                # No "Page N of M" label — the embedded reference viewer shows the
                # passage text only; page numbers belong in the chat prose, not here.
                pages.append(
                    f'<div style="margin-bottom:1rem;padding-bottom:1rem;border-bottom:1px solid #e5e7eb;">'
                    f'<div>{escaped_text}</div></div>'
                )
        content = "\n".join(pages)

    if highlight:
        match_span = _locate_highlight_span(highlight, content)
        if debug:
            span_words = 0
            if match_span:
                span_words = len(re.sub(r"<[^>]+>", " ", content[match_span[0]:match_span[1]]).split())
            return JSONResponse({
                "hl_len": len(highlight),
                "hl_head": highlight[:60],
                "hl_tail": highlight[-60:],
                "content_len": len(content),
                "span": list(match_span) if match_span else None,
                "span_words": span_words,
            })
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
            # The matched range can cross block elements (</p><p> in epub
            # sections, page divs in PDFs). A single wrapping <span> is invalid
            # HTML there — browsers auto-close it at the first block boundary,
            # which visually truncates the highlight to one paragraph. Wrap
            # each text run between tags individually instead; the first run
            # carries id="hl" as the scroll anchor.
            first_seg = [True]

            def _wrap_seg(m: "re.Match[str]") -> str:
                seg = m.group(0)
                if seg.startswith("<"):
                    return seg
                if not seg.strip():
                    return seg
                anchor = ' id="hl"' if first_seg[0] else ""
                first_seg[0] = False
                return (
                    f'<span{anchor} class="hl-seg" '
                    f'style="background:#d4f5e9;padding:2px 0;border-radius:3px;">{seg}</span>'
                )

            highlighted = re.sub(r"<[^>]*>|[^<>]+", _wrap_seg, snippet)
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
