"""Tests for the website generator: payload shape, headline logic, HTML safety, file output."""
import datetime
import json
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import sitegen
from sitegen import render
from sources import boards
from sources import evaluate as E

TZ = datetime.timezone(datetime.timedelta(hours=-7))
DAY0 = datetime.date(2026, 10, 13)
IDENTITY = {"h_scale": 1.0, "p_shift": 0.0}


def at(day_offset, hour, minute=0):
    d = DAY0 + datetime.timedelta(days=day_offset)
    return datetime.datetime(d.year, d.month, d.day, hour, minute, tzinfo=TZ)


def sun_for(days):
    return {DAY0 + datetime.timedelta(days=i): (at(i, 6, 30), at(i, 18, 0)) for i in range(days)}


def forecast(days, height_m, period=14.0, wind_kn=3.0, wind_dir=75):
    marine, wind = {}, {}
    for i in range(days):
        for h in range(24):
            t = at(i, h)
            marine[t] = {"swell_wave_height": height_m, "swell_wave_period": period,
                         "swell_wave_direction": 250}
            wind[t] = {"wind_speed_10m": wind_kn, "wind_direction_10m": wind_dir}
    return marine, wind


def make_inputs(now, height_m=1.2, spots=(0, 1), first_name=None):
    marine, wind = forecast(10, height_m)
    sun = sun_for(10)
    inputs = []
    for idx in spots:
        cfg = config.spot_config(config.SPOTS[idx])
        if first_name and idx == spots[0]:
            cfg = dict(cfg, name=first_name)
        res = E.evaluate_spot(cfg, now, None, None, marine, wind, sun[DAY0], sun[DAY0 + datetime.timedelta(days=1)])
        calib = E.calibration(now, marine, wind, None, None)
        today_sun = sun[DAY0]
        day = DAY0 if now < today_sun[1] - datetime.timedelta(minutes=45) else DAY0 + datetime.timedelta(days=1)
        inputs.append({
            "result": res,
            "outlook": E.outlook(cfg, now, None, None, marine, wind, sun, calib, days=7),
            "sun": today_sun,
            "timeline_day": day,
            "timeline": E.timeline(cfg, day, sun[day], now, None, None, marine, wind, calib),
        })
    return inputs


class Payload(unittest.TestCase):
    def test_is_json_serialisable(self):
        payload = sitegen.make_payload(make_inputs(at(0, 10)), at(0, 10))
        json.dumps(payload)

    def test_spot_shape(self):
        payload = sitegen.make_payload(make_inputs(at(0, 10)), at(0, 10))
        spot = payload["spots"][0]
        for key in ("slug", "name", "area", "verdict", "rating", "band", "label", "now", "board",
                    "window", "timeline", "outlook", "ideal", "ntfy"):
            self.assertIn(key, spot)
        self.assertEqual(len(spot["outlook"]), 7)
        self.assertIn(spot["board"]["label"], boards.LABELS.values())

    def test_public_topics_come_from_config(self):
        payload = sitegen.make_payload(make_inputs(at(0, 10)), at(0, 10))
        ntfy = payload["spots"][0]["ntfy"]
        self.assertTrue(ntfy["topic"].startswith(config.PUBLIC_TOPIC_BASE))
        self.assertTrue(ntfy["app_url"].startswith("ntfy://"))
        self.assertTrue(ntfy["web_url"].startswith("https://"))
        self.assertEqual(payload["digest"]["topic"], config.public_topic("daily"))

    def test_ranking_is_best_first(self):
        payload = sitegen.make_payload(make_inputs(at(0, 10)), at(0, 10))
        by_slug = {s["slug"]: s for s in payload["spots"]}
        ratings = [by_slug[s]["rating"] for s in payload["ranking"]]
        self.assertEqual(ratings, sorted(ratings, reverse=True))


