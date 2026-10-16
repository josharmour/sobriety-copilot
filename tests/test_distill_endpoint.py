"""Tests for POST /api/distill — the FR11 memory-distillation passthrough.

Builds a FastAPI TestClient against the REAL src.server app with heavy deps
stubbed the way the rest of this repo's offline tests do:

- chromadb is faked in sys.modules BEFORE importing src.server (the RAG stack
  imports it eagerly; the 1.3.0 cleanup removed the ontology/concepts/deepdive
  stack, so this is the only heavy blocker left).
- LLM_API_KEY is set so the module-level InferenceEngine can construct its
  OpenAI client (never called in tests).
- The shared engine is monkeypatched to a controllable fake (no network).
- get_redis_client is monkeypatched to a spy to prove the endpoint performs
  ZERO writes (nothing touches disk/DB/Redis).

Run:  python3 -m pytest tests/test_distill_endpoint.py -q
"""

import os
import sys
import types

os.environ.setdefault("LLM_API_KEY", "test")  # OpenAI client construction only


def _stub_chromadb() -> None:
    """Pre-seed sys.modules with a dummy chromadb package so src.rag modules
    import without the real (heavy, optional) dependency."""
    m = types.ModuleType("chromadb")
    m.__version__ = "0.0.0"
    m.__path__ = []
    cfg = types.ModuleType("chromadb.config")
    cfg.Settings = object
    api = types.ModuleType("chromadb.api")
    api.__path__ = []
    client_mod = types.ModuleType("chromadb.api.client")
    client_mod.Client = object
    ep = types.ModuleType("chromadb.api.types")
    utils = types.ModuleType("chromadb.utils")
    utils.__path__ = []
    ef = types.ModuleType("chromadb.utils.embedding_functions")
    ef.DefaultEmbeddingFunction = object
    sys.modules.update(
        {
            "chromadb": m,
            "chromadb.config": cfg,
            "chromadb.api": api,
            "chromadb.api.client": client_mod,
            "chromadb.api.types": ep,
            "chromadb.utils": utils,
            "chromadb.utils.embedding_functions": ef,
        }
    )


_stub_chromadb()

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import src.server as server  # noqa: E402

CANNED_RESPONSE = (
    '{"new_facts":["Prefers evening meetings over morning ones"],'
    '"threads":[{"id":"step-8-amends","title":"Step 8 amends list",'
    '"detail":"Working out who to write to","resolved":false}]}'
)


class _FakeEngine:
    """Controllable stand-in for the shared InferenceEngine."""

    def __init__(self, response: str = CANNED_RESPONSE, error: Exception | None = None):
        self.response = response
        self.error = error
        self.prompts: list[str] = []
        self.calls = 0

    def generate(self, prompt, history=None, max_tokens=4096, system_message=None, enable_thinking=None):  # noqa: ANN001
        self.calls += 1
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return self.response


class _RedisSpy:
    """Records every write-ish call made against the job-store Redis client."""

    def __init__(self):
        self.writes: list[tuple[str, tuple]] = []

    def set(self, *a, **k):
        self.writes.append(("set", a))
        return True

    def setex(self, *a, **k):
        self.writes.append(("setex", a))
        return True

    def lpush(self, *a, **k):
        self.writes.append(("lpush", a))
        return True

    def rpush(self, *a, **k):
        self.writes.append(("rpush", a))
        return True

    def delete(self, *a, **k):
        self.writes.append(("delete", a))
        return True

    def setnx(self, *a, **k):
        self.writes.append(("setnx", a))
        return True

    def hset(self, *a, **k):
        self.writes.append(("hset", a))
        return True

    def get(self, *a, **k):
        return None

    def expire(self, *a, **k):
        self.writes.append(("expire", a))
        return True


@pytest.fixture()
def env(monkeypatch):
    engine = _FakeEngine()
    monkeypatch.setattr(server, "engine", engine)
    spy = _RedisSpy()
    monkeypatch.setattr(server, "get_redis_client", lambda: spy)
    client = TestClient(server.app)
    return client, engine, spy


def _turn(role: str, content: str) -> dict[str, str]:
    return {"role": role, "content": content}


def _transcript(n: int) -> list[dict[str, str]]:
    return [
        _turn("user" if i % 2 == 1 else "assistant", f"msg-{i:02d}-content")
        for i in range(1, n + 1)
    ]


