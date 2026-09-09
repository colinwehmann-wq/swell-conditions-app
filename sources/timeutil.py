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
