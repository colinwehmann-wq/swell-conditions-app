"""The extra details on a break's page: water temperature and what to wear, sunrise and sunset, and the tide graph."""
import datetime
import os
import sys
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import check
from sitegen import render, tide_chart
from sitegen.build import _sun, _tide_day, _water
from sources import ndbc, tides, words
from sources.tides import TideSeries
from sources.timeutil import TZ
from tests.test_feedback_js import payload as site_payload

DAY = datetime.date(2026, 10, 21)


def at(h, m=0, day=DAY):
    return datetime.datetime(day.year, day.month, day.day, h, m, tzinfo=TZ)


def series():
    """High 4.4 at 7:17, low 2.0 at 12:58, high 4.6 at 18:42, with a low either side to interpolate from."""
    return TideSeries([(at(1, 10), 0.8, "L"), (at(7, 17), 4.4, "H"), (at(12, 58), 2.0, "L"), (at(18, 42), 4.6, "H"), (at(23, 50), 0.5, "L")])


# ----------------------------------------------------------------------------- what to wear

class Wetsuit(unittest.TestCase):
    def test_steps_from_warm_to_cold(self):
        cases = [(75, "Boardshorts"), (72.0, "Boardshorts"), (71.9, "Spring suit"), (68.0, "Spring suit"), (67.9, "3/2 wetsuit"),
                 (64.0, "3/2 wetsuit"), (63.9, "4/3 wetsuit"), (60.0, "4/3 wetsuit"), (59.9, "4/3 plus boots"),
                 (55.0, "4/3 plus boots"), (54.9, "5/4 hooded"), (40, "5/4 hooded")]
        for temp, label in cases:
            self.assertEqual(words.wetsuit(temp)["label"], label, temp)

    def test_unknown_temperature(self):
        self.assertIsNone(words.wetsuit(None))

    def test_every_step_has_a_hint_and_they_run_warmest_first(self):
        floors = [f for f, _, _ in words.WETSUIT_STEPS]
        self.assertEqual(floors, sorted(floors, reverse=True))
        self.assertTrue(all(h for _, _, h in words.WETSUIT_STEPS))


# ----------------------------------------------------------------------------- reading the temperature

def buoy_text(rows):
    """rows: [(minutes_ago, WTMP)] as a realtime2 .txt file."""
    now = datetime.datetime.now(ndbc.UTC)
    lines = ["#YY  MM DD hh mm WDIR WSPD GST  WVHT   DPD   APD MWD   PRES  ATMP  WTMP  DEWP  VIS PTDY  TIDE",
             "#yr  mo dy hr mn degT m/s  m/s     m   sec   sec degT   hPa  degC  degC  degC  nmi  hPa    ft"]
    for ago, wtmp in rows:
        t = (now - datetime.timedelta(minutes=ago)).replace(second=0, microsecond=0)
        lines.append("%s  MM   MM   MM   1.2    15  11.0 194     MM    MM  %s    MM   MM   MM    MM" % (t.strftime("%Y %m %d %H %M"), wtmp))
    return "\n".join(lines) + "\n"


class BuoyWater(unittest.TestCase):
    def fetch(self, rows, **kw):
        with mock.patch.object(ndbc.http, "get", return_value=buoy_text(rows)):
            return ndbc.fetch_water_temp("46224", **kw)

    def test_celsius_becomes_fahrenheit(self):
        w = self.fetch([(20, "22.9")])
        self.assertAlmostEqual(w["temp_f"], 73.22)
        self.assertEqual(w["source"], "buoy 46224")
        self.assertLess(w["age_hours"], 0.5)

    def test_rows_with_no_reading_are_skipped_for_the_newest_that_has_one(self):
        self.assertAlmostEqual(self.fetch([(20, "MM"), (50, "MM"), (80, "21.0")])["temp_f"], 69.8)

    def test_a_reading_that_is_too_old_is_not_used(self):
        self.assertIsNone(self.fetch([(300, "22.9")]))

    def test_an_impossible_reading_is_not_used(self):
        self.assertIsNone(self.fetch([(20, "99.0")]))
        self.assertIsNone(self.fetch([(20, "-5.0")]))

    def test_no_readings_at_all(self):
        self.assertIsNone(self.fetch([(20, "MM")]))

    def test_a_network_failure_is_none_not_an_error(self):
        with mock.patch.object(ndbc.http, "get", side_effect=RuntimeError("down")):
            self.assertIsNone(ndbc.fetch_water_temp("46224"))


