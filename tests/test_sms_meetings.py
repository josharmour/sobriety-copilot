"""SMS "where's a meeting?" (src/sms_meetings.py): parsing and the conversation, with fakes."""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.sms_meetings import MeetingFinder, parse

# Friday 6:30 PM Pacific.
NOW = datetime(2026, 10, 16, 18, 30, tzinfo=ZoneInfo("America/Los_Angeles")).astimezone(ZoneInfo("UTC"))
FRI, SAT = 5, 6


def _m(name, day, time, dist=1.2, fellowship="AA"):
    return {"name": name, "day": day, "time": time, "location": "St. Mark's Church",
            "formatted_address": "100 Main St, Oakland, CA 94612", "distance_mi": dist, "fellowship": fellowship}


MEETINGS = [_m("Early Birds", FRI, "19:00", 0.8), _m("Big Book Study", FRI, "20:00", 1.5),
            _m("Night Owls", FRI, "21:30", 2.0), _m("Sat Sunrise", SAT, "07:00", 0.5),
            _m("Sat Noon", SAT, "12:00", 3.1)]


class FakeStore(dict):
    def setex(self, key, ttl, value):
        self[key] = value

    def delete(self, key):
        self.pop(key, None)


class Fakes:
    def __init__(self, meetings=MEETINGS):
        self.store = FakeStore()
        self.searches = []
        self.geocoded = []
        self.meetings = meetings

    async def geocode(self, q):
        self.geocoded.append(q)
        places = {"94110": "94110, San Francisco, California", "oakland": "Oakland, California",
                  "berkeley": "Berkeley, California"}
        label = places.get(q.lower())
        return {"lat": 37.8, "lng": -122.27, "label": label} if label else None

    async def search(self, **kw):
        self.searches.append(kw)
        ms = self.meetings
        if kw.get("fellowship"):
            ms = [m for m in ms if m["fellowship"] == kw["fellowship"]]
        if kw.get("range_") == "tonight":
            ms = [m for m in ms if m["day"] == FRI and m["time"] >= "18:00"]
        if kw.get("range_") == "tomorrow":
            ms = [m for m in ms if m["day"] == SAT]
        return {"meetings": ms[: kw["max_results"]]}

    async def search_online(self, **kw):
        return {"meetings": [{"name": "Zoom Big Book", "fellowship": "AA", "is_live_now": True,
                              "conference_url": "https://zoom.us/j/1"}]}

    def finder(self):
        return MeetingFinder(store=self.store, geocode=self.geocode, search=self.search,
                             search_online=self.search_online, tz_for=lambda lng, lat: "America/Los_Angeles",
                             now_utc=lambda: NOW)


def run(f, phone, text):
    return asyncio.run(f.finder().handle(phone, text))


@pytest.mark.parametrize("text", [
    "where's a meeting", "wheres a meeting", "Where is a meeting?", "where are meetings near me",
    "any meetings tonight?", "meeting tonight in oakland", "NA meeting near 94110", "I need a meeting",
    "need a meeting now", "is there a meeting nearby", "find me an AA meeting", "meetings?", "meeting",
    "next meeting", "closest meeting", "online meeting now", "where can I find a meeting in Denver",
    "help me find a meeting", "any AA mtgs around here", "wheres the nearest meetin",
])
def test_meeting_requests_are_recognised(text):
    assert parse(text) is not None


@pytest.mark.parametrize("text", [
    "I went to a meeting today and it was great", "how do I share at a meeting?",
    "I'm scared to go to my first meeting", "what happens at an AA meeting", "my home group meeting was tense tonight",
    "what does the big book say about fear", "I feel so alone tonight",
])
def test_other_messages_are_left_to_the_conversation(text):
    assert parse(text) is None


def test_asks_once_then_answers_and_remembers():
    f = Fakes()
    q = run(f, "p1", "where's a meeting")
    assert q.startswith("What city or zip code")
    a = run(f, "p1", "94110")
    assert "Next meetings near San Francisco, CA" in a
    assert "7:00 PM" in a and "in 30 min" in a, "soonest first, local time"
    assert "Saved San Francisco, CA for next time" in a
    assert f.searches[-1]["now_day"] == FRI and f.searches[-1]["now_min"] == 18 * 60 + 30
    # Next time: no question.
    again = run(f, "p1", "wheres a meeting")
    assert again.startswith("Next meetings near") and "Saved" not in again


def test_place_and_time_in_one_message_need_no_question():
    f = Fakes()
    a = run(f, "p2", "any AA meetings tonight in Oakland?")
    assert a.startswith("Next meetings near Oakland, CA")
    assert f.geocoded == ["Oakland"] and f.searches[-1]["range_"] == "tonight"
    assert f.searches[-1]["fellowship"] == "AA" and f.searches[-1]["attendance"] == "inperson"


