"""The top-of-page headline: which peak it names, when it goes stale, and the markup the script needs."""
import datetime
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sitegen
from sitegen import render
from sitegen.build import peak_title, pick_next_peak
from tests.test_sitegen import at, make_inputs

PDT = datetime.timezone(datetime.timedelta(hours=-7))


def peak(slug, day, hour, score, name=None, minute=0):
    t = datetime.datetime(2026, 10, day, hour, minute, tzinfo=PDT)
    return {"slug": slug, "name": name or slug.title(), "date": t.date().isoformat(), "time": t.isoformat(),
            "time_label": "%d:%02d %s" % (hour % 12 or 12, minute, "AM" if hour < 12 else "PM"),
            "weekday": t.strftime("%A"), "score": score, "rating": round(score / 10, 1),
            "band": "green" if score >= 75.5 else "yellow" if score >= 50 else "red",
            "label": "Good", "sub": "Chest-high. About 3-4 ft."}


def when(day, hour, minute=0):
    return datetime.datetime(2026, 10, day, hour, minute, tzinfo=PDT)


class PickNextPeak(unittest.TestCase):
    PEAKS = [
        peak("blacks", 15, 6, 92.0),
        peak("swamis", 15, 9, 88.0),
        peak("blacks", 16, 7, 70.0),
        peak("swamis", 16, 8, 80.0),
        peak("swamis", 17, 8, 55.0),
    ]

    def slug_time(self, now):
        p = pick_next_peak(self.PEAKS, now)
        return (p["slug"], p["time"][11:16]) if p else None

    def test_names_the_best_spot_on_the_earliest_day_with_a_strong_peak(self):
        self.assertEqual(self.slug_time(when(15, 3)), ("blacks", "06:00"))

    def test_moves_to_the_next_peak_the_moment_the_shown_time_passes(self):
        self.assertEqual(self.slug_time(when(15, 5, 59)), ("blacks", "06:00"))
        self.assertEqual(self.slug_time(when(15, 6, 1)), ("swamis", "09:00"))

    def test_rolls_to_tomorrow_once_todays_peaks_are_all_behind_us(self):
        self.assertEqual(self.slug_time(when(15, 9, 1)), ("swamis", "08:00"))       # best strong on the 16th

    def test_a_peak_exactly_now_has_passed(self):
        self.assertEqual(self.slug_time(when(15, 6, 0)), ("swamis", "09:00"))

    def test_with_nothing_strong_left_it_takes_the_best_rideable_one(self):
        self.assertEqual(self.slug_time(when(16, 9)), ("swamis", "08:00"))

    def test_nothing_ahead_means_none(self):
        self.assertIsNone(self.slug_time(when(18, 0)))

    def test_nothing_rideable_means_none(self):
        self.assertIsNone(pick_next_peak([peak("a", 20, 8, 30.0)], when(15, 0)))

    def test_ties_on_score_go_to_the_earlier_time(self):
        peaks = [peak("b", 15, 9, 80.0), peak("a", 15, 7, 80.0)]
        self.assertEqual(pick_next_peak(peaks, when(15, 0))["slug"], "a")


class PeakTitle(unittest.TestCase):
    P = peak("blacks", 16, 6, 90.0, name="Blacks")

    def test_today(self):
        self.assertEqual(peak_title(self.P, 0), "Today, Blacks peaks around 6:00 AM.")

    def test_tomorrow(self):
        self.assertEqual(peak_title(self.P, 1), "Tomorrow is the one — Blacks peaks around 6:00 AM.")

    def test_further_out_names_the_day(self):
        self.assertEqual(peak_title(self.P, 3), "Not today. Best bet: Friday at Blacks.")


