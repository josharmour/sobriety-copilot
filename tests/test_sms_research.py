"""SMS routing: literature questions → acknowledged now, researched answer texted after; the rest stays instant."""

import os

import pytest

pytest.importorskip("fastapi")
os.environ.setdefault("LLM_API_KEY", "test")

from fastapi.testclient import TestClient  # noqa: E402

from src import server  # noqa: E402

PHONE = "+15550100999"


class FakeRedis(dict):
    def get(self, k):
        return super().get(k)

    def setex(self, k, ttl, v):
        self[k] = v

    def incr(self, k):
        self[k] = int(super().get(k) or 0) + 1
        return self[k]

    def expire(self, k, ttl):
        pass

    def delete(self, *ks):
        for k in ks:
            self.pop(k, None)


@pytest.fixture
def sms(monkeypatch, tmp_path):
    fake = FakeRedis()
    started = []
    monkeypatch.setattr(server, "_TWILIO_VALIDATE_SIGNATURE", False)
    monkeypatch.setattr(server, "SMS_ENGINE", "research")
    monkeypatch.setattr(server, "get_redis_client", lambda: fake)
    monkeypatch.setattr(server, "get_subscriber", lambda phone: None)
    monkeypatch.setattr(server, "_start_sms_research", lambda *a: started.append(a))
    monkeypatch.setattr(server, "_safe_get_retriever", lambda: None)
    monkeypatch.setattr(server.engine, "generate", lambda **kw: "Classic reply.")
    client = TestClient(server.app)

    def send(body, returning=True):
        if returning:
            fake["sc:sms:seen:" + server._phone_hash(PHONE)] = "5"
        r = client.post("/api/sms", data={"Body": body, "From": PHONE})
        return r.text

    return send, started


def test_texts_go_to_the_research_agent_and_twilio_gets_an_empty_reply(sms):
    send, started = sms
    for body in ("How many prayers are in each chapter of the Big Book?", "waht's serentiy", "rough day today"):
        reply = send(body)
        assert "<Message>" not in reply, "the answer is sent as its own SMS"
    assert [a[1] for a in started] == ["How many prayers are in each chapter of the Big Book?",
                                       "waht's serentiy", "rough day today"]


@pytest.mark.parametrize("body", ["I want to drink tonight and the Big Book isn't helping",
                                  "should I drink tonight", "thinking about using"])
def test_crisis_wording_gets_the_instant_reply(sms, body):
    send, started = sms
    reply = send(body)
    assert "Classic reply." in reply and not started


def test_a_first_text_gets_the_instant_reply(sms):
    send, started = sms
    reply = send("What does the Big Book say about fear?", returning=False)
    assert "Classic reply." in reply and not started


@pytest.mark.parametrize("delay,expect_ack", [(0.0, False), (0.6, True)])
def test_looking_that_up_is_sent_only_when_slow(monkeypatch, delay, expect_ack):
    import time as _t
    sent = []
    monkeypatch.setattr(server, "SMS_ACK_AFTER_S", 0.3)
    monkeypatch.setattr(server, "_sms_answer", lambda q, h, r: (_t.sleep(delay), "Serenity is…")[1])
    monkeypatch.setattr(server, "send_twilio_sms", lambda to, body, record_in_history=True: sent.append(body))
    monkeypatch.setattr(server, "get_redis_client", lambda: FakeRedis())
    server._sms_research_job(PHONE, "what's serenity", [], "h", "seen", "")
    assert sent == ([server._SMS_RESEARCH_ACK] if expect_ack else []) + ["Serenity is…"]


def test_answers_are_cleaned_for_sms():
    raw = "**Seven times.**\n\n| Chapter | Count |\n|---|---|\n| Into Action | 7 |\n\nSee (Big Book, p. 76)."
    out = server._clean_sms_text(raw)
    assert "*" not in out and "|" not in out and "---" not in out
    assert "Seven times." in out and "Into Action 7" in out
    long = ("A sentence that keeps going. " * 80).strip()
    assert len(server._clean_sms_text(long)) <= 1480
