"""Personal alerts: turn a profile (saved breaks and the conditions someone calls ideal) into a
heads-up about an hour before those conditions peak at one of their breaks.

Everything here is pure: a profile and the hourly conditions in, a decision and a message out.
`tools/profile_alerts.py` does the fetching, the sending and the state file.

A profile (see worker/src/validate.js for the exact shape) has `breaks`, `prefs` (height_ft,
period_min_s, wind, wind_max_kn, swell_dir_deg, tide_ft), per-break `overrides` of those, and
`alerts` (lead_min, min_hours, quiet_from, quiet_to).

An hour *matches* when every preference the person set is met. A run of matching hours at least
`min_hours` long is a *window*; its *peak* is the hour this break rates best. The alert goes out
once the clock reaches `lead_min` minutes before the peak, if the window still has time left.
"""
import datetime

from . import evaluate, words
from .timeutil import clock, hour_label

DEFAULT_PREFS = {
    "height_ft": [3.0, 8.0], "period_min_s": 8.0, "wind": "light", "wind_max_kn": 12.0,
    "swell_dir_deg": None, "tide_ft": None,
}
DEFAULT_ALERTS = {"lead_min": 60, "min_hours": 1, "quiet_from": None, "quiet_to": None}

CALM_KN = 4.0               # under this the surface is glassy whatever direction it blows from
OFFSHORE_MAX_KN = 25.0      # an offshore wind grooms the face until it is nearly a gale
MIN_LEFT = datetime.timedelta(minutes=30)     # a window with less than this left isn't worth the drive
RESEND_IF_PEAK_MOVES = datetime.timedelta(hours=3)
STATE_KEEP = datetime.timedelta(days=3)


# ---------------------------------------------------------------------------- preferences

def prefs_for(profile, slug):
    """The profile's preferences for one break: defaults, then the profile's, then that break's own."""
    out = dict(DEFAULT_PREFS)
    out.update(profile.get("prefs") or {})
    out.update((profile.get("overrides") or {}).get(slug) or {})
    return out


def alerts_of(profile):
    out = dict(DEFAULT_ALERTS)
    out.update(profile.get("alerts") or {})
    return out


def check_hour(cond, prefs, cfg):
    """The preferences this hour fails, as short names; empty means every one is met.

    `cond` is (height_ft, period_s, swell_dir, wind_kn, wind_dir, tide_ft). Something the
    forecast can't tell us (a missing tide, say) never blocks, except size and period, which
    every profile asks about."""
    h, p, sd, wk, wd, tide = cond
    failed = []
    lo, hi = prefs["height_ft"]
    if h is None or not lo <= h <= hi:
        failed.append("size")
    if p is None or p < prefs["period_min_s"]:
        failed.append("period")

    mode = prefs["wind"]
    if mode != "any" and wk is not None:
        if mode == "offshore":
            ok = wk < CALM_KN or (evaluate.wind_relation(wd, cfg) == "offshore" and wk <= OFFSHORE_MAX_KN)
        else:
            ok = wk <= prefs["wind_max_kn"]
        if not ok:
            failed.append("wind")

    arc = prefs["swell_dir_deg"]
    if arc is not None and sd is not None and not evaluate._in_arc(sd, arc[0], arc[1]):
        failed.append("direction")

    tide_range = prefs["tide_ft"]
    if tide_range is not None and tide is not None and not tide_range[0] <= tide <= tide_range[1]:
        failed.append("tide")
    return failed


# ------------------------------------------------------------------------------- windows

def windows(rows, prefs, cfg, min_hours=1):
    """Runs of consecutive matching hours at least `min_hours` long, each as
    {start, end, hours, peak} where `end` is when the last matching hour finishes and `peak` is the
    row that rates best (the earliest, on a tie)."""
    runs, cur = [], []
    for row in rows:
        if check_hour(row["cond"], prefs, cfg):          # something this hour misses: the run ends
            if cur:
                runs.append(cur)
            cur = []
        elif cur and row["time"] - cur[-1]["time"] != datetime.timedelta(hours=1):
            runs.append(cur)
            cur = [row]
        else:
            cur.append(row)
    if cur:
        runs.append(cur)
    out = []
    for run in runs:
        if len(run) < min_hours:
            continue
        peak = max(run, key=lambda r: (r["score"], -r["time"].timestamp()))
        out.append({"start": run[0]["time"], "end": run[-1]["time"] + datetime.timedelta(hours=1),
                    "hours": len(run), "peak": peak})
    return out


def in_quiet_hours(hour, quiet_from, quiet_to):
    if quiet_from is None or quiet_to is None or quiet_from == quiet_to:
        return False
    if quiet_from < quiet_to:
        return quiet_from <= hour < quiet_to
    return hour >= quiet_from or hour < quiet_to          # wraps midnight: 22 to 4


