#!/usr/bin/env python3
"""
Surf checker for North County San Diego.

  python3 check.py                 evaluate every spot, print a report, push alerts
                                   for anything newly GO, remember what was sent
  python3 check.py --report        print the report only (no alerts, no state change)
  python3 check.py --quiet         print nothing unless there's something to alert
  python3 check.py --force         alert every GO spot, ignoring what was already sent
  python3 check.py --spot swami    only this spot (substring match)
  python3 check.py --json          machine-readable dump of the full evaluation

Notifications: console always. Set env vars to add channels:
  NTFY_TOPIC=my-secret-topic          free phone push via the ntfy app
  SURF_WEBHOOK_URL=https://...         Slack/Discord/× incoming webhook
  SURF_MACOS_NOTIFY=1                  local macOS banner
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from sources import evaluate, forecast, http, ndbc, notify, tides
from sources.timeutil import TZ, clock, floor_hour, hour_label, next_check_after, now as now_local

STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".state.json")


# ------------------------------------------------------------------- data layer

class Context:
    """Fetches shared data once and hands it to each spot."""

    def __init__(self, now):
        self.now = now
        self._buoys = {}
        self._tides = {}
        self._marine = {}
        self._wind = {}
        self._sun = {}

    def buoy(self, ids):
        key = tuple(ids)
        if key not in self._buoys:
            fresh = fallback = None
            for bid in ids:
                if bid not in self._buoys:
                    self._buoys[bid] = ndbc.fetch_spec(bid)
                d = self._buoys[bid]
                if d is None:
                    continue
                if not d["stale"] and fresh is None:
                    fresh = d
                fallback = fallback or d
            self._buoys[key] = fresh or fallback
        return self._buoys[key]

    def tide(self, station):
        if station not in self._tides:
            start = (self.now - datetime.timedelta(days=1)).date()
            try:
                self._tides[station] = tides.fetch(station, start, days=4)
            except Exception as e:  # noqa: BLE001
                print("  ! tide fetch failed (%s): %s" % (station, e), file=sys.stderr)
                self._tides[station] = None
        return self._tides[station]

    def _grid(self, lat, lon):
        return (round(lat, 2), round(lon, 2))

    def marine(self, lat, lon):
        k = self._grid(lat, lon)
        if k not in self._marine:
            try:
                self._marine[k] = forecast.marine(lat, lon, days=3)
            except Exception as e:  # noqa: BLE001
                print("  ! marine forecast failed: %s" % e, file=sys.stderr)
                self._marine[k] = {}
        return self._marine[k]

    def _load_wind(self, lat, lon):
        k = self._grid(lat, lon)
        if k not in self._wind:
            try:
                self._wind[k], self._sun[k] = forecast.wind_and_sun(lat, lon, days=3)
            except Exception as e:  # noqa: BLE001
                print("  ! wind/sun forecast failed: %s" % e, file=sys.stderr)
                self._wind[k], self._sun[k] = {}, {}
        return k

    def wind(self, lat, lon):
        return self._wind[self._load_wind(lat, lon)]

    def sun(self, lat, lon, date):
        return self._sun[self._load_wind(lat, lon)].get(date, (None, None))


# -------------------------------------------------------------------- formatting

_COMPASS_16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
               "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def _compass(deg):
    if deg is None:
        return "?"
    return _COMPASS_16[int((deg % 360) / 22.5 + 0.5) % 16]


def _wind_phrase(wk, wd, rel):
    if wk is None:
        return "wind ?"
    if wk < 4:
        return "wind %.0f kt %s glassy" % (wk, _compass(wd))
    return "wind %.0f kt %s%s" % (wk, _compass(wd), " " + rel if rel else "")


def _cond_line(cond, tide_state, wind_rel=None):
    h, p, sd, wk, wd, tf = cond
    parts = [
        "%s ft" % ("%.1f" % h if h is not None else "?"),
        "@ %s s" % ("%.0f" % p if p is not None else "?"),
        "%s (%s)" % (_compass(sd), "%.0f" % sd if sd is not None else "?"),
        _wind_phrase(wk, wd, wind_rel),
    ]
    if tf is not None:
        parts.append("tide %.1f ft %s" % (tf, tide_state))
    return "  ".join(parts)


def _limiter_phrase(limiter, cond, cfg):
    h, p, sd, wk, wd, tf = cond
    if limiter == "height":
        if h is None:
            return "no wave data"
        return "waves only %.1f ft" % h if h < cfg["height_ideal_ft"][0] else "waves %.1f ft (large)" % h
    if limiter == "period":
        return "short period %.0f s" % p if p else "no period data"
    if limiter == "swell_dir":
        return "swell angle off the break (%s)" % _compass(sd)
    if limiter == "wind":
        if wk is None:
            return "wind unknown"
        rel = evaluate.wind_relation(wd, cfg)
        return "wind %.0f kt%s" % (wk, " " + rel if rel else "")
    if limiter == "tide":
        return "tide %.1f ft" % tf if tf is not None else "tide unknown"
    return limiter


def _window_line(res):
    w = res["window"]
    if w:
        soon = "  • before next check" if res.get("window_soon") else ""
        return "%s %s–%s, best ~%s   %s%s" % (
            res["window_day"], hour_label(w["start"]), hour_label(w["end"]),
            clock(w["peak"]), _rating_tag(w["peak_score"]), soon)
    nm = res.get("near_miss")
    if not nm:
        return "not enough data for a window"
    return "best %s ~%s  %s — held back by %s" % (
        nm["day"], clock(nm["time"]), _rating_tag(nm["score"]),
        _limiter_phrase(nm["limiter"], nm["cond"], res["cfg"]))


def _rating(score):
    """0-100 internal score -> 1.0-10.0 surf rating."""
    return max(1.0, min(10.0, round(score / 10.0, 1)))


def _rating_band(r):
    # gap in the spec (5-6) folded into yellow: red <5, yellow 5-7.5, green >7.5
    if r < 5.0:
        return "red"
    if r <= 7.5:
        return "yellow"
    return "green"


_DOT = {"red": "\U0001f534", "yellow": "\U0001f7e1", "green": "\U0001f7e2"}
_ANSI = {"red": "31", "yellow": "33", "green": "32"}
_USE_ANSI = sys.stdout.isatty()


def _paint(text, band):
    if not _USE_ANSI:
        return text
    return "\033[1;%sm%s\033[0m" % (_ANSI[band], text)


def _rating_tag(score, plain=False):
    """'🟢 8.1/10' — number ANSI-coloured too when writing to a terminal."""
    r = _rating(score)
    band = _rating_band(r)
    num = "%.1f/10" % r
    return "%s %s" % (_DOT[band], num if plain else _paint(num, band))


def format_report(results, now):
    out = ["", "SURF CHECK — %s" % now.strftime("%a %b %-d, %-I:%M %p %Z"), "=" * 46]
    order = {"GO": 0, "LATER": 1, "MARGINAL": 2, "FLAT": 3}
    for res in sorted(results, key=lambda r: (order[r["verdict"]], -r["now_score"])):
        b = res["buoy"]
        if b:
            age = b["age_hours"]
            src = "buoy %s, %s" % (b["buoy"], "%d min ago" % round(age * 60) if age < 1.5
                                   else "%.1f h ago%s" % (age, " (stale)" if b["stale"] else ""))
        else:
            src = "forecast only (no buoy)"
        r = _rating(res["rating_score"])
        band = _rating_band(r)
        out.append("")
        out.append("%s  %-16s  %s  %s" % (_DOT[band], res["name"].upper(),
                                          _paint("%.1f/10" % r, band), res["verdict"]))
        out.append("   now:   %s" % _cond_line(res["now_cond"], res["tide_state"], res["wind_rel"]))
        out.append("   src:   %s" % src)
        if res["forecast_height_ft"]:
            h_now = res["now_cond"][0]
            out.append("   note:  buoy %.1f ft vs model %.1f ft at the beach — treat size as a range"
                       % (h_now, res["forecast_height_ft"]))
        out.append("   peak:  %s" % _window_line(res))
    out.append("")
    out.append(_bottom_line(results))
    out.append("")
    return "\n".join(out)


def _bottom_line(results):
    """The surfer-talk verdict across all spots."""
    order = {"GO": 0, "LATER": 1, "MARGINAL": 2, "FLAT": 3}
    best = min(results, key=lambda r: (order[r["verdict"]], -r["now_score"]))
    name = best["name"]
    if best["verdict"] == "GO":
        band = _rating_band(_rating(best["rating_score"]))
        if band == "green":
            return "\U0001f919 Bottom line: %s is FIRING — get out there, bra! Whatcha waitin' for?!" % name
        return "\U0001f919 Bottom line: %s's got a little somethin', bra. Worth a paddle out. Shoots!" % name
    if best["verdict"] == "LATER" and best["window"]:
        return ("Bottom line: Nothin' doin' right now, bra — but %s could switch on 'round %s. Stay loose."
                % (name, clock(best["window"]["peak"])))
    return "Bottom line: Na bra, not this time around. Shoots! \U0001f919"


def _signoff(band):
    if band == "green":
        return "\U0001f919 Get out there, bra! Whatcha waitin' for?!"
    return "\U0001f919 Not epic, but it'll do, bra. Go get wet — shoots!"


# --- plain-language translations for the phone notification --------------------

_RATING_WORD = {"green": "GOOD", "yellow": "OKAY", "red": "POOR"}


def _size_words(ft):
    if ft is None:
        return "size unknown"
    if ft < 1.5:
        return "tiny (ankle-high)"
    if ft < 2.5:
        return "small (knee-high)"
    if ft < 3.5:
        return "waist-high"
    if ft < 4.5:
        return "chest-high"
    if ft < 5.5:
        return "shoulder- to head-high"
    if ft < 7:
        return "head-high and bigger"
    if ft < 9:
        return "overhead"
    return "well overhead — big"


def _power_words(period_s):
    if period_s is None:
        return ""
    if period_s < 8:
        return "weak, wind-choppy swell"
    if period_s < 10:
        return "average swell"
    if period_s < 13:
        return "solid, lined-up swell"
    return "powerful long-period swell"


def _wind_words(wk, wd, cfg):
    if wk is None:
        return "wind unknown"
    rel = evaluate.wind_relation(wd, cfg)
    if wk < 4:
        return "no wind — glassy and clean"
    if rel == "offshore":
        return "offshore wind — grooming the waves clean"
    if wk < 8:
        return "light wind — mostly clean" if rel == "cross" else "light wind — slightly bumpy"
    if wk < 13:
        return "breezy — bumpy and choppy"
    return "windy — choppy and messy"


def _tide_words(tf, state=None):
    if tf is None:
        return "tide unknown"
    level = "Low" if tf < 2.0 else "Medium" if tf < 4.0 else "High"
    move = {"rising": "coming in", "falling": "going out"}.get(state)
    return "%s tide, %s" % (level, move) if move else "%s tide" % level


def _when_words(res, now):
    w = res["window"]
    if not w:
        return "good right now"
    peak, end = w["peak"], w["end"]
    if res["window_day"] != "today":
        return "best tomorrow around %s (from %s)" % (clock(peak), hour_label(w["start"]))
    if abs((peak - now).total_seconds()) <= 3600 or peak <= now:
        return "go now — stays good until about %s" % hour_label(end)
    return "best around %s — good until about %s" % (clock(peak), hour_label(end))


def alert_title(res):
    if res["verdict"] == "GO":
        rt = _rating(res["rating_score"])
        return "%s: go surf — %s, %.0f/10" % (res["name"], _RATING_WORD[_rating_band(rt)], rt)
    w = res["window"]
    rt = _rating(w["peak_score"])
    return "%s: window coming — peak ~%s, %.0f/10" % (res["name"], clock(w["peak"]), rt)


def _peak_row(w):
    for r in w["rows"]:
        if r["time"] == w["peak"]:
            return r
    return w["rows"][0]


def format_alert(res, now):
    if res["verdict"] != "GO":
        return _format_upcoming(res, now)

    rt = _rating(res["rating_score"])
    band = _rating_band(rt)
    h, p, sd, wk, wd, tf = res["now_cond"]
    power = _power_words(p)
    when = _when_words(res, now)
    if res.get("next_check"):
        when += " (next check ~%s)" % clock(res["next_check"])
    lines = [
        "%s %s looks %s (%.1f/10)" % (_DOT[band], res["name"], _RATING_WORD[band], rt),
        "",
        "Waves: %s%s" % (_size_words(h), (", " + power) if power else ""),
        "Wind: %s" % _wind_words(wk, wd, res["cfg"]),
        "When: %s" % when,
        "Tide: %s" % _tide_words(tf, res["tide_state"]),
        "",
        _signoff(band),
        "",
        "(buoy: %s ft, %s sec, from the %s; wind %s kt)" % (
            "%.1f" % h if h is not None else "?",
            "%.0f" % p if p is not None else "?",
            _compass(sd),
            "%.0f" % wk if wk is not None else "?"),
    ]
    return "\n".join(lines)


def _format_upcoming(res, now):
    """Alert for a spot that isn't good now but has a quality window before the next check."""
    w = res["window"]
    pr = _peak_row(w)
    ph, pp, psd, pwk, pwd, ptf = pr["cond"]
    rt = _rating(w["peak_score"])
    band = _rating_band(rt)
    power = _power_words(pp)
    lines = [
        "%s %s turns on later — %s at its peak (%.1f/10)" % (
            _DOT[band], res["name"], _RATING_WORD[band], rt),
        "",
        "Not yet: right now it's %s" % _cond_line(res["now_cond"], res["tide_state"], res["wind_rel"]),
        "",
        "Best window: %s–%s, peak around %s" % (
            hour_label(w["start"]), hour_label(w["end"]), clock(w["peak"])),
    ]
    if res.get("next_check"):
        lines.append("Next check is ~%s — this is your heads-up to catch it before then." % clock(res["next_check"]))
    lines += [
        "",
        "At the peak:",
        "  Waves: %s%s" % (_size_words(ph), (", " + power) if power else ""),
        "  Wind: %s" % _wind_words(pwk, pwd, res["cfg"]),
        "  Tide: %s" % _tide_words(ptf, pr.get("tide_state")),
        "",
        _signoff(band),
    ]
    return "\n".join(lines)


