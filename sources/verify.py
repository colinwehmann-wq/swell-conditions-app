"""Forecast-accuracy log: record what the wave models predicted and what the buoys measured.

Appends JSON lines to `<dir>/YYYY-MM.jsonl`. Two kinds of record (metres, seconds, degrees-from):

  fc  {"k": "fc", "issued": ISO, "buoy": "46224", "model": "ncep_gfswave016",
       "rows": [{"t": ISO, "lead": 3, "hs": 1.2, "tp": 13.1, "sh": 1.0, "sp": 13.0, "sd": 198,
                 "s2h": 0.4, "s2p": 8.7, "wwh": 0.1}, ...]}
      One model's forecast at the buoy's location, every 3 h out to 72 h. `issued` is when we
      asked (floored to the hour), so `lead` is "how far ahead was this call made".
  ob  {"k": "ob", "buoy": "46224", "t": ISO (UTC), "hs": 1.1, "sh": 1.0, "sp": 14.3,
       "sd": 202.5, "wwh": 0.6, "wwp": 6.2, "ap": 8.1}
      One buoy reading.

  mp  {"k": "mp", "issued": ISO, "slug": "swamis", "site": "D0708",
       "rows": [{"t": ISO, "lead": 5, "mhs": 0.9, "mtp": 14.3, "mdp": 252,
                 "ohs": 1.1, "osh": 1.0, "osp": 14.0, "osd": 250}, ...]}
      The CDIP MOP nearshore forecast for a break's nearest point (m*) beside the wave model the live app
      scores that break with (o*), at the MOP's 3-hourly times in daylight. This is the side-by-side that
      shows whether MOP would be a better source of break-level swell; `tools/mop_report.py` reads it.

Short keys: hs total wave height, tp mean period, sh/sp primary swell height/period, sd swell
direction, s2h/s2p/s2d secondary swell, wwh/wwp wind-wave height/period, ap average period.

`sources/skill.py` pairs the two kinds to measure how wrong each model is by lead time.
"""
import datetime
import json
import os
from concurrent.futures import ThreadPoolExecutor

from . import cdip, forecast, ndbc
from .timeutil import UTC

# Buoy -> where to ask the models. Verifying at the buoy compares the model with the thing it
# is trying to predict, without the coastline effects that sit between a buoy and a break.
BUOYS = {
    "46224": (33.178, -117.472),   # Oceanside Offshore
    "46225": (32.933, -117.391),   # Torrey Pines Outer
}

# "default" is what the live app uses today (Open-Meteo's best match, identical to
# meteofrance_wave at this location). The others are Phase 2 blend candidates; logging them now
# means their history is already there when we decide how to weight them.
MODELS = ["default", "meteofrance_wave", "ncep_gfswave016", "ecmwf_wam", "gwam"]

LEAD_STEP_H = 3
MAX_LEAD_H = 72
MIN_FC_GAP_H = 5            # models update ~4x a day; closer repeats add size, not information
OBS_HOURS = 30
BACKFILL_HOURS = 24 * 46    # the NDBC feed keeps ~45 days; a first run takes all of it

_FC_KEYS = {
    "wave_height": "hs", "wave_period": "tp",
    "swell_wave_height": "sh", "swell_wave_period": "sp", "swell_wave_direction": "sd",
    "secondary_swell_wave_height": "s2h", "secondary_swell_wave_period": "s2p",
    "secondary_swell_wave_direction": "s2d",
    "wind_wave_height": "wwh",
}
FC_VARS = list(_FC_KEYS)

MOP_MIN_GAP_H = 11          # MOP updates about twice a day; one record per break per half-day is plenty
MOP_FIRST_HOUR, MOP_LAST_HOUR = 5, 19      # local hours worth surfing; the night rows only add size

_OB_KEYS = {
    "wvht_m": "hs", "swh_m": "sh", "swp_s": "sp", "swd_deg": "sd",
    "wwh_m": "wwh", "wwp_s": "wwp", "apd_s": "ap",
}


def _round(key, v):
    if key in ("sd", "s2d"):
        return round(v, 0)
    return round(v, 1 if key in ("tp", "sp", "s2p", "wwp", "ap") else 2)


def _dt(text):
    return datetime.datetime.fromisoformat(text)


