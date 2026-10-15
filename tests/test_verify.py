"""Tests for the forecast-accuracy log: record building, the JSONL store, dedupe, and collect()."""
import datetime
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sources import verify
from sources.timeutil import TZ, UTC

PDT = datetime.timezone(datetime.timedelta(hours=-7))
NOW = datetime.datetime(2026, 10, 14, 6, 17, tzinfo=PDT)


def hourly(start, hours, **vals):
    """{aware datetime: {var: value}} for `hours` consecutive hours from `start`."""
    return {start + datetime.timedelta(hours=h): dict(vals) for h in range(hours)}


class ForecastRecord(unittest.TestCase):
    def test_keeps_only_three_hour_steps_up_to_72h(self):
        base = NOW.replace(minute=0)
        series = hourly(base, 100, swell_wave_height=1.234, swell_wave_period=14.06)
        rec = verify.forecast_record(NOW, "46224", "default", series)
        leads = [r["lead"] for r in rec["rows"]]
        self.assertEqual(leads, list(range(0, 73, 3)))

    def test_drops_hours_before_issue_time(self):
        base = NOW.replace(minute=0)
        series = hourly(base - datetime.timedelta(hours=6), 12, swell_wave_height=1.0)
        rec = verify.forecast_record(NOW, "46224", "default", series)
        self.assertEqual([r["lead"] for r in rec["rows"]], [0, 3])

    def test_issue_time_is_floored_to_the_hour(self):
        rec = verify.forecast_record(NOW, "46224", "default", hourly(NOW.replace(minute=0), 4, wave_height=1))
        self.assertEqual(rec["issued"], "2026-10-14T06:00:00-07:00")

    def test_rounds_and_omits_missing_values(self):
        base = NOW.replace(minute=0)
        series = {base: {"swell_wave_height": 1.23456, "swell_wave_period": 14.06,
                         "swell_wave_direction": 197.6, "wave_height": None}}
        row = verify.forecast_record(NOW, "46224", "m", series)["rows"][0]
        self.assertEqual((row["sh"], row["sp"], row["sd"]), (1.23, 14.1, 198.0))
        self.assertNotIn("hs", row)

    def test_a_model_with_nothing_usable_gives_none(self):
        base = NOW.replace(minute=0)
        self.assertIsNone(verify.forecast_record(NOW, "46224", "ecmwf", hourly(base, 6, swell_wave_height=None)))
        self.assertIsNone(verify.forecast_record(NOW, "46224", "ecmwf", {}))

    def test_lead_is_real_elapsed_hours_across_a_dst_change(self):
        # Pacific clocks go back on 2026-11-01, so local wall-clock hours repeat. Leads must come
        # from real elapsed time, which means each 3-hour step is hit exactly once.
        issued = datetime.datetime(2026, 11, 1, 0, 0, tzinfo=TZ)
        start_utc = issued.astimezone(UTC)
        series = {(start_utc + datetime.timedelta(hours=h)).astimezone(TZ): {"wave_height": 1.0}
                  for h in range(0, 10)}
        rec = verify.forecast_record(issued, "46224", "m", series)
        self.assertEqual([r["lead"] for r in rec["rows"]], [0, 3, 6, 9])


class ObservationRecords(unittest.TestCase):
    def test_utc_time_short_keys_and_missing_omitted(self):
        t = datetime.datetime(2026, 10, 14, 13, 26, tzinfo=UTC)
        recs = verify.observation_records("46224", [{
            "time": t, "wvht_m": 1.1, "swh_m": 1.0, "swp_s": 14.3, "swd_deg": 202.5,
            "wwh_m": None, "wwp_s": 6.2, "apd_s": 8.1}])
        self.assertEqual(recs[0], {"k": "ob", "buoy": "46224", "t": "2026-10-14T13:26:00+00:00",
                                   "hs": 1.1, "sh": 1.0, "sp": 14.3, "sd": 202.0, "wwp": 6.2, "ap": 8.1})