def format_check(res, now):
    """On-demand 'what's it doing right now' notification for one spot — any verdict."""
    rt = _rating(res["rating_score"])
    band = _rating_band(rt)
    h, p, sd, wk, wd, tf = res["now_cond"]
    power = _power_words(p)
    b = res["buoy"]
    src = ("buoy %s, %d min old" % (b["buoy"], round(b["age_hours"] * 60))) if b else "no buoy (model only)"
    lines = [
        "%s %s right now — %s (%.1f/10)" % (_DOT[band], res["name"], _RATING_WORD[band], rt),
        "",
        "Waves: %s%s" % (_size_words(h), (", " + power) if power else ""),
        "Wind: %s" % _wind_words(wk, wd, res["cfg"]),
        "Tide: %s" % _tide_words(tf, res["tide_state"]),
        "",
    ]
    w = res["window"]
    if w:
        lines.append("Best %s: %s–%s, peak ~%s (%s)" % (
            res["window_day"], hour_label(w["start"]), hour_label(w["end"]),
            clock(w["peak"]), _rating_tag(w["peak_score"], plain=True)))
        if res.get("window_soon"):
            lines.append("That's before the next check (~%s)." % clock(res["next_check"]))
    elif res.get("near_miss"):
        nm = res["near_miss"]
        lines.append("No window %s — closest is ~%s, held back by %s" % (
            nm["day"], clock(nm["time"]), _limiter_phrase(nm["limiter"], nm["cond"], res["cfg"])))
    lines += [
        "",
        _bottom_line([res]),
        "",
        "(%s · %s ft @ %s s from the %s, wind %s kt)" % (
            src,
            "%.1f" % h if h is not None else "?",
            "%.0f" % p if p is not None else "?",
            _compass(sd),
            "%.0f" % wk if wk is not None else "?"),
    ]
    return "\n".join(lines)


