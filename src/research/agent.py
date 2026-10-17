"""Research mode: the model reads the literature through tools, then answers.

Ordinary chat answers from ~10 retrieved excerpts. Research mode instead lets
the model plan and gather its own evidence — open a book's outline, read whole
chapters, count exact words, search, or put one question to every chapter in
parallel — and only then write, citing pages it actually read.

``ResearchSession.run`` is a generator of SSE payload dicts using the same
events as ``/api/chat`` (``thinking``, ``token``, ``sources``) plus
``research`` progress events, so the chat UI can render it unchanged; a
``None`` item means "send a keepalive".
"""

from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from src.research.library import Block, BookText, Library

MAX_TOOL_ROUNDS = 14
READ_WORDS_PER_CALL = 9000
TOTAL_READ_WORDS = 140_000
ANALYZE_MAX_SECTIONS = 40
ANALYZE_CONCURRENCY = int(os.environ.get("RESEARCH_ANALYZE_CONCURRENCY", "3"))
TIME_LIMIT_S = float(os.environ.get("RESEARCH_TIME_LIMIT_S", "420"))
PREFETCH_PASSAGES = 4
# Characters of reply text (with no tool call yet) before a turn is taken to be
# the answer and starts streaming.
OPTIMISTIC_CHARS = 40
# Messages that may be a crisis: skip the up-front search so the safety reply starts immediately.
_URGENT_RE = re.compile(
    r"\b(suicid\w*|kill (?:my|him|her)self|end (?:it all|my life)|hurt(?:ing)? myself|self[- ]harm|overdos\w*"
    r"|(?:want|going|about|need) to (?:drink|use|get (?:high|drunk))|(?:drink|use|relapse)\w* (?:right )?now"
    r"|can'?t stop (?:myself|drinking|using))", re.IGNORECASE)
MAX_SOURCES = 12
# vLLM priority: lower runs first. Chat requests send none (0), so research
# never makes a live chat wait behind it.
PRIORITY_AGENT = 2
PRIORITY_ANALYZE = 4
# Reasoning effort for the planning and answer turns. "medium" spent close to a
# minute deliberating before each answer on the shared GPU; the readers and
# the verified quotes carry the rigour.
AGENT_EFFORT = os.environ.get("RESEARCH_EFFORT", "low")

TOOLS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "get_outline",
        "description": "List a book's sections (chapters, stories, Steps, daily readings) with their index, "
                       "page range and length. Use it before reading or analysing a book.",
        "parameters": {"type": "object", "properties": {
            "book": {"type": "string", "description": "Book id from the catalog, or its title or common name."},
        }, "required": ["book"]}}},
    {"type": "function", "function": {
        "name": "read_section",
        "description": "Read the full text of one section. Every paragraph is prefixed with its page and "
                       "block id like [p.67 b00629]. Long sections come in parts.",
        "parameters": {"type": "object", "properties": {
            "book": {"type": "string"},
            "section": {"type": ["integer", "string"],
                        "description": "The section's [index] from get_outline (not a chapter or Step number), "
                                       "or its exact title, e.g. \"Step Six\" or \"How It Works\"."},
            "part": {"type": "integer", "description": "Part number for long sections (default 1)."},
        }, "required": ["book", "section"]}}},
    {"type": "function", "function": {
        "name": "find_text",
        "description": "Exact, case-insensitive search for words or phrases, counted per section (one book) "
                       "or per book (whole library), with the sentences they occur in. A trailing * matches "
                       "word endings (pray* = pray, prays, prayer, prayed). Use this for any counting question.",
        "parameters": {"type": "object", "properties": {
            "terms": {"type": "array", "items": {"type": "string"}, "description": "Up to 8 words or phrases."},
            "book": {"type": "string", "description": "Limit to one book (omit to search every book)."},
            "section": {"type": ["integer", "string"], "description": "Limit to one section of that book."},
        }, "required": ["terms"]}}},
    {"type": "function", "function": {
        "name": "search",
        "description": "Find passages about an idea even when the wording differs (semantic + keyword search).",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "book": {"type": "string", "description": "Limit to one book (omit to search the library)."},
            "limit": {"type": "integer", "description": "Number of passages, default 8, max 15."},
        }, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "analyze_sections",
        "description": "Put one task to many sections of a book at once — each section is read in full by a "
                       "separate reader that returns exact quotes with pages. Use it for questions that need "
                       "every chapter examined (e.g. 'list every prayer in each chapter').",
        "parameters": {"type": "object", "properties": {
            "book": {"type": "string"},
            "sections": {"type": "array", "items": {"type": "integer"},
                         "description": f"Section indexes from get_outline (max {ANALYZE_MAX_SECTIONS})."},
            "task": {"type": "string", "description": "What each reader should extract or judge."},
        }, "required": ["book", "sections", "task"]}}},
    {"type": "function", "function": {
        "name": "ready_to_answer",
        "description": "Call once you have what you need. You will then write the answer.",
        "parameters": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["reply", "research"],
                     "description": "reply = a conversational answer in the person's tone; research = a full, "
                                    "cited answer to a question that needed real reading."},
            "plan": {"type": "string", "description": "One or two sentences on what the answer will say."},
        }, "required": ["kind", "plan"]}}},
]

