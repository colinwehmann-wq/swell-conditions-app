"""Assemble the public data payload and write the static site.

`make_payload` turns evaluation results into a plain, JSON-serialisable dict (this
is also published as data/latest.json so anyone can build on it). `build` writes
that file plus the HTML pages and assets.
"""
import datetime
import json
import os
import shutil

import config
from sources import boards, evaluate, words
from sources.timeutil import clock, hour_label

from . import render

_ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
_NTFY_HOST = "ntfy.sh"
_ORDER = {"GO": 0, "LATER": 1, "MARGINAL": 2, "FLAT": 3}

SOURCES = {
    "waves": "NOAA National Data Buoy Center — buoys 46224 (Oceanside Offshore), 46225 (Torrey Pines Outer), "
             "46258 (Mission Bay West) and 46232 (Point Loma South)",
    "tides": "NOAA CO-OPS tide predictions — station 9410230 (La Jolla)",
    "forecast": "Open-Meteo Marine and Weather APIs (CC BY 4.0)",
}


def _r(x, nd=1):
    return None if x is None else round(x, nd)


def _iso(dt):
    return dt.isoformat() if dt is not None else None


def _cap(s):
    return s[:1].upper() + s[1:] if s else s


def _band(score):
    r = words.rating(score)
    band = words.rating_band(r)
    return {"rating": r, "band": band, "label": words.rating_label(r)}


def _conditions(cond, tide_state, cfg):
    h, p, sd, wk, wd, tf = cond
    return {
        "height_ft": _r(h),
        "period_s": _r(p, 0),
        "swell_dir_deg": _r(sd, 0),
        "swell_dir": words.compass(sd) if sd is not None else None,
        "wind_kn": _r(wk, 0),
        "wind_dir_deg": _r(wd, 0),
        "wind_dir": words.compass(wd) if wd is not None else None,
        "wind_relation": evaluate.wind_relation(wd, cfg),
        "tide_ft": _r(tf),
        "tide_state": tide_state,
        "words": {
            "size": words.size_words(h),
            "power": words.power_words(p),
            "wind": words.wind_words(wk, wd, cfg),
            "tide": words.tide_words(tf, tide_state),
        },
    }


def _board(cond, cfg):
    h, p, _sd, wk, wd, _tf = cond
    return boards.recommend(h, p, wk, evaluate.wind_relation(wd, cfg))


def _window(w, day=None):
    if not w:
        return None
    return {
        "day": day,
        "start": _iso(w["start"]),
        "end": _iso(w["end"]),
        "peak": _iso(w["peak"]),
        "peak_rating": words.rating(w["peak_score"]),
    }


def _ntfy(topic):
    return {
        "topic": topic,
        "app_url": "ntfy://%s/%s" % (_NTFY_HOST, topic),
        "web_url": "https://%s/%s" % (_NTFY_HOST, topic),
    }


def _timeline(rows, cfg):
    out = []
    for r in rows:
        score = r["score"] if r["gates_ok"] else min(r["score"], evaluate.RATING_GATE_CAP)
        h, p, _sd, wk, _wd, tf = r["cond"]
        out.append({
            "time": _iso(r["time"]),
            "label": hour_label(r["time"]),
            **_band(score),
            "gates_ok": r["gates_ok"],
            "height_ft": _r(h),
            "period_s": _r(p, 0),
            "wind_kn": _r(wk, 0),
            "tide_ft": _r(tf),
        })
    return out


def _confidence(lead):
    return "high" if lead <= 1 else "medium" if lead <= 3 else "low"


def _outlook(days, cfg):
    out = []
    for d in days:
        best = d["best"]
        lo, hi = d["height_range_ft"]
        out.append({
            "date": d["date"].isoformat(),
            "weekday": d["date"].strftime("%a"),
            "day": "%s %d" % (d["date"].strftime("%b"), d["date"].day),
            "lead_days": d["lead_days"],
            "confidence": _confidence(d["lead_days"]),
            **_band(d["rating_score"]),
            "height_range_ft": [_r(lo), _r(hi)],
            "peak": _iso(best["time"]),
            "peak_conditions": _conditions(best["cond"], best.get("tide_state"), cfg),
            "window": _window(d["window"]),
            "board": _board(best["cond"], cfg),
        })
    return out


