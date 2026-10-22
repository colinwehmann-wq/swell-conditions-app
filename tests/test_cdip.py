"""CDIP MOP: reading the OPeNDAP response, matching breaks to MOP points, logging the side-by-side and reporting on it."""
import datetime
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from sources import cdip, mop_compare, verify
from tools import build_mop_sites

PDT = datetime.timezone(datetime.timedelta(hours=-7))
UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 10, 21, 19, 12, tzinfo=PDT)

# A trimmed real response for waveTime, waveHs, waveTp, waveDp and waveFlagPrimary (the second reading is flagged bad).
T0 = int(datetime.datetime(2026, 10, 22, 12, 0, tzinfo=UTC).timestamp())          # 5 AM Pacific
ASCII = """Dataset {
    Int32 waveTime[waveTime = 3];
    Float32 waveHs[waveTime = 3];
} cdip/model/MOP_alongshore/D0580_forecast.nc;
---------------------------------------------
waveTime[3]
%d, %d, %d

waveHs[3]
0.75, 0.80, -999.989990234375

waveTp[3]
15.38, 15.38, 14.3

waveDp[3]
250.6, 251.0, 249.0

waveFlagPrimary[3]
1, 4, 1

""" % (T0, T0 + 10800, T0 + 21600)


class Parse(unittest.TestCase):
    def test_reads_times_and_values_and_drops_flagged_and_missing_readings(self):
        rows = cdip.parse(ASCII)
        self.assertEqual(len(rows), 1)          # the second is flagged bad, the third has no height
        self.assertEqual(rows[0]["time"], datetime.datetime(2026, 10, 22, 12, 0, tzinfo=UTC))
        self.assertEqual((rows[0]["hs"], rows[0]["tp"], rows[0]["dp"]), (0.75, 15.38, 250.6))

    def test_a_response_without_data_is_empty_not_an_error(self):
        self.assertEqual(cdip.parse("Error { code = 0; }"), [])

    def test_scalars_come_back_as_numbers(self):
        a = cdip._arrays("Dataset {\n}\n---\nmetaLatitude, 32.92472\nmetaLongitude, -117.26693\n")
        self.assertEqual(a["metaLatitude"], ["32.92472"])
        self.assertEqual(a["metaLongitude"], ["-117.26693"])


class Fetch(unittest.TestCase):
    def setUp(self):
        self._get = cdip.http.get
        self.urls = []

        def fake(url, **kw):
            self.urls.append(url)
            return "Dataset {\nwaveTime = 500\n}" if url.endswith(".dds") else ASCII
        cdip.http.get = fake

    def tearDown(self):
        cdip.http.get = self._get

    def test_asks_for_the_site_and_kind(self):
        cdip.fetch("D0580", "nowcast")
        self.assertIn("MOP_alongshore/D0580_nowcast.nc.ascii?", self.urls[0])

    def test_an_unknown_kind_is_refused(self):
        with self.assertRaises(ValueError):
            cdip.fetch("D0580", "hindcast")

    def test_recent_asks_only_for_the_tail_of_a_long_file(self):
        cdip.fetch_recent("D0580", 24)
        self.assertIn("waveTime[476:1:499]", self.urls[-1])


class Sites(unittest.TestCase):
    def test_every_break_has_a_nearby_mop_point(self):
        sites = cdip.load_sites()
        for cfg in config.SPOTS:
            self.assertIn(cfg["slug"], sites, cfg["slug"])
            self.assertRegex(sites[cfg["slug"]]["site"], r"^D\d{4}$")
            self.assertLess(sites[cfg["slug"]]["km"], 2.0, cfg["slug"])

    def test_points_run_south_to_north_with_the_breaks(self):
        sites = cdip.load_sites()
        ordered = sorted(config.SPOTS, key=lambda c: c["lat"])
        numbers = [int(sites[c["slug"]]["site"][1:]) for c in ordered]
        self.assertEqual(numbers, sorted(numbers))

    def test_a_missing_file_gives_no_sites(self):
        self.assertEqual(cdip.load_sites("/nonexistent/mop_sites.json"), {})