def test_follow_ups_refine_the_last_answer():
    f = Fakes()
    run(f, "p3", "meeting near 94110")
    more = run(f, "p3", "more")
    assert "Sat Sunrise" in more and "Early Birds" not in more
    tomorrow = run(f, "p3", "tomorrow?")
    assert "Sat Sunrise" in tomorrow and "tomorrow" in tomorrow
    assert run(f, "p3", "thanks!") is None


def test_now_with_nothing_soon_says_so():
    f = Fakes(meetings=[_m("Sat Sunrise", SAT, "07:00")])
    a = run(f, "p4", "meeting right now near 94110")
    assert a.startswith("Nothing starting in the next 2 hours")
    assert "Sat Sunrise" in a


def test_online_needs_no_location():
    f = Fakes()
    a = run(f, "p5", "online meeting now")
    assert "live now" in a and "zoom.us" in a and not f.geocoded


def test_someone_about_to_drink_gets_the_helpline_first():
    f = Fakes()
    a = run(f, "p6", "I'm about to drink, where's a meeting")
    assert a.startswith("If you're about to drink, call the A.A. helpline at (212) 647-1680")
    assert "city or zip" in a


@pytest.mark.parametrize("reply", ["never mind", "I'm feeling really low", "no thanks", "why?"])
def test_a_non_place_reply_drops_the_question(reply):
    f = Fakes()
    run(f, "p7", "where's a meeting")
    assert run(f, "p7", reply) is None
    assert not any(k.startswith("sc:sms:meet:pending") for k in f.store)


def test_unknown_place_asks_for_a_zip():
    f = Fakes()
    a = run(f, "p8", "meeting in Atlantis")
    assert a.startswith('I couldn\'t find "Atlantis"')
    b = run(f, "p8", "94110")
    assert b.startswith("Next meetings near San Francisco, CA")


def test_short_ask_uses_a_place_from_earlier_in_the_conversation():
    f = Fakes()
    a = asyncio.run(f.finder().handle("p9", "wheres a meeting",
                                      recent=["I'm in recovery and visiting Oakland this week", "it's hard"]))
    assert a.startswith("Next meetings near Oakland, CA (from your earlier message;")
    assert f.geocoded == ["Oakland"], "'in recovery' is not a place"
    assert not any(k.startswith("sc:sms:meet:place") for k in f.store), "a guess is never saved"


def test_short_ask_falls_back_to_the_phone_numbers_area():
    f = Fakes()
    a = asyncio.run(f.finder().handle("p10", "wheres a meeting", recent=[], number_area="Berkeley"))
    assert a.startswith("Next meetings near Berkeley, CA (going by your phone number's area;")
    assert "city or zip if you're elsewhere" in a


def test_a_stated_place_beats_every_guess_and_is_saved():
    f = Fakes()
    a = asyncio.run(f.finder().handle("p11", "meeting near 94110", recent=["visiting Oakland"],
                                      number_area="Berkeley"))
    assert a.startswith("Next meetings near San Francisco, CA:")
    again = asyncio.run(f.finder().handle("p11", "wheres a meeting", number_area="Berkeley"))
    assert again.startswith("Next meetings near San Francisco, CA:"), "remembered beats the number's area"


def test_nothing_to_go_on_still_asks():
    f = Fakes()
    a = asyncio.run(f.finder().handle("p12", "wheres a meeting", recent=["hi"], number_area=None))
    assert a.startswith("What city or zip code")


def test_follow_ups_keep_a_guess_a_guess():
    f = Fakes()
    asyncio.run(f.finder().handle("p13", "wheres a meeting", number_area="Berkeley"))
    more = asyncio.run(f.finder().handle("p13", "more", number_area="Berkeley"))
    assert "Saved" not in more
    assert not any(k.startswith("sc:sms:meet:place") for k in f.store)
    # Typing a place in a follow-up is stated, so it is saved.
    asyncio.run(f.finder().handle("p13", "in Oakland", number_area="Berkeley"))
    assert f.store["sc:sms:meet:place:p13"] == "Oakland"


def test_an_empty_window_shows_the_next_meetings_instead():
    f = Fakes(meetings=[_m("Sat Sunrise", SAT, "07:00", fellowship="NA")])
    a = run(f, "p14", "any NA meetings tonight in Oakland")
    assert a.startswith("No more NA meetings tonight near Oakland, CA. Next ones near Oakland, CA:")
    assert "Sat Sunrise" in a