def is_due(window, now, lead_min):
    """True from `lead_min` minutes before the peak until the window is nearly over."""
    target = window["peak"]["time"] - datetime.timedelta(minutes=lead_min)
    return target <= now < window["end"] - MIN_LEFT


def upcoming(profile, slug, cfg, rows, now):
    """The window to alert about for this profile at this break right now, or None."""
    alerts = alerts_of(profile)
    for w in windows(rows, prefs_for(profile, slug), cfg, alerts["min_hours"]):
        if is_due(w, now, alerts["lead_min"]):
            return w
    return None


# ----------------------------------------------------------------------------------- state

def should_send(entry, window, now):
    """`entry` is what was recorded the last time this break alerted this person ({"date", "peak"})."""
    if not entry or entry.get("date") != now.date().isoformat():
        return True
    try:
        before = datetime.datetime.fromisoformat(entry["peak"])
    except (KeyError, ValueError):
        return True
    return abs(window["peak"]["time"] - before) >= RESEND_IF_PEAK_MOVES


def record(state, topic, slug, window, now):
    state.setdefault(topic, {})[slug] = {"date": now.date().isoformat(), "peak": window["peak"]["time"].isoformat()}


def prune(state, live_topics, now):
    """Drop people who deleted their profile, and breaks not alerted about for a few days."""
    cutoff = (now - STATE_KEEP).date().isoformat()
    for topic in list(state):
        if topic not in live_topics:
            del state[topic]
            continue
        state[topic] = {s: e for s, e in state[topic].items() if e.get("date", "") >= cutoff}
        if not state[topic]:
            del state[topic]
    return state


# --------------------------------------------------------------------------------- message

def _in_words(delta):
    minutes = int(round(delta.total_seconds() / 60.0))
    if minutes <= 10:
        return "right about now"
    if minutes < 90:
        return "in about %d minutes" % (round(minutes / 5.0) * 5)
    return "in about %d hours" % round(minutes / 60.0)


def when_phrase(window, now):
    """Where a window stands: still ahead, peaking now, or already under way with its best hour behind us."""
    peak = window["peak"]["time"]
    gap = peak - now
    span = "%s to %s" % (hour_label(window["start"]), hour_label(window["end"]))
    if gap > datetime.timedelta(minutes=10):
        return "best around %s (%s), lined up %s" % (clock(peak), _in_words(gap), span)
    if gap >= -datetime.timedelta(minutes=10):
        return "peaking now, lined up %s" % span
    return "on now until %s (best was around %s)" % (hour_label(window["end"]), clock(peak))


def message(name, window, cfg, now, site_url=""):
    """(title, body) for one alert."""
    peak = window["peak"]
    h, p, sd, wk, wd, tide = peak["cond"]
    rating = words.rating(peak["score"])
    title = "%s: your conditions peak at %s" % (name, hour_label(peak["time"]))
    lines = [
        "Your ideal conditions: %s." % when_phrase(window, now),
        "",
        "Waves: %s, %s (%.1f ft at %d s)" % (words.size_words(h), words.power_words(p), h, round(p)),
        "Wind: %s" % words.wind_words(wk, wd, cfg),
        "Tide: %s" % words.tide_words(tide, peak.get("tide_state")),
        "",
        "%s rates this %.1f/10 (%s)." % (name, rating, words.rating_label(rating)),
    ]
    if site_url:
        lines += ["", "Edit your ideal conditions: %s/profile/" % site_url.rstrip("/")]
    return title, "\n".join(lines)


MAX_LISTED = 8          # more breaks than this in one message are summarised as "+N more"


def digest(items, now, site_url=""):
    """(title, body) for everything due for one person at once: one message that lists every break that
    matches their ideal conditions, best-rated first. `items` is [(cfg, window), ...]. A single break
    gets the fuller message above."""
    items = sorted(items, key=lambda it: -it[1]["peak"]["score"])
    if len(items) == 1:
        cfg, window = items[0]
        return message(cfg["name"], window, cfg, now, site_url=site_url)
    lines = ["These breaks match your ideal conditions:", ""]
    for i, (cfg, window) in enumerate(items[:MAX_LISTED], 1):
        peak = window["peak"]
        h, p, sd, wk, wd, tide = peak["cond"]
        rating = words.rating(peak["score"])
        wind = "%d kt %s" % (round(wk), words.compass(wd)) if wk is not None else "wind unknown"
        lines.append("%d. %s: %s" % (i, cfg["name"], when_phrase(window, now)))
        lines.append("   %.1f ft at %d s, %s, %s ft tide, %s %.1f/10" % (
            h, round(p), wind, "%.1f" % tide if tide is not None else "?", words.rating_label(rating), rating))
    if len(items) > MAX_LISTED:
        lines.append("+%d more" % (len(items) - MAX_LISTED))
    if site_url:
        lines += ["", "Edit your ideal conditions: %s/profile/" % site_url.rstrip("/")]
    return "%d of your breaks are lining up" % len(items), "\n".join(lines)