class BuildSites(unittest.TestCase):
    # A straight north-south coast: point n sits at latitude 32.5 + n/1000.
    @staticmethod
    def locate(site):
        n = int(site[1:])
        return 32.5 + n / 1000.0, -117.3, 10.0

    def test_finds_the_closest_point_by_sampling_then_refining(self):
        asked = []

        def fetch(site):
            asked.append(site)
            return self.locate(site)
        spots = [{"slug": "a", "lat": 32.5 + 0.0437, "lon": -117.3}]
        out = build_mop_sites.build(spots, fetch, step=10, first=1, last=100)
        self.assertEqual(out["a"]["site"], "D0044")
        self.assertLess(len(set(asked)), 100)           # it did not ask for every point

    def test_a_point_that_cannot_be_read_is_skipped(self):
        def fetch(site):
            if site == "D0044":
                raise RuntimeError("down")
            return self.locate(site)
        out = build_mop_sites.build([{"slug": "a", "lat": 32.5437, "lon": -117.3}], fetch, step=10, first=1, last=100)
        self.assertIn(out["a"]["site"], ("D0043", "D0045"))


def series(start, hours, **vals):
    return {start + datetime.timedelta(hours=h): dict(vals) for h in range(hours)}


def mop_rows(first_utc, count, hs=0.8, tp=14.0, dp=250.0):
    return [{"time": first_utc + datetime.timedelta(hours=3 * i), "hs": hs, "tp": tp, "dp": dp} for i in range(count)]


class MopRecord(unittest.TestCase):
    def test_pairs_mop_with_the_apps_model_at_the_same_instants_in_daylight(self):
        base = NOW.replace(minute=0)
        ours = series(base, 100, wave_height=1.04, swell_wave_height=0.78, swell_wave_period=11.8, swell_wave_direction=200.0)
        rec = verify.mop_record(NOW, "swamis", "D0708", mop_rows(datetime.datetime(2026, 10, 22, 0, 0, tzinfo=UTC), 8), ours)
        self.assertEqual((rec["k"], rec["slug"], rec["site"]), ("mp", "swamis", "D0708"))
        hours = [datetime.datetime.fromisoformat(r["t"]).hour for r in rec["rows"]]
        self.assertTrue(all(5 <= h <= 19 for h in hours), hours)        # no night rows
        first = rec["rows"][0]
        self.assertEqual((first["mhs"], first["mtp"], first["mdp"]), (0.8, 14.0, 250.0))
        self.assertEqual((first["ohs"], first["osh"], first["osp"], first["osd"]), (1.04, 0.78, 11.8, 200.0))

    def test_rows_in_the_past_or_beyond_72_hours_are_left_out(self):
        base = NOW.replace(minute=0)
        ours = series(base - datetime.timedelta(days=3), 24 * 8, wave_height=1.0)
        rec = verify.mop_record(NOW, "swamis", "D0708", mop_rows(datetime.datetime(2026, 10, 18, 12, 0, tzinfo=UTC), 80), ours)
        self.assertTrue(all(0 <= r["lead"] <= 72 for r in rec["rows"]))

    def test_nothing_overlapping_gives_none(self):
        self.assertIsNone(verify.mop_record(NOW, "swamis", "D0708", [], {}))


class CollectMop(unittest.TestCase):
    def setUp(self):
        self.base = NOW.replace(minute=0)
        self.ours = series(self.base, 100, wave_height=1.0, swell_wave_height=0.9, swell_wave_period=12.0, swell_wave_direction=200.0)
        self.breaks = {"swamis": ("D0708", self.ours), "blacks": ("D0539", self.ours)}
        self.calls = []

    def fetch(self, site):
        self.calls.append(site)
        if site == "D0539":
            raise RuntimeError("down")
        return mop_rows(datetime.datetime(2026, 10, 22, 0, 0, tzinfo=UTC), 20)

    def test_a_failing_site_is_reported_and_the_others_still_logged(self):
        records, problems = verify.collect_mop(NOW, [], self.breaks, self.fetch)
        self.assertEqual([r["slug"] for r in records], ["swamis"])
        self.assertEqual(len(problems), 1)
        self.assertIn("blacks", problems[0])

    def test_a_break_logged_recently_is_not_fetched_again(self):
        recent = [{"k": "mp", "slug": "swamis", "issued": (NOW - datetime.timedelta(hours=3)).isoformat()}]
        verify.collect_mop(NOW, recent, self.breaks, self.fetch)
        self.assertEqual(self.calls, ["D0539"])

    def test_it_is_fetched_again_once_the_gap_has_passed(self):
        old = [{"k": "mp", "slug": "swamis", "issued": (NOW - datetime.timedelta(hours=12)).isoformat()}]
        verify.collect_mop(NOW, old, self.breaks, self.fetch)
        self.assertIn("D0708", self.calls)

    def test_collect_writes_mop_records_without_disturbing_the_rest(self):
        with tempfile.TemporaryDirectory() as d:
            out = verify.collect(NOW, d, fetch_model=lambda *a: {}, fetch_obs=lambda *a: [], buoys={"46224": (33.0, -117.4)},
                                 models=["default"], mop_breaks={"swamis": ("D0708", self.ours)}, fetch_mop=self.fetch)
            self.assertEqual(out["problems"], [])
            self.assertEqual([r["k"] for r in verify.load(d)], ["mp"])
            again = verify.collect(NOW, d, fetch_model=lambda *a: {}, fetch_obs=lambda *a: [], buoys={"46224": (33.0, -117.4)},
                                   models=["default"], mop_breaks={"swamis": ("D0708", self.ours)}, fetch_mop=self.fetch)
            self.assertEqual(again["written"], 0)
            self.assertEqual(len(verify.load(d)), 1)

    def test_the_skill_report_ignores_mop_records(self):
        from sources import skill
        rec = verify.mop_record(NOW, "swamis", "D0708", mop_rows(datetime.datetime(2026, 10, 22, 0, 0, tzinfo=UTC), 8), self.ours)
        skill.format_report([rec])           # must not raise