# ------------------------------------------------------------------------- records

def forecast_record(issued, buoy, model, series):
    """Turn one model's hourly series ({aware datetime: {open-meteo var: value}}) into a log
    record, or None if it holds nothing usable in the next 72 hours."""
    base = issued.replace(minute=0, second=0, microsecond=0)
    base_utc = base.astimezone(UTC)
    rows = []
    for t in sorted(series):
        lead = (t.astimezone(UTC) - base_utc).total_seconds() / 3600.0
        if lead < 0 or lead > MAX_LEAD_H or lead % LEAD_STEP_H:
            continue
        row = {"t": t.isoformat(), "lead": int(lead)}
        for var, key in _FC_KEYS.items():
            v = series[t].get(var)
            if v is not None:
                row[key] = _round(key, v)
        if len(row) > 2:
            rows.append(row)
    if not rows:
        return None
    return {"k": "fc", "issued": base.isoformat(), "buoy": buoy, "model": model, "rows": rows}


def observation_records(buoy, readings):
    """Log records for `ndbc.fetch_spec_history` readings."""
    out = []
    for r in readings:
        rec = {"k": "ob", "buoy": buoy, "t": r["time"].astimezone(UTC).isoformat()}
        for src, key in _OB_KEYS.items():
            if r.get(src) is not None:
                rec[key] = _round(key, r[src])
        out.append(rec)
    return out


def mop_record(issued, slug, site, mop_rows, series):
    """One break's MOP forecast beside the live app's model at the same instants, or None if they never overlap.

    `mop_rows` are `sources.cdip.fetch` rows; `series` is the hourly model data the app already holds for the
    break ({aware datetime: {open-meteo var: value}}). Only daylight rows from now to MAX_LEAD_H are kept."""
    base = issued.replace(minute=0, second=0, microsecond=0)
    rows = []
    for m in mop_rows:
        lead = (m["time"] - base.astimezone(UTC)).total_seconds() / 3600.0
        local = m["time"].astimezone(issued.tzinfo)
        if lead < 0 or lead > MAX_LEAD_H or not (MOP_FIRST_HOUR <= local.hour <= MOP_LAST_HOUR):
            continue
        row = {"t": local.isoformat(), "lead": int(round(lead))}
        for src, key in (("hs", "mhs"), ("tp", "mtp"), ("dp", "mdp")):
            if m.get(src) is not None:
                row[key] = _round("sd" if key == "mdp" else "tp" if key == "mtp" else "hs", m[src])
        ours = series.get(local.replace(minute=0, second=0, microsecond=0)) or {}
        for src, key in (("wave_height", "ohs"), ("swell_wave_height", "osh"),
                         ("swell_wave_period", "osp"), ("swell_wave_direction", "osd")):
            if ours.get(src) is not None:
                row[key] = _round("sd" if key == "osd" else "sp" if key == "osp" else "hs", ours[src])
        if "mhs" in row and len(row) > 4:
            rows.append(row)
    if not rows:
        return None
    return {"k": "mp", "issued": base.isoformat(), "slug": slug, "site": site, "rows": rows}


# ---------------------------------------------------------------------------- store

def _files(log_dir, last_months=None):
    try:
        names = sorted(n for n in os.listdir(log_dir) if n.endswith(".jsonl"))
    except OSError:
        return []
    if last_months:
        names = names[-last_months:]
    return [os.path.join(log_dir, n) for n in names]


def load(log_dir, last_months=None):
    """Every record in the log, oldest first. Bad lines are skipped; a missing dir gives []."""
    out = []
    for path in _files(log_dir, last_months):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    return out


def _fc_key(rec):
    """What makes two forecast records 'the same forecast': the buoy and model, or the break's MOP point."""
    return ("mp", rec["slug"]) if rec["k"] == "mp" else (rec["buoy"], rec["model"])


