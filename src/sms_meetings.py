"""Meeting lookups over SMS, with as few questions as possible.

"where's a meeting", "any meetings tonight in Oakland?", "NA meeting near 94110"
→ the next meetings near them. The only question ever asked is "what city or
zip?", and only when the message didn't say where and no place is remembered.
Timing defaults to the meetings starting soonest from now, in that place's
local time; "tonight", "tomorrow", "now" and "online" are honoured when said.
Short follow-ups right after an answer ("tomorrow?", "more", "online") refine
it, and a fresh city or zip searches there instead.

With no place in the message, it uses (in order) the place they gave last
time, a zip or city mentioned earlier in the conversation, then where their
phone number was issued (Twilio's FromZip / FromCity + FromState — texts carry
no IP to locate). Only with none of those does it ask; a guess says so and
how to correct it, and is never saved.

Someone who sounds about to drink gets the A.A. helpline first, then meetings,
per the crisis rules.

Privacy: the remembered place is the text they sent (a city or zip), kept 30
days under a hashed key — never coordinates.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Protocol
from zoneinfo import ZoneInfo

from src.prompts.templates import AA_HELPLINE

PLACE_TTL = 30 * 86400        # remembered city/zip
PENDING_TTL = 30 * 60         # waiting for "what city or zip?"
LAST_TTL = 30 * 60            # follow-ups ("more", "tomorrow?") refine the last answer
SHOW = 3                      # meetings per reply
NOW_WINDOW_MIN = 120          # "now" = starting within two hours
RADII_MI = (15.0, 40.0)       # widen once if the nearby list is thin
DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

_MEETING = re.compile(r"\b(?:meet(?:ing|ings|in|ins|n)|mtgs?)\b", re.IGNORECASE)
_SEEKING = re.compile(
    r"\b(?:where(?:'?s|s| is| are| can)?|find|any|anything|next|nearest|closest|near(?:by)?|around|close by|"
    r"local|need|looking|is there|are there|know (?:of|a|any)|got a|show me|list|open|soon|asap)\b",
    re.IGNORECASE)
_WHEN = re.compile(r"\b(?:tonight|today|tomorrow|now|right now|this (?:morning|afternoon|evening))\b", re.IGNORECASE)
# Talking *about* meetings rather than looking for one.
_NARRATIVE = re.compile(
    r"\b(?:went|was|were|had|got back|came back|just left|left early|last night|yesterday|share|shared|sharing|"
    r"speaker|chair(?:ed|ing)?|home group|what happens|what (?:do|should) i (?:say|do)|how (?:do|should|can) i|"
    r"afraid|scared|nervous|anxious|first (?:ever )?meeting|after the meeting|at the meeting)\b",
    re.IGNORECASE)
_ZIP = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
_PLACE = re.compile(
    r"\b(?:in|near|around|by|close to|at)\s+([A-Za-z][A-Za-z .,'-]{1,60}?)\s*"
    r"(?:\b(?:tonight|today|tomorrow|now|right now|asap|soon|please|this (?:morning|afternoon|evening))\b.*)?[?.!]*$",
    re.IGNORECASE)
_NOT_A_PLACE = {"me", "here", "my area", "the area", "my town", "town", "you", "the morning", "the evening",
                "the afternoon", "person", "real life"}
_FILLER = re.compile(r"^(?:i'?m|i am|im|we'?re|it'?s|its|in|near|around|at|just|um+|uh+|ok(?:ay)?|sure)\b[\s,]*",
                     re.IGNORECASE)
_URGENT = re.compile(
    r"\b(?:about to (?:drink|use)|going to (?:drink|use)|want to (?:drink|use)|wanna (?:drink|use)|"
    r"(?:drink|use|relapse)\w* (?:right )?now|can'?t stop|craving|suicid\w*|kill (?:my|him|her)self|hurt myself)\b",
    re.IGNORECASE)
_MORE = re.compile(r"^\s*(?:more|others?|any (?:more|others)|next(?: ones?)?|what else|keep going)\s*[?.!]*\s*$",
                   re.IGNORECASE)


@dataclass
class Ask:
    range: str = "upcoming"          # upcoming | now | today | tonight | tomorrow
    fellowship: str | None = None    # "AA" | "NA" | None
    online: bool = False
    place: str | None = None         # text to geocode, if the message said where
    urgent: bool = False
    offset: int = 0
    guessed: bool = False             # place inferred (earlier message / number's area), never saved

    def to_json(self) -> str:
        return json.dumps(self.__dict__)

    @classmethod
    def from_json(cls, raw: str | bytes | None) -> "Ask | None":
        if not raw:
            return None
        try:
            return cls(**json.loads(raw))
        except Exception:
            return None


def _when(text: str) -> str | None:
    t = text.lower()
    if re.search(r"\btonight|this evening\b", t):
        return "tonight"
    if "tomorrow" in t:
        return "tomorrow"
    if re.search(r"\b(?:right now|now|asap|soon)\b", t):
        return "now"
    if re.search(r"\btoday|this (?:morning|afternoon)\b", t):
        return "today"
    return None


def _fellowship(text: str) -> str | None:
    if re.search(r"\b(?:na|narcotics)\b", text, re.IGNORECASE):
        return "NA"
    if re.search(r"\b(?:aa|a\.a\.|alcoholics)\b", text, re.IGNORECASE):
        return "AA"
    return None


def place_in(text: str) -> str | None:
    """A zip code or "in/near <place>" from the message, if it names one."""
    z = _ZIP.search(text)
    if z:
        return z.group(1)
    m = _PLACE.search(text.strip())
    if m:
        place = m.group(1).strip(" ,.-'")
        if place.lower() not in _NOT_A_PLACE and not _MEETING.search(place):
            return place
    return None


# Words that mean a reply to "what city or zip?" is something else (a feeling,
# a no-thanks, a question) — it goes to the normal conversation instead.
_NOT_PLACE_WORDS = {"i", "me", "my", "feel", "feeling", "felt", "want", "need", "help", "sad", "scared", "drink",
                    "drinking", "thanks", "thank", "no", "nope", "nah", "never", "nevermind", "cancel", "forget",
                    "yes", "yeah", "ok", "okay", "why", "what", "how", "who", "when", "not", "don't", "dont"}


def _answer_place(text: str) -> str | None:
    """The place in a reply to "what city or zip?", or None if the reply is about something else."""
    t = text.strip()
    if _ZIP.search(t):
        return _ZIP.search(t).group(1)
    named = place_in(t)
    if named:
        return named
    rest = _FILLER.sub("", _FILLER.sub("", t)).strip(" .!?")
    words = re.findall(r"[A-Za-z']+", rest.lower())
    if not words or len(words) > 5 or any(w in _NOT_PLACE_WORDS for w in words) or rest.lower() in _NOT_A_PLACE:
        return None
    return rest


# Words after "in" that aren't places ("in recovery", "in the program").
_PROGRAM_WORDS = {"recovery", "program", "the program", "aa", "na", "a.a", "the rooms", "rehab", "treatment",
                  "detox", "sobriety", "step", "steps", "meeting", "meetings", "god", "pain", "trouble", "love"}


def _mentioned_place(text: str) -> str | None:
    """A zip, or a capitalised "in/near <Place>", from an earlier message — not "in recovery"."""
    z = _ZIP.search(text or "")
    if z:
        return z.group(1)
    m = re.search(r"\b(?:in|near|around|visiting|staying in|live in|moved to)\s+([A-Z][A-Za-z.'-]+(?:[ ,]+[A-Z][A-Za-z.'-]+){0,3})",
                  text or "")
    if not m:
        return None
    place = m.group(1).strip(" ,.")
    return None if place.lower() in _PROGRAM_WORDS or place.lower() in _NOT_A_PLACE else place


def parse(text: str) -> Ask | None:
    """A meeting request, or None if the message isn't asking where/when a meeting is."""
    t = (text or "").strip()
    if not t or not _MEETING.search(t) or _NARRATIVE.search(t):
        return None
    if not (_SEEKING.search(t) or _WHEN.search(t) or len(t.split()) <= 4):
        return None
    return Ask(range=_when(t) or "upcoming", fellowship=_fellowship(t),
               online=bool(re.search(r"\b(?:online|zoom|virtual)\b", t, re.IGNORECASE)),
               place=place_in(t), urgent=bool(_URGENT.search(t)))