_VERDICT_ORDER = {"GO": 0, "LATER": 1, "MARGINAL": 2, "FLAT": 3}


def _best_first(results):
    return sorted(results, key=lambda r: (_VERDICT_ORDER[r["verdict"]], -r["now_score"]))


def _digest_row(res):
    h, p, sd, wk, wd, tf = res["now_cond"]
    r = _rating(res["rating_score"])
    size = "%.1f ft" % h if h is not None else "? ft"
    per = " @ %.0fs" % p if (p is not None and p >= 12) else ""
    if wk is None:
        wind = "wind ?"
    elif wk < 4:
        wind = "%.0f kt glassy" % wk
    else:
        rel = evaluate.wind_relation(wd, res["cfg"])
        wind = ("%.0f kt %s" % (wk, rel)).strip() if rel else "%.0f kt" % wk
    if res["verdict"] == "GO":
        tail = "  → GO now"
    elif res["verdict"] == "LATER" and res["window"]:
        label = "window" if res.get("window_soon") else "later"
        tail = "  → %s ~%s" % (label, clock(res["window"]["peak"]))
    else:
        tail = ""
    return "%s %s  %.1f/10 — %s%s, %s%s" % (
        _DOT[_rating_band(r)], res["name"], r, size, per, wind, tail)


def _time_of_day(now):
    h = now.hour
    return "Morning" if h < 11 else "Midday" if h < 15 else "Evening"


