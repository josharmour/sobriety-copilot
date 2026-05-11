"""NA meeting lookup via the public BMLT aggregator.

BMLT (https://bmlt.app) is the standard meeting-list backend used by NA
service offices worldwide. The aggregator federates many regional root
servers, so a single query covers most of the US/Canada.

Spec: https://bmlt.app/semantic/semantic-interface/
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

# Aggregator root that federates regional NA BMLT servers.
BMLT_AGGREGATOR = "https://aggregator.bmltenabled.org/main_server/client_interface/json/"
BMLT_TIMEOUT = 6.0
BMLT_CACHE_TTL = 60 * 60  # 1h

# (lat, lng, radius_mi) -> (timestamp, results)
_cache: dict[tuple[float, float, float], tuple[float, list[dict[str, Any]]]] = {}
_cache_lock = asyncio.Lock()


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_day_bmlt(value: Any) -> int | None:
    """BMLT weekday_tinyint: 1=Sun, 2=Mon, ..., 7=Sat. Convert to 0-Sun..6-Sat."""
    try:
        d = int(value)
    except (TypeError, ValueError):
        return None
    if 1 <= d <= 7:
        return d - 1
    return None


def _normalize_time(value: Any) -> str:
    """BMLT start_time arrives as 'HH:MM:SS' or 'HH:MM'. Return 'HH:MM'."""
    if not value:
        return ""
    parts = str(value).split(":")
    if len(parts) < 2:
        return ""
    return f"{parts[0].zfill(2)}:{parts[1].zfill(2)}"


def _normalize_bmlt(raw: dict[str, Any]) -> dict[str, Any] | None:
    lat = _coerce_float(raw.get("latitude"))
    lng = _coerce_float(raw.get("longitude"))
    if lat is None or lng is None:
        return None

    formats_raw = raw.get("formats") or ""
    formats = [f.strip() for f in str(formats_raw).split(",") if f.strip()]
    formats_upper = {f.upper() for f in formats}
    is_online = bool({"VM", "TC", "ONL", "HY"} & formats_upper) or bool(raw.get("virtual_meeting_link"))
    is_inperson = "VM" not in formats_upper or "HY" in formats_upper

    address_parts = [
        raw.get("location_text") or raw.get("location_street"),
        raw.get("location_municipality"),
        raw.get("location_province"),
        raw.get("location_postal_code_1"),
    ]
    formatted = ", ".join(p for p in (str(s).strip() for s in address_parts if s) if p)

    name = (raw.get("meeting_name") or "").strip()
    return {
        "slug": str(raw.get("id_bigint") or "").strip() or None,
        "name": name,
        "group": "",
        "group_id": str(raw.get("worldid_mixed") or "").strip() or None,
        "day": _coerce_day_bmlt(raw.get("weekday_tinyint")),
        "time": _normalize_time(raw.get("start_time")),
        "time_formatted": "",
        "end_time": _normalize_time(raw.get("end_time")) if raw.get("end_time") else "",
        "formatted_address": formatted,
        "region": (raw.get("service_body_name") or "").strip(),
        "sub_region": (raw.get("location_municipality") or "").strip(),
        "location": (raw.get("location_text") or "").strip(),
        "location_url": "",
        "types": formats[:6],
        "url": (raw.get("meeting_name_url") or "").strip(),
        "website": "",
        "conference_url": (raw.get("virtual_meeting_link") or "").strip(),
        "conference_url_notes": (raw.get("virtual_meeting_additional_info") or "").strip(),
        "conference_phone": (raw.get("phone_meeting_number") or "").strip(),
        "attendance_option": "online" if is_online and not is_inperson else ("hybrid" if is_online and is_inperson else "in_person"),
        "approximate": False,
        "is_online": is_online,
        "is_inperson": is_inperson,
        "lat": lat,
        "lng": lng,
        "source": "BMLT (NA aggregator)",
        "source_home": "https://bmlt.app",
        "fellowship": "NA",
    }


async def fetch_na_meetings(lat: float, lng: float, radius_mi: float) -> list[dict[str, Any]]:
    """Query BMLT aggregator for NA meetings near (lat, lng) within radius_mi.

    Returns an empty list on any failure — meeting search shouldn't fail because
    one upstream is down.
    """
    cache_key = (round(lat, 3), round(lng, 3), round(radius_mi, 0))
    now = time.time()
    async with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and now - cached[0] < BMLT_CACHE_TTL:
            return cached[1]

    # geo_width: negative value = radius in miles
    params = {
        "switcher": "GetSearchResults",
        "lat_val": f"{lat}",
        "long_val": f"{lng}",
        "geo_width": f"-{int(radius_mi)}",
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                BMLT_AGGREGATOR,
                params=params,
                timeout=BMLT_TIMEOUT,
                headers={"User-Agent": "sobriety-copilot/1.0 (+meeting-aggregator)"},
                follow_redirects=True,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        async with _cache_lock:
            entry = _cache.get(cache_key)
            if entry:
                return entry[1]  # serve stale on failure
        return []

    if not isinstance(data, list):
        return []

    normalized: list[dict[str, Any]] = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        meeting = _normalize_bmlt(raw)
        if meeting:
            normalized.append(meeting)

    async with _cache_lock:
        _cache[cache_key] = (now, normalized)
    return normalized
