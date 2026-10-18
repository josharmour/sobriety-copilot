"""Unique-user counts (daily / 7-day / 30-day) without keeping who the users are.

Each chat, research or SMS message adds a hash of the sender's identity to a
per-day Redis HyperLogLog: the app's random per-install id, else the client
IP (older web builds send no id), else the SMS number. A HyperLogLog holds
only ~12 KB of registers per day: it can count distinct members (±0.8%) but
cannot list them or say whether a given user is in it. Unions of days
(PFCOUNT over several keys) give 7- and 30-day uniques without double
counting someone who came back.

Days follow STATS_TIMEZONE (default America/Los_Angeles, like the SMS
schedule). Read with GET /api/stats/active-users (admin token).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
from typing import Any
from zoneinfo import ZoneInfo

CHANNELS = ("app", "web", "sms")
_KEY = "sc:dau:{day}"
_CHANNEL_KEY = "sc:dau:{channel}:{day}"
_TTL_S = 400 * 86400  # a year of history plus slack


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(os.environ.get("STATS_TIMEZONE", "America/Los_Angeles"))
    except Exception:
        return ZoneInfo("UTC")


def _today() -> dt.date:
    return dt.datetime.now(_tz()).date()


def record_active(rc: Any, channel: str, identity: str) -> None:
    """Count [identity] as active today on [channel]. Never raises."""
    if rc is None or not identity or channel not in CHANNELS:
        return
    member = hashlib.sha256(f"sc-user:{identity}".encode()).hexdigest()[:24]
    day = _today().isoformat()
    try:
        for key in (_KEY.format(day=day), _CHANNEL_KEY.format(channel=channel, day=day)):
            if rc.pfadd(key, member):
                rc.expire(key, _TTL_S)
    except Exception:
        pass


def chat_identity(user_id: str | None, client_ip: str) -> str:
    """The install id when the client sent one, else the IP."""
    uid = (user_id or "").strip()
    if uid and uid != "default_user":
        return f"id:{uid}"
    return f"ip:{client_ip}"


def active_users(rc: Any, days: int = 30) -> dict[str, Any]:
    """Daily unique users for the last [days] days (oldest first) plus the
    distinct users across the last 7 and 30 days."""
    days = max(1, min(int(days), 366))
    tz = _tz()
    today = _today()
    span = [today - dt.timedelta(days=i) for i in range(days - 1, -1, -1)]
    daily = []
    for d in span:
        iso = d.isoformat()
        row: dict[str, Any] = {
            "date": iso,
            # Local midnight in ms, so Grafana places the bar on the right day.
            "time": int(dt.datetime(d.year, d.month, d.day, tzinfo=tz).timestamp() * 1000),
            "users": int(rc.pfcount(_KEY.format(day=iso))),
        }
        for ch in CHANNELS:
            row[ch] = int(rc.pfcount(_CHANNEL_KEY.format(channel=ch, day=iso)))
        daily.append(row)

    def window(n: int) -> int:
        keys = [_KEY.format(day=(today - dt.timedelta(days=i)).isoformat()) for i in range(n)]
        return int(rc.pfcount(*keys))

    return {
        "timezone": str(tz),
        "today": daily[-1]["users"],
        "last_7_days": window(7),
        "last_30_days": window(30),
        "daily": daily,
    }