class StationWater(unittest.TestCase):
    def fetch(self, payload, **kw):
        with mock.patch.object(tides.http, "get_json", return_value=payload):
            return tides.fetch_water_temp("9410230", **kw)

    def row(self, ago_minutes, v):
        t = datetime.datetime.now(TZ) - datetime.timedelta(minutes=ago_minutes)
        return {"data": [{"t": t.strftime("%Y-%m-%d %H:%M"), "v": v, "f": "0,0,0"}]}

    def test_it_reads_the_latest_value(self):
        w = self.fetch(self.row(10, "72.9"))
        self.assertEqual(w["temp_f"], 72.9)
        self.assertEqual(w["source"], "tide station 9410230")

    def test_old_missing_or_silly_data_is_none(self):
        self.assertIsNone(self.fetch(self.row(600, "72.9")))
        self.assertIsNone(self.fetch({"data": []}))
        self.assertIsNone(self.fetch({"error": {"message": "No data was found"}}))
        self.assertIsNone(self.fetch(self.row(10, "abc")))
        self.assertIsNone(self.fetch(self.row(10, "250")))

    def test_a_network_failure_is_none(self):
        with mock.patch.object(tides.http, "get_json", side_effect=RuntimeError("down")):
            self.assertIsNone(tides.fetch_water_temp("9410230"))


class ContextWater(unittest.TestCase):
    CFG = {"buoys": ["46224", "46225"], "tide_station": "9410230"}

    def test_the_first_buoy_that_reports_wins(self):
        ctx = check.Context(at(8))
        with mock.patch.object(check.ndbc, "fetch_water_temp", side_effect=lambda b: {"temp_f": 70.0, "source": "buoy " + b}) as f, \
                mock.patch.object(check.tides, "fetch_water_temp", return_value={"temp_f": 99.0}):
            self.assertEqual(ctx.water(self.CFG)["source"], "buoy 46224")
            self.assertEqual(f.call_count, 1)

    def test_the_next_buoy_is_tried_when_the_first_has_nothing(self):
        ctx = check.Context(at(8))
        with mock.patch.object(check.ndbc, "fetch_water_temp", side_effect=lambda b: None if b == "46224" else {"temp_f": 71.0, "source": "buoy " + b}):
            self.assertEqual(ctx.water(self.CFG)["source"], "buoy 46225")

    def test_the_tide_station_is_the_backup(self):
        ctx = check.Context(at(8))
        with mock.patch.object(check.ndbc, "fetch_water_temp", return_value=None), \
                mock.patch.object(check.tides, "fetch_water_temp", return_value={"temp_f": 72.9, "source": "tide station 9410230"}):
            self.assertEqual(ctx.water(self.CFG)["temp_f"], 72.9)

    def test_nothing_anywhere_is_none(self):
        ctx = check.Context(at(8))
        with mock.patch.object(check.ndbc, "fetch_water_temp", return_value=None), mock.patch.object(check.tides, "fetch_water_temp", return_value=None):
            self.assertIsNone(ctx.water(self.CFG))

    def test_an_error_never_breaks_a_run(self):
        ctx = check.Context(at(8))
        with mock.patch.object(check.ndbc, "fetch_water_temp", side_effect=RuntimeError("boom")), \
                mock.patch.object(check.tides, "fetch_water_temp", side_effect=RuntimeError("boom")):
            self.assertIsNone(ctx.water(self.CFG))

    def test_each_source_is_asked_once_however_many_breaks_ask(self):
        ctx = check.Context(at(8))
        with mock.patch.object(check.ndbc, "fetch_water_temp", return_value={"temp_f": 70.0, "source": "buoy"}) as f:
            for _ in range(5):
                ctx.water(self.CFG)
            self.assertEqual(f.call_count, 1)


# ----------------------------------------------------------------------------- the tide graph