_RESEARCH_METHOD = """You can read the recovery literature itself with your tools. Decide how much each \
message needs, then answer:
- Someone in crisis or at risk: no tools at all — answer at once per the Safety rules.
- A greeting, thanks, or small talk: no tools — just write your reply.
- Someone sharing what they're going through, or asking for support: if the passages attached to their \
message speak to it, just write your reply from them, right away, with no tool call; otherwise one quick \
search first. A warm, human reply in their chosen tone, not a report; at most one short quote, copied exactly.
- A simple factual question (is a phrase in a book, where is a passage, a definition): the one or two lookups \
that settle it, then ready_to_answer with kind "reply".
- A question that needs real reading (each chapter, comparisons, counts, tracing an idea across books, "what \
does the literature say about…"): research properly, then ready_to_answer with kind "research".
Never answer questions about what the books say from memory: your memory of these books blurs chapters, \
pages and which book said what.

How to research:
- Start from the catalog below. For questions about a book's structure ("each chapter", "every Step"), call \
get_outline first.
- Read whole sections with read_section when the question needs close reading of a few chapters.
- For any count ("how many times", "how many prayers"), use find_text for words, and analyze_sections when \
judgement is needed (e.g. what counts as a prayer). Never estimate counts.
- Use analyze_sections when many sections each need examining; use search to find where an idea is discussed \
when you don't know where to look.
- Compare books by gathering evidence from each, not by recalling them.
- Only cite what you have seen in a tool result. If you want to bring in another chapter, an appendix or \
another book, read or search it first — before calling ready_to_answer.
- When analyze_sections is used for judgement calls, word the task broadly enough to catch every candidate \
(for prayers: any words addressed to God, any "we ask God…" petition, set prayers and short prayers alike), \
then apply your own criteria to what comes back.
- Several tool calls in one turn are fine. Be efficient: stop when you have what you need, then call \
ready_to_answer. You have at most {max_rounds} rounds of tool calls.
- Whether a phrase or idea is "in" a book is a factual question: check the exact wording with find_text \
before answering, and keep exact wording, paraphrase and meeting-room slogans distinct.
- When you cite a passage, situate it: which chapter, what it is doing in that chapter's argument, what comes \
just before or after when that matters.
- Use the catalog's copyright years (this copy's edition; first editions may be older) and what you read to \
show how an idea developed across books and decades, and which book draws on which.
- Where books or fellowships differ or pull against each other, say so plainly instead of blending them.
- If the scope is ambiguous (e.g. "the Big Book": first 164 pages, or the stories too?), pick the most likely \
reading, say in a few words which you chose, and offer the other at the end — don't stop to ask.
- Earlier turns may end with [Research notes: …] listing what was already read; build on it (re-read a passage \
if you need its exact words) rather than starting over.

Library catalog (book id: title — use the id in tool calls):
{catalog}"""

_ANSWER_INSTRUCTIONS = """Research is complete. Now write the answer for the person.
- Ground every claim in what you read above. Quote exactly — copy wording from the tool output, never from \
memory — and give the page, e.g. (Big Book, p. 67). Never cite a page, chapter or appendix you did not see \
in a tool result above, and don't describe what an unread passage says. Every quote and page will be checked \
against the text.
- Lead with the direct answer. For counts or comparisons, a short markdown table or list works well.
- When readers returned findings (analyze_sections), account for every one: include it, or say in a few \
words why you left it out. Never drop a finding silently — a count must add up to the findings listed.
- When a classification is a judgement call (e.g. religious vs. spiritual), say briefly what criteria you used.
- Say plainly when the text doesn't settle something.
- Never mention tools, block ids, sections indexes or "the research"; just answer.
- Keep the Voice and Safety rules. Be thorough but not padded."""

_REPLY_INSTRUCTIONS = """Now write your reply to the person.
- Use their chosen tone and length; this is a conversation, not a report — no headings or tables.
- If a passage you found speaks to it, weave in at most one short quote, copied exactly from the tool output, \
with its page, e.g. (Big Book, p. 67). Never quote from memory.
- Never mention tools, searches or block ids.
- Keep the Voice and Safety rules."""

_ANALYZE_SYSTEM = """You read one section of a recovery book for a research task. Report only what this text \
says. Quote exactly, copying words from the text. Each paragraph starts with a marker like [p.67 b00629]; put \
the marker of the paragraph you quote in front of each finding."""

_ANALYZE_USER = """Research task: {task}

Book: {book}
Section: {section} ({pages})

{text}

Reply in exactly this format:
SUMMARY: <one to three sentences on what this section contributes to the task, or "Nothing relevant.">
FINDINGS:
- [p.<page> <block>] "<exact quote>" — <short note>
(write "- none" if there are no findings)"""

