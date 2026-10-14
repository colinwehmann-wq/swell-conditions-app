"""Turn raw buoy / tide / forecast data into a per-spot verdict and a peak window."""
import datetime

from .timeutil import floor_hour

M_TO_FT = 3.28084

# Relative importance of each factor in the 0-100 score.
WEIGHTS = {"height": 0.34, "period": 0.24, "swell_dir": 0.14, "wind": 0.20, "tide": 0.08}

# When a hard gate fails, the displayed rating is capped here (-> "red").
RATING_GATE_CAP = 48.0


# --------------------------------------------------------------------------- math

def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _ramp(x, a, b):
    """0 at a, 1 at b, linear, clamped."""
    if a == b:
        return 1.0 if x >= a else 0.0
    return _clamp((x - a) / (b - a))


def _band(x, ok, ideal):
    """1.0 inside `ideal`, tapering to 0 at the `ok` edges, 0 beyond `ok`."""
    ok_lo, ok_hi = ok
    id_lo, id_hi = ideal
    if x < ok_lo or x > ok_hi:
        return 0.0
    if x < id_lo:
        return _ramp(x, ok_lo, id_lo)
    if x > id_hi:
        return 1.0 - _ramp(x, id_hi, ok_hi)
    return 1.0


def _ang_dist(a, b):
    d = abs((a - b) % 360)
    return min(d, 360 - d)


def _in_arc(deg, lo, hi):
    if deg is None:
        return False
    deg, lo, hi = deg % 360, lo % 360, hi % 360
    return lo <= deg <= hi if lo <= hi else (deg >= lo or deg <= hi)


def _arc_center(lo, hi):
    return (lo + hi) / 2.0 if lo <= hi else ((lo + hi + 360) / 2.0) % 360


def _dir_score(deg, lo, hi, falloff=45.0):
    if deg is None:
        return 0.5
    if _in_arc(deg, lo, hi):
        return 1.0
    edge = min(_ang_dist(deg, lo), _ang_dist(deg, hi))
    return _clamp(1.0 - edge / falloff) * 0.6


def _wind_score(speed_kn, dir_deg, cfg):
    if speed_kn is None:
        return 0.6
    if dir_deg is not None and _in_arc(dir_deg, *cfg["offshore_dir_deg"]):
        return _clamp(1.0 - _ramp(speed_kn, 22, 38) * 0.5)   # offshore: only a gale hurts
    base = 1.0 - _ramp(speed_kn, cfg["wind_ideal_kn"], cfg["wind_max_kn"])
    if dir_deg is not None:
        center = _arc_center(*cfg["offshore_dir_deg"])
        cross = _clamp(1.0 - _ang_dist(dir_deg, center) / 110.0)  # 1 near offshore .. 0 dead onshore
        base *= 0.6 + 0.4 * cross
    else:
        base *= 0.8
    return _clamp(base)


# ----------------------------------------------------------------------- scoring

def score(height_ft, period_s, swell_dir, wind_kn, wind_dir, tide_ft, cfg):
    sub = {
        "height": _band(height_ft, cfg["height_ok_ft"], cfg["height_ideal_ft"]) if height_ft is not None else 0.0,
        "period": _ramp(period_s, cfg["period_min_s"], cfg["period_ideal_s"]) if period_s is not None else 0.0,
        "swell_dir": _dir_score(swell_dir, *cfg["swell_dir_deg"]),
        "wind": _wind_score(wind_kn, wind_dir, cfg),
        "tide": _band(tide_ft, cfg["tide_ok_ft"], cfg["tide_ideal_ft"]) if tide_ft is not None else 0.5,
    }
    total = sum(sub[k] * WEIGHTS[k] for k in WEIGHTS) * 100.0
    return total, sub


def _gates_ok(height_ft, period_s, wind_kn, wind_dir, cfg):
    """Hard cutoffs a spot must clear to be 'on', regardless of overall score."""
    if height_ft is None or not (cfg["height_ok_ft"][0] <= height_ft <= cfg["height_ok_ft"][1]):
        return False
    if period_s is None or period_s < cfg["period_min_s"]:
        return False
    if _wind_score(wind_kn, wind_dir, cfg) < 0.35:   # blown out / too onshore to be worth it
        return False
    return True


def wind_relation(dir_deg, cfg):
    if dir_deg is None:
        return None
    if _in_arc(dir_deg, *cfg["offshore_dir_deg"]):
        return "offshore"
    return "cross" if _ang_dist(dir_deg, _arc_center(*cfg["offshore_dir_deg"])) <= 70 else "onshore"


# ----------------------------------------------------------------- data assembly