def digest_title(results, now):
    best = _best_first(results)[0]
    r = _rating(best["rating_score"])
    when = _time_of_day(now)
    if best["verdict"] == "GO":
        return "%s check: %s is ON (%.0f/10)" % (when, best["name"], r)
    if best["verdict"] == "LATER":
        return "%s check: %s window later (%.0f/10)" % (when, best["name"], r)
    return "%s check: nothing today (best %.0f/10)" % (when, r)


def _last_alert_note(meta, now):
    """A one-liner confirming the alert path still works (or when it last fired)."""
    iso = (meta or {}).get("last_alert")
    if not iso:
        return "No GO alerts sent yet — you'll get one when a spot fires."
    try:
        days = (now - datetime.datetime.fromisoformat(iso)).total_seconds() / 86400.0
    except ValueError:
        return None
    if days < 1:
        return "Last GO alert: earlier today."
    n = int(days)
    tail = " — all quiet, nothing wrong, just no swell" if n >= 6 else ""
    return "Last GO alert: %d day%s ago%s" % (n, "" if n == 1 else "s", tail)


def format_digest(results, now, meta=None):
    lines = ["%s surf check — %s" % (_time_of_day(now), now.strftime("%a %b %-d")), ""]
    lines += [_digest_row(res) for res in _best_first(results)]
    lines += ["", _bottom_line(results)]
    note = _last_alert_note(meta, now)
    if note:
        lines += ["", note]
    return "\n".join(lines)