_FINDING_RE = re.compile(r"^\s*-\s*\[p\.?\s*([^\s\]]+)\s+(b\d+|i\d+)\]\s*[\"“](.+?)[\"”]\s*(?:—|-|–)?\s*(.*)$")
# Any quoted span; short ones are skipped after matching so a short quote
# ("two-stepping") can't shift the pairing of the quotes that follow it.
_QUOTE_IN_ANSWER_RE = re.compile(r"[\"“]([^\"”\n]{1,600})[\"”]")


@dataclass
class Evidence:
    doc_id: str
    title: str
    source_file: str
    block: Block


@dataclass
class _Step:
    id: int
    tool: str
    label: str


@dataclass
class ResearchSession:
    client: Any                      # an openai.OpenAI-compatible client
    model: str
    library: Library
    extra_body: dict[str, Any]       # backend knobs (thinking flags) shared with chat
    retriever: Any = None
    show_thinking: bool = False
    use_priority: bool = True
    clock: Callable[[], float] = time.monotonic
    evidence: dict[tuple[str, str], Evidence] = field(default_factory=dict)
    consulted: set[str] = field(default_factory=set)  # every book a tool touched, even with no hits
    question: str = ""
    # Limited library categories (the person's settings), or None for all.
    categories: list[str] | None = None
    # Called before whole-chapter reading; False = server busy, so ordinary
    # messages are never held up by other people's deep research.
    heavy_gate: Callable[[], bool] | None = None
    answer_kind: str = "reply"
    preamble: str = ""  # text streamed in a turn that then called tools
    words_read: int = 0
    steps: int = 0

    # ── public ──────────────────────────────────────────────────────────

    def run(self, question: str, history: list[dict[str, str]], system_message: str) -> Iterator[dict | None]:
        t0 = self.clock()
        self.question = question
        system = system_message + "\n\n" + _RESEARCH_METHOD.format(
            max_rounds=MAX_TOOL_ROUNDS, catalog=self.library.catalog_text(self.categories))
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}, *history,
                                          {"role": "user", "content": question + self._prefetch(question)}]
        for _round in range(MAX_TOOL_ROUNDS):
            if self.clock() - t0 > TIME_LIMIT_S:
                break
            turn = yield from self._stream_turn(messages, tools=True, optimistic=True)
            if not turn["tool_calls"]:
                # Answered directly: that text is the answer (already streamed if long enough).
                text = turn["content"].strip()
                if not text:
                    break  # an empty turn: fall through to the answer-writing turn
                if not turn["streamed"]:
                    yield {"research": {"type": "phase", "phase": "writing"}}
                    for piece in _chunks(text):
                        yield {"token": piece}
                yield from self._finish(self.preamble + text)
                return
            if turn["streamed"]:
                # Text already shown before the model decided to look things up.
                self.preamble += turn["content"].strip() + "\n\n"
            messages.append({"role": "assistant", "content": turn["content"] or None,
                             "tool_calls": [{"id": c["id"], "type": "function",
                                             "function": {"name": c["name"], "arguments": c["arguments"]}}
                                            for c in turn["tool_calls"]]})
            ready = False
            for call in turn["tool_calls"]:
                if call["name"] == "ready_to_answer":
                    ready = True
                    try:
                        kind = json.loads(call["arguments"] or "{}").get("kind")
                    except Exception:
                        kind = None
                    self.answer_kind = "reply" if kind == "reply" else "research"
                    messages.append({"role": "tool", "tool_call_id": call["id"],
                                     "content": _REPLY_INSTRUCTIONS if kind == "reply" else _ANSWER_INSTRUCTIONS})
                    continue
                result = yield from self._run_tool(call)
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
            if ready:
                break
        if messages[-1]["role"] != "tool" or messages[-1]["content"] not in (_ANSWER_INSTRUCTIONS, _REPLY_INSTRUCTIONS):
            messages.append({"role": "user", "content": "(Time to answer.) " + _ANSWER_INSTRUCTIONS})
        yield {"research": {"type": "phase", "phase": "writing"}}
        if self.preamble:
            yield {"token": "\n\n"}
        turn = yield from self._stream_turn(messages, tools=False, live=True)
        if not turn["content"].strip():
            # Thinking models sometimes put the whole reply in the reasoning
            # channel and leave the answer empty; ask once more, plainly.
            print("[RESEARCH] empty answer turn; asking again", flush=True)
            messages.append({"role": "user", "content": "Please write your answer to the person now, as plain text."})
            turn = yield from self._stream_turn(messages, tools=False, live=True)
        if not turn["content"].strip():
            turn["content"] = ("I gathered the passages but couldn't finish writing the answer. "
                               "Please ask again in a moment.")
            yield {"token": turn["content"]}
        yield from self._finish(self.preamble + turn["content"])

    def _prefetch(self, question: str) -> str:
        """The passages ordinary chat would have retrieved, attached up front so a
        conversational reply needs no extra tool round (deep questions still read on)."""
        if self.retriever is None or len(question.split()) < 3 or _URGENT_RE.search(question):
            return ""  # someone at risk gets the safety reply at once, not after a search
        try:
            hits = semantic_search(self.retriever, self.library, question, [], PREFETCH_PASSAGES,
                                   categories=self.categories, allowed=self._allowed_books())
        except Exception as exc:
            print(f"[RESEARCH] prefetch failed: {type(exc).__name__}: {exc}", flush=True)
            return ""
        lines = []
        for doc_id, b in hits:
            book = self.library.book(doc_id)
            if book is None:
                continue
            self._remember(book, b)
            sec = book.outline[b.section].title if b.section is not None else ""
            page = f"p.{b.page} " if b.page is not None else ""
            text = b.text if len(b.text) <= 700 else b.text[:700].rsplit(" ", 1)[0] + "…"
            lines.append(f"[{page}{b.id}] {book.info.title}" + (f", “{sec}”" if sec else "") + f": {text}")
        if not lines:
            return ""
        return ("\n\n[The app already found these passages for this message. Use them if they fit; quote only "
                "from these or from tool results. They may not be enough for a question that needs real reading.]\n"
                + "\n".join(lines))

    # ── model calls ─────────────────────────────────────────────────────

    def _body(self, priority: int, effort: str | None = None) -> dict[str, Any]:
        body = json.loads(json.dumps(self.extra_body or {}))
        kwargs = body.get("chat_template_kwargs")
        if effort and isinstance(kwargs, dict) and "reasoning_effort" in kwargs:
            kwargs["reasoning_effort"] = effort
        if self.use_priority:
            body["priority"] = priority
        return body

    def _stream_turn(self, messages: list[dict[str, Any]], tools: bool, live: bool = False,
                     optimistic: bool = False):
        """One streamed model turn. With ``live`` the content is the answer and streams as tokens."""
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages, "stream": True,
                                  "max_tokens": 6000 if live else 4000, "temperature": 0.6,
                                  "extra_body": self._body(PRIORITY_AGENT, AGENT_EFFORT)}
        # The final answer keeps the tool list (tool_choice "none") so the
        # prompt prefix is identical and the server's prefix cache is reused.
        kwargs["tools"] = TOOLS
        if not tools:
            kwargs["tool_choice"] = "none"
        stream = self.client.chat.completions.create(**kwargs)
        content: list[str] = []
        calls: dict[int, dict[str, str]] = {}
        in_think = False
        streaming = False
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            reasoning = getattr(delta, "reasoning", None) or getattr(delta, "reasoning_content", None)
            if reasoning:
                yield {"thinking": reasoning} if self.show_thinking else None
            text = delta.content or ""
            if text:
                # Some servers leave <think>…</think> inline.
                if "<think>" in text:
                    in_think = True
                    text = text.split("<think>", 1)[1]
                if in_think:
                    if "</think>" in text:
                        thought, text = text.split("</think>", 1)
                        in_think = False
                    else:
                        thought, text = text, ""
                    if thought:
                        yield {"thinking": thought} if self.show_thinking else None
                if text:
                    content.append(text)
                    if live:
                        yield {"token": text}
                    elif optimistic and not calls:
                        # A reply written straight away (no tool call so far):
                        # stream it instead of holding it until the turn ends.
                        if streaming:
                            yield {"token": text}
                        elif len("".join(content).strip()) >= OPTIMISTIC_CHARS:
                            streaming = True
                            yield {"research": {"type": "phase", "phase": "writing"}}
                            yield {"token": "".join(content).lstrip()}
            for tc in getattr(delta, "tool_calls", None) or []:
                slot = calls.setdefault(tc.index if tc.index is not None else len(calls),
                                        {"id": "", "name": "", "arguments": ""})
                if tc.id:
                    slot["id"] = tc.id
                fn = tc.function
                if fn is not None:
                    if fn.name:
                        slot["name"] += fn.name
                    if fn.arguments:
                        slot["arguments"] += fn.arguments
        tool_calls = [dict(c, id=c["id"] or f"call_{i}") for i, c in sorted(calls.items()) if c["name"]]
        return {"content": "".join(content), "tool_calls": tool_calls, "streamed": streaming}

    # ── tools ───────────────────────────────────────────────────────────

    def _step(self, tool: str, label: str) -> tuple[_Step, dict]:
        self.steps += 1
        step = _Step(self.steps, tool, label)
        return step, {"research": {"type": "step", "id": step.id, "tool": tool, "label": label, "status": "running"}}

    def _done(self, step: _Step, detail: str, ok: bool = True) -> dict:
        return {"research": {"type": "step", "id": step.id, "tool": step.tool, "label": step.label,
                             "status": "done" if ok else "error", "detail": detail}}

    def _run_tool(self, call: dict[str, str]):
        try:
            args = json.loads(call["arguments"] or "{}")
            if not isinstance(args, dict):
                raise ValueError("arguments must be an object")
        except Exception:
            return f"Error: could not parse arguments for {call['name']}; send valid JSON."
        handler = {
            "get_outline": self._t_outline,
            "read_section": self._t_read,
            "find_text": self._t_find,
            "search": self._t_search,
            "analyze_sections": self._t_analyze,
        }.get(call["name"])
        if handler is None:
            return f"Error: unknown tool {call['name']}."
        try:
            return (yield from handler(args))
        except Exception as exc:  # a tool bug must not end the research
            print(f"[RESEARCH] tool {call['name']} failed: {type(exc).__name__}: {exc}", flush=True)
            return f"Error: {call['name']} failed ({type(exc).__name__})."

    def _allowed_books(self) -> list[str]:
        cats = set(self.categories or [])
        return [d for d, info in self.library.catalog().items() if not cats or info.category in cats]

    def _book_or_error(self, name: Any) -> tuple[BookText | None, str]:
        doc_id = self.library.resolve_book(str(name or ""))
        book = self.library.book(doc_id) if doc_id else None
        if book is None:
            return None, f"Error: no book matches {name!r}. Use a book id from the catalog."
        self.consulted.add(book.info.doc_id)
        return book, ""

    def _t_outline(self, args: dict):
        book, err = self._book_or_error(args.get("book"))
        if book is None:
            return err
        step, ev = self._step("get_outline", f"Looking through the contents of {book.info.title}")
        yield ev
        yield self._done(step, f"{len(book.outline)} sections")
        return self.library.outline_text(book)

    def _t_read(self, args: dict):
        book, err = self._book_or_error(args.get("book"))
        if book is None:
            return err
        n = self.library.resolve_section(book, args.get("section"))
        if n is None:
            return f"Error: no section {args.get('section')!r} in {book.info.title}. Call get_outline."
        title = book.outline[n].title
        pages = self.library.section_pages(book, n)
        if self.heavy_gate is not None and not self.heavy_gate():
            return ("Deep reading is busy on the server right now. Answer from what you have, or use search and "
                    "find_text, and say the fuller research can be done in a few minutes.")
        if self.words_read >= TOTAL_READ_WORDS:
            return ("Reading budget used up. Work from what you have read, use find_text/search for "
                    "specifics, or call ready_to_answer.")
        step, ev = self._step("read_section", f"Reading “{title}” — {book.info.title}" + (f", {pages}" if pages else ""))
        yield ev
        text, shown, parts = self.library.read(book, n, READ_WORDS_PER_CALL, int(args.get("part") or 1))
        words = sum(len(b.text.split()) for b in shown)
        self.words_read += words
        for b in shown:
            self._remember(book, b)
        part = int(args.get("part") or 1)
        more = f" Part {part} of {parts}; call again with part={part + 1} to continue." if part < parts else ""
        yield self._done(step, f"{words:,} words" + (f" (part {part} of {parts})" if parts > 1 else ""))
        head = f"{book.info.title} — section [{n}] “{title}”" + (f" ({pages})" if pages else "") + f".{more}\n\n"
        return head + text

    def _t_find(self, args: dict):
        terms = _clean_terms(args.get("terms"))
        if not terms:
            return "Error: give at least one term."
        section = None
        if args.get("book"):
            book, err = self._book_or_error(args.get("book"))
            if book is None:
                return err
            doc_ids = [book.info.doc_id]
            if args.get("section") not in (None, ""):
                section = self.library.resolve_section(book, args.get("section"))
                if section is None:
                    return f"Error: no section {args.get('section')!r} in {book.info.title}."
            where = book.info.title + (f", “{book.outline[section].title}”" if section is not None else "")
        else:
            doc_ids = self._allowed_books()
            where = "the whole library"
        step, ev = self._step("find_text", f"Counting {', '.join(repr(t) for t in terms)} in {where}")
        yield ev
        res = self.library.find(terms, doc_ids, section)
        lines = [f"Exact matches in {where} (case-insensitive):"]
        for t in res["terms"]:
            lines.append(f"- {t}: {res['totals'].get(t, 0)}")
        if res["by_scope"]:
            lines.append("\nBy " + ("section" if len(doc_ids) == 1 else "book") + ":")
            for scope, counts in sorted(res["by_scope"].items(), key=lambda kv: -sum(kv[1].values()))[:60]:
                lines.append(f"- {scope}: " + ", ".join(f"{t} {n}" for t, n in counts.items()))
        if res["quotes"]:
            lines.append("\nWhere they occur:")
            for q in res["quotes"]:
                b: Block = q["block"]
                book = self.library.book(q["doc_id"])
                if book is not None:
                    self._remember(book, b)
                sec = book.outline[b.section].title if book and b.section is not None else ""
                page = f"p.{b.page} " if b.page is not None else ""
                lines.append(f"[{page}{b.id}] {book.info.title if book else ''}" + (f", “{sec}”" if sec else "")
                             + f": {q['quote']}")
            total_hits = sum(res["totals"].values())
            if total_hits > len(res["quotes"]):
                lines.append(f"(showing {len(res['quotes'])} of {total_hits} occurrences)")
        total = sum(res["totals"].values())
        yield self._done(step, f"{total:,} match{'es' if total != 1 else ''}")
        return "\n".join(lines)

    def _t_search(self, args: dict):
        query = str(args.get("query") or "").strip()
        if not query:
            return "Error: empty query."
        limit = max(1, min(int(args.get("limit") or 8), 15))
        doc_ids: list[str]
        if args.get("book"):
            book, err = self._book_or_error(args.get("book"))
            if book is None:
                return err
            doc_ids = [book.info.doc_id]
            where = book.info.title
        else:
            doc_ids = []
            where = "the library"
        step, ev = self._step("search", f"Searching {where} for “{query}”")
        yield ev
        hits = semantic_search(self.retriever, self.library, query, doc_ids, limit,
                               categories=None if doc_ids else self.categories,
                               allowed=None if doc_ids else self._allowed_books())
        lines = [f"Passages about “{query}” in {where}:"]
        for doc_id, b in hits:
            book = self.library.book(doc_id)
            if book is None:
                continue
            self._remember(book, b)
            sec = book.outline[b.section].title if b.section is not None else ""
            page = f"p.{b.page} " if b.page is not None else ""
            lines.append(f"\n[{page}{b.id}] {book.info.title}" + (f", “{sec}”" if sec else "") + f"\n{b.text}")
        yield self._done(step, f"{len(hits)} passages")
        return "\n".join(lines) if hits else f"No passages found for “{query}” in {where}."

    def _t_analyze(self, args: dict):
        book, err = self._book_or_error(args.get("book"))
        if book is None:
            return err
        task = str(args.get("task") or "").strip()
        if not task:
            return "Error: give the task each reader should carry out."
        raw = args.get("sections") or []
        if isinstance(raw, (int, str)):
            raw = [raw]
        idx: list[int] = []
        for r in raw:
            n = self.library.resolve_section(book, r)
            if n is not None and n not in idx:
                idx.append(n)
        idx = idx[:ANALYZE_MAX_SECTIONS]
        if not idx:
            return f"Error: no valid sections. Call get_outline for {book.info.title}."
        if self.heavy_gate is not None and not self.heavy_gate():
            return ("Deep reading is busy on the server right now. Answer from what you have, or use search and "
                    "find_text, and say the fuller research can be done in a few minutes.")

        step, ev = self._step("analyze_sections", f"Reading {len(idx)} section{'s' if len(idx) != 1 else ''} of "
                                                  f"{book.info.title} in parallel")
        yield ev
        results: dict[int, str] = {}
        with ThreadPoolExecutor(max_workers=max(1, ANALYZE_CONCURRENCY)) as pool:
            futures = {pool.submit(self._analyze_one, book, n, task): n for n in idx}
            pending = set(futures)
            while pending:
                done, pending = wait(pending, timeout=5.0, return_when=FIRST_COMPLETED)
                if not done:
                    yield None  # keepalive while the readers work
                for f in done:
                    n = futures[f]
                    try:
                        results[n] = f.result()
                    except Exception as exc:
                        results[n] = f"(could not read this section: {type(exc).__name__})"
                    yield {"research": {"type": "step", "id": step.id, "tool": step.tool, "label": step.label,
                                        "status": "running", "progress": [len(results), len(idx)]}}
        yield self._done(step, f"{len(idx)} sections read")
        out = [f"Findings from {book.info.title} for: {task}"]
        for n in idx:
            pages = self.library.section_pages(book, n)
            out.append(f"\n### [{n}] {book.outline[n].title}" + (f" ({pages})" if pages else "") + f"\n{results[n]}")
        return "\n".join(out)

    def _analyze_one(self, book: BookText, n: int, task: str) -> str:
        text, shown, parts = self.library.read(book, n, 14000)
        if parts > 1:
            text += "\n(This section continues; only its first part was read.)"
        prompt = _ANALYZE_USER.format(task=task, book=book.info.title, section=book.outline[n].title,
                                      pages=self.library.section_pages(book, n) or "pages unknown", text=text)
        resp = self.client.chat.completions.create(
            model=self.model, max_tokens=2500, temperature=0.3,
            messages=[{"role": "system", "content": _ANALYZE_SYSTEM}, {"role": "user", "content": prompt}],
            extra_body=self._body(PRIORITY_ANALYZE, "low"),
        )
        reply = (resp.choices[0].message.content or "").split("</think>")[-1].strip()
        return self._verify_findings(book, shown, reply)

    def _verify_findings(self, book: BookText, shown: list[Block], reply: str) -> str:
        """Keep findings whose quote really is in the section; record them as evidence."""
        by_id = {b.id: b for b in shown}
        lines = []
        for line in reply.splitlines():
            m = _FINDING_RE.match(line)
            if not m:
                if line.strip() and not line.strip().startswith("- ["):
                    lines.append(line)
                continue
            _page, bid, quote, note = m.groups()
            block = by_id.get(bid)
            target = _tight(re.split(r"…|\.\.\.", quote)[0])[:50]
            if len(target) < 8:
                continue
            if block is None or not _contains(_tight(block.text), target):
                block = next((b for b in shown if _contains(_tight(b.text), target)), None)
            if block is None:
                continue  # misquoted or invented — drop it
            self._remember(book, block)
            page = f"p.{block.page} " if block.page is not None else ""
            lines.append(f"- [{page}{block.id}] “{quote.strip()}” — {note.strip()}".rstrip(" —"))
        return "\n".join(lines).strip() or "SUMMARY: Nothing relevant.\nFINDINGS:\n- none"

    # ── sources ─────────────────────────────────────────────────────────

    def _remember(self, book: BookText, b: Block) -> None:
        key = (book.info.doc_id, b.id)
        if key not in self.evidence:
            self.evidence[key] = Evidence(book.info.doc_id, book.info.title, book.info.source_file, b)

    def _finish(self, answer: str):
        sources = self.sources_for(answer)
        if sources:
            yield {"sources": sources}
        check = self.verify(answer)
        if check["quotes"] or check["pages"]:
            yield {"research": {"type": "verification", **check}}

    def verify(self, answer: str) -> dict[str, Any]:
        """Check the answer's quotes and page citations against the text.

        A quote counts as verified if it appears in any passage the research
        saw, or anywhere in a book it consulted (quotes may come from a reader's
        findings). A page citation is verified when the research saw that page.
        """
        consulted = sorted({e.doc_id for e in self.evidence.values()} | self.consulted)
        corpus = [_tight(e.block.text) for e in self.evidence.values()]
        books_text: list[str] | None = None
        quotes = unverified = 0
        missing: list[str] = []
        asked = _tight(self.question)
        for m in _QUOTE_IN_ANSWER_RE.finditer(answer):
            raw = m.group(1)
            if len(raw.split()) < 4:
                continue
            if _tight(raw) and _tight(raw) in asked:
                continue  # the phrase the person asked about, not a citation
            quotes += 1
            parts = [p for p in (_tight(x) for x in re.split(r"…|\.\.\.|\[|\]", raw)) if len(p) >= 12]
            if not parts:
                continue
            def found(hay: list[str]) -> bool:
                return all(any(_contains(h, p) for h in hay) for p in parts)
            if found(corpus):
                continue
            if books_text is None:
                books_text = []
                for doc_id in consulted:
                    book = self.library.book(doc_id)
                    if book is not None:
                        books_text.append(_tight(" ".join(b.text for b in book.blocks)))
            if not found(books_text):
                unverified += 1
                missing.append(raw[:120])
        seen_pages = {str(e.block.page).lower() for e in self.evidence.values() if e.block.page is not None}
        pages = bad_pages = 0
        for m in re.finditer(r"\b(?:p\.|page)\s*([0-9ivxlc]{1,5})\b", answer, re.IGNORECASE):
            pages += 1
            if m.group(1).lower() not in seen_pages:
                bad_pages += 1
        for m in re.finditer(r"\b(?:pp\.|pages)\s*([0-9]{1,4})\s*[–-]\s*([0-9]{1,4})", answer, re.IGNORECASE):
            pages += 1
            a, z = int(m.group(1)), int(m.group(2))
            if not any(str(p) in seen_pages for p in range(a, z + 1)):
                bad_pages += 1
        return {"quotes": quotes, "quotes_verified": quotes - unverified, "unverified_quotes": missing[:5],
                "pages": pages, "pages_verified": pages - bad_pages}

    def sources_for(self, answer: str) -> list[dict[str, Any]]:
        """The passages the answer quotes or cites, in the order it mentions them."""
        picked: list[tuple[int, Evidence]] = []
        seen: set[tuple[str, str]] = set()
        squashed = {k: _tight(e.block.text) for k, e in self.evidence.items()}
        for m in _QUOTE_IN_ANSWER_RE.finditer(answer):
            q = _tight(re.split(r"…|\.\.\.", m.group(1))[0])
            probe = q[:40]
            if len(probe) < 15:
                continue
            for k, s in squashed.items():
                if _contains(s, probe) and k not in seen:
                    seen.add(k)
                    picked.append((m.start(), self.evidence[k]))
                    break
        # Page citations: "(Big Book, p. 67)" / "page 67" → evidence on that page,
        # preferring the book named just before it.
        for m in re.finditer(r"\b(?:p\.|pp\.|page|pages)\s*([0-9ivxlc]{1,5})\b", answer, re.IGNORECASE):
            page = m.group(1).lower()
            window = _squash(answer[max(0, m.start() - 90):m.start()])
            cands = [(k, e) for k, e in self.evidence.items() if str(e.block.page).lower() == page and k not in seen]
            if not cands:
                continue
            named = [(k, e) for k, e in cands if _book_named(window, e)]
            k, e = (named or cands)[0]
            seen.add(k)
            picked.append((m.start(), e))
        picked.sort(key=lambda x: x[0])
        out = []
        for _, e in picked[:MAX_SOURCES]:
            out.append(_source_payload(e))
        return out


