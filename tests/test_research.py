"""Research mode: library tools on the real manifests + the agent loop against a scripted fake LLM."""

import json
import os
from types import SimpleNamespace

import pytest

from src.research.agent import ResearchSession, _clean_terms
from src.research.library import Library

DOCS = os.path.join(os.path.dirname(__file__), "..", "documents")
BIG_BOOK = "alcoholics-anonymous"

pytestmark = pytest.mark.skipif(not os.path.isfile(os.path.join(DOCS, ".manifests", f"{BIG_BOOK}.json")),
                                reason="manifests not present")


@pytest.fixture(scope="module")
def lib():
    return Library(DOCS)


# ── library ──────────────────────────────────────────────────────────────


def test_resolves_common_names(lib):
    assert lib.resolve_book("Big Book") == BIG_BOOK
    assert lib.resolve_book("the big book") == BIG_BOOK
    assert lib.resolve_book("12&12") == "twelve-steps-and-twelve-traditions"
    assert lib.resolve_book("Twelve and Twelve") == "twelve-steps-and-twelve-traditions"
    assert lib.resolve_book("Living Sober") == "living-sober"
    assert lib.resolve_book("no such book anywhere") is None


def test_excluded_duplicates_are_not_in_catalog(lib):
    cat = lib.catalog()
    assert "trimmed-big-book" not in cat
    assert BIG_BOOK in cat


def test_read_section_has_page_and_block_markers(lib):
    bb = lib.book(BIG_BOOK)
    n = lib.resolve_section(bb, "How It Works")
    text, shown, parts = lib.read(bb, n, 20000)
    assert parts == 1
    assert "[p.58 " in text
    assert "rarely have we seen a person fail" in text.lower()  # drop cap "R" rejoined
    assert "God, I offer myself to Thee" in text  # the Third Step prayer, p. 63


def test_ligature_splits_are_repaired(lib):
    tt = lib.book("twelve-steps-and-twelve-traditions")
    n = lib.resolve_section(tt, "Tradition Twelve")
    text, _, _ = lib.read(tt, n, 20000)
    assert "THE spiritual substance of anonymity is sacrifice." in text


def test_find_counts_exactly(lib):
    bb = lib.book(BIG_BOOK)
    into_action = lib.resolve_section(bb, "Into Action")
    res = lib.find(["pray*"], [BIG_BOOK], into_action)
    assert res["totals"]["pray*"] == 7
    assert any("defect of character" in q["quote"] for q in res["quotes"])


# ── agent loop with a fake model ─────────────────────────────────────────


def _delta(content=None, tool_calls=None, reasoning=None):
    return SimpleNamespace(choices=[SimpleNamespace(
        delta=SimpleNamespace(content=content, tool_calls=tool_calls, reasoning=reasoning),
        finish_reason=None)])


def _call(i, name, args):
    return SimpleNamespace(index=i, id=f"c{i}", function=SimpleNamespace(name=name, arguments=json.dumps(args)))


class FakeLLM:
    """Plays back scripted turns: lists of stream deltas for streamed calls, text for analyze calls."""

    def __init__(self, turns, analyze_reply=""):
        self.turns = list(turns)
        self.analyze_reply = analyze_reply
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.requests.append(kw)
        if kw.get("stream"):
            return iter(self.turns.pop(0))
        msg = SimpleNamespace(content=self.analyze_reply)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _run(session, question="q"):
    events = [e for e in session.run(question, [], "SYSTEM") if e is not None]
    answer = "".join(e["token"] for e in events if "token" in e)
    return events, answer


def test_agent_reads_then_answers_with_verified_sources(lib):
    llm = FakeLLM([
        [_delta(tool_calls=[_call(0, "read_section", {"book": "Big Book", "section": "How It Works"})])],
        [_delta(tool_calls=[_call(0, "ready_to_answer", {"plan": "quote the prayer"})])],
        [_delta(content="The Third Step prayer begins “God, I offer myself to Thee—to build with me” "),
         _delta(content="(Big Book, p. 63).")],
    ])
    s = ResearchSession(client=llm, model="m", library=lib, extra_body={})
    events, answer = _run(s)
    steps = [e["research"] for e in events if "research" in e and e["research"]["type"] == "step"]
    assert steps[0]["tool"] == "read_section" and steps[-1]["status"] == "done"
    assert "God, I offer myself to Thee" in answer
    sources = next(e["sources"] for e in events if "sources" in e)
    assert sources[0]["doc_id"] == BIG_BOOK and sources[0]["page"] == 63
    check = next(e["research"] for e in events if e.get("research", {}).get("type") == "verification")
    assert check["quotes"] == 1 and check["quotes_verified"] == 1
    assert check["pages_verified"] == check["pages"] == 1
    # The final turn keeps the tool list but may not call tools (prefix cache reuse).
    assert llm.requests[-1]["tool_choice"] == "none" and llm.requests[-1]["tools"]


def test_agent_flags_invented_quotes(lib):
    llm = FakeLLM([
        [_delta(tool_calls=[_call(0, "ready_to_answer", {"plan": "x"})])],
        [_delta(content="The book says “courage is the antidote to every resentment we hold” (p. 999).")],
    ])
    s = ResearchSession(client=llm, model="m", library=lib, extra_body={})
    events, _ = _run(s)
    check = next(e["research"] for e in events if e.get("research", {}).get("type") == "verification")
    assert check["quotes_verified"] == 0 and check["pages_verified"] == 0