def test_valid_transcript_returns_parsed_json(env):
    client, engine, _ = env
    res = client.post(
        "/api/distill",
        json={
            "transcript": _transcript(4),
            "existing": {"facts": ["Known fact"], "threads": ["Old thread"]},
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["new_facts"] == ["Prefers evening meetings over morning ones"]
    assert body["threads"] == [
        {
            "id": "step-8-amends",
            "title": "Step 8 amends list",
            "detail": "Working out who to write to",
            "resolved": False,
        }
    ]
    # The engine got exactly one prompt built from the same instruction the
    # Flutter distiller uses, with the digest folded in for dedupe.
    assert engine.calls == 1
    prompt = engine.prompts[0]
    assert "You are reading the last 12 turns" in prompt
    assert "Existing memory — facts: [Known fact]" in prompt
    assert "Existing memory — open threads: [Old thread]" in prompt
    assert "Conversation (last 4 turns):" in prompt
    assert "User: msg-01-content" in prompt
    assert "Assistant: msg-02-content" in prompt


def test_suggest_mode_uses_single_fact_instruction(env):
    client, engine, _ = env
    res = client.post(
        "/api/distill",
        json={
            "transcript": _transcript(6),
            "suggest_mode": True,
            "existing": {"facts": ["Got sober on September 21, 2001"]},
        },
    )
    assert res.status_code == 200, res.text
    prompt = engine.prompts[0]
    # The suggest-mode instruction replaces the standard distill instruction.
    assert "propose the SINGLE fact" in prompt
    assert "You are reading the last 12 turns" not in prompt
    # Digest still folds in for dedupe; window/turns still capped the same.
    assert "Existing memory — facts: [Got sober on September 21, 2001]" in prompt
    assert "Conversation (last 6 turns):" in prompt


def test_more_than_12_turns_truncated_to_last_12(env):
    client, engine, _ = env
    res = client.post("/api/distill", json={"transcript": _transcript(15)})
    assert res.status_code == 200, res.text
    prompt = engine.prompts[0]
    assert "Conversation (last 12 turns):" in prompt
    assert "msg-15-content" in prompt  # newest kept
    assert "msg-03-content" not in prompt  # 15-12=3 oldest dropped
    assert "msg-01-content" not in prompt


def test_content_truncated_to_2000_chars_server_side(env):
    client, engine, _ = env
    long = "x" * 3000
    res = client.post(
        "/api/distill", json={"transcript": [_turn("user", long)]}
    )
    assert res.status_code == 200, res.text
    prompt = engine.prompts[0]
    assert "x" * 2000 in prompt
    assert "x" * 2001 not in prompt


def test_garbage_transcript_is_422(env):
    client, _, _ = env
    # Non-list transcript.
    assert client.post("/api/distill", json={"transcript": "nope"}).status_code == 422
    # Entry values that are not strings.
    assert (
        client.post(
            "/api/distill", json={"transcript": [{"role": "user", "content": 42}]}
        ).status_code
        == 422
    )
    # Zero usable turns (empty list).
    r = client.post("/api/distill", json={"transcript": []})
    assert r.status_code == 422
    # Turns with junk roles only -> dropped -> 422.
    r = client.post(
        "/api/distill", json={"transcript": [{"role": "system", "content": "x"}]}
    )
    assert r.status_code == 422


def test_engine_failure_is_502(env, monkeypatch):
    client, _, _ = env
    monkeypatch.setattr(
        server,
        "engine",
        _FakeEngine(error=RuntimeError("backend down")),
    )
    res = client.post("/api/distill", json={"transcript": _transcript(4)})
    assert res.status_code == 502
    assert "inference engine failure" in res.json()["error"]


def test_malformed_model_output_is_502_with_detail(env, monkeypatch):
    client, _, _ = env
    monkeypatch.setattr(server, "engine", _FakeEngine(response="not json at all"))
    res = client.post("/api/distill", json={"transcript": _transcript(4)})
    assert res.status_code == 502
    assert "malformed model output" in res.json()["error"]


def test_response_caps_facts_threads_and_lengths(env, monkeypatch):
    client, _, _ = env
    monkeypatch.setattr(
        server,
        "engine",
        _FakeEngine(
            response=(
                '{"new_facts":["f1","f2","f3","f4","f5",42,null],'
                '"threads":[{"id":"a","title":"' + ("t" * 80) + '","detail":"'
                + ("d" * 200) + '","resolved":false},'
                '{"id":"b","title":"B","detail":"","resolved":false},'
                '{"id":"c","title":"C","detail":"","resolved":false},'
                '"junk",42]}'
            )
        ),
    )
    res = client.post("/api/distill", json={"transcript": _transcript(4)})
    assert res.status_code == 200, res.text
    body = res.json()
    assert [f["id"] for f in body["threads"]] == ["a", "b"]  # capped at 2
    assert len(body["new_facts"]) == 3  # capped at 3, garbage dropped
    assert len(body["threads"][0]["title"]) == 50
    assert len(body["threads"][0]["detail"]) == 120


def test_zero_writes_to_redis(env):
    client, _, spy = env
    res = client.post("/api/distill", json={"transcript": _transcript(6)})
    assert res.status_code == 200
    assert spy.writes == [], f"endpoint must not write to Redis, got {spy.writes}"
