"""Meeting catalog: feed normalization, BMLT query, dedupe, time-aware selection.

Offline — upstream fetches are stubbed.  python -m unittest tests.test_meetings
"""

import asyncio
import unittest
from unittest import mock

from src.meetings import bmlt, service
from src.meetings.feeds import FEEDS, USER_AGENT

FEED = {"name": "Test Intergroup", "home": "https://example.org", "url": "https://example.org/feed"}
HERE = (40.0, -75.0)


def _raw(name="Big Book Study", day=1, time="19:00", lat=40.001, lng=-75.001, **kw):
    return {"name": name, "day": day, "time": time, "latitude": lat, "longitude": lng,
            "formatted_address": "1 Main St, Town, PA 19000, USA", **kw}


def _meeting(**kw):
    return service._normalize_meeting(_raw(**kw), FEED)


class NormalizeTests(unittest.TestCase):
    def test_latitude_longitude(self):
        m = _meeting()
        self.assertEqual((m["lat"], m["lng"]), (40.001, -75.001))

    def test_sheets_coordinates_string(self):
        # code4recovery Sheets feeds (e.g. Silicon Valley) carry "lat,lng".
        raw = {"name": "No Bull", "day": 2, "time": "17:00", "coordinates": "37.24887,-121.87943"}
        m = service._normalize_meeting(raw, FEED)
        self.assertIsNotNone(m)
        self.assertAlmostEqual(m["lat"], 37.24887)
        self.assertAlmostEqual(m["lng"], -121.87943)

    def test_missing_or_null_island_coords_dropped(self):
        self.assertIsNone(service._normalize_meeting({"name": "x"}, FEED))
        self.assertIsNone(service._normalize_meeting(_raw(lat=0, lng=0), FEED))
        self.assertIsNone(service._normalize_meeting({"name": "x", "coordinates": "garbage"}, FEED))

    def test_approximate_bool_or_string(self):
        self.assertTrue(_meeting(approximate="yes")["approximate"])
        self.assertFalse(_meeting(approximate=False)["approximate"])


class FeedListTests(unittest.TestCase):
    def test_unique_urls_and_required_keys(self):
        urls = [f["url"] for f in FEEDS]
        self.assertEqual(len(urls), len(set(urls)))
        for f in FEEDS:
            self.assertTrue({"name", "home", "url", "region"} <= f.keys(), f)

    def test_user_agent_is_not_spoofed_browser(self):
        # Cloudflare-fronted intergroups 403 a fake Chrome UA from a server.
        self.assertNotIn("Chrome", USER_AGENT)
        self.assertIn("sobriety-copilot", USER_AGENT)


class BmltTests(unittest.TestCase):
    def test_geo_width_is_positive_radius(self):
        captured = {}

        class FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return []

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, params=None, **kw):
                captured.update(params)
                return FakeResp()

        bmlt._cache.clear()
        with mock.patch.object(bmlt.httpx, "AsyncClient", FakeClient):
            asyncio.run(bmlt.fetch_na_meetings(41.88, -87.63, 30))
        # Negative geo_width is BMLT's "N nearest meetings" auto-radius.
        self.assertEqual(captured["geo_width"], "30")
        self.assertIn("latitude", captured["data_field_key"])

    def test_end_time_from_duration(self):
        self.assertEqual(bmlt._end_time("19:00", "01:30:00"), "20:30")
        self.assertEqual(bmlt._end_time("23:30", "01:00:00"), "00:30")
        self.assertEqual(bmlt._end_time("19:00", ""), "")