class Compare(unittest.TestCase):
    def rec(self, slug="swamis", n=10, mhs=0.8, ohs=1.0, mdp=230.0, osd=200.0, mtp=15.0, osp=12.0, hours_ahead=0):
        t0 = datetime.datetime(2026, 10, 22, 5, 0, tzinfo=PDT) + datetime.timedelta(hours=hours_ahead)
        rows = [{"t": (t0 + datetime.timedelta(hours=3 * i)).isoformat(), "lead": 3 * i, "mhs": mhs, "mtp": mtp, "mdp": mdp,
                 "ohs": ohs, "osp": osp, "osd": osd} for i in range(n)]
        return {"k": "mp", "issued": "2026-10-21T19:00:00-07:00", "slug": slug, "site": "D0708", "rows": rows}

    def test_difference_reports_size_ratio_and_the_period_and_direction_offsets(self):
        d = mop_compare.difference(mop_compare.rows([self.rec()]))
        self.assertAlmostEqual(d["size_ratio"], 0.8)
        self.assertAlmostEqual(d["period_diff_s"], 3.0)
        self.assertAlmostEqual(d["dir_diff_deg"], 30.0)

    def test_direction_difference_goes_the_short_way_round_the_circle(self):
        d = mop_compare.difference(mop_compare.rows([self.rec(mdp=10.0, osd=350.0)]))
        self.assertAlmostEqual(d["dir_diff_deg"], 20.0)

    def test_tiny_model_heights_do_not_blow_up_the_ratio(self):
        d = mop_compare.difference(mop_compare.rows([self.rec(ohs=0.05, mhs=0.4)]))
        self.assertIsNone(d["size_ratio"])

    def test_error_against_the_nowcast_only_counts_hours_already_past(self):
        records = [self.rec(hours_ahead=-48, n=4, mhs=1.0, ohs=1.5)]
        t0 = datetime.datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
        truth = [{"time": t0 + datetime.timedelta(hours=3 * i), "hs": 1.1} for i in range(6)]
        err = mop_compare.error_vs_truth(mop_compare.rows(records), truth, NOW)
        self.assertEqual(err["n"], 4)
        self.assertAlmostEqual(err["mop_mae_m"], 0.1)
        self.assertAlmostEqual(err["model_mae_m"], 0.4)
        future = mop_compare.error_vs_truth(mop_compare.rows([self.rec(hours_ahead=48)]), truth, NOW)
        self.assertEqual(future["n"], 0)
        self.assertIsNone(future["mop_mae_m"])

    def test_report_has_a_row_per_break_and_flags_thin_ones(self):
        text = mop_compare.format_report([self.rec("swamis"), self.rec("blacks", n=3)], {}, NOW)
        self.assertIn("| swamis | 10 | 0.80 |", text)
        self.assertIn("| blacks (thin) | 3 |", text)

    def test_report_with_nothing_logged_says_so(self):
        self.assertIn("No MOP records logged yet", mop_compare.format_report([], {}, NOW))


if __name__ == "__main__":
    unittest.main()
