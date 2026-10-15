"""Score logged forecasts against the buoy readings that followed.

Pure functions over the records `sources/verify.py` writes, so everything here is testable
without a network. For every forecast row whose valid time has since been measured, the error
is (forecast - observed). Errors are grouped by model, variable and lead time:

  bias   average signed error (positive = the model runs high)
  mae    mean absolute error, in the variable's own units
  rmse   root-mean-square error (punishes the big misses)
  ratio  total forecast / total observed, for heights: the h_scale the live calibration guesses at

A "persistence" pseudo-model is scored alongside: it simply assumes the ocean stays as it was
when the forecast was issued. A real model has to beat that to earn its place.
"""
import bisect
import datetime
import math

from . import evaluate
from .timeutil import UTC

LEAD_BUCKETS = [(0, 6), (6, 12), (12, 24), (24, 48), (48, 73)]   # [lo, hi) in hours
TOLERANCE_MIN = 45     # a reading this close to the valid time counts as "that hour"
MIN_N = 5              # fewer pairs than this are shown, but flagged as thin

# label, forecast key, observation key, circular?
# A forecast key starting "c:" is derived: the swell band put back together from both of the
# model's swell trains, exactly as the live scoring does it (evaluate.combine_swell). Those
# rows sit beside the primary-only ones so the table shows which is closer to the buoy.
VARIABLES = [
    ("Total wave height (m)", "hs", "hs", False),
    ("Swell height (m)", "sh", "sh", False),
    ("Swell height, both trains (m)", "c:h", "sh", False),
    ("Swell period (s)", "sp", "sp", False),
    ("Swell period, both trains (s)", "c:p", "sp", False),
    ("Swell direction (deg)", "sd", "sd", True),
    ("Swell direction, both trains (deg)", "c:d", "sd", True),
]
# Not scored yet: the models' total `tp` (wave_period) against the buoy. NDBC's `ap` is an
# average period (~8 s here) while the model's is nearer a peak period (~13 s), so the two
# aren't the same quantity. Comparing against the buoy's dominant period (DPD, in the .txt
# feed) would be fair; the forecast side is already logged.
_CIRCULAR = {label for label, _f, _o, circ in VARIABLES if circ}
_DECIMALS = {"Swell direction (deg)": 0, "Swell period (s)": 1,
             "Swell direction, both trains (deg)": 0, "Swell period, both trains (s)": 1}


def angle_diff(a, b):
    """Signed difference a - b in degrees, wrapped to (-180, 180]."""
    d = (a - b + 180.0) % 360.0 - 180.0
    return 180.0 if d == -180.0 else d


def bucket(lead):
    for lo, hi in LEAD_BUCKETS:
        if lo <= lead < hi:
            return "%d-%dh" % (lo, min(hi, 72))
    return None


def _utc(text):
    d = datetime.datetime.fromisoformat(text)
    return d.astimezone(UTC) if d.tzinfo else d.replace(tzinfo=UTC)


def _observations(records):
    """{buoy: (sorted times, readings)}"""
    raw = {}
    for r in records:
        if r.get("k") == "ob":
            raw.setdefault(r["buoy"], []).append((_utc(r["t"]), r))
    out = {}
    for buoy, items in raw.items():
        items.sort(key=lambda x: x[0])
        out[buoy] = ([t for t, _ in items], [r for _, r in items])
    return out


def _nearest(times, readings, t, tol_min, only_before=False):
    i = bisect.bisect_left(times, t)
    best = None
    for j in (i - 1, i):
        if not 0 <= j < len(times):
            continue
        if only_before and times[j] > t:
            continue
        gap = abs((times[j] - t).total_seconds())
        if gap <= tol_min * 60 and (best is None or gap < best[0]):
            best = (gap, readings[j])
    return best[1] if best else None


_ROW_TO_MODEL = {
    "sh": "swell_wave_height", "sp": "swell_wave_period", "sd": "swell_wave_direction",
    "s2h": "secondary_swell_wave_height", "s2p": "secondary_swell_wave_period",
    "s2d": "secondary_swell_wave_direction",
}


def _forecast_value(row, key):
    """A logged row's value for `key`, or None if the row can't supply it."""
    if not key.startswith("c:"):
        return row.get(key)
    trains = evaluate.model_trains({m: row[k] for k, m in _ROW_TO_MODEL.items() if k in row})
    if not trains:
        return None
    height, period, direction = evaluate.combine_swell(trains)
    return {"c:h": height, "c:p": period, "c:d": direction}[key]


def _pair(model, buoy, lead, var, fc, ob):
    err = angle_diff(fc, ob) if var in _CIRCULAR else fc - ob
    return {"model": model, "buoy": buoy, "lead": lead, "var": var, "fc": fc, "ob": ob, "err": err}


