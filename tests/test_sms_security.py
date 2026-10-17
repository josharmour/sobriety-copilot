"""SMS abuse/privacy guards: Twilio signature check on /api/sms, double opt-in
for web/app sign-ups, and no endpoint revealing whether a number subscribes.

Run:  python3 -m pytest tests/test_sms_security.py -q
"""

import pytest

from tests.test_sms_reply import PHONE, TWILIO_TOKEN, _Engine, _Redis, post_sms, sign
import src.server as server
from fastapi.testclient import TestClient


@pytest.fixture()
def env(monkeypatch, tmp_path):
    redis = _Redis()
    texts: list[tuple[str, str]] = []
    readings: list[str] = []
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", TWILIO_TOKEN)
    monkeypatch.setenv("SMS_SUBSCRIPTIONS_DB_PATH", str(tmp_path / "subs.db"))
    monkeypatch.setattr(server, "engine", _Engine())
    monkeypatch.setattr(server, "engine_fallback", None)
    monkeypatch.setattr(server, "get_redis_client", lambda: redis)
    monkeypatch.setattr(server, "_safe_get_retriever", lambda: None)
    monkeypatch.setattr(server, "send_twilio_sms", lambda to, body, *a, **k: texts.append((to, body)))
    monkeypatch.setattr(
        server, "send_daily_readings_for_subscriber", lambda sub, day: readings.append(sub["phone"]) or 1
    )
    return TestClient(server.app), redis, texts, readings


def _optin(client, **extra):
    body = {"phone": "(555) 555-0123", "consent": True, "delivery_time": "07:30",
            "timezone": "America/Chicago", "books": ["daily-reflections"], **extra}
    return client.post("/api/sms/optin", json=body).json()


# --- Twilio signature -------------------------------------------------------

def test_matches_twilios_published_test_vector(monkeypatch):
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "12345")
    monkeypatch.setattr(server, "_TWILIO_SMS_WEBHOOK_URL", "https://mycompany.com/myapp.php?foo=1&bar=2")
    params = {"CallSid": ["CA1234567890ABCDE"], "Caller": ["+14158675309"], "Digits": ["1234"],
              "From": ["+14158675309"], "To": ["+18005551212"]}
    assert server._twilio_signature_valid("RSOYDt4T1cUTdK1PDd93/VVr8B8=", params)
    assert not server._twilio_signature_valid("RSOYDt4T1cUTdK1PDd93/VVr8B9=", params)


def test_unsigned_or_forged_requests_are_rejected(env):
    client, redis, _, _ = env
    params = {"From": PHONE, "Body": "STOP"}
    assert post_sms(client, params, signature="").status_code == 403
    assert post_sms(client, params, signature=sign({"From": "+15555550999", "Body": "STOP"})).status_code == 403
    assert client.post("/api/sms", json={"From": PHONE, "Body": "hi"}).status_code == 403
    assert redis.data == {}


def test_signed_request_with_blank_params_and_explicit_port(env):
    client, _, _, _ = env
    params = {"From": PHONE, "Body": "HELP", "FromCity": "", "NumMedia": "0"}
    assert post_sms(client, params).status_code == 200
    with_port = server._TWILIO_SMS_WEBHOOK_URL.replace(".com/", ".com:443/")
    assert post_sms(client, params, signature=sign(params, url=with_port)).status_code == 200


# --- Double opt-in -----------------------------------------------------------

def test_web_signup_only_texts_a_confirmation(env):
    client, _, texts, readings = env
    data = _optin(client, send_now=True)
    assert data["pending_confirmation"] is True and data["subscription"] is None
    assert len(texts) == 1 and "Reply YES" in texts[0][1]
    assert readings == []
    assert server.get_subscriber(PHONE) is None


def test_reply_yes_activates_the_pending_schedule(env):
    client, redis, _, readings = env
    _optin(client, send_now=True)
    assert post_sms(client, {"From": PHONE, "Body": "YES"}).status_code == 200
    sub = server.get_subscriber(PHONE)
    assert sub["enabled"] and sub["delivery_time"] == "07:30" and sub["timezone"] == "America/Chicago"
    assert readings == [PHONE]
    assert not any(k.startswith("sc:sms:pending_optin:") for k in redis.data)


def test_repeat_signups_do_not_spam_a_phone(env):
    client, _, texts, _ = env
    for _ in range(5):
        _optin(client)
    assert len(texts) == 1


def test_send_now_only_texts_confirmed_subscribers(env):
    client, _, texts, readings = env
    data = client.post("/api/sms/optin", json={"phone": PHONE, "action": "send_now"}).json()
    assert readings == [] and texts == [] and data["subscription"] is None
    server.upsert_subscriber(PHONE, enabled=True)
    client.post("/api/sms/optin", json={"phone": PHONE, "action": "send_now"})
    client.post("/api/sms/optin", json={"phone": PHONE, "action": "send_now"})
    assert readings == [PHONE]  # second call is inside the 1-hour cooldown


# --- No subscription lookups -------------------------------------------------

def test_nothing_reveals_whether_a_number_subscribes(env):
    client, _, _, _ = env
    server.upsert_subscriber(PHONE, enabled=True, delivery_time="06:00")
    lookup = client.get("/api/sms/subscription", params={"phone": PHONE}).json()
    assert lookup["subscription"] is None and lookup["catalog"]
    paused = client.post("/api/sms/optin", json={"phone": PHONE, "action": "pause"}).json()
    assert paused["subscription"] is None
    assert server.get_subscriber(PHONE)["enabled"] is False