class Headline(unittest.TestCase):
    def test_daylight_and_good_names_the_pick(self):
        h = sitegen.make_payload(make_inputs(at(0, 10)), at(0, 10))["headline"]
        self.assertTrue(h["title"].endswith("is the pick."))
        self.assertTrue(h["slug"])

    def test_after_dark_looks_ahead_instead_of_claiming_right_now(self):
        h = sitegen.make_payload(make_inputs(at(0, 20)), at(0, 20))["headline"]
        self.assertEqual(h["kicker"], "Looking ahead")
        self.assertTrue(h["title"].startswith("Tomorrow is the one"))

    def test_flat_week(self):
        h = sitegen.make_payload(make_inputs(at(0, 10), height_m=0.2), at(0, 10))["headline"]
        self.assertEqual(h["title"], "A flat spell.")
        self.assertIsNone(h["slug"])


class Render(unittest.TestCase):
    def pages(self, **kw):
        now = kw.pop("now", at(0, 10))
        payload = sitegen.make_payload(make_inputs(now, **kw), now)
        return payload, render.index_page(payload), render.spot_page(payload["spots"][0], payload)

    def test_untrusted_text_is_escaped(self):
        evil = "<script>alert(1)</script>"
        _payload, index, spot = self.pages(first_name=evil)
        for page in (index, spot):
            self.assertNotIn(evil, page)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)

    def test_index_has_all_sections_and_opt_in(self):
        payload, index, _ = self.pages()
        for anchor in ('id="now"', 'id="week"', 'id="alerts"', 'id="how"', 'id="boards"'):
            self.assertIn(anchor, index)
        self.assertIn("Open in ntfy app", index)
        self.assertIn(payload["spots"][0]["ntfy"]["topic"], index)
        self.assertIn(payload["digest"]["topic"], index)

    def test_every_rating_chip_has_icon_number_and_label(self):
        _payload, index, spot = self.pages()
        for page in (index, spot):
            chips = page.count('class="chip chip-')
            self.assertGreater(chips, 0)
            self.assertEqual(page.count('class="chip-ico"'), chips)
            self.assertEqual(page.count('class="chip-lbl"'), chips)

    def test_chart_has_a_table_alternative_and_hover_data(self):
        _payload, _index, spot = self.pages()
        self.assertIn("View as a table", spot)
        self.assertIn('data-tip="', spot)
        self.assertRegex(spot, r"Today, hour by hour")

    def test_after_dark_charts_tomorrow(self):
        _payload, _index, spot = self.pages(now=at(0, 20))
        self.assertIn("Tomorrow, hour by hour", spot)

    def test_asset_paths_are_relative_for_nested_pages(self):
        _payload, index, spot = self.pages()
        self.assertIn('href="assets/style.css"', index)
        self.assertIn('href="../../assets/style.css"', spot)

    def test_not_found_uses_absolute_asset_paths(self):
        payload, _i, _s = self.pages()
        page = render.not_found_page(payload)
        base = re.sub(r"^https?://[^/]+", "", config.SITE_URL).rstrip("/") + "/"
        self.assertIn('href="%sassets/style.css"' % base, page)


class Build(unittest.TestCase):
    def test_writes_every_file(self):
        now = at(0, 10)
        with tempfile.TemporaryDirectory() as out:
            sitegen.build(make_inputs(now), now, out)
            for rel in ("index.html", "404.html", ".nojekyll", "assets/style.css", "assets/site.js",
                        "data/latest.json"):
                self.assertTrue(os.path.exists(os.path.join(out, rel)), rel)
            with open(os.path.join(out, "data", "latest.json"), encoding="utf-8") as f:
                data = json.load(f)
            for spot in data["spots"]:
                self.assertTrue(os.path.exists(os.path.join(out, "spots", spot["slug"], "index.html")))

    def test_rebuilding_into_an_existing_dir_works(self):
        now = at(0, 10)
        with tempfile.TemporaryDirectory() as out:
            sitegen.build(make_inputs(now), now, out)
            sitegen.build(make_inputs(now), now, out)


if __name__ == "__main__":
    unittest.main()
