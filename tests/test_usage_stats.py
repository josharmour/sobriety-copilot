"""Unique-user counting (src/usage_stats.py) and GET /api/stats/active-users.

Run:  python3 -m pytest tests/test_usage_stats.py -q
"""

import datetime as dt

import pytest
from fastapi.testclient import TestClient

import tests.test_distill_endpoint  # noqa: F401  (stubs chromadb before src.server)
import src.server as server
import src.usage_stats as usage_stats
from src.usage_stats import active_users, chat_identity, record_active


class _HLLRedis:
    """Exact stand-in for Redis HyperLogLog commands (sets instead of sketches)."""

    def __init__(self):
        self.sets: dict[str, set] = {}
        self.ttl: dict[str, int] = {}

    def pfadd(self, key, *members):
        s = self.sets.setdefault(key, set())
        before = len(s)
        s.update(members)
        return int(len(s) != before)

    def pfcount(self, *keys):
        return len(set().union(*(self.sets.get(k, set()) for k in keys)))

    def expire(self, key, seconds):
        self.ttl[key] = seconds


def _on(monkeypatch, day: dt.date):
    monkeypatch.setattr(usage_stats, "_today", lambda: day)


def test_counts_each_user_once_per_day_and_keeps_no_identities(monkeypatch):
    rc = _HLLRedis()
    _on(monkeypatch, dt.date(2026, 10, 18))
    for _ in range(3):
        record_active(rc, "app", chat_identity("install-a", "1.2.3.4"))
    record_active(rc, "web", chat_identity(None, "5.6.7.8"))
    record_active(rc, "sms", "sms:+15555550123")
    out = active_users(rc, days=1)
    assert out["today"] == 3
    assert {k: out["daily"][-1][k] for k in ("app", "web", "sms")} == {"app": 1, "web": 1, "sms": 1}
    stored = "".join(m for s in rc.sets.values() for m in s)
    assert "install-a" not in stored and "5.6.7.8" not in stored and "5555550123" not in stored
    assert all(t > 300 * 86400 for t in rc.ttl.values())


def test_windows_count_returning_users_once(monkeypatch):
    rc = _HLLRedis()
    start = dt.date(2026, 10, 10)
    for i in range(5):  # same two users every day, plus one new user per day
        _on(monkeypatch, start + dt.timedelta(days=i))
        record_active(rc, "app", "id:regular-1")
        record_active(rc, "app", "id:regular-2")
        record_active(rc, "app", f"id:new-{i}")
    out = active_users(rc, days=7)
    assert [r["users"] for r in out["daily"][-5:]] == [3, 3, 3, 3, 3]
    assert out["last_7_days"] == 7
    assert out["last_30_days"] == 7
    assert len(out["daily"]) == 7 and out["daily"][-1]["date"] == "2026-10-14"


def test_default_user_falls_back_to_ip():
    assert chat_identity("default_user", "9.9.9.9") == "ip:9.9.9.9"
    assert chat_identity("abc", "9.9.9.9") == "id:abc"


def test_redis_errors_never_break_a_request():
    class Broken:
        def pfadd(self, *a):
            raise ConnectionError("down")

    record_active(Broken(), "app", "id:x")  # no exception
    record_active(None, "app", "id:x")


@pytest.fixture()
def client(monkeypatch):
    rc = _HLLRedis()
    monkeypatch.setattr(server, "get_redis_client", lambda: rc)
    monkeypatch.setenv("STATS_ADMIN_TOKEN", "tok")
    return TestClient(server.app), rc


def test_endpoint_requires_admin_token(client):
    c, _ = client
    assert c.get("/api/stats/active-users").status_code == 403
    assert c.get("/api/stats/active-users", headers={"X-Admin-Token": "nope"}).status_code == 403


def test_endpoint_fails_closed_without_configured_token(client, monkeypatch):
    c, _ = client
    monkeypatch.delenv("STATS_ADMIN_TOKEN")
    monkeypatch.delenv("BUG_ADMIN_TOKEN", raising=False)
    assert c.get("/api/stats/active-users", headers={"X-Admin-Token": ""}).status_code == 403


def test_chat_requests_are_counted_by_channel(client, monkeypatch):
    c, rc = client
    req = server.ChatRequest(message="hi", user_id="install-z")

    class _Req:
        def __init__(self, headers):
            self.headers = headers
            self.client = None

    server._record_chat_user(req, _Req({"origin": "https://sobrietycopilot.com"}))
    server._record_chat_user(req, _Req({}))
    body = c.get("/api/stats/active-users?days=1", headers={"X-Admin-Token": "tok"}).json()
    assert body["today"] == 1
    assert body["daily"][-1]["web"] == 1 and body["daily"][-1]["app"] == 1


def test_endpoint_takes_grafanas_range(client):
    c, _ = client
    h = {"X-Admin-Token": "tok"}
    assert len(c.get("/api/stats/active-users?range_s=21600", headers=h).json()["daily"]) == 2  # 6 h spans 2 days
    assert len(c.get("/api/stats/active-users?range_s=2592000", headers=h).json()["daily"]) == 31
    assert len(c.get("/api/stats/active-users?range_s=999999999", headers=h).json()["daily"]) == 366
