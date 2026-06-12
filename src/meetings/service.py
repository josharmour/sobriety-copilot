"""Aggregate Meeting Guide JSON feeds, filter by location, return inline results."""

from __future__ import annotations

import asyncio
import html
import time
from math import asin, cos, radians, sin, sqrt
from typing import Any

import httpx

from .bmlt import fetch_na_meetings
from .feeds import FEEDS

CACHE_TTL_SECONDS = 60 * 60  # 1h — feeds change at most a few times a day
FETCH_TIMEOUT = 6.0  # one slow upstream shouldn't stall the whole search
EARTH_RADIUS_MI = 3958.8

DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_cache_lock = asyncio.Lock()


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


def _normalize_meeting(raw: dict[str, Any], feed: dict[str, str]) -> dict[str, Any] | None:
    lat = _coerce_float(raw.get("latitude") or raw.get("lat"))
    lng = _coerce_float(raw.get("longitude") or raw.get("lng"))
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
        "approximate": (raw.get("approximate") or "").lower() in ("yes", "true", "1"),
        "is_online": is_online,
        "is_inperson": is_inperson,
        "lat": lat,
        "lng": lng,
        "source": feed["name"],
        "source_home": feed.get("home", ""),
        "fellowship": feed.get("fellowship", "AA"),
    }


async def _fetch_feed(client: httpx.AsyncClient, feed: dict[str, str]) -> list[dict[str, Any]]:
    url = feed["url"]
    async with _cache_lock:
        cached = _cache.get(url)
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
            entry = _cache.get(url)
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
        meeting = _normalize_meeting(raw, feed)
        if meeting:
            normalized.append(meeting)

    async with _cache_lock:
        _cache[url] = (time.time(), normalized)
    return normalized


async def warmup_feeds() -> None:
    """Pre-fetch all feeds so the first user request hits a warm cache."""
    async with httpx.AsyncClient() as client:
        await asyncio.gather(*[_fetch_feed(client, feed) for feed in FEEDS], return_exceptions=True)


async def search_meetings(
    lat: float,
    lng: float,
    radius_mi: float = 25.0,
    max_results: int = 30,
    day: int | None = None,
    attendance: str | None = None,
    fellowship: str | None = None,
) -> dict[str, Any]:
    """Aggregate all configured feeds and return meetings within the given radius.

    `attendance`:
        "inperson" — drop online-only meetings
        "online"   — keep only meetings flagged as online
        None / "all" — no filter
    `fellowship`:
        "AA" — only AA intergroup feeds
        "NA" — only NA via the BMLT aggregator
        None / "all" — both
    """
    fellowship_norm = (fellowship or "").upper() if fellowship else None
    want_aa = fellowship_norm in (None, "ALL", "AA")
    want_na = fellowship_norm in (None, "ALL", "NA")

    async with httpx.AsyncClient() as client:
        aa_task = asyncio.gather(*[_fetch_feed(client, feed) for feed in FEEDS]) if want_aa else None
        na_task = fetch_na_meetings(lat, lng, radius_mi) if want_na else None
        aa_results, na_results = await asyncio.gather(
            aa_task or _empty_list(),
            na_task or _empty_list(),
        )

    if isinstance(aa_results, list) and aa_results and isinstance(aa_results[0], list):
        aa_feed_lists = aa_results
    else:
        aa_feed_lists = []

    want_inperson = attendance == "inperson"
    want_online = attendance == "online"

    candidates: list[dict[str, Any]] = []
    feeds_with_data = 0

    def consider(meeting: dict[str, Any]) -> None:
        if want_inperson and not meeting.get("is_inperson"):
            return
        if want_online and not meeting.get("is_online"):
            return
        distance = _haversine_mi(lat, lng, meeting["lat"], meeting["lng"])
        if distance > radius_mi:
            return
        day_idx = meeting.get("day")
        day_name = DAY_NAMES[day_idx] if isinstance(day_idx, int) else None
        candidates.append({
            **meeting,
            "distance_mi": round(distance, 1),
            "day_name": day_name,
            "online": meeting.get("is_online", False),
        })

    for feed_meetings in aa_feed_lists:
        if feed_meetings:
            feeds_with_data += 1
        for meeting in feed_meetings:
            consider(meeting)

    if isinstance(na_results, list):
        for meeting in na_results:
            consider(meeting)
        if na_results:
            feeds_with_data += 1

    if day is not None:
        candidates = [c for c in candidates if c.get("day") == day]

    candidates.sort(key=lambda m: (
        m["distance_mi"],
        m.get("day", 7),
        m.get("time", "") or "",
    ))

    return {
        "meetings": candidates[:max_results],
        "total_in_radius": len(candidates),
        "feeds_total": len(FEEDS) + (1 if want_na else 0),
        "feeds_with_data": feeds_with_data,
    }


async def _empty_list() -> list:
    return []