class Store(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self._tmp.name, "log")

    def tearDown(self):
        self._tmp.cleanup()

    def ob(self, t, buoy="46224"):
        return {"k": "ob", "buoy": buoy, "t": t, "hs": 1.0}

    def fc(self, issued, model="default", buoy="46224"):
        return {"k": "fc", "issued": issued, "buoy": buoy, "model": model,
                "rows": [{"t": issued, "lead": 0, "hs": 1.0}]}

    def test_missing_dir_loads_as_empty(self):
        self.assertEqual(verify.load(self.dir), [])

    def test_writes_one_file_per_month_and_reads_back_in_order(self):
        written, skipped = verify.append_new(self.dir, [
            self.ob("2026-09-30T23:56:00+00:00"), self.ob("2026-10-01T00:26:00+00:00")])
        self.assertEqual((written, skipped), (2, 0))
        self.assertEqual(sorted(os.listdir(self.dir)), ["2026-09.jsonl", "2026-10.jsonl"])
        self.assertEqual([r["t"][:10] for r in verify.load(self.dir)], ["2026-09-30", "2026-10-01"])

    def test_observations_are_not_logged_twice(self):
        verify.append_new(self.dir, [self.ob("2026-10-14T13:26:00+00:00")])
        written, skipped = verify.append_new(self.dir, [
            self.ob("2026-10-14T13:26:00+00:00"), self.ob("2026-10-14T13:56:00+00:00")])
        self.assertEqual((written, skipped), (1, 1))
        self.assertEqual(len(verify.load(self.dir)), 2)

    def test_same_time_at_a_different_buoy_is_a_different_observation(self):
        written, _ = verify.append_new(self.dir, [
            self.ob("2026-10-14T13:26:00+00:00", "46224"), self.ob("2026-10-14T13:26:00+00:00", "46225")])
        self.assertEqual(written, 2)

    def test_duplicates_inside_one_batch_are_dropped(self):
        written, skipped = verify.append_new(self.dir, [self.ob("2026-10-14T13:26:00+00:00")] * 3)
        self.assertEqual((written, skipped), (1, 2))

    def test_forecast_repeat_within_the_gap_is_skipped_but_later_is_kept(self):
        verify.append_new(self.dir, [self.fc("2026-10-14T05:00:00-07:00")])
        w1, s1 = verify.append_new(self.dir, [self.fc("2026-10-14T07:00:00-07:00")])      # 2 h later
        w2, s2 = verify.append_new(self.dir, [self.fc("2026-10-14T11:00:00-07:00")])      # 6 h later
        self.assertEqual((w1, s1, w2, s2), (0, 1, 1, 0))

    def test_forecast_gap_is_tracked_per_model_and_buoy(self):
        verify.append_new(self.dir, [self.fc("2026-10-14T05:00:00-07:00")])
        written, _ = verify.append_new(self.dir, [
            self.fc("2026-10-14T06:00:00-07:00", model="gwam"),
            self.fc("2026-10-14T06:00:00-07:00", buoy="46225")])
        self.assertEqual(written, 2)

    def test_dedupe_works_across_a_month_boundary(self):
        verify.append_new(self.dir, [self.fc("2026-09-30T23:00:00-07:00")])
        written, skipped = verify.append_new(self.dir, [self.fc("2026-10-01T01:00:00-07:00")])
        self.assertEqual((written, skipped), (0, 1))

    def test_a_corrupt_line_is_skipped_not_fatal(self):
        verify.append_new(self.dir, [self.ob("2026-10-14T13:26:00+00:00")])
        with open(os.path.join(self.dir, "2026-10.jsonl"), "a", encoding="utf-8") as f:
            f.write("{not json\n\n")
        self.assertEqual(len(verify.load(self.dir)), 1)

    def test_records_are_compact_valid_json(self):
        verify.append_new(self.dir, [self.ob("2026-10-14T13:26:00+00:00")])
        with open(os.path.join(self.dir, "2026-10.jsonl"), encoding="utf-8") as f:
            line = f.readline()
        self.assertNotIn(" ", line.strip())
        self.assertEqual(json.loads(line)["buoy"], "46224")


class Collect(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self._tmp.name, "log")
        self.obs_hours = []
        self.base = NOW.replace(minute=0)

    def tearDown(self):
        self._tmp.cleanup()

    def fetch_model(self, lat, lon, model, variables):
        return hourly(self.base, 30, swell_wave_height=1.0, swell_wave_period=14.0)

    def fetch_obs(self, buoy, hours):
        self.obs_hours.append(hours)
        t = datetime.datetime(2026, 10, 14, 12, 56, tzinfo=UTC)
        return [{"time": t, "wvht_m": 1.1, "swh_m": 1.0, "swp_s": 14.0, "swd_deg": 200.0,
                 "wwh_m": 0.3, "wwp_s": 6.0, "apd_s": 8.0}]

    def run_collect(self, **kw):
        return verify.collect(NOW, self.dir, fetch_model=kw.pop("fetch_model", self.fetch_model),
                              fetch_obs=kw.pop("fetch_obs", self.fetch_obs),
                              buoys={"46224": (33.178, -117.472)}, models=["default", "gwam"], **kw)

    def test_logs_one_forecast_per_model_plus_the_observations(self):
        out = self.run_collect()
        self.assertEqual((out["written"], out["problems"]), (3, []))
        kinds = sorted(r["k"] + ":" + r.get("model", "") for r in verify.load(self.dir))
        self.assertEqual(kinds, ["fc:default", "fc:gwam", "ob:"])

    def test_first_run_backfills_then_later_runs_stay_short(self):
        self.run_collect()
        self.run_collect()
        self.assertEqual(self.obs_hours, [verify.BACKFILL_HOURS, verify.OBS_HOURS])

    def test_running_twice_logs_nothing_new(self):
        self.run_collect()
        out = self.run_collect()
        self.assertEqual(out["written"], 0)

    def test_a_failing_model_is_reported_and_the_rest_still_logged(self):
        def flaky(lat, lon, model, variables):
            if model == "gwam":
                raise RuntimeError("HTTP 500")
            return self.fetch_model(lat, lon, model, variables)
        out = self.run_collect(fetch_model=flaky)
        self.assertEqual(out["written"], 2)
        self.assertEqual(len(out["problems"]), 1)
        self.assertIn("gwam", out["problems"][0])

    def test_a_failing_observation_feed_does_not_stop_forecasts(self):
        def boom(buoy, hours):
            raise RuntimeError("feed down")
        out = self.run_collect(fetch_obs=boom)
        self.assertEqual(out["written"], 2)
        self.assertIn("observations", out["problems"][0])


if __name__ == "__main__":
    unittest.main()
