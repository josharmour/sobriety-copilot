"""Location-agnostic online-meeting directory (OIAA + Virtual NA).

Two sources, both cached server-side with stale-on-failure like the
geographic feeds in service.py:

- OIAA (Online Intergroup of A.A., aa-intergroup.org): Meeting Guide JSON
  feed behind their directory app. ~7,700 online AA meetings worldwide with
  one-tap conference URLs. Public but unadvertised — cache aggressively and
  never proxy per-user requests to it.
- Virtual NA (virtual-na.org): their own BMLT root server; the source of
  truth for online NA meetings, join links in virtual_meeting_link.

Every returned meeting carries a conference_url or conference_phone, plus
`starts_in_minutes` / `is_live_now` computed from the meeting's timezone so
clients can show a "happening now / starting soon" directory.
"""

from __future__ import annotations

import asyncio
import html
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

# OIAA's public directory feed (Meeting Guide format, served via
# code4recovery's Central). Hash-named app feed — courteous use is a long
# cache, not live per-user queries.
OIAA_FEED_URL = "https://data.aa-intergroup.org/6436f5a3f03fdecef8459055.json"
# Virtual NA's BMLT root (standard semantic API, virtual meetings only).
VIRTUAL_NA_URL = (
    "https://bmlt.virtual-na.org/main_server/client_interface/json/"
    "?switcher=GetSearchResults"
)

FETCH_TIMEOUT = 15.0  # these feeds are large (multi-MB); allow slow upstreams
CACHE_TTL_SECONDS = 6 * 60 * 60  # online directories change rarely

DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

# Live-now window: treat a meeting that started within the last 90 minutes
# as joinable.
LIVE_WINDOW_MINUTES = 90

# source key -> (timestamp, normalized meetings)
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_cache_lock = asyncio.Lock()


def _decode(value: Any) -> str:
    return html.unescape(str(value)).strip() if value else ""


def _coerce_day(value: Any) -> int | None:
    """Meeting Guide day: 0=Sunday..6=Saturday (may arrive as str or list)."""
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None or value == "":
        return None
    try:
        d = int(value)
    except (TypeError, ValueError):
        return None
    return d if 0 <= d <= 6 else None


def _normalize_time(value: Any) -> str:
    """'HH:MM[:SS]' -> 'HH:MM'; anything unparsable -> ''."""
    if not value:
        return ""
    parts = str(value).split(":")
    if len(parts) < 2:
        return ""
    try:
        hh, mm = int(parts[0]), int(parts[1])
    except ValueError:
        return ""
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return ""
    return f"{hh:02d}:{mm:02d}"


def _format_time(hhmm: str) -> str:
    if not hhmm:
        return ""
    hh, mm = int(hhmm[:2]), int(hhmm[3:5])
    suffix = "am" if hh < 12 else "pm"
    display_h = hh % 12 or 12
    return f"{display_h}:{mm:02d} {suffix}"


def _normalize_oiaa(raw: dict[str, Any]) -> dict[str, Any] | None:
    """OIAA rows are Meeting Guide spec, usually without coordinates."""
    conference_url = (raw.get("conference_url") or "").strip()
    conference_phone = (raw.get("conference_phone") or "").strip()
    if not conference_url and not conference_phone:
        return None

    raw_types = raw.get("types") or []
    if isinstance(raw_types, str):
        raw_types = raw_types.split(",")
    types = [str(t).strip() for t in raw_types if str(t).strip()]

    hhmm = _normalize_time(raw.get("time"))
    return {
        "slug": _decode(raw.get("slug")),
        "name": _decode(raw.get("name")),
        "group": _decode(raw.get("group")),
        "group_id": raw.get("group_id"),
        "day": _coerce_day(raw.get("day")),
        "time": hhmm,
        "time_formatted": _decode(raw.get("time_formatted")) or _format_time(hhmm),
        "end_time": _normalize_time(raw.get("end_time")),
        "formatted_address": "",
        "region": _decode(raw.get("timezone")),
        "sub_region": "",
        "location": _decode(raw.get("location")),
        "location_url": "",
        "types": types[:6],
        "url": (raw.get("url") or "").strip(),
        "website": (raw.get("website") or "").strip(),
        "conference_url": conference_url,
        "conference_url_notes": _decode(raw.get("conference_url_notes")),
        "conference_phone": conference_phone,
        "attendance_option": "online",
        "approximate": False,
        "is_online": True,
        "is_inperson": False,
        "lat": 0.0,
        "lng": 0.0,
        "source": "Online Intergroup of A.A.",
        "source_home": "https://aa-intergroup.org",
        "fellowship": "AA",
        # OIAA entries without an explicit timezone list Eastern times.
        "timezone": _decode(raw.get("timezone")) or "America/New_York",
    }