def _secondary(s):
    """The secondary swell worth a mention (or None), shaped for the page and the JSON."""
    if not s:
        return None
    return {
        "height_ft": _r(s["height_ft"]),
        "period_s": _r(s["period_s"], 0),
        "dir_deg": _r(s["dir_deg"], 0),
        "dir": words.compass(s["dir_deg"]) if s["dir_deg"] is not None else None,
        "in_window": bool(s["in_window"]),
    }


def _spot(item, now):
    res = item["result"]
    cfg = res["cfg"]
    now_c = _conditions(res["now_cond"], res["tide_state"], cfg)
    buoy = res["buoy"]
    return {
        "slug": cfg["slug"],
        "name": cfg["name"],
        "area": cfg.get("area", ""),
        "aliases": list(cfg.get("aliases", [])),
        "lat": cfg["lat"],
        "lon": cfg["lon"],
        "notes": cfg.get("notes", ""),
        "verdict": res["verdict"],
        **_band(res["rating_score"]),
        "now": now_c,
        "secondary_swell": _secondary(res.get("secondary_swell")),
        "board": _board(res["now_cond"], cfg),
        "buoy": None if not buoy else {
            "id": buoy["buoy"],
            "age_minutes": int(round(buoy["age_hours"] * 60)),
            "stale": bool(buoy["stale"]),
        },
        "window": _window(res["window"], res["window_day"]),
        "window_soon": bool(res.get("window_soon")),
        "timeline_label": "Tomorrow" if item.get("timeline_day") and item["timeline_day"] > now.date() else "Today",
        "timeline": _timeline(item["timeline"], cfg),
        "outlook": _outlook(item["outlook"], cfg),
        "ideal": {
            "height_ft": cfg["height_ideal_ft"],
            "period_min_s": cfg["period_min_s"],
            "period_ideal_s": cfg["period_ideal_s"],
            "swell_dir_deg": cfg["swell_dir_deg"],
            "swell_dir": [words.compass(cfg["swell_dir_deg"][0]), words.compass(cfg["swell_dir_deg"][1])],
            "tide_ft": cfg["tide_ideal_ft"],
            "wind_max_kn": cfg["wind_max_kn"],
        },
        "benchmark": _benchmark(cfg.get("benchmark")),
        "ntfy": _ntfy(cfg["ntfy_topic"]),
    }


def _benchmark(b):
    """What a 7 and a 9 have looked like at this break (from tools/build_benchmarks.py), or None."""
    if not b or not b.get("typical"):
        return None
    out = {"days_per_year": b["days_per_year"], "years": int(round(b["history"]["days"] / 365.25)), "typical": {}}
    for rating, t in b["typical"].items():
        out["typical"][rating] = {
            "label": words.rating_label(float(rating)), "size_ft": t["size_ft"], "period_s": t["period_s"],
            "swell_dir": words.compass(t["swell_dir_deg"]), "swell_dir_deg": t["swell_dir_deg"],
            "wind_kn": t["wind_kn"], "tide_ft": t["tide_ft"], "hour": t["hour"],
        }
    return out


def _directory_entry(s):
    """What the search box and the directory need to know about one break, nothing more."""
    c = s["now"]
    size = None
    if c["height_ft"] is not None:
        size = ("%.1f" % c["height_ft"]).rstrip("0").rstrip(".") + " ft"
        if c["period_s"] is not None:
            size += " at %d s" % c["period_s"]
    return {"slug": s["slug"], "name": s["name"], "area": s["area"], "aliases": s["aliases"],
            "rating": s["rating"], "band": s["band"], "label": s["label"], "size": size}