def semantic_search(retriever: Any, library: Library, query: str, doc_ids: list[str], limit: int,
                    categories: list[str] | None = None, allowed: list[str] | None = None) -> list[tuple[str, Block]]:
    """Vector + keyword search mapped onto manifest blocks; manifest keyword search if the index is unavailable."""
    hits: list[tuple[str, Block]] = []
    seen: set[tuple[str, str]] = set()

    def add(doc_id: str | None, block_ids: Any, text: str) -> None:
        if not doc_id:
            return
        book = library.book(doc_id)
        if book is None:
            return
        ids = block_ids
        if isinstance(ids, str):
            try:
                ids = json.loads(ids)
            except Exception:
                ids = []
        block = None
        for bid in ids or []:
            n = book.by_id.get(bid)
            if n is not None and book.blocks[n].kind == "p":
                block = book.blocks[n]
                break
        if block is None:  # index built against an older extraction: match by text
            probe = _squash(text)[20:80]
            block = next((b for b in book.blocks if b.kind == "p" and probe and probe in _squash(b.text)), None)
        if block is None or (doc_id, block.id) in seen:
            return
        seen.add((doc_id, block.id))
        hits.append((doc_id, block))

    if retriever is not None:
        try:
            if len(doc_ids) == 1:
                from src.rag.embeddings import embed_query
                res = retriever.collection.query(
                    query_embeddings=[embed_query(query)], n_results=limit * 3,
                    where={"$and": [{"doc_id": doc_ids[0]}, {"scale": "medium"}]},
                    include=["documents", "metadatas"])
                for doc, meta in zip(res.get("documents", [[]])[0], res.get("metadatas", [[]])[0]):
                    add((meta or {}).get("doc_id"), (meta or {}).get("block_ids"), doc or "")
                    if len(hits) >= limit:
                        break
            else:
                for r in retriever.retrieve(query, top_k=limit, categories=categories):
                    add(r.doc_id, r.block_ids, r.text)
        except Exception as exc:
            print(f"[RESEARCH] vector search failed, using keyword search: {type(exc).__name__}: {exc}", flush=True)
    if len(hits) < limit:
        for doc_id, b, _score in library.keyword_search(query, doc_ids or allowed or list(library.catalog()), limit * 2):
            if (doc_id, b.id) not in seen:
                seen.add((doc_id, b.id))
                hits.append((doc_id, b))
            if len(hits) >= limit:
                break
    return hits[:limit]