def _normalize_virtual_na(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Virtual NA BMLT rows; virtual-only root, coordinates meaningless."""
    conference_url = (raw.get("virtual_meeting_link") or "").strip()
    conference_phone = (raw.get("phone_meeting_number") or "").strip()
    if not conference_url and not conference_phone:
        return None

    formats_raw = raw.get("formats") or ""
    formats = [f.strip() for f in str(formats_raw).split(",") if f.strip()]

    day_raw = raw.get("weekday_tinyint")
    day: int | None
    try:
        d = int(day_raw)
        day = d - 1 if 1 <= d <= 7 else None  # BMLT 1=Sun..7=Sat -> 0..6
    except (TypeError, ValueError):
        day = None

    hhmm = _normalize_time(raw.get("start_time"))
    return {
        "slug": str(raw.get("id_bigint") or "").strip() or None,
        "name": _decode(raw.get("meeting_name")),
        "group": "",
        "group_id": str(raw.get("worldid_mixed") or "").strip() or None,
        "day": day,
        "time": hhmm,
        "time_formatted": _format_time(hhmm),
        "end_time": _normalize_time(raw.get("end_time")) if raw.get("end_time") else "",
        "formatted_address": "",
        "region": _decode(raw.get("service_body_name")),
        "sub_region": "",
        "location": _decode(raw.get("location_text")),
        "location_url": "",
        "types": formats[:6],
        "url": (raw.get("meeting_name_url") or "").strip(),
        "website": "",
        "conference_url": conference_url,
        "conference_url_notes": _decode(raw.get("virtual_meeting_additional_info")),
        "conference_phone": conference_phone,
        "attendance_option": "online",
        "approximate": False,
        "is_online": True,
        "is_inperson": False,
        "lat": 0.0,
        "lng": 0.0,
        "source": "Virtual NA",
        "source_home": "https://virtual-na.org",
        "fellowship": "NA",
        # BMLT rows carry time_zone per meeting; the root's convention when
        # absent is UTC.
        "timezone": _decode(raw.get("time_zone")) or "UTC",
    }


async def _fetch_source(
    client: httpx.AsyncClient,
    key: str,
    url: str,
    normalize,
) -> list[dict[str, Any]]:
    async with _cache_lock:
        cached = _cache.get(key)
        if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]

    try:
        resp = await client.get(
            url,
            timeout=FETCH_TIMEOUT,
            headers={"User-Agent": "sobriety-copilot/1.0 (+meeting-aggregator)"},
            follow_redirects=True,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        async with _cache_lock:
            entry = _cache.get(key)
            if entry:
                return entry[1]  # serve stale on failure
        return []

    if isinstance(data, dict):
        data = data.get("meetings", [])
    if not isinstance(data, list):
        return []

    normalized: list[dict[str, Any]] = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        meeting = normalize(raw)
        if meeting:
            normalized.append(meeting)

    async with _cache_lock:
        _cache[key] = (time.time(), normalized)
    return normalized


def _schedule_meeting(meeting: dict[str, Any], now_utc: datetime) -> dict[str, Any]:
    """Attach starts_in_minutes / is_live_now, resolved in the meeting's tz.

    Meeting Guide day is 0=Sunday; Python weekday() is 0=Monday, so the
    target weekday index is (day + 6) % 7.
    """
    day = meeting.get("day")
    hhmm = meeting.get("time") or ""
    starts_in: int | None = None
    live = False

    if isinstance(day, int) and hhmm:
        try:
            tzinfo = ZoneInfo(meeting.get("timezone") or "UTC")
        except Exception:
            tzinfo = ZoneInfo("UTC")
        now_local = now_utc.astimezone(tzinfo)
        target_weekday = (day + 6) % 7
        days_ahead = (target_weekday - now_local.weekday()) % 7
        hh, mm = int(hhmm[:2]), int(hhmm[3:5])
        candidate = (now_local + timedelta(days=days_ahead)).replace(
            hour=hh, minute=mm, second=0, microsecond=0
        )
        delta_min = int((candidate - now_local).total_seconds() // 60)
        if delta_min < -LIVE_WINDOW_MINUTES:
            # Started too long ago today — next occurrence is next week.
            delta_min += 7 * 24 * 60
        starts_in = delta_min
        live = -LIVE_WINDOW_MINUTES <= delta_min <= 0

    day_idx = meeting.get("day")
    return {
        **meeting,
        "distance_mi": 0.0,
        "day_name": DAY_NAMES[day_idx] if isinstance(day_idx, int) else None,
        "online": True,
        "starts_in_minutes": starts_in,
        "is_live_now": live,
    }


async def warmup_online_feeds() -> None:
    """Pre-fetch both directories so the first request hits a warm cache."""
    async with httpx.AsyncClient() as client:
        await asyncio.gather(
            _fetch_source(client, "oiaa", OIAA_FEED_URL, _normalize_oiaa),
            _fetch_source(client, "virtual_na", VIRTUAL_NA_URL, _normalize_virtual_na),
            return_exceptions=True,
        )


async def search_online_meetings(
    fellowship: str | None = None,
    max_results: int = 50,
    day: int | None = None,
) -> dict[str, Any]:
    """Directory search: live-now first (most recent start first), then by
    time-to-start. Entries without a parseable schedule sort last."""
    fellowship_norm = (fellowship or "").strip().lower() or None
    want_aa = fellowship_norm in (None, "all", "aa")
    want_na = fellowship_norm in (None, "all", "na")

    async with httpx.AsyncClient() as client:
        oiaa_task = (
            _fetch_source(client, "oiaa", OIAA_FEED_URL, _normalize_oiaa)
            if want_aa
            else _empty_list()
        )
        vna_task = (
            _fetch_source(client, "virtual_na", VIRTUAL_NA_URL, _normalize_virtual_na)
            if want_na
            else _empty_list()
        )
        oiaa, vna = await asyncio.gather(oiaa_task, vna_task)

    now_utc = datetime.now(ZoneInfo("UTC"))
    candidates = [
        _schedule_meeting(m, now_utc)
        for m in [*oiaa, *vna]
    ]
    if day is not None:
        candidates = [c for c in candidates if c.get("day") == day]

    def sort_key(m: dict[str, Any]):
        starts = m.get("starts_in_minutes")
        if starts is None:
            return (2, 0, m.get("name") or "")
        if m.get("is_live_now"):
            # Most recently started first: starts is in [-90, 0].
            return (0, -starts, m.get("name") or "")
        return (1, starts, m.get("name") or "")

    candidates.sort(key=sort_key)

    feeds_queried = (1 if want_aa else 0) + (1 if want_na else 0)
    feeds_with_data = (1 if oiaa else 0) + (1 if vna else 0)
    return {
        "meetings": candidates[:max_results],
        "total": len(candidates),
        "feeds_total": feeds_queried,
        "feeds_with_data": feeds_with_data,
    }


async def _empty_list() -> list:
    return []