# ------------------------------------------------------------------------- state

def load_state():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    try:
        with open(STATE_PATH, "w") as f:
            json.dump(state, f, indent=2)
    except OSError as e:
        print("  ! could not write state: %s" % e, file=sys.stderr)


def alert_kind(res):
    """'GO' (good now), 'SOON' (quality window before the next check), or None."""
    if res["verdict"] == "GO":
        return "GO"
    if res["verdict"] == "LATER" and res.get("window_soon"):
        return "SOON"
    return None


def _peaks_far_apart(iso_a, iso_b):
    if not iso_a or not iso_b:
        return iso_a != iso_b
    try:
        return abs((datetime.datetime.fromisoformat(iso_a)
                    - datetime.datetime.fromisoformat(iso_b)).total_seconds()) > 3600
    except ValueError:
        return iso_a != iso_b


def should_alert(res, state, today, force):
    kind = alert_kind(res)
    if kind is None:
        return False
    if force:
        return True
    prev = state.get(res["name"], {})
    if prev.get("kind") != kind:            # newly good, or SOON -> GO
        return True
    if prev.get("date") != today:           # fresh day
        return True
    cur_peak = res["window"]["peak"].isoformat() if res["window"] else None
    if _peaks_far_apart(prev.get("peak"), cur_peak):   # window moved > 1h
        return True
    return False


# -------------------------------------------------------------------------- main