class SearchTests(unittest.TestCase):
    def setUp(self):
        service._cache.clear()
        service._health.clear()

    def _search(self, feed_meetings, na=(), **kw):
        async def fake_fetch(client, feed):
            return feed_meetings if feed is FEEDS[0] else []

        async def fake_na(*a):
            return list(na)

        with mock.patch.object(service, "_fetch_feed", fake_fetch), \
                mock.patch.object(service, "fetch_na_meetings", fake_na):
            return asyncio.run(service.search_meetings(*HERE, **kw))

    def test_radius_and_bbox(self):
        near = _meeting(name="Near")
        far = _meeting(name="Far", lat=41.0, lng=-75.0)  # ~69 mi north
        res = self._search([near, far], radius_mi=30, max_results=10)
        self.assertEqual([m["name"] for m in res["meetings"]], ["Near"])

    def test_dedupes_same_meeting_across_feeds(self):
        a = _meeting(name="Friday Night Live!", day=5, time="20:00")
        b = {**_meeting(name="Friday night live", day=5, time="20:00", lat=40.0012), "source": "Other"}
        other = _meeting(name="Women's Step Study", day=5, time="20:00")
        res = self._search([a, b, other], radius_mi=30, max_results=10)
        self.assertEqual(res["total_in_radius"], 2)

    def test_legacy_nearest_first_without_clock(self):
        close = _meeting(name="Close", day=3, time="09:00", lat=40.0001)
        soon_far = _meeting(name="SoonFar", day=1, time="19:30", lat=40.2)
        res = self._search([soon_far, close], radius_mi=30, max_results=10)
        self.assertEqual(res["meetings"][0]["name"], "Close")

    def test_upcoming_is_soonest_first(self):
        close_later = _meeting(name="CloseLater", day=3, time="09:00", lat=40.0001)
        soon_far = _meeting(name="SoonFar", day=1, time="19:30", lat=40.2)
        res = self._search([close_later, soon_far], radius_mi=30, max_results=10,
                           range_="upcoming", now_day=1, now_min=19 * 60)
        self.assertEqual([m["name"] for m in res["meetings"]], ["SoonFar", "CloseLater"])

    def test_upcoming_wraps_past_meetings_to_next_week(self):
        earlier_today = _meeting(name="Earlier", day=1, time="07:00")
        tomorrow = _meeting(name="Tomorrow", day=2, time="07:00")
        res = self._search([earlier_today, tomorrow], radius_mi=30, max_results=10,
                           range_="upcoming", now_day=1, now_min=12 * 60)
        self.assertEqual([m["name"] for m in res["meetings"]], ["Tomorrow", "Earlier"])

    def test_tonight_and_tomorrow_filters(self):
        ms = [
            _meeting(name="Noon", day=1, time="12:00"),
            _meeting(name="Eve", day=1, time="19:00"),
            _meeting(name="Tue", day=2, time="07:00"),
        ]
        tonight = self._search(ms, radius_mi=30, max_results=10,
                               range_="tonight", now_day=1, now_min=10 * 60)
        self.assertEqual([m["name"] for m in tonight["meetings"]], ["Eve"])
        tomorrow = self._search(ms, radius_mi=30, max_results=10,
                                range_="tomorrow", now_day=1, now_min=10 * 60)
        self.assertEqual([m["name"] for m in tomorrow["meetings"]], ["Tue"])

    def test_time_of_day_filter(self):
        ms = [_meeting(name="AM", time="07:00"), _meeting(name="PM", time="19:00")]
        res = self._search(ms, radius_mi=30, max_results=10,
                           range_="any", time_of_day="evening", now_day=0, now_min=0)
        self.assertEqual([m["name"] for m in res["meetings"]], ["PM"])

    def test_max_applies_after_time_selection(self):
        # 150 nearby Wednesday meetings would crowd out tonight's farther one
        # under nearest-first; soonest-first must still surface it.
        crowd = [_meeting(name=f"Wed {i}", day=3, time="09:00", lat=40.0 + i * 1e-5) for i in range(150)]
        tonight = _meeting(name="Tonight", day=1, time="20:00", lat=40.3)
        res = self._search(crowd + [tonight], radius_mi=30, max_results=100,
                           range_="upcoming", now_day=1, now_min=18 * 60)
        self.assertEqual(res["meetings"][0]["name"], "Tonight")

    def test_na_results_merge(self):
        na = [{**_meeting(name="NA Group"), "fellowship": "NA", "source": "BMLT (NA aggregator)"}]
        res = self._search([_meeting()], na=na, radius_mi=30, max_results=10)
        self.assertEqual(res["total_in_radius"], 2)


class HealthTests(unittest.TestCase):
    def setUp(self):
        service._health.clear()

    def test_statuses_and_last_good_count(self):
        service._record_health(FEED, count=500, raw_count=500, error=None)
        self.assertEqual(service._health[FEED["url"]]["status"], "ok")
        with self.assertLogs(service.log, "WARNING"):
            service._record_health(FEED, count=0, raw_count=0, error="HTTPStatusError: 403")
        h = service._health[FEED["url"]]
        self.assertEqual(h["status"], "error")
        self.assertEqual(h["last_good_count"], 500)

    def test_drop_warning(self):
        service._record_health(FEED, count=1000, raw_count=1000, error=None)
        with self.assertLogs(service.log, "WARNING"):
            service._record_health(FEED, count=100, raw_count=100, error=None)

    def test_feed_health_lists_every_feed(self):
        report = service.feed_health()
        self.assertEqual(len(report["feeds"]), len(FEEDS))
        self.assertTrue(all(r["status"] == "pending" for r in report["feeds"]))


if __name__ == "__main__":
    unittest.main()