def test_direct_reply_without_tools_is_streamed(lib):
    llm = FakeLLM([[_delta(content="You're welcome — glad it helped.")]])
    s = ResearchSession(client=llm, model="m", library=lib, extra_body={})
    _, answer = _run(s)
    assert answer == "You're welcome — glad it helped."


def test_analyze_keeps_only_real_quotes(lib):
    bb = lib.book(BIG_BOOK)
    n = lib.resolve_section(bb, "Into Action")
    first_para = next(b for b in bb.blocks if b.section == n and b.kind == "p" and len(b.text) > 80)
    real = first_para.text[:70]
    reply = ("SUMMARY: test\nFINDINGS:\n"
             f"- [p.{first_para.page} {first_para.id}] \"{real}\" — real\n"
             f"- [p.76 {first_para.id}] \"This sentence does not occur anywhere in the book at all\" — invented\n")
    llm = FakeLLM([
        [_delta(tool_calls=[_call(0, "analyze_sections", {"book": BIG_BOOK, "sections": [n], "task": "t"})])],
        [_delta(content="Done.")],
    ], analyze_reply=reply)
    s = ResearchSession(client=llm, model="m", library=lib, extra_body={})
    out = []
    gen = s._run_tool({"id": "c0", "name": "analyze_sections",
                       "arguments": json.dumps({"book": BIG_BOOK, "sections": [n], "task": "t"})})
    try:
        while True:
            out.append(next(gen))
    except StopIteration as stop:
        result = stop.value
    assert real[:40] in result
    assert "does not occur anywhere" not in result


def test_priority_and_effort_are_sent(lib):
    llm = FakeLLM([[_delta(content="hi")]])
    s = ResearchSession(client=llm, model="m", library=lib,
                        extra_body={"chat_template_kwargs": {"thinking": True, "reasoning_effort": "low"}})
    _run(s)
    body = llm.requests[0]["extra_body"]
    assert body["priority"] > 0
    assert body["chat_template_kwargs"]["reasoning_effort"] == "low"


def test_clean_terms():
    assert _clean_terms(["oh god", "| lord| jesus]"]) == ["oh god", "lord", "jesus"]
    assert _clean_terms('["a", "b"]') == ["a", "b"]


def test_embedded_running_headers_are_stripped(lib):
    bb = lib.book(BIG_BOOK)
    text = bb.blocks[bb.by_id["b00229"]].text
    assert "which comes at once by taking a few drinks" in text
    assert "OPINION xxix" not in text


def test_phrases_from_the_question_are_not_citations(lib):
    llm = FakeLLM([
        [_delta(tool_calls=[_call(0, "find_text", {"terms": ["fake it till you make it"], "book": "Big Book"})])],
        [_delta(tool_calls=[_call(0, "ready_to_answer", {"plan": "no"})])],
        [_delta(content="No — “fake it till you make it” does not appear in the Big Book.")],
    ])
    s = ResearchSession(client=llm, model="m", library=lib, extra_body={})
    events = [e for e in s.run("Is “fake it till you make it” in the Big Book?", [], "SYSTEM") if e is not None]
    checks = [e["research"] for e in events if e.get("research", {}).get("type") == "verification"]
    assert not checks or checks[0]["quotes"] == 0


def test_empty_answer_turn_is_retried(lib):
    llm = FakeLLM([
        [_delta(tool_calls=[_call(0, "ready_to_answer", {"plan": "x"})])],
        [_delta(reasoning="the whole answer ended up in here")],  # empty answer
        [_delta(content="Into Action, p. 76.")],
    ])
    s = ResearchSession(client=llm, model="m", library=lib, extra_body={})
    _, answer = _run(s)
    assert answer == "Into Action, p. 76."


def test_quotes_are_checked_against_books_searched_without_hits(lib):
    llm = FakeLLM([
        [_delta(tool_calls=[_call(0, "find_text", {"terms": ["fake it till you make it"], "book": "Big Book"})])],
        [_delta(tool_calls=[_call(0, "ready_to_answer", {"plan": "no"})])],
        [_delta(content="No. The book's own line is “Half measures availed us nothing” (p. 59).")],
    ])
    s = ResearchSession(client=llm, model="m", library=lib, extra_body={})
    events = [e for e in s.run("Is “fake it till you make it” in the Big Book?", [], "SYSTEM") if e is not None]
    check = next(e["research"] for e in events if e.get("research", {}).get("type") == "verification")
    assert check["quotes"] == 1 and check["quotes_verified"] == 1


def test_direct_replies_stream_and_preambles_are_kept(lib):
    long_reply = "That sounds really hard, and it makes sense that today feels heavy for you."
    llm = FakeLLM([[_delta(content=long_reply[:30]), _delta(content=long_reply[30:50]),
                    _delta(content=long_reply[50:])]])
    s = ResearchSession(client=llm, model="m", library=lib, extra_body={})
    events, answer = _run(s)
    assert answer == long_reply
    assert sum(1 for e in events if "token" in e) == 2, "streamed as it arrived, not re-chunked"

    llm = FakeLLM([
        [_delta(content="Let me look at what the Big Book says about that for you."),
         _delta(tool_calls=[_call(0, "ready_to_answer", {"kind": "reply", "plan": "x"})])],
        [_delta(content="Here it is.")],
    ])
    s = ResearchSession(client=llm, model="m", library=lib, extra_body={})
    _, answer = _run(s)
    assert answer == "Let me look at what the Big Book says about that for you.\n\nHere it is."