def append_new(log_dir, records):
    """Write the records that aren't already logged. Returns (written, skipped).

    Observations are unique by (buoy, time). A forecast is skipped if the same model at the
    same buoy was already logged within MIN_FC_GAP_H hours.
    """
    existing = load(log_dir, last_months=2)
    seen_ob = {(r["buoy"], r["t"]) for r in existing if r.get("k") == "ob"}
    last_fc = {}
    for r in existing:
        if r.get("k") in ("fc", "mp"):
            key, t = _fc_key(r), _dt(r["issued"])
            if key not in last_fc or t > last_fc[key]:
                last_fc[key] = t

    by_month = {}
    skipped = 0
    for rec in records:
        if rec["k"] == "ob":
            key = (rec["buoy"], rec["t"])
            if key in seen_ob:
                skipped += 1
                continue
            seen_ob.add(key)
            month = rec["t"][:7]
        else:
            key, t = _fc_key(rec), _dt(rec["issued"])
            prev = last_fc.get(key)
            if prev is not None and abs((t - prev).total_seconds()) / 3600.0 < (MOP_MIN_GAP_H if rec["k"] == "mp" else MIN_FC_GAP_H):
                skipped += 1
                continue
            last_fc[key] = t
            month = rec["issued"][:7]
        by_month.setdefault(month, []).append(json.dumps(rec, separators=(",", ":")))

    written = 0
    if by_month:
        os.makedirs(log_dir, exist_ok=True)
    for month, lines in by_month.items():
        with open(os.path.join(log_dir, "%s.jsonl" % month), "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        written += len(lines)
    return written, skipped


# -------------------------------------------------------------------------- collect

def _mop_due(now, existing, slugs):
    """The slugs whose last MOP record is old enough that a new one adds something."""
    last = {}
    for r in existing:
        if r.get("k") == "mp":
            t = _dt(r["issued"])
            if r["slug"] not in last or t > last[r["slug"]]:
                last[r["slug"]] = t
    return [s for s in slugs
            if s not in last or abs((now - last[s]).total_seconds()) / 3600.0 >= MOP_MIN_GAP_H]


def collect_mop(now, existing, breaks, fetch_mop=None, workers=4):
    """MOP records for the breaks that are due. `breaks` is {slug: (mop site, hourly series)}.
    Returns (records, problems); a failing site is reported and skipped."""
    fetch_mop = fetch_mop or cdip.fetch
    records, problems = [], []
    due = _mop_due(now, existing, list(breaks))

    def one(slug):
        site, series = breaks[slug]
        try:
            return slug, mop_record(now, slug, site, fetch_mop(site), series), None
        except Exception as e:  # noqa: BLE001
            return slug, None, "%s MOP %s: %s" % (slug, site, e)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for slug, rec, problem in pool.map(one, due):
            if rec:
                records.append(rec)
            if problem:
                problems.append(problem)
    return records, problems


def collect(now, log_dir, fetch_model=None, fetch_obs=None, buoys=None, models=None, mop_breaks=None, fetch_mop=None):
    """Fetch every model's forecast and the recent buoy readings, and log what's new.

    A failing source is reported in `problems` and skipped, never raised: this runs inside the
    alert job and must not be able to stop an alert. The fetchers are injectable for tests.
    `mop_breaks` ({slug: (MOP site, hourly series)}) adds the CDIP side-by-side records.
    """
    fetch_model = fetch_model or forecast.marine_model
    fetch_obs = fetch_obs or ndbc.fetch_spec_history
    buoys = buoys or BUOYS
    models = models or MODELS
    have_obs = {r["buoy"] for r in load(log_dir, last_months=2) if r.get("k") == "ob"}

    records, problems = [], []
    for buoy, (lat, lon) in buoys.items():
        hours = OBS_HOURS if buoy in have_obs else BACKFILL_HOURS
        try:
            records += observation_records(buoy, fetch_obs(buoy, hours))
        except Exception as e:  # noqa: BLE001
            problems.append("%s observations: %s" % (buoy, e))
        for model in models:
            try:
                series = fetch_model(lat, lon, model, FC_VARS)
            except Exception as e:  # noqa: BLE001
                problems.append("%s %s forecast: %s" % (buoy, model, e))
                continue
            rec = forecast_record(now, buoy, model, series)
            if rec:
                records.append(rec)
    if mop_breaks:
        mop_records, mop_problems = collect_mop(now, load(log_dir, last_months=2), mop_breaks, fetch_mop)
        records += mop_records
        problems += mop_problems
    written, skipped = append_new(log_dir, records)
    return {"written": written, "skipped": skipped, "problems": problems}