def _conditions(dt, marine_row, wind_row, tide, buoy, use_buoy, calib=None):
    """(height_ft, period_s, swell_dir, wind_kn, wind_dir, tide_ft) for one moment.

    When reading from the wave model (not the buoy), `calib` (a {h_scale, p_shift}
    dict) nudges the model onto the live buoy so only its trend carries through.
    """
    if use_buoy and buoy and not buoy["stale"]:
        h_m = buoy["swh_m"] or buoy["wvht_m"]
        height_ft = h_m * M_TO_FT if h_m else None
        period_s = buoy["swp_s"] or buoy["apd_s"]
        swell_dir = buoy["swd_deg"] if buoy["swd_deg"] is not None else buoy["mwd_deg"]
    else:
        m = marine_row or {}
        h_m = m.get("swell_wave_height")
        if h_m is None:
            h_m = m.get("wave_height")
        height_ft = h_m * M_TO_FT if h_m is not None else None
        period_s = m.get("swell_wave_period") or m.get("wave_period")
        swell_dir = m.get("swell_wave_direction")
        if swell_dir is None:
            swell_dir = m.get("wave_direction")
        if calib:
            if height_ft is not None:
                height_ft *= calib["h_scale"]
            if period_s is not None:
                period_s += calib["p_shift"]
    w = wind_row or {}
    return (height_ft, period_s, swell_dir,
            w.get("wind_speed_10m"), w.get("wind_direction_10m"),
            tide.height(dt) if tide else None)


def _daylight_rows(cfg, sun, now, marine, wind, tide, buoy, allow_buoy=True, calib=None,
                   start=None):
    """Hourly scores for daylight hours that are still ahead (or all of a future day).

    `allow_buoy` lets the hour nearest `now` use the live buoy reading instead of
    the wave model; pass False for a future day, where the buoy is no proxy.
    """
    sunrise, sunset = sun
    if sunrise is None:
        return []
    first = floor_hour(start) if start is not None else floor_hour(now)
    dt = max(floor_hour(sunrise), first)
    last = sunset - datetime.timedelta(minutes=45)   # need real daylight left to surf
    fresh_buoy = allow_buoy and bool(buoy) and not (buoy or {}).get("stale", True)
    rows = []
    while dt <= last:
        near = abs((dt - now).total_seconds()) <= 3 * 3600
        cond = _conditions(dt, marine.get(dt), wind.get(dt), tide, buoy,
                           use_buoy=near and fresh_buoy, calib=calib)
        total, sub = score(*cond, cfg=cfg)
        rows.append({"time": dt, "score": total, "sub": sub, "cond": cond,
                     "gates_ok": _gates_ok(cond[0], cond[1], cond[3], cond[4], cfg),
                     "tide_state": tide.state(dt) if tide else None})
        dt += datetime.timedelta(hours=1)
    return rows


def _best_window(rows, threshold):
    best, i = None, 0
    while i < len(rows):
        if rows[i]["score"] >= threshold and rows[i]["gates_ok"]:
            j = i
            while j + 1 < len(rows) and rows[j + 1]["score"] >= threshold and rows[j + 1]["gates_ok"]:
                j += 1
            block = rows[i:j + 1]
            peak = max(block, key=lambda r: r["score"])
            cand = {
                "start": block[0]["time"],
                "end": block[-1]["time"] + datetime.timedelta(hours=1),
                "peak": peak["time"],
                "peak_score": peak["score"],
                "rows": block,
            }
            if best is None or cand["peak_score"] > best["peak_score"]:
                best = cand
            i = j + 1
        else:
            i += 1
    return best


def calibration(now, marine, wind, tide, buoy):
    """Nudge the wave model onto the live buoy.

    Coastal model points run low and a bit short here, so carry only the model's
    trend, not its absolute level. Returns {"h_scale", "p_shift"}; identity when
    there is no fresh buoy.
    """
    hour = floor_hour(now)
    live = _conditions(now, marine.get(hour), wind.get(hour), tide, buoy, use_buoy=True)
    model = _conditions(now, marine.get(hour), wind.get(hour), tide, buoy, use_buoy=False)
    calib = {"h_scale": 1.0, "p_shift": 0.0}
    if buoy and not buoy["stale"] and live[0] and model[0] and model[0] > 0.3:
        calib["h_scale"] = _clamp(live[0] / model[0], 0.6, 2.0)
        if live[1] and model[1]:
            calib["p_shift"] = _clamp(live[1] - model[1], -3.0, 3.0)
    return calib


def timeline(cfg, day, sun, now, buoy, tide, marine, wind, calib):
    """Hourly scored rows across the whole daylight span of `day` (not just what's left)."""
    return _daylight_rows(cfg, sun, now, marine, wind, tide, buoy,
                          allow_buoy=(day == now.date()), calib=calib, start=sun[0])


def _day_summary(cfg, day, rows, lead):
    passing = [r for r in rows if r["gates_ok"]]
    best = max(passing or rows, key=lambda r: r["score"])
    heights = [r["cond"][0] for r in rows if r["cond"][0] is not None]
    return {
        "date": day,
        "lead_days": lead,
        # same rule as the live rating: a failed hard gate caps the day at "red"
        "rating_score": best["score"] if passing else min(best["score"], RATING_GATE_CAP),
        "best": best,
        "window": _best_window(rows, cfg["alert_score_min"]),
        "height_range_ft": (min(heights), max(heights)) if heights else (None, None),
        "rows": rows,
    }