def pairs(records, tol_minutes=TOLERANCE_MIN):
    """Every (forecast, outcome) pair the log can support, persistence included."""
    obs = _observations(records)
    out = []
    persisted = set()
    for r in records:
        if r.get("k") != "fc" or r["buoy"] not in obs:
            continue
        times, readings = obs[r["buoy"]]
        issued = _utc(r["issued"])

        for row in r["rows"]:
            ob = _nearest(times, readings, _utc(row["t"]), tol_minutes)
            if ob is None:
                continue
            for label, fk, ok, _circ in VARIABLES:
                value = _forecast_value(row, fk)
                if value is not None and ok in ob:
                    out.append(_pair(r["model"], r["buoy"], row["lead"], label, value, ob[ok]))

        key = (r["buoy"], r["issued"])
        if key in persisted:
            continue
        persisted.add(key)
        start = _nearest(times, readings, issued, 90, only_before=True)
        if start is None:
            continue
        for lead in range(3, 73, 3):   # lead 0 would just compare a reading with itself
            ob = _nearest(times, readings, issued + datetime.timedelta(hours=lead), tol_minutes)
            if ob is None:
                continue
            for label, _fk, ok, _circ in VARIABLES:
                if ok in start and ok in ob:
                    out.append(_pair("persistence", r["buoy"], lead, label, start[ok], ob[ok]))
    return out


def summarize(pair_list):
    """{variable: {model: {bucket: {n, bias, mae, rmse, ratio}}}}"""
    acc = {}
    for p in pair_list:
        b = bucket(p["lead"])
        if b is None:
            continue
        a = acc.setdefault((p["var"], p["model"], b),
                           {"n": 0, "sum": 0.0, "abs": 0.0, "sq": 0.0, "fc": 0.0, "ob": 0.0})
        a["n"] += 1
        a["sum"] += p["err"]
        a["abs"] += abs(p["err"])
        a["sq"] += p["err"] ** 2
        a["fc"] += p["fc"]
        a["ob"] += p["ob"]
    out = {}
    for (var, model, b), a in acc.items():
        n = a["n"]
        ratio = a["fc"] / a["ob"] if var not in _CIRCULAR and a["ob"] > 0 else None
        out.setdefault(var, {}).setdefault(model, {})[b] = {
            "n": n, "bias": a["sum"] / n, "mae": a["abs"] / n,
            "rmse": math.sqrt(a["sq"] / n), "ratio": ratio,
        }
    return out


def coverage(records):
    fcs = [r for r in records if r.get("k") == "fc"]
    obs = [r for r in records if r.get("k") == "ob"]
    return {
        "forecasts": len(fcs),
        "issues": len({(r["buoy"], r["issued"]) for r in fcs}),
        "models": sorted({r["model"] for r in fcs}),
        "observations": len(obs),
        "first_forecast": min((r["issued"] for r in fcs), default=None),
        "last_observation": max((r["t"] for r in obs), default=None),
    }


# ------------------------------------------------------------------------- report

def _cell(var, st):
    d = _DECIMALS.get(var, 2)
    text = "%.*f (%+.*f)" % (d, st["mae"], d, st["bias"])
    return text if st["n"] >= MIN_N else "%s n=%d" % (text, st["n"])


def format_report(records):
    """Markdown tables, one per variable: rows are models, columns are lead-time buckets.
    Each cell is `MAE (bias)`; the lowest MAE in a column is starred."""
    cov = coverage(records)
    lines = ["# Forecast skill", ""]
    if not cov["forecasts"]:
        return "\n".join(lines + ["No forecasts logged yet."])
    lines += [
        "%d forecasts logged over %d issue times from %s; %d buoy readings, latest %s." % (
            cov["forecasts"], cov["issues"], cov["first_forecast"][:10], cov["observations"],
            (cov["last_observation"] or "none")[:16]),
        "",
        "Each cell is mean absolute error (signed bias) against the buoy. Lower is better; "
        "`*` marks the best in a column. `persistence` assumes nothing changes from the moment "
        "the forecast was made, and a model has to beat it.",
        "",
    ]
    stats = summarize(pairs(records))
    if not stats:
        return "\n".join(lines + ["Nothing to score yet: no forecast has had time to come true."])
    buckets = ["%d-%dh" % (lo, min(hi, 72)) for lo, hi in LEAD_BUCKETS]
    for label, _fk, _ok, _circ in VARIABLES:
        by_model = stats.get(label)
        if not by_model:
            continue
        lines += ["## %s" % label, "", "| Model | " + " | ".join(buckets) + " |",
                  "|---|" + "---|" * len(buckets)]
        best = {}
        for b in buckets:
            cands = [(m[b]["mae"], name) for name, m in by_model.items() if b in m and m[b]["n"] >= MIN_N]
            if cands:
                best[b] = min(cands)[1]
        for name in sorted(by_model, key=lambda n: (n == "persistence", n)):
            cells = []
            for b in buckets:
                st = by_model[name].get(b)
                cells.append("–" if not st else _cell(label, st) + (" *" if best.get(b) == name else ""))
            lines.append("| %s | %s |" % (name, " | ".join(cells)))
        lines.append("")
        if label.startswith(("Total", "Swell height")):
            ratios = ["%s %.2f" % (name, by_model[name]["0-6h"]["ratio"])
                      for name in sorted(by_model)
                      if name != "persistence" and "0-6h" in by_model[name]
                      and by_model[name]["0-6h"]["ratio"] is not None and by_model[name]["0-6h"]["n"] >= MIN_N]
            if ratios:
                lines += ["Forecast/observed height ratio at 0-6h (1.00 = unbiased): " + ", ".join(ratios), ""]
    return "\n".join(lines)
