"""Open-Meteo hourly forecast: marine (waves/swell) + 10 m wind + daily sun. Free, no key."""
import datetime

from config import TIMEZONE

from . import http
from .timeutil import TZ

_MARINE = "https://marine-api.open-meteo.com/v1/marine"
_WIND = "https://api.open-meteo.com/v1/forecast"
_TZ_PARAM = TIMEZONE.replace("/", "%2F")

_MARINE_VARS = [
    "wave_height", "wave_direction", "wave_period",
    "swell_wave_height", "swell_wave_period", "swell_wave_direction",
    "wind_wave_height",
]
_WIND_VARS = ["wind_speed_10m", "wind_direction_10m", "wind_gusts_10m"]


def _hourly(payload):
    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    rows = {}
    for i, tstr in enumerate(times):
        dt = datetime.datetime.strptime(tstr, "%Y-%m-%dT%H:%M").replace(tzinfo=TZ)
        rows[dt] = {k: (v[i] if i < len(v) else None) for k, v in hourly.items() if k != "time"}
    return rows


def marine(lat, lon, days=3):
    url = ("%s?latitude=%.4f&longitude=%.4f&hourly=%s&forecast_days=%d&timezone=%s"
           % (_MARINE, lat, lon, ",".join(_MARINE_VARS), days, _TZ_PARAM))
    return _hourly(http.get_json(url))


def wind_and_sun(lat, lon, days=3):
    """(hourly wind dict, {date: (sunrise_dt, sunset_dt)})."""
    url = ("%s?latitude=%.4f&longitude=%.4f&hourly=%s&daily=sunrise,sunset"
           "&wind_speed_unit=kn&forecast_days=%d&timezone=%s"
           % (_WIND, lat, lon, ",".join(_WIND_VARS), days, _TZ_PARAM))
    payload = http.get_json(url)
    wind = _hourly(payload)
    sun = {}
    daily = payload.get("daily", {})
    for d, sr, ss in zip(daily.get("time", []), daily.get("sunrise", []), daily.get("sunset", [])):
        date = datetime.datetime.strptime(d, "%Y-%m-%d").date()
        sun[date] = (
            datetime.datetime.strptime(sr, "%Y-%m-%dT%H:%M").replace(tzinfo=TZ),
            datetime.datetime.strptime(ss, "%Y-%m-%dT%H:%M").replace(tzinfo=TZ),
        )
    return wind, sun