def _is_daylight(items, now):
    """True while the sun is up (or when we can't tell) — 'right now' headlines only
    make sense in daylight."""
    for i in items:
        sun = i.get("sun")
        if sun and sun[0] and sun[1]:
            return sun[0] <= now <= sun[1]
    return True


PEAK_STRONG = 70.0      # same bar as a GO (a 7)
PEAK_RIDEABLE = 50.0
PEAKS_PER_DAY = 5


def _peaks(items):
    """Every spot's best hour on every forecast day, soonest first. The page carries this list
    so the headline can roll over to the next peak as the clock passes the one on show; the
    wording is precomputed here so the browser only has to choose. See sitegen/assets/peaks.js."""
    found = []
    for item in items:
        cfg = item["result"]["cfg"]
        for d in item["outlook"]:
            best = d["best"]
            h, p = best["cond"][0], best["cond"][1]
            lo, hi = d["height_range_ft"]
            found.append((best["time"], {
                "slug": cfg["slug"],
                "name": cfg["name"],
                "date": d["date"].isoformat(),
                "time": _iso(best["time"]),
                "time_label": clock(best["time"]),
                "weekday": d["date"].strftime("%A"),
                "score": _r(d["rating_score"], 1),
                **_band(d["rating_score"]),
                "sub": "%s, %s. About %s–%s ft." % (_cap(words.size_words(h)), words.power_words(p),
                                                    _r(lo), _r(hi)),
            }))
    # Keep each day's best few. The headline only ever needs the best peak still ahead on the
    # earliest good day, and carrying every break's every day would bloat the page for nothing.
    by_day = {}
    for t, p in found:
        by_day.setdefault(p["date"], []).append((t, p))
    kept = []
    for day in by_day.values():
        kept += sorted(day, key=lambda x: (-x[1]["score"], x[0]))[:PEAKS_PER_DAY]
    return [p for _t, p in sorted(kept, key=lambda x: x[0])]


def pick_next_peak(peaks, now):
    """The peak the headline should name at `now`: the earliest day that still has a strong
    peak ahead (best spot that day), else the best rideable one, else None. Mirrors
    `pick` in sitegen/assets/peaks.js, which tests/test_peaks_js.py checks it against."""
    ahead = [p for p in peaks if datetime.datetime.fromisoformat(p["time"]) > now]
    strong = [p for p in ahead if p["score"] >= PEAK_STRONG]
    if strong:
        return min(strong, key=lambda p: (p["date"], -p["score"], datetime.datetime.fromisoformat(p["time"])))
    ok = [p for p in ahead if p["score"] >= PEAK_RIDEABLE]
    if ok:
        return min(ok, key=lambda p: (-p["score"], datetime.datetime.fromisoformat(p["time"])))
    return None


def peak_title(p, lead_days):
    """Mirrors `title` in peaks.js."""
    if lead_days == 0:
        return "Today, %s peaks around %s." % (p["name"], p["time_label"])
    if lead_days == 1:
        return "Tomorrow is the one — %s peaks around %s." % (p["name"], p["time_label"])
    return "Not today. Best bet: %s at %s." % (p["weekday"], p["name"])


def _fig(slug, name, rating, band, label):
    return {"slug": slug, "name": name, "rating": rating, "band": band, "label": label}


