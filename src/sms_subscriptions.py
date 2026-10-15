"""Daily Reflection / Daily Meditation SMS subscription store, formatter, and scheduler."""

from __future__ import annotations

import base64
import datetime as _dt
import json
import os
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from typing import Any
from zoneinfo import ZoneInfo

VALID_DAILY_BOOKS: tuple[str, ...] = (
    "daily-reflections",
    "twenty-four-hours-a-day",
    "just-for-today",
)

BOOK_LABELS: dict[str, str] = {
    "daily-reflections": "Daily Reflections (A.A.)",
    "twenty-four-hours-a-day": "Twenty-Four Hours a Day",
    "just-for-today": "Just for Today (N.A.)",
}

DAILY_BOOKS_CATALOG: dict[str, dict[str, str]] = {
    "daily-reflections": {"label": "Daily Reflections (A.A.)", "fellowship": "A.A."},
    "twenty-four-hours-a-day": {"label": "Twenty-Four Hours a Day", "fellowship": "Hazelden / A.A."},
    "just-for-today": {"label": "Just for Today (N.A.)", "fellowship": "N.A."},
}

TZ_ALIASES: dict[str, str] = {
    "pt": "America/Los_Angeles",
    "pst": "America/Los_Angeles",
    "pdt": "America/Los_Angeles",
    "pacific": "America/Los_Angeles",
    "mt": "America/Denver",
    "mst": "America/Denver",
    "mdt": "America/Denver",
    "mountain": "America/Denver",
    "az": "America/Phoenix",
    "arizona": "America/Phoenix",
    "ct": "America/Chicago",
    "cst": "America/Chicago",
    "cdt": "America/Chicago",
    "central": "America/Chicago",
    "et": "America/New_York",
    "est": "America/New_York",
    "edt": "America/New_York",
    "eastern": "America/New_York",
    "akt": "America/Anchorage",
    "akst": "America/Anchorage",
    "akdt": "America/Anchorage",
    "alaska": "America/Anchorage",
    "ht": "Pacific/Honolulu",
    "hst": "Pacific/Honolulu",
    "hawaii": "Pacific/Honolulu",
    "utc": "UTC",
}

DEFAULT_TIMEZONE = "America/Los_Angeles"
DEFAULT_DELIVERY_TIME = "07:00"

_manifests_cache: dict[str, dict[str, Any]] = {}


def _db_path() -> str:
    explicit = os.environ.get("SMS_SUBSCRIPTIONS_DB_PATH")
    if explicit:
        os.makedirs(os.path.dirname(os.path.abspath(explicit)), exist_ok=True)
        return explicit
    default_dir = os.path.dirname(
        os.environ.get("USER_MEMORY_DB_PATH", "/home/app/memory/user_memory.db")
    )
    try:
        os.makedirs(default_dir, exist_ok=True)
        return os.path.join(default_dir, "sms_subscriptions.db")
    except OSError:
        return "/tmp/sms_subscriptions.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sms_subscribers (
            phone TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1,
            delivery_time TEXT NOT NULL DEFAULT '07:00',
            timezone TEXT NOT NULL DEFAULT 'America/Los_Angeles',
            books TEXT NOT NULL DEFAULT '["daily-reflections"]',
            last_sent_date TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    return conn


def normalize_phone(raw: str | None) -> str | None:
    """Normalize a US or international phone number to E.164 format (+1XXXXXXXXXX)."""
    if not raw:
        return None
    s = str(raw).strip()
    digits = re.sub(r"\D", "", s)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if s.startswith("+") and 10 <= len(digits) <= 15:
        return f"+{digits}"
    return None


def normalize_timezone(raw: str | None) -> str:
    """Validate or resolve a timezone alias into a valid IANA timezone."""
    if not raw:
        return DEFAULT_TIMEZONE
    cleaned = str(raw).strip()
    lower = cleaned.lower()
    if lower in TZ_ALIASES:
        return TZ_ALIASES[lower]
    try:
        ZoneInfo(cleaned)
        return cleaned
    except Exception:
        return DEFAULT_TIMEZONE


def normalize_delivery_time(raw: str | None) -> str:
    """Parse '07:00', '7:30 am', '8pm', '19:15', etc. into 24-hour 'HH:MM'."""
    if not raw:
        return DEFAULT_DELIVERY_TIME
    s = str(raw).strip().lower()
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.|a|p)?$", s)
    if not m:
        return DEFAULT_DELIVERY_TIME
    hour = int(m.group(1))
    minute = int(m.group(2) or "0")
    meridiem = (m.group(3) or "").replace(".", "")
    if meridiem in ("pm", "p") and hour < 12:
        hour += 12
    elif meridiem in ("am", "a") and hour == 12:
        hour = 0
    hour = max(0, min(23, hour))
    minute = max(0, min(59, minute))
    return f"{hour:02d}:{minute:02d}"


