"""Aggregate Meeting Guide JSON feeds, filter by location, return inline results.

Feeds are kept in an in-process cache that a background loop refreshes every
hour (``run_refresh_loop``), so user requests read memory instead of waiting
on ~40 upstream sites. A feed that has never loaded is fetched on demand.
Per-feed health (count, status, last error) is exposed via ``feed_health`` so
a feed that silently drops to zero shows up in ``/api/meetings/sources`` and
the logs instead of just shrinking the catalog.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from math import asin, cos, radians, sin, sqrt
from typing import Any

import httpx

from .bmlt import fetch_na_meetings
from .feeds import FEEDS, USER_AGENT

log = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 60 * 60  # 1h — feeds change at most a few times a day
FETCH_TIMEOUT = 6.0  # on-demand (cold) fetch: one slow upstream shouldn't stall a search
REFRESH_TIMEOUT = 30.0  # background refresh: nobody is waiting, allow slow upstreams
REFRESH_CONCURRENCY = 8
EARTH_RADIUS_MI = 3958.8
MILES_PER_DEG_LAT = 69.0

DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

RANGES = ("upcoming", "today", "tonight", "tomorrow", "week", "any")
TIMES_OF_DAY = ("any", "morning", "afternoon", "evening", "late")

_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_cache_lock = asyncio.Lock()
_health: dict[str, dict[str, Any]] = {}
_refresh_loop_running = False


def _haversine_mi(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_MI * asin(sqrt(a))


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_day(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        d = int(value)
    except (TypeError, ValueError):
        return None
    return d if 0 <= d <= 6 else None


def _decode(value: str | None) -> str:
    return html.unescape(value).strip() if value else ""


def _coords(raw: dict[str, Any]) -> tuple[float | None, float | None]:
    """latitude/longitude (TSML), lat/lng, or a "lat,lng" `coordinates`
    string (code4recovery Sheets feeds)."""
    lat = _coerce_float(raw.get("latitude") or raw.get("lat"))
    lng = _coerce_float(raw.get("longitude") or raw.get("lng"))
    if lat is None or lng is None:
        coords = raw.get("coordinates")
        if isinstance(coords, str) and "," in coords:
            a, b = coords.split(",", 1)
            lat, lng = _coerce_float(a.strip()), _coerce_float(b.strip())
    if lat is None or lng is None:
        return None, None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0 and lng == 0):
        return None, None
    return lat, lng


def _normalize_meeting(raw: dict[str, Any], feed: dict[str, str]) -> dict[str, Any] | None:
    lat, lng = _coords(raw)
    if lat is None or lng is None:
        return None

    raw_types = raw.get("types") or []
    if isinstance(raw_types, str):
        raw_types = raw_types.split(",")
    types = [str(t).strip() for t in raw_types if str(t).strip()]

    formatted = _decode(raw.get("formatted_address"))
    if not formatted:
        parts = [
            _decode(raw.get("address")),
            _decode(raw.get("city")),
            _decode(raw.get("state")),
            _decode(raw.get("postal_code")),
        ]
        formatted = ", ".join(p for p in parts if p)

    attendance = (raw.get("attendance_option") or "").strip().lower()
    has_conf = bool(raw.get("conference_url") or raw.get("conference_phone"))
    type_set = {t.upper() for t in types}

    if attendance == "online":
        is_online, is_inperson = True, False
    elif attendance == "hybrid":
        is_online, is_inperson = True, True
    elif attendance == "in_person":
        is_online, is_inperson = False, True
    else:
        # Fall back to types/conference
        is_online = has_conf or bool(type_set & {"ONL", "VM", "TC"})
        is_inperson = bool(formatted) and not (is_online and not formatted)

    return {
        "slug": _decode(raw.get("slug")),
        "name": _decode(raw.get("name")),
        "group": _decode(raw.get("group")),
        "group_id": raw.get("group_id"),
        "day": _coerce_day(raw.get("day")),
        "time": raw.get("time", "") or "",
        "time_formatted": _decode(raw.get("time_formatted")),
        "end_time": raw.get("end_time", "") or "",
        "formatted_address": formatted,
        "region": _decode(raw.get("region")),
        "sub_region": _decode(raw.get("sub_region")),
        "location": _decode(raw.get("location")),
        "location_url": raw.get("location_url", "") or "",
        "types": types,
        "url": raw.get("url", "") or "",
        "website": raw.get("website", "") or "",
        "conference_url": raw.get("conference_url", "") or "",
        "conference_url_notes": _decode(raw.get("conference_url_notes")),
        "conference_phone": raw.get("conference_phone", "") or "",
        "attendance_option": attendance,
        "approximate": str(raw.get("approximate") or "").lower() in ("yes", "true", "1"),
        "is_online": is_online,
        "is_inperson": is_inperson,
        "lat": lat,
        "lng": lng,
        "source": feed["name"],
        "source_home": feed.get("home", ""),
        "fellowship": feed.get("fellowship", "AA"),
    }


def _record_health(feed: dict[str, str], *, count: int, raw_count: int, error: str | None) -> None:
    url = feed["url"]
    prev = _health.get(url, {})
    prev_count = prev.get("last_good_count") or 0
    if error:
        status = "error"
    elif count == 0:
        status = "empty"
    else:
        status = "ok"
    if status != "ok":
        log.warning("meeting feed %s: %s (%s)", feed["name"], status, error or f"{raw_count} rows, 0 usable")
    elif prev_count and count < prev_count * 0.5:
        log.warning("meeting feed %s dropped from %d to %d meetings", feed["name"], prev_count, count)
    _health[url] = {
        "name": feed["name"],
        "region": feed.get("region", ""),
        "fellowship": feed.get("fellowship", "AA"),
        "home": feed.get("home", ""),
        "status": status,
        "count": count,
        "raw_count": raw_count,
        "error": error,
        "checked_at": int(time.time()),
        # Keep the last good count so a failure still shows what was lost.
        "last_good_count": count if status == "ok" else prev.get("last_good_count", 0),
    }


async def _download_feed(
    client: httpx.AsyncClient, feed: dict[str, str], timeout: float
) -> list[dict[str, Any]] | None:
    """Fetch + normalize one feed and update the cache. None on failure."""
    url = feed["url"]
    try:
        resp = await client.get(
            url,
            timeout=timeout,
            # Honest UA: several Cloudflare-fronted intergroup sites 403 a
            # spoofed desktop-browser UA from a server IP but serve this one.
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        _record_health(feed, count=0, raw_count=0, error=f"{type(exc).__name__}: {exc}"[:200])
        return None

    if isinstance(data, dict):
        data = data.get("meetings", [])
    if not isinstance(data, list):
        _record_health(feed, count=0, raw_count=0, error="response is not a meeting list")
        return None

    normalized: list[dict[str, Any]] = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        meeting = _normalize_meeting(raw, feed)
        if meeting:
            normalized.append(meeting)

    _record_health(feed, count=len(normalized), raw_count=len(data), error=None)
    if not normalized:
        return None
    async with _cache_lock:
        _cache[url] = (time.time(), normalized)
    return normalized


async def _fetch_feed(client: httpx.AsyncClient, feed: dict[str, str]) -> list[dict[str, Any]]:
    """Cached feed contents for a search.

    While the background loop runs, any cached copy is served as-is (the loop
    keeps it fresh); without it, a copy older than the TTL is refetched.
    A feed with no cached copy is fetched now. Stale data beats no data.
    """
    url = feed["url"]
    async with _cache_lock:
        cached = _cache.get(url)
    if cached and (_refresh_loop_running or time.time() - cached[0] < CACHE_TTL_SECONDS):
        return cached[1]

    fresh = await _download_feed(client, feed, FETCH_TIMEOUT)
    if fresh is not None:
        return fresh
    return cached[1] if cached else []


async def refresh_all_feeds() -> dict[str, int]:
    """Re-download every feed (bounded concurrency). Returns name -> count."""
    sem = asyncio.Semaphore(REFRESH_CONCURRENCY)

    async def one(client: httpx.AsyncClient, feed: dict[str, str]) -> tuple[str, int]:
        async with sem:
            result = await _download_feed(client, feed, REFRESH_TIMEOUT)
        return feed["name"], len(result or [])

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[one(client, f) for f in FEEDS], return_exceptions=True)
        counts = dict(r for r in results if isinstance(r, tuple))
        # One retry for transient failures (seen: a big feed returning a
        # truncated body under concurrent load) so a blip at boot doesn't
        # leave a metro empty until the next hourly pass.
        failed = [f for f in FEEDS if not counts.get(f["name"])]
        if failed:
            await asyncio.sleep(5)
            for feed in failed:
                counts[feed["name"]] = len(await _download_feed(client, feed, REFRESH_TIMEOUT) or [])
    ok = sum(1 for c in counts.values() if c)
    log.info("meeting feeds refreshed: %d/%d with data, %d meetings", ok, len(FEEDS), sum(counts.values()))
    return counts


async def warmup_feeds() -> None:
    """Pre-fetch all feeds so the first user request hits a warm cache."""
    await refresh_all_feeds()


async def run_refresh_loop(interval: float = CACHE_TTL_SECONDS) -> None:
    """Keep every feed warm forever: refresh now, then every `interval`."""
    global _refresh_loop_running
    _refresh_loop_running = True
    try:
        while True:
            try:
                await refresh_all_feeds()
            except Exception:
                log.exception("meeting feed refresh failed")
            await asyncio.sleep(interval)
    finally:
        _refresh_loop_running = False


def feed_health() -> dict[str, Any]:
    """Per-feed status for /api/meetings/sources, worst first."""
    rows = []
    for feed in FEEDS:
        h = _health.get(feed["url"])
        rows.append(h or {
            "name": feed["name"],
            "region": feed.get("region", ""),
            "fellowship": feed.get("fellowship", "AA"),
            "home": feed.get("home", ""),
            "status": "pending",
            "count": 0,
        })
    order = {"error": 0, "empty": 1, "pending": 2, "ok": 3}
    rows.sort(key=lambda r: (order.get(r["status"], 9), r["name"]))
    return {
        "feeds": rows,
        "feeds_total": len(FEEDS),
        "feeds_ok": sum(1 for r in rows if r["status"] == "ok"),
        "meetings_total": sum(r.get("count") or 0 for r in rows),
    }


# ---------------------------------------------------------------------------
# Time-aware selection. Mirrors the Flutter sheet's client-side filters so the
# server can pick the right `max` meetings out of thousands in a dense metro,
# instead of the 100 nearest (which in NYC covered ~1 mile and ~14/day).
# ---------------------------------------------------------------------------

def _time_as_minutes(t: str) -> int:
    parts = (t or "").split(":")
    if len(parts) < 2:
        return -1
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        return -1
    return h * 60 + m if 0 <= h <= 24 and 0 <= m <= 59 else -1


def _time_of_day_bucket(t: str) -> str | None:
    minutes = _time_as_minutes(t)
    if minutes < 0:
        return None
    if 5 * 60 <= minutes < 12 * 60:
        return "morning"
    if 12 * 60 <= minutes < 17 * 60:
        return "afternoon"
    if 17 * 60 <= minutes < 21 * 60:
        return "evening"
    return "late"


def _minutes_until_next(m: dict[str, Any], now_day: int, now_min: int) -> int | None:
    day = m.get("day")
    t = _time_as_minutes(m.get("time") or "")
    if not isinstance(day, int) or not 0 <= day <= 6 or t < 0:
        return None
    total = ((day - now_day + 7) % 7) * 1440 + (t - now_min)
    if total < 0:
        total += 7 * 1440
    return total


def _in_range(m: dict[str, Any], rng: str, now_day: int, now_min: int) -> bool:
    if rng in ("upcoming", "week", "any"):
        return True
    day = m.get("day")
    t = _time_as_minutes(m.get("time") or "")
    if rng == "today":
        return day == now_day and t >= now_min
    if rng == "tonight":
        if now_min < 4 * 60:
            return day == now_day and now_min <= t < 4 * 60
        return day == now_day and t >= max(now_min, 18 * 60)
    if rng == "tomorrow":
        return day == (now_day + 1) % 7
    return True


_NAME_RE = re.compile(r"[^a-z0-9]+")


def _dedupe_key(m: dict[str, Any]) -> tuple:
    """Same meeting listed by two overlapping feeds (e.g. neighbouring
    intergroups): same fellowship, slot, ~100 m location and name stem."""
    name = _NAME_RE.sub("", (m.get("name") or "").lower())[:16]
    return (
        (m.get("fellowship") or "").lower(),
        m.get("day"),
        (m.get("time") or "")[:5],
        round(m["lat"], 3),
        round(m["lng"], 3),
        name,
    )


async def search_meetings(
    lat: float,
    lng: float,
    radius_mi: float = 25.0,
    max_results: int = 30,
    day: int | None = None,
    attendance: str | None = None,
    fellowship: str | None = None,
    range_: str | None = None,
    time_of_day: str | None = None,
    now_day: int | None = None,
    now_min: int | None = None,
) -> dict[str, Any]:
    """Aggregate all configured feeds and return meetings within the given radius.

    `attendance`:
        "inperson" — drop online-only meetings
        "online"   — keep only meetings flagged as online
        None / "all" — no filter
    `fellowship`:
        "AA" — only AA intergroup feeds
        "NA" — only NA via the BMLT aggregator
        any other value — case-insensitive match against a feed's
            "fellowship" (e.g. "cma", "recovery dharma")
        None / "all" — everything
    `range_` / `time_of_day` (needs `now_day` 0=Sun..6 and `now_min`, the
    client's local clock): filter like the app's Day/Time chips and, except
    for the grouped "week"/"any" views, return the soonest meetings first
    instead of the nearest. Without them results are nearest-first, as older
    app builds expect.
    """
    fellowship_norm = (fellowship or "").strip().lower() or None
    if fellowship_norm == "all":
        fellowship_norm = None

    def _feed_wanted(feed: dict[str, str]) -> bool:
        if fellowship_norm is None:
            return True
        return feed.get("fellowship", "AA").lower() == fellowship_norm

    wanted_feeds = [f for f in FEEDS if _feed_wanted(f)]
    want_na = fellowship_norm in (None, "na")

    async with httpx.AsyncClient() as client:
        feed_lists, na_results = await asyncio.gather(
            asyncio.gather(*[_fetch_feed(client, feed) for feed in wanted_feeds]),
            fetch_na_meetings(lat, lng, radius_mi) if want_na else _empty_list(),
        )

    want_inperson = attendance == "inperson"
    want_online = attendance == "online"
    # Cheap bounding box before the haversine: most of ~40k meetings are
    # thousands of miles away.
    dlat = radius_mi / MILES_PER_DEG_LAT
    dlng = radius_mi / max(MILES_PER_DEG_LAT * cos(radians(lat)), 1e-6)

    candidates: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    feeds_with_data = 0

    def consider(meeting: dict[str, Any]) -> None:
        if abs(meeting["lat"] - lat) > dlat:
            return
        if dlng < 180 and abs(((meeting["lng"] - lng + 180) % 360) - 180) > dlng:
            return
        if want_inperson and not meeting.get("is_inperson"):
            return
        if want_online and not meeting.get("is_online"):
            return
        distance = _haversine_mi(lat, lng, meeting["lat"], meeting["lng"])
        if distance > radius_mi:
            return
        key = _dedupe_key(meeting)
        if key in seen:
            return
        seen.add(key)
        day_idx = meeting.get("day")
        day_name = DAY_NAMES[day_idx] if isinstance(day_idx, int) else None
        candidates.append({
            **meeting,
            "distance_mi": round(distance, 1),
            "day_name": day_name,
            "online": meeting.get("is_online", False),
        })

    for feed_meetings in feed_lists:
        if feed_meetings:
            feeds_with_data += 1
        for meeting in feed_meetings:
            consider(meeting)

    for meeting in na_results:
        consider(meeting)
    if na_results:
        feeds_with_data += 1

    if day is not None:
        candidates = [c for c in candidates if c.get("day") == day]

    time_aware = now_day is not None and now_min is not None and bool(range_ or time_of_day)
    rng = range_ if range_ in RANGES else "any"
    if time_aware:
        tod = time_of_day if time_of_day in TIMES_OF_DAY else "any"
        candidates = [
            c for c in candidates
            if _in_range(c, rng, now_day, now_min)
            and (tod == "any" or _time_of_day_bucket(c.get("time") or "") == tod)
        ]

    if time_aware and rng not in ("week", "any"):
        def soonest(m: dict[str, Any]) -> tuple[int, float]:
            until = _minutes_until_next(m, now_day, now_min)
            return (until if until is not None else 1 << 30, m["distance_mi"])

        candidates.sort(key=soonest)
    else:
        candidates.sort(key=lambda m: (
            m["distance_mi"],
            m.get("day") if m.get("day") is not None else 7,
            m.get("time", "") or "",
        ))

    return {
        "meetings": candidates[:max_results],
        "total_in_radius": len(candidates),
        "feeds_total": len(wanted_feeds) + (1 if want_na else 0),
        "feeds_with_data": feeds_with_data,
    }


async def _empty_list() -> list:
    return []