def outlook(cfg, now, buoy, tide, marine, wind, sun_by_date, calib, days=7):
    """One summary per upcoming day: the best daylight hour, a quality window if
    there is one, and the size range. Today counts only while daylight remains;
    days with no forecast data are skipped."""
    out = []
    today = now.date()
    for lead in range(0, days + 1):
        if len(out) >= days:
            break
        day = today + datetime.timedelta(days=lead)
        sun = sun_by_date.get(day)
        if not sun or sun[0] is None:
            continue
        if lead == 0:
            rows = _daylight_rows(cfg, sun, now, marine, wind, tide, buoy, calib=calib)
        else:
            rows = _daylight_rows(cfg, sun, now, marine, wind, tide, buoy,
                                  allow_buoy=False, calib=calib, start=sun[0])
        if not rows or all(r["cond"][0] is None for r in rows):
            continue
        out.append(_day_summary(cfg, day, rows, lead))
    return out


# ------------------------------------------------------------------------- entry

def evaluate_spot(cfg, now, buoy, tide, marine, wind, sun_today, sun_tomorrow, next_check=None):
    now_cond = _conditions(now, marine.get(floor_hour(now)), wind.get(floor_hour(now)),
                           tide, buoy, use_buoy=True)
    now_total, now_sub = score(*now_cond, cfg=cfg)
    now_gates = _gates_ok(now_cond[0], now_cond[1], now_cond[3], now_cond[4], cfg)

    calib = calibration(now, marine, wind, tide, buoy)

    today_rows = _daylight_rows(cfg, sun_today, now, marine, wind, tide, buoy, calib=calib)
    thr = cfg["alert_score_min"]
    window = _best_window(today_rows, thr)
    day_label = "today"
    if window is None:
        tomo_rows = _daylight_rows(cfg, sun_tomorrow, sun_tomorrow[0] or now, marine, wind, tide,
                                   buoy, allow_buoy=False, calib=calib)
        window = _best_window(tomo_rows, thr)
        day_label = "tomorrow"

    if window is not None:
        sunset_day = (sun_today if day_label == "today" else sun_tomorrow)[1]
        if sunset_day is not None and window["end"] > sunset_day:
            window["end"] = sunset_day

    if now_gates and now_total >= thr:
        verdict = "GO"
    elif window is not None and day_label == "today":
        verdict = "LATER"
    elif now_total >= thr - 12:
        verdict = "MARGINAL"
    else:
        verdict = "FLAT"

    # Does a quality window open between now and the next scheduled check?
    window_soon = bool(
        window is not None and day_label == "today"
        and next_check is not None and window["start"] <= next_check
    )

    # A rating (vs the raw score) reads red whenever a hard gate fails — the
    # swell may be there, but it's not a session you'd want.
    rating_score = now_total if now_gates else min(now_total, RATING_GATE_CAP)

    # When there's no qualifying window, say what's holding it back.
    near_miss = None
    if window is None:
        pool = today_rows or _daylight_rows(cfg, sun_tomorrow, sun_tomorrow[0] or now,
                                            marine, wind, tide, buoy, allow_buoy=False, calib=calib)
        if pool:
            best = max(pool, key=lambda r: r["score"])
            limiter = min(WEIGHTS, key=lambda k: best["sub"][k])
            near_miss = {
                "day": "today" if today_rows else "tomorrow",
                "time": best["time"],
                "score": best["score"] if best["gates_ok"] else min(best["score"], RATING_GATE_CAP),
                "limiter": limiter,
                "cond": best["cond"],
            }

    # buoy-vs-model size sanity note (they measure different things / places)
    disagree = None
    fc = _conditions(now, marine.get(floor_hour(now)), wind.get(floor_hour(now)), tide, buoy, use_buoy=False)
    if buoy and not buoy["stale"] and now_cond[0] and fc[0] and abs(now_cond[0] - fc[0]) >= 2.5:
        disagree = fc[0]

    return {
        "name": cfg["name"],
        "verdict": verdict,
        "now_score": now_total,
        "rating_score": rating_score,
        "now_sub": now_sub,
        "now_cond": now_cond,
        "now_gates_ok": now_gates,
        "buoy": buoy,
        "tide_state": tide.state(now) if tide else "?",
        "wind_rel": wind_relation(now_cond[4], cfg),
        "window": window,
        "window_day": day_label if window else None,
        "window_soon": window_soon,
        "next_check": next_check,
        "near_miss": near_miss,
        "forecast_height_ft": disagree,
        "notes": cfg.get("notes", ""),
        "cfg": cfg,
    }