def format_time_12h(hhmm: str) -> str:
    """Format '07:00' -> '7:00 AM', '19:30' -> '7:30 PM'."""
    try:
        h_str, m_str = (hhmm or DEFAULT_DELIVERY_TIME).split(":", 1)
        h = int(h_str)
        m = int(m_str)
    except Exception:
        h, m = 7, 0
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {suffix}"


def format_tz_short(tz_name: str) -> str:
    """Human-friendly short label for a timezone."""
    short_map = {
        "America/Los_Angeles": "PT",
        "America/Denver": "MT",
        "America/Phoenix": "MST",
        "America/Chicago": "CT",
        "America/New_York": "ET",
        "America/Anchorage": "AKT",
        "Pacific/Honolulu": "HT",
        "UTC": "UTC",
    }
    return short_map.get(tz_name, tz_name)


def normalize_books(books: Any) -> list[str]:
    """Validate and deduplicate a list of daily book IDs, defaulting to daily-reflections."""
    if isinstance(books, str):
        try:
            books = json.loads(books)
        except Exception:
            books = [b.strip() for b in books.split(",") if b.strip()]
    if not isinstance(books, (list, tuple, set)):
        return ["daily-reflections"]
    out: list[str] = []
    for item in books:
        b = str(item).strip().lower()
        if b in VALID_DAILY_BOOKS and b not in out:
            out.append(b)
    return out or ["daily-reflections"]


