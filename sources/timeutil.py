"""Shared time helpers: one timezone for the whole app."""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import TIMEZONE

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo(TIMEZONE)
except Exception:  # pragma: no cover - zoneinfo is stdlib on 3.9+
    TZ = datetime.timezone(datetime.timedelta(hours=-7))  # PDT fallback

UTC = datetime.timezone.utc


def now():
    return datetime.datetime.now(TZ)


def to_local(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(TZ)


def floor_hour(dt):
    return dt.replace(minute=0, second=0, microsecond=0)


def parse_local(text, fmt="%Y-%m-%dT%H:%M"):
    """Parse a wall-clock string that is already in TZ."""
    return datetime.datetime.strptime(text, fmt).replace(tzinfo=TZ)


def clock(dt):
    """'6:40 AM' style, no leading zero."""
    return dt.strftime("%I:%M %p").lstrip("0")


def hour_label(dt):
    """'6 AM' / '5 PM' style."""
    return dt.strftime("%I %p").lstrip("0")


def next_check_after(when, times):
    """TZ-aware datetime of the next scheduled check strictly after `when`.

    `times` is a list of "HH:MM" local strings. Falls back to +6h if the list
    is empty or unparseable.
    """
    candidates = []
    for hhmm in times:
        try:
            h, m = (int(x) for x in hhmm.split(":"))
        except (ValueError, AttributeError):
            continue
        for day_offset in (0, 1):
            d = (when + datetime.timedelta(days=day_offset)).date()
            slot = datetime.datetime(d.year, d.month, d.day, h, m, tzinfo=when.tzinfo or TZ)
            if slot > when:
                candidates.append(slot)
    return min(candidates) if candidates else when + datetime.timedelta(hours=6)