def _headline(items, now, peaks):
    """What the top of the page says, plus `fig` (the big rating beside it) and `anchor` (the
    moment this text goes stale: the page then swaps in the next peak itself)."""
    results = [i["result"] for i in items]
    daylight = _is_daylight(items, now)

    go = sorted((r for r in results if r["verdict"] == "GO" and daylight), key=lambda r: -r["rating_score"])
    if go:
        r = go[0]
        cfg = r["cfg"]
        h, p, _sd, wk, wd, _tf = r["now_cond"]
        sub = "%s, %s. %s." % (_cap(words.size_words(h)), words.power_words(p),
                               _cap(words.wind_words(wk, wd, cfg)))
        w = r["window"] if r["window_day"] == "today" else None
        if w:
            sub += " Good until about %s." % hour_label(w["end"])
        return {"kicker": "Right now · %s" % clock(now), "title": "%s is the pick." % cfg["name"],
                "sub": sub, "slug": cfg["slug"],
                "fig": _fig(cfg["slug"], cfg["name"], **_band(r["rating_score"])),
                "anchor": _iso(w["end"] if w else now + datetime.timedelta(hours=1))}

    later = [r for r in results if r["verdict"] == "LATER" and r["window"] and daylight]
    if later:
        r = min(later, key=lambda r: r["window"]["start"])
        w = r["window"]
        return {
            "kicker": "Heads-up · %s" % clock(now),
            "title": "Nothing yet — %s turns on around %s." % (r["cfg"]["name"], clock(w["peak"])),
            "sub": "Best window %s to %s today." % (hour_label(w["start"]), hour_label(w["end"])),
            "slug": r["cfg"]["slug"],
            "fig": _fig(r["cfg"]["slug"], r["cfg"]["name"], **_band(w["peak_score"])),
            "anchor": _iso(w["peak"]),
        }

    # Nothing good right now: look ahead to the next peak still in front of us.
    best = pick_next_peak(peaks, now)
    if best:
        lead = (datetime.date.fromisoformat(best["date"]) - now.date()).days
        return {
            "kicker": "Looking ahead",
            "title": peak_title(best, lead),
            "sub": best["sub"],
            "slug": best["slug"],
            "fig": _fig(best["slug"], best["name"], best["rating"], best["band"], best["label"]),
            "anchor": best["time"],
        }

    return {"kicker": "Looking ahead", "title": "A flat spell.",
            "sub": "Nothing worth paddling out for this week. We'll tell you when that changes.",
            "slug": None, "fig": None, "anchor": None}


def make_payload(inputs, now):
    """inputs: [{"result", "outlook", "timeline"}, ...] -> JSON-serialisable dict."""
    spots = [_spot(i, now) for i in inputs]
    ranking = sorted(spots, key=lambda s: (_ORDER[s["verdict"]], -s["rating"]))
    peaks = _peaks(inputs)
    # North to south, which is also how the directory reads.
    by_coast = sorted(spots, key=lambda s: -s["lat"])
    return {
        "generated": now.isoformat(),
        "generated_label": "%s, %s %s" % (now.strftime("%a %b ") + str(now.day), clock(now), now.strftime("%Z")),
        "site_url": config.SITE_URL,
        "profiles_api": config.PROFILES_API,
        "repo_url": "https://github.com/colinwehmann-wq/swell-conditions-app",
        "headline": _headline(inputs, now, peaks),
        "peaks": peaks,
        "ranking": [s["slug"] for s in ranking],
        "top": [s["slug"] for s in ranking[:config.HOME_COUNT]],
        "breaks": [_directory_entry(s) for s in by_coast],
        "spots": spots,
        "digest": _ntfy(config.public_topic("daily")),
        "sources": SOURCES,
    }


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def build(inputs, now, outdir):
    payload = make_payload(inputs, now)
    _write(os.path.join(outdir, "data", "latest.json"), json.dumps(payload, indent=2, ensure_ascii=False))
    _write(os.path.join(outdir, "index.html"), render.index_page(payload))
    for spot in payload["spots"]:
        _write(os.path.join(outdir, "spots", spot["slug"], "index.html"), render.spot_page(spot, payload))
    _write(os.path.join(outdir, "breaks", "index.html"), render.breaks_page(payload))
    _write(os.path.join(outdir, "profile", "index.html"), render.profile_page(payload))
    _write(os.path.join(outdir, "map", "index.html"), render.map_page(payload))
    _write(os.path.join(outdir, "404.html"), render.not_found_page(payload))
    _write(os.path.join(outdir, ".nojekyll"), "")
    shutil.copytree(_ASSETS, os.path.join(outdir, "assets"), dirs_exist_ok=True)
    return payload