class BuildDay(unittest.TestCase):
    def test_a_point_every_half_hour_from_before_sunrise_to_after_sunset(self):
        td = tide_chart.build_day(series(), DAY, at(6, 58), at(18, 8))
        self.assertEqual(td["start"], at(5, 0).isoformat())          # the hour before sunrise
        self.assertEqual(td["end"], at(20, 0).isoformat())           # two hours after the sunset hour
        self.assertEqual(len(td["points"]), 31)
        self.assertEqual(td["sunrise"], at(6, 58).isoformat())

    def test_the_highs_and_lows_in_the_span_are_listed_in_order(self):
        td = tide_chart.build_day(series(), DAY, at(6, 58), at(18, 8))
        self.assertEqual([(e["type"], e["ft"]) for e in td["extremes"]], [("H", 4.4), ("L", 2.0), ("H", 4.6)])

    def test_heights_follow_the_predictions(self):
        td = tide_chart.build_day(series(), DAY, at(6, 58), at(18, 8))
        by = {p[0]: p[1] for p in td["points"]}
        self.assertAlmostEqual(by[at(13, 0).isoformat()], 2.0, delta=0.05)         # just after the 12:58 low

    def test_no_predictions_no_graph(self):
        self.assertIsNone(tide_chart.build_day(None, DAY, at(6, 58), at(18, 8)))
        self.assertIsNone(tide_chart.build_day(TideSeries([]), DAY, at(6, 58), at(18, 8)))

    def test_no_sun_times_no_graph(self):
        self.assertIsNone(tide_chart.build_day(series(), DAY, None, at(18, 8)))

    def test_predictions_that_do_not_cover_the_day_no_graph(self):
        far = TideSeries([(at(1, 0, day=DAY + datetime.timedelta(days=5)), 1.0, "L"), (at(7, 0, day=DAY + datetime.timedelta(days=5)), 4.0, "H")])
        self.assertIsNone(tide_chart.build_day(far, DAY, at(6, 58), at(18, 8)))


class Svg(unittest.TestCase):
    def td(self):
        return tide_chart.build_day(series(), DAY, at(6, 58), at(18, 8))

    def test_it_is_well_formed_xml(self):
        root = ET.fromstring(tide_chart.tide_svg(self.td()))
        self.assertTrue(root.tag.endswith("svg"))

    def test_a_screen_reader_gets_the_highs_and_lows_in_words(self):
        svg = tide_chart.tide_svg(self.td())
        self.assertIn("<title id=\"tide-t\">Tide for the day</title>", svg)
        self.assertIn("High 4.4 ft at 7:17 AM, low 2.0 ft at 12:58 PM, high 4.6 ft at 6:42 PM.", svg)
        self.assertIn('role="img"', svg)

    def test_one_dot_and_label_per_extreme(self):
        svg = tide_chart.tide_svg(self.td())
        self.assertEqual(svg.count('class="tide-dot"'), 3)
        for label in ("4.4 ft", "2.0 ft", "4.6 ft", "7:17 AM", "12:58 PM", "6:42 PM"):
            self.assertIn(label, svg)

    def test_the_daylight_hours_are_shaded_and_labelled(self):
        svg = tide_chart.tide_svg(self.td())
        self.assertIn('class="tide-day"', svg)
        self.assertIn("sunrise 6:58 AM", svg)
        self.assertIn("sunset 6:08 PM", svg)

    def test_now_is_marked_only_when_it_falls_inside_the_day_shown(self):
        self.assertIn('class="tide-now"', tide_chart.tide_svg(self.td(), at(12, 0).isoformat()))
        self.assertNotIn('class="tide-now"', tide_chart.tide_svg(self.td(), at(23, 0).isoformat()))
        self.assertNotIn('class="tide-now"', tide_chart.tide_svg(self.td(), None))

    def test_the_zero_line_is_drawn_and_the_axis_covers_the_whole_curve(self):
        svg = tide_chart.tide_svg(self.td())
        self.assertIn("tide-zero", svg)
        self.assertIn('>-1<', svg)                                   # headroom below zero for a minus tide
        self.assertIn('>6<', svg)                                    # and above the highest high

    def test_hour_labels_every_two_hours(self):
        svg = tide_chart.tide_svg(self.td())
        for label in (">6a<", ">8a<", ">12p<", ">6p<"):
            self.assertIn(label, svg, label)

    def test_a_day_with_no_extremes_still_draws(self):
        td = self.td()
        td["extremes"] = []
        svg = tide_chart.tide_svg(td)
        ET.fromstring(svg)
        self.assertIn("No highs or lows in daylight", svg)

    def test_describe_reads_naturally(self):
        self.assertEqual(tide_chart.describe(self.td()), "High 4.4 ft at 7:17 AM, low 2.0 ft at 12:58 PM, high 4.6 ft at 6:42 PM")
        self.assertEqual(tide_chart.describe(dict(self.td(), extremes=[])), "")