class Store(Protocol):
    def get(self, key: str) -> Any: ...
    def setex(self, key: str, ttl: int, value: str) -> Any: ...
    def delete(self, key: str) -> Any: ...


Geocoder = Callable[[str], Awaitable[dict[str, Any] | None]]   # -> {"lat","lng","label"} | None
Search = Callable[..., Awaitable[dict[str, Any]]]
TzLookup = Callable[[float, float], str | None]


@dataclass
class MeetingFinder:
    store: Store
    geocode: Geocoder
    search: Search
    search_online: Search
    tz_for: TzLookup
    now_utc: Callable[[], datetime] = field(default=lambda: datetime.now(ZoneInfo("UTC")))

    def _key(self, kind: str, phone_key: str) -> str:
        return f"sc:sms:meet:{kind}:{phone_key}"

    async def handle(self, phone_key: str, text: str, recent: list[str] | None = None,
                     number_area: str | None = None) -> str | None:
        """The reply if this message asks for (or completes, or refines) a meeting lookup; else None.

        ``recent``: their earlier messages, newest last (a place mentioned there
        is used before asking). ``number_area``: where their phone number was
        issued (Twilio's FromZip, or FromCity + FromState) — the last guess
        before asking "what city or zip?".
        """
        t = (text or "").strip()
        ask = parse(t)
        pending = Ask.from_json(self.store.get(self._key("pending", phone_key)))
        last = Ask.from_json(self.store.get(self._key("last", phone_key)))

        if ask is None and pending is not None:
            # We asked "what city or zip?" — a reply that looks like a place is the answer.
            place = _answer_place(t)
            if place:
                pending.place = place
                ask = pending
            if ask is None:
                self.store.delete(self._key("pending", phone_key))
                return None

        if ask is None and last is not None and len(t.split()) <= 5:
            ask = self._refine(last, t)
        if ask is None:
            return None

        if ask.online:
            self.store.delete(self._key("pending", phone_key))
            self.store.setex(self._key("last", phone_key), LAST_TTL, ask.to_json())
            return await self._online_reply(ask)

        remembered = self._decode(self.store.get(self._key("place", phone_key)))
        # Where to look, best evidence first; a guess is never saved.
        guess_note = ""
        place, where = ask.place or remembered, None
        if place:
            where = await self.geocode(place)
            if not where and ask.place:
                self.store.setex(self._key("pending", phone_key), PENDING_TTL,
                                 Ask(**{**ask.__dict__, "place": None}).to_json())
                return f"I couldn't find \"{place}\". What's your zip code (or city and state)?"
        if not where:
            for earlier in reversed(recent or []):
                mentioned = _mentioned_place(earlier)
                if mentioned and (where := await self.geocode(mentioned)):
                    place, guess_note = mentioned, "from your earlier message"
                    break
        if not where and number_area:
            if where := await self.geocode(number_area):
                place, guess_note = number_area, "going by your phone number's area"
        if not where:
            self.store.setex(self._key("pending", phone_key), PENDING_TTL, ask.to_json())
            first = (f"If you're about to drink, call {AA_HELPLINE} now. " if ask.urgent else "")
            return first + "What city or zip code are you in? I'll find the next meetings near you."

        self.store.delete(self._key("pending", phone_key))
        ask.guessed = bool(guess_note) or (ask.guessed and place == ask.place)
        if not ask.guessed:
            self.store.setex(self._key("place", phone_key), PLACE_TTL, place)
        ask.place = place
        self.store.setex(self._key("last", phone_key), LAST_TTL, ask.to_json())
        reply = await self._nearby_reply(ask, where)
        if reply.startswith("I couldn't"):
            return reply
        if guess_note:
            reply = reply.replace(":\n", f" ({guess_note}; text your city or zip if you're elsewhere):\n", 1)
        elif remembered is None and not ask.guessed:
            reply = reply.replace("\nReply MORE,", f"\nSaved {short_label(where.get('label') or place)} "
                                                   "for next time. Reply MORE,", 1)
        return reply

    @staticmethod
    def _decode(raw: Any) -> str | None:
        if raw is None:
            return None
        return raw.decode() if isinstance(raw, bytes) else str(raw)

    @staticmethod
    def _refine(last: Ask, t: str) -> Ask | None:
        """Follow-ups to the last answer: more, another time, online, another fellowship or place."""
        if _MORE.match(t):
            return Ask(**{**last.__dict__, "offset": last.offset + SHOW, "urgent": False})
        when = _when(t)
        fellowship = _fellowship(t)
        online = bool(re.search(r"\b(?:online|zoom|virtual)\b", t, re.IGNORECASE))
        place = place_in(t) if (_ZIP.search(t) or re.match(r"^\s*(?:in|near|around)\b", t, re.IGNORECASE)) else None
        if not (when or fellowship or online or place):
            return None
        return Ask(range=when or last.range, fellowship=fellowship or last.fellowship, online=online,
                   place=place or last.place, offset=0, guessed=last.guessed and not place)

    def _local_now(self, lat: float, lng: float) -> datetime:
        try:
            tz = ZoneInfo(self.tz_for(lng, lat) or "America/Los_Angeles")
        except Exception:
            tz = ZoneInfo("America/Los_Angeles")
        return self.now_utc().astimezone(tz)

    async def _nearby_reply(self, ask: Ask, where: dict[str, Any]) -> str:
        now = self._local_now(where["lat"], where["lng"])
        now_day = (now.weekday() + 1) % 7          # Meeting Guide: 0 = Sunday
        now_min = now.hour * 60 + now.minute
        rng = "upcoming" if ask.range == "now" else ask.range
        meetings: list[dict[str, Any]] = []
        for radius in RADII_MI:
            res = await self.search(lat=where["lat"], lng=where["lng"], radius_mi=radius,
                                    max_results=ask.offset + 12, attendance="inperson",
                                    fellowship=ask.fellowship, range_=rng, now_day=now_day, now_min=now_min)
            meetings = res.get("meetings") or []
            if len(meetings) >= ask.offset + SHOW:
                break
        label = short_label(where.get("label") or ask.place or "")
        head = f"If you're about to drink, call {AA_HELPLINE} now. Meetings near" if ask.urgent \
            else "Next meetings near"
        if ask.range == "now":
            soon = [m for m in meetings if (_until(m, now_day, now_min) or 1 << 30) <= NOW_WINDOW_MIN]
            if soon:
                meetings = soon
            else:
                head = f"Nothing starting in the next 2 hours near {label}. Next up near"
        if not meetings and rng in ("today", "tonight", "tomorrow"):
            # Nothing left in the asked window: show what's next rather than a dead end.
            res = await self.search(lat=where["lat"], lng=where["lng"], radius_mi=RADII_MI[-1],
                                    max_results=ask.offset + 12, attendance="inperson",
                                    fellowship=ask.fellowship, range_="upcoming", now_day=now_day, now_min=now_min)
            meetings = res.get("meetings") or []
            if meetings:
                what = f"{ask.fellowship} meetings" if ask.fellowship else "meetings"
                more = "No more" if rng in ("today", "tonight") else "No"
                head = f"{more} {what} {rng} near {label}. Next ones near"
        page = meetings[ask.offset:ask.offset + SHOW]
        if not page:
            if ask.offset:
                return f"That's all I have listed near {label}. Reply ONLINE for online meetings."
            when = {"tonight": " tonight", "tomorrow": " tomorrow", "today": " today"}.get(ask.range, "")
            return (f"I couldn't find in-person {ask.fellowship + ' ' if ask.fellowship else ''}meetings listed"
                    f"{when} near {label}. Reply ONLINE for online meetings starting soon, or try another city or zip.")
        lines = [f"{head} {label}:"]
        for m in page:
            lines.append("- " + _line(m, now_day, now_min))
        lines.append("Reply MORE, TOMORROW, ONLINE, or another city/zip.")
        return "\n".join(lines)

    async def _online_reply(self, ask: Ask) -> str:
        res = await self.search_online(fellowship=ask.fellowship, max_results=ask.offset + 10)
        page = (res.get("meetings") or [])[ask.offset:ask.offset + SHOW]
        if not page:
            return "I couldn't load online meetings right now. Try again in a few minutes."
        lines = ["Online meetings starting soonest:" if not ask.urgent else
                 f"If you're about to drink, call {AA_HELPLINE} now. Online meetings starting soonest:"]
        for m in page:
            starts = m.get("starts_in_minutes")
            when = ("live now" if m.get("is_live_now") else
                    f"in {starts} min" if isinstance(starts, int) and starts < 60 else
                    f"{m.get('day_name') or ''} {m.get('time_formatted') or ''} {_tz_short(m.get('timezone'))}".strip())
            link = m.get("conference_url") or m.get("url") or ""
            lines.append(f"- {when}: {_short(m.get('name'), 40)} ({m.get('fellowship') or 'AA'}) {link}".rstrip())
        lines.append("Reply MORE for more.")
        return "\n".join(lines)