class Payload(unittest.TestCase):
    def payload(self, now=at(0, 20), **kw):
        return sitegen.make_payload(make_inputs(now, spots=(0, 1, 2), **kw), now)

    def test_lists_every_spot_on_every_forecast_day_soonest_first(self):
        p = self.payload()
        self.assertEqual(len(p["peaks"]), 3 * 7)
        times = [datetime.datetime.fromisoformat(x["time"]) for x in p["peaks"]]
        self.assertEqual(times, sorted(times))

    def test_each_peak_carries_everything_the_page_needs(self):
        first = self.payload()["peaks"][0]
        for key in ("slug", "name", "date", "time", "time_label", "weekday", "score", "rating", "band", "label", "sub"):
            self.assertIn(key, first)
        self.assertRegex(first["date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertIn(first["band"], ("green", "yellow", "red"))

    def test_the_payload_stays_json_serialisable(self):
        json.dumps(self.payload())

    def test_after_dark_the_headline_is_the_first_peak_still_ahead(self):
        now = at(0, 20)
        p = self.payload(now)
        best = pick_next_peak(p["peaks"], now)
        self.assertEqual(p["headline"]["slug"], best["slug"])
        self.assertEqual(p["headline"]["anchor"], best["time"])
        self.assertEqual(p["headline"]["fig"]["rating"], best["rating"])

    def test_the_figure_is_the_peaks_rating_not_the_spots_rating_right_now(self):
        now = at(0, 20)
        p = self.payload(now)
        fig = p["headline"]["fig"]
        best = pick_next_peak(p["peaks"], now)
        self.assertEqual((fig["slug"], fig["rating"], fig["band"], fig["label"]),
                         (best["slug"], best["rating"], best["band"], best["label"]))

    def test_a_flat_week_has_no_figure_and_no_anchor(self):
        p = self.payload(at(0, 10), height_m=0.2)
        self.assertIsNone(p["headline"]["fig"])
        self.assertIsNone(p["headline"]["anchor"])

    def test_in_daylight_the_right_now_text_expires_when_the_window_does(self):
        now = at(0, 10)
        p = self.payload(now)
        self.assertEqual(p["headline"]["kicker"][:9], "Right now")
        anchor = datetime.datetime.fromisoformat(p["headline"]["anchor"])
        self.assertGreater(anchor, now)


class Markup(unittest.TestCase):
    def page(self, now=at(0, 20), **kw):
        payload = sitegen.make_payload(make_inputs(now, spots=(0, 1, 2), **kw), now)
        return payload, render.index_page(payload)

    def test_the_hero_exposes_the_hooks_the_script_updates(self):
        payload, html = self.page()
        for hook in ('data-hero="root"', 'data-hero="kicker"', 'data-hero="title"', 'data-hero="sub"',
                     'data-hero="fig"', 'data-hero="num"', 'data-hero="name"', 'id="peaks-data"'):
            self.assertIn(hook, html)
        self.assertIn('data-anchor="%s"' % payload["headline"]["anchor"], html)

    def test_the_embedded_peaks_round_trip(self):
        payload, html = self.page()
        raw = re.search(r'<script type="application/json" id="peaks-data">(.*?)</script>', html, re.S).group(1)
        self.assertEqual(json.loads(raw), payload["peaks"])

    def test_the_peaks_script_loads_before_the_site_script(self):
        _p, html = self.page()
        self.assertLess(html.index("assets/peaks.js"), html.index("assets/site.js"))

    def test_other_pages_do_not_load_the_peaks_script(self):
        payload, _html = self.page()
        self.assertNotIn("peaks.js", render.spot_page(payload["spots"][0], payload))

    def test_a_name_cannot_break_out_of_the_embedded_data(self):
        evil = "</script><script>alert(1)</script>"
        _payload, html = self.page(first_name=evil)
        block = re.search(r'id="peaks-data">(.*?)</script>', html, re.S).group(1)
        self.assertNotIn("<", block)
        self.assertNotIn(evil, html)
        # the data still decodes to the original name: it was escaped, not altered
        self.assertIn(evil, {p["name"] for p in json.loads(block)})

    def test_a_flat_week_hides_the_figure_but_keeps_it_in_the_page(self):
        _p, html = self.page(at(0, 10), height_m=0.2)
        self.assertRegex(html, r'<a class="hero-fig" data-hero="fig" href="\./" hidden>')
        self.assertIn("A flat spell.", html)


if __name__ == "__main__":
    unittest.main()
