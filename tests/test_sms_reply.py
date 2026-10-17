"""Tests for POST /api/sms conversational replies: newcomer brevity and the
one-time first-contact STOP/HELP disclosure.

Reuses test_distill_endpoint's offline stubs (fake chromadb, LLM_API_KEY) and
drives the REAL webhook with a fake engine and an in-memory Redis.

Run:  python3 -m pytest tests/test_sms_reply.py -q
"""

import html
import re

import pytest

import tests.test_distill_endpoint  # noqa: F401  (stubs chromadb before src.server)
import src.server as server
from fastapi.testclient import TestClient

PHONE = "+15555550123"


class _Engine:
    def __init__(self, response: str = "Call your sponsor tonight."):
        self.response = response
        self.system_messages: list[str] = []

    def generate(self, prompt, history=None, max_tokens=4096, system_message=None, enable_thinking=None):  # noqa: ANN001
        self.system_messages.append(system_message or "")
        return self.response


class _Redis:
    def __init__(self):
        self.data: dict[str, str] = {}

    def get(self, key):
        return self.data.get(key)

    def setex(self, key, ttl, value):
        self.data[key] = value

    def incr(self, key):
        self.data[key] = str(int(self.data.get(key, 0)) + 1)
        return int(self.data[key])

    def expire(self, key, ttl):
        return True

    def delete(self, key):
        self.data.pop(key, None)


@pytest.fixture()
def env(monkeypatch):
    engine = _Engine()
    redis = _Redis()
    monkeypatch.setattr(server, "engine", engine)
    monkeypatch.setattr(server, "engine_fallback", None)
    monkeypatch.setattr(server, "get_redis_client", lambda: redis)
    monkeypatch.setattr(server, "_safe_get_retriever", lambda: None)
    monkeypatch.setattr(server, "get_subscriber", lambda phone: None)
    return TestClient(server.app), engine, redis


def _text(client, body: str) -> str:
    resp = client.post("/api/sms", data={"From": PHONE, "Body": body})
    assert resp.status_code == 200
    return html.unescape(re.search(r"<Message>(.*)</Message>", resp.text, re.S).group(1))


def test_first_reply_identifies_program_and_offers_stop(env):
    client, engine, _ = env
    reply = _text(client, "hi, is this the recovery bot?")
    assert reply.startswith("Sobriety Copilot: Call your sponsor tonight.")
    assert reply.endswith("Reply STOP to opt out or HELP for help. Msg & data rates may apply.")
    assert "new to texting" in engine.system_messages[-1]


def test_disclosure_only_once_and_not_in_history(env):
    client, _, redis = env
    _text(client, "first")
    reply = _text(client, "second")
    assert reply == "Call your sponsor tonight."
    history = redis.data[f"sc:sms:history:{PHONE}"]
    assert "Reply STOP" not in history


def test_brief_for_newcomers_then_adaptive(env):
    client, engine, _ = env
    for _ in range(server._SMS_NEWCOMER_EXCHANGES):
        _text(client, "question")
        assert "new to texting" in engine.system_messages[-1]
    _text(client, "question")
    assert "new to texting" not in engine.system_messages[-1]
    assert "Match the reply length" in engine.system_messages[-1]


def test_newcomer_count_survives_new_reset(env):
    client, engine, _ = env
    for _ in range(server._SMS_NEWCOMER_EXCHANGES):
        _text(client, "question")
    _text(client, "NEW")
    reply = _text(client, "question")
    assert "Reply STOP" not in reply
    assert "new to texting" not in engine.system_messages[-1]


def test_opted_in_subscriber_gets_no_disclosure(env, monkeypatch):
    client, engine, _ = env
    monkeypatch.setattr(server, "get_subscriber", lambda phone: {"enabled": True})
    reply = _text(client, "hello")
    assert reply == "Call your sponsor tonight."
    assert "new to texting" in engine.system_messages[-1]


def test_long_first_reply_still_fits_one_twilio_message(env):
    client, engine, _ = env
    engine.response = "The Big Book says acceptance is the answer. " * 60
    reply = _text(client, "list all twelve steps")
    assert len(reply) <= 1480
    assert reply.endswith("Msg & data rates may apply.")
