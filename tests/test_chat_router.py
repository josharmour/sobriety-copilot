"""Which engine answers a message: the fast classic reply or the research agent."""

import os

import pytest

pytest.importorskip("fastapi")
os.environ.setdefault("LLM_API_KEY", "test")

from src import server  # noqa: E402

CLASSIC = ["hi", "thanks so much", "I'm having a rough day", "I feel so alone tonight", "I want to drink right now",
           "I'm really struggling with resentment toward my mom today."]
RESEARCH = ["What's the difference between Step 6 and Step 7?", "how many prayers are in each chapter of the big book",
            "is let go and let god in the big book?", "what does the literature say about fear",
            "who was Ebby Thatcher?", "my sponsor says I need to do my 4th step and I'm scared",
            "I have 30 days sober and I'm scared I'm going to relapse at my sister's wedding this weekend.",
            "What's serenity?", "waht's serentiy", "how do I pray"]


@pytest.mark.parametrize("message", CLASSIC)
def test_conversation_takes_the_fast_path(message):
    assert not server._wants_research(message)


@pytest.mark.parametrize("message", RESEARCH)
def test_literature_and_longer_messages_go_to_the_agent(message):
    assert server._wants_research(message)


def test_agent_router_sends_everything(monkeypatch):
    monkeypatch.setattr(server, "CHAT_ROUTER", "agent")
    assert server._wants_research("hi")


def test_chat_engine_switch(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "research", lambda p, r: calls.append("research"))
    monkeypatch.setattr(server, "_classic_chat", lambda p, r: calls.append("classic"))
    payload = server.ChatRequest(message="hi")
    monkeypatch.setattr(server, "CHAT_ENGINE", "classic")
    server.chat(payload, None)
    monkeypatch.setattr(server, "CHAT_ENGINE", "research")
    server.chat(payload, None)
    assert calls == ["classic", "research"]