def run(args):
    if args.test_alert:
        notify.send(
            "Surf check: test alert",
            "\U0001f919 If this lands on your phone, notifications are wired up, bra.\n"
            "Real alerts only fire when a spot is actually worth surfing.\n\n"
            "Shoots!")
        return 0

    if args.now:
        now = datetime.datetime.strptime(args.now, "%Y-%m-%dT%H:%M").replace(tzinfo=TZ)
    else:
        now = now_local()
    ctx = Context(now)
    today = now.date()
    tomorrow = today + datetime.timedelta(days=1)
    next_check = next_check_after(now, config.CHECK_TIMES)

    spots = [config.spot_config(s) for s in config.SPOTS]
    spot_filter = args.spot or args.notify
    if spot_filter:
        q = spot_filter.lower()
        spots = [s for s in spots if q in s["name"].lower()]
        if not spots:
            print("no spot matches %r" % spot_filter, file=sys.stderr)
            return 2

    results = []
    for cfg in spots:
        res = evaluate.evaluate_spot(
            cfg, now,
            ctx.buoy(cfg["buoys"]),
            ctx.tide(cfg["tide_station"]),
            ctx.marine(cfg["lat"], cfg["lon"]),
            ctx.wind(cfg["lat"], cfg["lon"]),
            ctx.sun(cfg["lat"], cfg["lon"], today),
            ctx.sun(cfg["lat"], cfg["lon"], tomorrow),
            next_check=next_check,
        )
        results.append(res)

    if args.json:
        print(json.dumps(_jsonable(results, now), indent=2, default=str))
        return 0

    if args.notify:
        for res in results:
            body = format_check(res, now)
            notify.send("Swell check: %s" % res["name"], body)
        return 0

    report = format_report(results, now)
    alerts = []
    if not args.report:
        state = load_state()
        meta = state.setdefault("_meta", {})

        if args.digest:
            notify.send(digest_title(results, now), format_digest(results, now, meta))

        for res in results:
            if should_alert(res, state, today.isoformat(), args.force):
                alerts.append(res)
        for res in alerts:
            notify.send(alert_title(res), format_alert(res, now))

        for res in results:
            entry = {"kind": alert_kind(res) or res["verdict"], "date": today.isoformat()}
            if res["window"]:
                entry["peak"] = res["window"]["peak"].isoformat()
            state[res["name"]] = entry
        if alerts:
            meta["last_alert"] = now.isoformat()
        meta["last_run"] = now.isoformat()
        save_state(state)
        _ping_healthcheck()

    if not args.quiet or alerts:
        print(report)
    return 0


def _ping_healthcheck():
    """Tell an external monitor (e.g. healthchecks.io) the run completed."""
    url = os.environ.get("HEALTHCHECK_URL", "").strip()
    if not url:
        return
    try:
        http.get(url, timeout=10, tries=2)
    except Exception:  # noqa: BLE001 - best effort
        pass


def _jsonable(results, now):
    def cond(c):
        keys = ["height_ft", "period_s", "swell_dir_deg", "wind_kn", "wind_dir_deg", "tide_ft"]
        return dict(zip(keys, c))

    out = {"generated": now.isoformat(), "spots": []}
    for r in results:
        w = r["window"]
        out["spots"].append({
            "name": r["name"],
            "verdict": r["verdict"],
            "alert_kind": alert_kind(r),
            "window_soon": r.get("window_soon", False),
            "next_check": r["next_check"].isoformat() if r.get("next_check") else None,
            "score": round(r["now_score"], 1),
            "rating": _rating(r["rating_score"]),
            "rating_band": _rating_band(_rating(r["rating_score"])),
            "sub_scores": {k: round(v, 3) for k, v in r["now_sub"].items()},
            "now": cond(r["now_cond"]),
            "tide_state": r["tide_state"],
            "buoy": None if not r["buoy"] else {
                "id": r["buoy"]["buoy"], "age_hours": round(r["buoy"]["age_hours"], 2),
                "stale": r["buoy"]["stale"]},
            "window": None if not w else {
                "day": r["window_day"],
                "start": w["start"].isoformat(), "end": w["end"].isoformat(),
                "peak": w["peak"].isoformat(), "peak_score": round(w["peak_score"], 1),
                "peak_rating": _rating(w["peak_score"])},
            "near_miss": None if not r.get("near_miss") else {
                "day": r["near_miss"]["day"],
                "time": r["near_miss"]["time"].isoformat(),
                "score": round(r["near_miss"]["score"], 1),
                "limiter": r["near_miss"]["limiter"]},
        })
    return out


def main():
    p = argparse.ArgumentParser(description="North County SD surf checker")
    p.add_argument("--report", action="store_true", help="print report only, no alerts")
    p.add_argument("--quiet", action="store_true", help="print nothing unless alerting")
    p.add_argument("--force", action="store_true", help="alert every GO / upcoming-window spot, ignoring dedupe")
    p.add_argument("--spot", metavar="TEXT", help="only spots matching TEXT")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--now", metavar="ISO", help="pretend it's this local time, e.g. 2026-09-09T06:30 (debug)")
    p.add_argument("--test-alert", action="store_true", help="send one sample notification to verify delivery, then exit")
    p.add_argument("--notify", metavar="SPOT", help="push an on-demand conditions check for SPOT (any verdict), then exit")
    p.add_argument("--digest", action="store_true", help="push a one-shot summary of all spots (use on the first check of the day)")
    sys.exit(run(p.parse_args()))


if __name__ == "__main__":
    main()