def format_books_label(books: Any) -> str:
    """Format a list of daily book IDs into a readable phrase."""
    norm = normalize_books(books)
    labels = [BOOK_LABELS.get(b, b) for b in norm]
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} & {labels[1]}"
    return ", ".join(labels[:-1]) + f", & {labels[-1]}"


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    books = normalize_books(row["books"])
    return {
        "phone": row["phone"],
        "enabled": bool(row["enabled"]),
        "delivery_time": row["delivery_time"],
        "delivery_time_12h": format_time_12h(row["delivery_time"]),
        "timezone": row["timezone"],
        "timezone_short": format_tz_short(row["timezone"]),
        "books": books,
        "book_labels": [BOOK_LABELS.get(b, b) for b in books],
        "last_sent_date": row["last_sent_date"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_subscriber(phone: str) -> dict[str, Any] | None:
    norm = normalize_phone(phone)
    if not norm:
        return None
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM sms_subscribers WHERE phone = ?", (norm,)
        ).fetchone()
    return _row_to_dict(row)


def upsert_subscriber(
    phone: str,
    *,
    enabled: bool = True,
    delivery_time: str | None = None,
    timezone: str | None = None,
    books: list[str] | None = None,
    mark_sent_today: bool = False,
) -> dict[str, Any] | None:
    norm = normalize_phone(phone)
    if not norm:
        return None
    existing = get_subscriber(norm)
    now_ts = time.time()
    final_time = (
        normalize_delivery_time(delivery_time)
        if delivery_time is not None
        else (existing["delivery_time"] if existing else DEFAULT_DELIVERY_TIME)
    )
    final_tz = (
        normalize_timezone(timezone)
        if timezone is not None
        else (existing["timezone"] if existing else DEFAULT_TIMEZONE)
    )
    final_books = (
        normalize_books(books)
        if books is not None
        else (existing["books"] if existing else ["daily-reflections"])
    )
    local_now = _dt.datetime.now(ZoneInfo(final_tz))
    today_str = local_now.strftime("%Y-%m-%d")
    current_hhmm = local_now.strftime("%H:%M")

    # If the user subscribes/updates for a time that has ALREADY passed today
    # (and didn't request mark_sent_today), pre-set last_sent_date to today_str
    # when current_hhmm > final_time so the scheduler doesn't unexpectedly fire
    # a "catch-up" text 30 seconds later unless they asked for "Send Now".
    last_sent = existing["last_sent_date"] if existing else ""
    if mark_sent_today or (enabled and current_hhmm > final_time and last_sent != today_str):
        last_sent = today_str
    elif (
        not mark_sent_today
        and enabled
        and current_hhmm <= final_time
        and last_sent == today_str
        and (not existing or existing.get("delivery_time") != final_time)
    ):
        last_sent = ""
        try:
            from src.tasks.job_store import get_redis_client
            get_redis_client().delete(f"sc:sms:daily_sent:{norm}:{today_str}")
        except Exception:
            pass

    created_at = existing["created_at"] if existing else now_ts
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO sms_subscribers (
                phone, enabled, delivery_time, timezone, books, last_sent_date, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(phone) DO UPDATE SET
                enabled = excluded.enabled,
                delivery_time = excluded.delivery_time,
                timezone = excluded.timezone,
                books = excluded.books,
                last_sent_date = excluded.last_sent_date,
                updated_at = excluded.updated_at
            """,
            (
                norm,
                1 if enabled else 0,
                final_time,
                final_tz,
                json.dumps(final_books),
                last_sent,
                created_at,
                now_ts,
            ),
        )
        conn.commit()
    return get_subscriber(norm)


def set_subscriber_enabled(phone: str, enabled: bool) -> dict[str, Any] | None:
    norm = normalize_phone(phone)
    if not norm:
        return None
    existing = get_subscriber(norm)
    if not existing:
        if not enabled:
            return None
        return upsert_subscriber(norm, enabled=True)
    with _connect() as conn:
        conn.execute(
            "UPDATE sms_subscribers SET enabled = ?, updated_at = ? WHERE phone = ?",
            (1 if enabled else 0, time.time(), norm),
        )
        conn.commit()
    return get_subscriber(norm)


def mark_subscriber_sent(phone: str, date_str: str) -> None:
    norm = normalize_phone(phone)
    if not norm:
        return
    with _connect() as conn:
        conn.execute(
            "UPDATE sms_subscribers SET last_sent_date = ?, updated_at = ? WHERE phone = ?",
            (date_str, time.time(), norm),
        )
        conn.commit()


def list_enabled_subscribers() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM sms_subscribers WHERE enabled = 1"
        ).fetchall()
    return [d for r in rows if (d := _row_to_dict(r)) is not None]


def format_daily_reading_sms(
    book_id: str,
    target_date: _dt.date | None = None,
    manifests_dir: str | None = None,
    include_reply_prompt: bool = True,
) -> str | None:
    """Extract and format the full verbatim daily reading for `book_id` on `target_date`."""
    if target_date is None:
        target_date = _dt.datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).date()
    try:
        leap_doy = (_dt.date(2024, target_date.month, target_date.day) - _dt.date(2024, 1, 1)).days + 1
    except Exception:
        return None

    date_label = target_date.strftime("%B %-d")
    m_dir = manifests_dir or os.environ.get("MANIFESTS_DIR") or os.path.join(
        os.environ.get("DOCUMENTS_DIR", "documents"), ".manifests"
    )

    spec_map = {
        "daily-reflections": ("daily-reflections.json", "Daily Reflections", 6 + leap_doy),
        "twenty-four-hours-a-day": ("twenty-four-hours-a-day.json", "Twenty-Four Hours a Day", 9 + leap_doy),
        "just-for-today": ("just-for-today.json", "Just for Today", 8 + leap_doy),
    }
    if book_id not in spec_map:
        return None
    fname, title, target_phys = spec_map[book_id]

    if fname not in _manifests_cache:
        fpath = os.path.join(m_dir, fname)
        if not os.path.exists(fpath):
            return None
        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                _manifests_cache[fname] = json.load(fh)
        except Exception:
            return None

    mdata = _manifests_cache.get(fname) or {}
    day_blocks = [
        b for b in mdata.get("blocks", [])
        if b.get("physical_page") == target_phys and (b.get("text") or "").strip()
    ]
    if not day_blocks:
        return None

    cleaned_blocks: list[str] = []
    for idx, b in enumerate(day_blocks):
        txt = re.sub(r"\s+", " ", (b.get("text") or "").strip())
        if not txt:
            continue
        if book_id == "daily-reflections":
            # Separate embedded uppercase citation at the start of the reflection block
            txt = re.sub(
                r"^([A-Z0-9][A-Z0-9\s,&.'\-\(\)]+,\s*pp?\.\s*\d+(?:[–\-]\d+)?)\s+",
                r"— \1\n\n",
                txt,
            )
            if idx == 0:
                txt = f'"{txt}"'
        elif book_id == "twenty-four-hours-a-day":
            txt = re.sub(
                r"^(A\.?A\.?\s+Thought for the Day|Meditation for the Day|Prayer for the Day)\s+",
                r"\1:\n",
                txt,
            )
        elif book_id == "just-for-today" and idx == 0:
            # First block is e.g. 'October 15 Choices “We did not choose to become addicts.”'
            txt = re.sub(
                rf"^{re.escape(date_label)}\s+(.+?)\s+([“\"].+)$",
                r'"\1"\n\n\2',
                txt,
                flags=re.IGNORECASE,
            )
        cleaned_blocks.append(txt)

    header = f"Sobriety Copilot — {title} ({date_label})"
    body = header + "\n\n" + "\n\n".join(cleaned_blocks)
    if include_reply_prompt:
        body += (
            "\n\nReply to this message to talk through how today's reading applies "
            "to your day (or text PAUSE to pause daily texts, STOP to cancel)."
        )

    if len(body) > 1520:
        window = body[:1515]
        cut = window.rsplit(" ", 1)[0]
        body = (cut or window) + "..."
    return body


def send_twilio_sms(
    to_phone: str,
    body: str,
    *,
    record_in_history: bool = True,
) -> bool:
    """Send an outbound SMS via Twilio REST API and optionally record it in Redis SMS history."""
    norm_to = normalize_phone(to_phone)
    if not norm_to or not body:
        return False

    account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
    from_number = os.environ.get("TWILIO_PHONE_NUMBER", "+17623769696").strip()
    messaging_service_sid = os.environ.get("TWILIO_MESSAGING_SERVICE_SID", "").strip()

    if not account_sid or not auth_token:
        print("[DAILY-SMS-ERR] Missing TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN", flush=True)
        return False

    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    form_data: dict[str, str] = {
        "To": norm_to,
        "Body": body,
    }
    if messaging_service_sid:
        form_data["MessagingServiceSid"] = messaging_service_sid
    else:
        form_data["From"] = from_number

    encoded = urllib.parse.urlencode(form_data).encode("utf-8")
    creds = base64.b64encode(f"{account_sid}:{auth_token}".encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        url,
        data=encoded,
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "SobrietyCopilot/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status_code = resp.getcode()
            ok = 200 <= status_code < 300
    except Exception as exc:
        print(f"[DAILY-SMS-ERR] Failed sending to {norm_to}: {exc}", flush=True)
        return False

    if ok and record_in_history:
        try:
            from src.tasks.job_store import get_redis_client
            rc = get_redis_client()
            hist_key = f"sc:sms:history:{norm_to}"
            raw_hist = rc.get(hist_key)
            sms_history = json.loads(raw_hist) if raw_hist else []
            if not isinstance(sms_history, list):
                sms_history = []
            sms_history.append({"role": "assistant", "content": body})
            rc.setex(hist_key, 604800, json.dumps(sms_history[-8:]))
        except Exception:
            pass
    return ok


def send_daily_readings_for_subscriber(
    sub: dict[str, Any],
    target_date: _dt.date | None = None,
) -> int:
    """Send all subscribed daily book readings for `sub` and return count sent."""
    phone = sub["phone"]
    tz_name = sub.get("timezone") or DEFAULT_TIMEZONE
    if target_date is None:
        target_date = _dt.datetime.now(ZoneInfo(tz_name)).date()
    books = normalize_books(sub.get("books"))
    sent_count = 0
    for b_id in books:
        msg = format_daily_reading_sms(b_id, target_date=target_date, include_reply_prompt=True)
        if msg and send_twilio_sms(phone, msg, record_in_history=True):
            sent_count += 1
    return sent_count


def run_daily_sms_scheduler_tick() -> int:
    """Check all enabled subscribers and send today's daily reading if their local
    delivery time has arrived and today's reading hasn't been sent yet.
    """
    try:
        from src.tasks.job_store import get_redis_client
        rc = get_redis_client()
    except Exception:
        rc = None

    # Acquire a short Redis lock so concurrent workers/processes don't double-send
    if rc is not None:
        try:
            if not rc.set("sc:sms:daily_scheduler_lock", "1", nx=True, ex=25):
                return 0
        except Exception:
            pass

    subscribers = list_enabled_subscribers()
    total_sent = 0
    for sub in subscribers:
        phone = sub["phone"]
        tz_name = sub.get("timezone") or DEFAULT_TIMEZONE
        try:
            now_local = _dt.datetime.now(ZoneInfo(tz_name))
        except Exception:
            now_local = _dt.datetime.now(ZoneInfo(DEFAULT_TIMEZONE))

        today_str = now_local.strftime("%Y-%m-%d")
        if sub.get("last_sent_date") == today_str:
            continue

        delivery_hhmm = sub.get("delivery_time") or DEFAULT_DELIVERY_TIME
        current_hhmm = now_local.strftime("%H:%M")
        if current_hhmm < delivery_hhmm:
            continue

        # Ensure we are within a 120-minute window past delivery_time so stale rows don't fire at midnight
        try:
            dh, dm = (int(x) for x in delivery_hhmm.split(":", 1))
            ch, cm = (int(x) for x in current_hhmm.split(":", 1))
            diff_mins = (ch * 60 + cm) - (dh * 60 + dm)
            if diff_mins < 0 or diff_mins > 120:
                continue
        except Exception:
            pass

        # Redis per-phone/day idempotency guard
        if rc is not None:
            try:
                guard_key = f"sc:sms:daily_sent:{phone}:{today_str}"
                if not rc.set(guard_key, "1", nx=True, ex=172800):
                    mark_subscriber_sent(phone, today_str)
                    continue
            except Exception:
                pass

        mark_subscriber_sent(phone, today_str)
        sent = send_daily_readings_for_subscriber(sub, target_date=now_local.date())
        if sent > 0:
            total_sent += sent
            print(
                f"[DAILY-SMS] Sent {sent} daily reading(s) to {phone} for {today_str} "
                f"(scheduled {delivery_hhmm} {tz_name})",
                flush=True,
            )
    return total_sent


def parse_sms_subscription_command(body_text: str) -> dict[str, Any] | None:
    """Detect and parse SMS commands for managing daily reflection subscriptions.

    Supported commands:
    - 'PAUSE', 'PAUSE DAILY', 'STOP DAILY', 'UNSUBSCRIBE DAILY' -> {'action': 'pause'}
    - 'SEND NOW', 'DAILY NOW' -> {'action': 'send_now'}
    - 'SCHEDULE', 'MY SCHEDULE', 'DAILY STATUS' -> {'action': 'status'}
    - 'DAILY', 'DAILY 7:00 AM PT', 'SUBSCRIBE 8am EST', 'Send me the daily reflection at 7:30am'
      -> {'action': 'subscribe', 'delivery_time': '07:30', 'timezone': ..., 'books': ...}
    """
    raw = (body_text or "").strip()
    if not raw:
        return None
    lower = raw.lower()

    if lower in {"pause", "pause daily", "stop daily", "unsubscribe daily", "cancel daily"}:
        return {"action": "pause"}

    if lower in {"send now", "daily now", "send daily now"}:
        return {"action": "send_now"}

    if lower in {"schedule", "my schedule", "daily status", "subscription", "my subscription"}:
        return {"action": "status"}

    # Explicit command prefix ('daily ...' or 'subscribe ...') or natural language ('send me the daily reflection every day at 7am')
    is_explicit_cmd = bool(re.match(r"^(?:daily|subscribe)\b", lower))
    is_natural_sub = bool(
        re.search(
            r"\b(?:subscribe|send\s+me|text\s+me)\b.*\b(?:daily|reflection|meditation|every\s+day|each\s+day|every\s+morning)\b",
            lower,
        )
        and re.search(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)\b", lower)
    )
    # Don't intercept normal questions like "What is the daily reflection for today?"
    if not is_explicit_cmd and not is_natural_sub:
        return None
    if re.match(r"^(?:what|where|why|how|who|can\s+you\s+explain|tell\s+me\s+about)\b", lower):
        return None

    # Extract time if present
    time_match = re.search(
        r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?\b",
        lower,
    )
    delivery_time: str | None = None
    if time_match:
        # Avoid matching "24" in "24 hours a day" as the hour unless followed by am/pm/:MM
        matched_full = time_match.group(0)
        after_str = lower[time_match.end():]
        if not (matched_full.strip() == "24" and after_str.lstrip().startswith("hour")):
            delivery_time = normalize_delivery_time(matched_full)

    # Extract timezone if present
    tz_val: str | None = None
    for alias, iana in TZ_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", lower):
            tz_val = iana
            break

    # Extract book selection if mentioned
    books: list[str] = []
    if "all" in lower or "both" in lower or "all three" in lower:
        books = list(VALID_DAILY_BOOKS)
    else:
        if "reflection" in lower or "aa" in lower:
            books.append("daily-reflections")
        if "24 hour" in lower or "twenty-four" in lower or "twenty four" in lower:
            books.append("twenty-four-hours-a-day")
        if "just for today" in lower or "na" in lower:
            books.append("just-for-today")

    return {
        "action": "subscribe",
        "delivery_time": delivery_time,
        "timezone": tz_val,
        "books": books or None,
    }