def _source_payload(e: Evidence) -> dict[str, Any]:
    rel = e.source_file
    if rel.startswith("documents/"):
        rel = rel[len("documents/"):]
    excerpt = e.block.text if len(e.block.text) <= 600 else e.block.text[:600].rsplit(" ", 1)[0] + "…"
    return {
        "source": os.path.basename(e.source_file) or e.title,
        "similarity": 0,
        # One chip per passage: the fragment keeps passages of one book apart.
        "url": f"/api/documents/{rel}#{e.block.id}",
        "excerpt": excerpt,
        "doc_id": e.doc_id,
        "block_ids": [e.block.id],
        "page": e.block.page,
    }


def _book_named(window: str, e: Evidence) -> bool:
    from src.research.library import ALIASES
    names = [e.title, *ALIASES.get(e.doc_id, [])]
    return any(_squash(n)[:14] in window for n in names if n)


def _clean_terms(raw: Any) -> list[str]:
    """Search terms as plain strings — models sometimes send '["a", "b"]' or 'a|b' inside one string."""
    items = raw if isinstance(raw, list) else [raw]
    out: list[str] = []
    for item in items:
        if item is None:
            continue
        text = str(item).strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    out.extend(_clean_terms(parsed))
                    continue
            except Exception:
                pass
        for piece in re.split(r"\s*\|\s*", text):
            piece = piece.strip(" []\"'“”,")
            if piece and piece not in out:
                out.append(piece)
    return out[:8]


def _tight(text: str) -> str:
    """Letters and digits only — immune to extraction artifacts like "sacrifi ce"."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _contains(hay: str, needle: str) -> bool:
    # A drop cap leaves the first letter elsewhere: "RACTICAL EXPERIENCE shows…".
    return needle in hay or (len(needle) > 12 and needle[1:] in hay)


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower().replace("’", "'").replace("'", "")).strip()


def _chunks(text: str, size: int = 24) -> Iterator[str]:
    words = re.split(r"(\s+)", text)
    buf = ""
    for w in words:
        buf += w
        if len(buf) >= size:
            yield buf
            buf = ""
    if buf:
        yield buf