def _until(m: dict[str, Any], now_day: int, now_min: int) -> int | None:
    day, t = m.get("day"), _minutes(m.get("time") or "")
    if not isinstance(day, int) or t < 0:
        return None
    total = ((day - now_day) % 7) * 1440 + (t - now_min)
    return total + 7 * 1440 if total < 0 else total


def _minutes(t: str) -> int:
    try:
        h, m = t.split(":")[:2]
        return int(h) * 60 + int(m)
    except Exception:
        return -1


def _clock(t: str) -> str:
    mins = _minutes(t)
    if mins < 0:
        return t or "?"
    h, m = divmod(mins, 60)
    suffix = "AM" if h < 12 or h == 24 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {suffix}"


def _line(m: dict[str, Any], now_day: int, now_min: int) -> str:
    until = _until(m, now_day, now_min)
    clock = _clock(m.get("time") or "")
    day = m.get("day")
    if until is not None and until <= 60:
        when = f"in {until} min ({clock})" if until > 0 else f"starting now ({clock})"
    elif day == now_day:
        when = f"{clock} {'tonight' if _minutes(m.get('time') or '') >= 17 * 60 else 'today'}"
    elif isinstance(day, int) and day == (now_day + 1) % 7:
        when = f"{clock} tomorrow"
    else:
        when = f"{clock} {DAY_NAMES[day] if isinstance(day, int) else ''}".strip()
    venue = _short(m.get("location"), 30)
    street = _short((m.get("formatted_address") or "").split(",")[0], 30)
    where = venue
    if street and street.lower() != venue.lower():
        where = f"{venue}, {street}" if venue else street
    dist = m.get("distance_mi")
    fellowship = m.get("fellowship") or "AA"
    parts = [f"{when}: {_short(m.get('name'), 36)} ({fellowship})", where]
    if isinstance(dist, (int, float)):
        parts.append(f"{dist:g} mi")
    return ", ".join(p for p in parts if p)


_STATES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO",
    "Connecticut": "CT", "Delaware": "DE", "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA",
    "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI",
    "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC",
    "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA",
    "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY",
}


def short_label(label: str) -> str:
    """"94110, San Francisco, California" → "San Francisco, CA"."""
    parts = [p.strip() for p in (label or "").split(",") if p.strip()]
    if parts and re.fullmatch(r"\d{5}(?:-\d{4})?", parts[0]) and len(parts) > 1:
        parts = parts[1:]
    parts = [_STATES.get(p, p) for p in parts[:2]]
    return ", ".join(parts) or label


def _short(text: Any, n: int) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _tz_short(tz: Any) -> str:
    return {"America/New_York": "ET", "America/Chicago": "CT", "America/Denver": "MT",
            "America/Los_Angeles": "PT", "America/Phoenix": "MST"}.get(str(tz or ""), "")
