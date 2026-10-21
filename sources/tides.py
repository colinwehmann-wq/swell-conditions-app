"""NOAA CO-OPS tide predictions (hi/lo) plus interpolation between extremes."""
import datetime
import math

from . import http
from .timeutil import TZ

_BASE = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"


class TideSeries:
    """Hi/lo extremes with cosine interpolation for any time in between."""

    def __init__(self, extremes):
        self.ext = extremes  # sorted [(aware_dt, height_ft, "H"|"L"), ...]

    def height(self, when):
        e = self.ext
        if not e or when < e[0][0] or when > e[-1][0]:
            return None
        for i in range(len(e) - 1):
            t1, h1, _ = e[i]
            t2, h2, _ = e[i + 1]
            if t1 <= when <= t2:
                frac = (when - t1).total_seconds() / (t2 - t1).total_seconds()
                mid, amp = (h1 + h2) / 2.0, (h1 - h2) / 2.0
                return mid + amp * math.cos(math.pi * frac)
        return None

    def state(self, when):
        for i in range(len(self.ext) - 1):
            t1, _, _ = self.ext[i]
            t2, _, ty2 = self.ext[i + 1]
            if t1 <= when <= t2:
                return "rising" if ty2 == "H" else "falling"
        return "flat"

    def next_extreme(self, when):
        for t, h, ty in self.ext:
            if t >= when:
                return t, h, ty
        return None


def fetch_water_temp(station, max_age_hours=6.0):
    """The station's latest water temperature in °F as {"temp_f", "time", "age_hours", "source"}, or None if it has none.
    A backup for buoys that report no water temperature; La Jolla's pier gauge agrees with the offshore buoys to ~1°F."""
    url = ("%s?product=water_temperature&application=swell-conditions-app&date=latest&units=english"
           "&time_zone=lst_ldt&format=json&station=%s" % (_BASE, station))
    try:
        rows = http.get_json(url).get("data") or []
        row = rows[-1]
        when = datetime.datetime.strptime(row["t"], "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
        temp = float(row["v"])
    except Exception:  # noqa: BLE001 - no data, a malformed row or the network: callers just go without
        return None
    age = (datetime.datetime.now(TZ) - when).total_seconds() / 3600.0
    if age > max_age_hours or not (30.0 <= temp <= 100.0):
        return None
    return {"temp_f": temp, "time": when, "age_hours": age, "source": "tide station %s" % station}


def fetch(station, start_date, days=3):
    url = (
        "%s?product=predictions&application=swell-conditions-app"
        "&begin_date=%s&range=%d&datum=MLLW&interval=hilo&units=english"
        "&time_zone=lst_ldt&format=json&station=%s"
        % (_BASE, start_date.strftime("%Y%m%d"), days * 24, station)
    )
    payload = http.get_json(url)
    out = []
    for p in payload.get("predictions", []):
        naive = datetime.datetime.strptime(p["t"], "%Y-%m-%d %H:%M")
        out.append((naive.replace(tzinfo=TZ), float(p["v"]), p["type"]))
    out.sort(key=lambda x: x[0])
    return TideSeries(out)
