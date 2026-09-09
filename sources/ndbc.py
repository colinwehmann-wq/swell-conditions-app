"""National Data Buoy Center real-time feeds (realtime2 .spec + .txt)."""
import datetime

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


def fetch_spec(buoy, max_age_hours=3.0):
    """Most recent separated swell / wind-wave reading, or None if unavailable.

    Columns: YY MM DD hh mm WVHT SwH SwP WWH WWP SwD WWD STEEPNESS APD MWD
    """
    try:
        rows = _data_rows(http.get("https://www.ndbc.noaa.gov/data/realtime2/%s.spec" % buoy))
    except Exception:
        return None
    for r in rows:
        if len(r) < 15:
            continue
        try:
            t = _row_time(r)
        except ValueError:
            continue
        wvht = _num(r[5])
        if wvht is None:
            continue
        age = _age_hours(t)
        return {
            "buoy": buoy,
            "time": t,
            "age_hours": age,
            "stale": age > max_age_hours,
            "wvht_m": wvht,
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
    return None


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
