"""National Data Buoy Center real-time feeds (realtime2 .spec + .txt)."""
import datetime
import math

from . import http
from .timeutil import UTC

_MS_TO_KN = 1.943844

_COMPASS = {
    "N": 0.0, "NNE": 22.5, "NE": 45.0, "ENE": 67.5, "E": 90.0, "ESE": 112.5,
    "SE": 135.0, "SSE": 157.5, "S": 180.0, "SSW": 202.5, "SW": 225.0, "WSW": 247.5,
    "W": 270.0, "WNW": 292.5, "NW": 315.0, "NNW": 337.5,
}


def _num(tok):
    if tok is None or tok == "MM":
        return None
    try:
        return float(tok)
    except ValueError:
        return None


def _dir(tok):
    if tok in _COMPASS:
        return _COMPASS[tok]
    return _num(tok)


def _data_rows(text):
    return [ln.split() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]


def _row_time(r):
    return datetime.datetime(int(r[0]), int(r[1]), int(r[2]), int(r[3]), int(r[4]), tzinfo=UTC)


def _age_hours(t):
    return (datetime.datetime.now(UTC) - t).total_seconds() / 3600.0


# A buoy's single reading jumps around: consecutive half-hourly swell heights can differ by a foot or more as sets and lulls
# pass. The rating should follow the swell, not the last wave group, so the "current" reading is the average of the newest
# few. It lags a rising or falling swell by about half an hour, which is a fair price for not swinging a whole point.
SMOOTH_ROWS = 3
SMOOTH_WINDOW_H = 1.25      # only readings this close to the newest are averaged, so an old one never drags the average back


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _median(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2.0


def _circular_mean(degrees):
    degrees = [d for d in degrees if d is not None]
    if len(degrees) <= 1:
        return degrees[0] if degrees else None
    x = sum(math.sin(math.radians(d)) for d in degrees)
    y = sum(math.cos(math.radians(d)) for d in degrees)
    if abs(x) < 1e-9 and abs(y) < 1e-9:
        return degrees[0]                    # exactly opposite directions: no meaningful average, keep the newest
    return round((math.degrees(math.atan2(x, y)) + 360.0) % 360.0, 1)


def _spec_row(r, t):
    return {
        "time": t,
        "wvht_m": _num(r[5]),
        "swh_m": _num(r[6]),
        "swp_s": _num(r[7]),
        "wwh_m": _num(r[8]),
        "wwp_s": _num(r[9]),
        "swd_deg": _dir(r[10]),
        "wwd_deg": _dir(r[11]),
        "steepness": r[12] if r[12] != "MM" else None,
        "apd_s": _num(r[13]),
        "mwd_deg": _num(r[14]),
    }


def fetch_spec(buoy, max_age_hours=3.0):
    """The buoy's current separated swell / wind-wave reading, or None if unavailable.

    "Current" is the newest reading with its swell height, period and direction smoothed over the last few readings
    (`SMOOTH_ROWS` within `SMOOTH_WINDOW_H`), so one big set or one lull does not swing the rating. The newest reading's own
    values are kept under "raw", and "smoothed_from" says how many readings were averaged.

    Columns: YY MM DD hh mm WVHT SwH SwP WWH WWP SwD WWD STEEPNESS APD MWD
    """
    try:
        rows = _data_rows(http.get("https://www.ndbc.noaa.gov/data/realtime2/%s.spec" % buoy))
    except Exception:
        return None
    recent = []
    for r in rows:
        if len(r) < 15:
            continue
        try:
            t = _row_time(r)
        except ValueError:
            continue
        if _num(r[5]) is None:
            continue
        if recent and (recent[0]["time"] - t).total_seconds() / 3600.0 > SMOOTH_WINDOW_H:
            break                           # rows come newest first: everything after this is older still
        recent.append(_spec_row(r, t))
        if len(recent) >= SMOOTH_ROWS:
            break
    if not recent:
        return None

    newest = recent[0]
    age = _age_hours(newest["time"])
    out = dict(newest)
    out.update({
        "buoy": buoy,
        "age_hours": age,
        "stale": age > max_age_hours,
        "wvht_m": _mean([x["wvht_m"] for x in recent]),
        "swh_m": _mean([x["swh_m"] for x in recent]),
        "swp_s": _median([x["swp_s"] for x in recent]),
        "swd_deg": _circular_mean([x["swd_deg"] for x in recent]),
        "smoothed_from": len(recent),
        "raw": {k: newest[k] for k in ("wvht_m", "swh_m", "swp_s", "swd_deg")},
    })
    return out


def fetch_spec_history(buoy, hours=30.0):
    """Every usable .spec reading from the last `hours`, newest first; [] on any failure.

    The realtime2 file keeps ~45 days of 30-minute rows, so a large `hours` backfills.
    Used to log what the ocean actually did, so forecasts can be scored against it.
    """
    try:
        rows = _data_rows(http.get("https://www.ndbc.noaa.gov/data/realtime2/%s.spec" % buoy))
    except Exception:
        return []
    out = []
    for r in rows:
        if len(r) < 15:
            continue
        try:
            t = _row_time(r)
        except ValueError:
            continue
        if _age_hours(t) > hours or _num(r[5]) is None:
            continue
        out.append({
            "time": t,
            "wvht_m": _num(r[5]),
            "swh_m": _num(r[6]),
            "swp_s": _num(r[7]),
            "wwh_m": _num(r[8]),
            "wwp_s": _num(r[9]),
            "swd_deg": _dir(r[10]),
            "apd_s": _num(r[13]),
        })
    return out


def fetch_wind(buoy, max_age_hours=2.0):
    """Buoy anemometer wind, if the buoy has one and it's fresh. Many CDIP wave
    buoys (incl. 46224 / 46225) report no wind, so callers must handle None.

    Columns: YY MM DD hh mm WDIR WSPD GST WVHT DPD APD MWD PRES ...
    """
    try:
        rows = _data_rows(http.get("https://www.ndbc.noaa.gov/data/realtime2/%s.txt" % buoy))
    except Exception:
        return None
    for r in rows:
        if len(r) < 8:
            continue
        try:
            t = _row_time(r)
        except ValueError:
            continue
        wspd = _num(r[6])
        if wspd is None:
            return None
        if _age_hours(t) > max_age_hours:
            return None
        return {
            "time": t,
            "wdir_deg": _num(r[5]),
            "wspd_kn": wspd * _MS_TO_KN,
            "gust_kn": (_num(r[7]) or wspd) * _MS_TO_KN,
        }
    return None