# ----------------------------------------------------------------------------- feeding the page

class PageData(unittest.TestCase):
    def test_water_carries_the_temperature_where_it_came_from_and_what_to_wear(self):
        w = _water({"temp_f": 72.74, "source": "buoy 46225", "age_hours": 0.5})
        self.assertEqual((w["temp_f"], w["source"], w["age_minutes"]), (72.7, "buoy 46225", 30))
        self.assertEqual(w["suit"]["label"], "Boardshorts")
        self.assertIsNone(_water(None))

    def test_sun_gives_sunrise_sunset_and_the_last_rated_hour(self):
        s = _sun((at(6, 58), at(18, 8)))
        self.assertEqual(s["sunrise"], at(6, 58).isoformat())
        self.assertEqual(s["last_light"], at(18, 23).isoformat())
        self.assertIsNone(_sun(None))
        self.assertIsNone(_sun((None, at(18, 8))))

    def test_the_tide_day_uses_the_day_the_chart_shows(self):
        item = {"chart_sun": (at(6, 58), at(18, 8)), "tide": series(), "timeline_day": DAY}
        self.assertEqual(_tide_day(item, at(9))["date"], DAY.isoformat())
        self.assertIsNone(_tide_day({"chart_sun": None, "tide": series()}, at(9)))


class Page(unittest.TestCase):
    def page(self, **spot_over):
        p = site_payload()
        spot = p["spots"][0]
        td = tide_chart.build_day(series(), DAY, at(6, 58), at(18, 8))
        spot.update(water={"temp_f": 72.7, "source": "buoy 46225", "age_minutes": 30, "suit": words.wetsuit(72.7)},
                    sun={"sunrise": at(6, 58).isoformat(), "sunset": at(18, 8).isoformat(), "last_light": at(18, 23).isoformat()},
                    tide_day=td, timeline_label="Tomorrow")
        spot.update(spot_over)
        return render.spot_page(spot, p)

    def test_the_water_tile_shows_the_temperature_and_what_to_wear(self):
        html = self.page()
        self.assertIn("<dt>Water</dt><dd>73 °F</dd>", html)
        self.assertIn("boardshorts weather", html)

    def test_no_water_reading_no_water_tile(self):
        self.assertNotIn("<dt>Water</dt>", self.page(water=None))

    def test_sunrise_and_sunset_sit_under_the_hourly_chart_heading(self):
        self.assertIn("Sunrise 6:58 AM · sunset 6:08 PM", self.page())

    def test_the_tide_section_has_a_heading_that_matches_the_day_and_the_graph(self):
        html = self.page()
        self.assertIn('id="tide"', html)
        self.assertIn("<h2>Tide, tomorrow</h2>", html)
        self.assertIn('<svg class="tide"', html)
        self.assertIn("High 4.4 ft at 7:17 AM", html)

    def test_no_tide_data_no_tide_section(self):
        self.assertNotIn('id="tide"', self.page(tide_day=None))

    def test_the_tide_comes_after_the_hourly_chart(self):
        html = self.page()
        self.assertLess(html.index('id="today"'), html.index('id="tide"'))

    def test_tomorrows_graph_has_no_now_marker(self):
        self.assertNotIn('class="tide-now"', self.page(timeline_label="Tomorrow"))


if __name__ == "__main__":
    unittest.main()
