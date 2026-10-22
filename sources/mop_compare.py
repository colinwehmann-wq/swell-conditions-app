"""Compare the CDIP MOP nearshore forecast with the wave model the app scores breaks with.

Reads the "mp" records `sources.verify` logs (see its docstring) and answers, break by break:
  - how do the two differ in size, period and direction? (they forecast the same hours)
  - how far was each from what the MOP nowcast later said the waves actually were?

The nowcast is MOP's own best reconstruction of the waves at that point, fed by the buoys, so it is a
fair stand-in for the truth but leans toward MOP. The real tie-breaker is a surfer's own sessions.
"""
import datetime
import statistics

from .skill import angle_diff
from .timeutil import UTC

M_TO_FT = 3.28084
TRUTH_TOLERANCE_MIN = 90       # a nowcast reading this close to a forecast hour counts as that hour
MIN_N = 8                      # fewer matched rows than this are shown but flagged as thin


def _t(text):
    return datetime.datetime.fromisoformat(text)


def _signed(a, b):
    """b - a around the circle, in (-180, 180]: positive means b is clockwise of a."""
    return angle_diff(b, a)


def rows(records):
    """Flat [{"slug", "site", "t", "lead", ...}] from the log's MOP records."""
    out = []
    for r in records:
        if r.get("k") != "mp":
            continue
        for row in r["rows"]:
            out.append(dict(row, slug=r["slug"], site=r["site"], issued=r["issued"]))
    return out


def _median(vals):
    return statistics.median(vals) if vals else None


def _mean(vals):
    return sum(vals) / len(vals) if vals else None


def difference(row_list):
    """How MOP differs from the app's model over `row_list`: {n, size_ratio, period_diff_s, dir_diff_deg}."""
    ratios = [r["mhs"] / r["ohs"] for r in row_list if r.get("mhs") is not None and (r.get("ohs") or 0) >= 0.2]
    periods = [r["mtp"] - r["osp"] for r in row_list if r.get("mtp") is not None and r.get("osp") is not None]
    dirs = [_signed(r["osd"], r["mdp"]) for r in row_list if r.get("mdp") is not None and r.get("osd") is not None]
    return {"n": len(row_list), "size_ratio": _median(ratios), "period_diff_s": _mean(periods),
            "dir_diff_deg": _mean(dirs), "dir_abs_deg": _mean([abs(d) for d in dirs]) if dirs else None}


def _nearest(truth, t):
    best = None
    for tr in truth:
        gap = abs((tr["time"] - t).total_seconds()) / 60.0
        if gap <= TRUTH_TOLERANCE_MIN and (best is None or gap < best[0]):
            best = (gap, tr)
    return best[1] if best else None


def error_vs_truth(row_list, truth, now):
    """Mean absolute height error of each model against the nowcast, over rows already in the past:
    {n, mop_mae_m, model_mae_m} (None when there are no past rows to judge)."""
    mop_err, our_err = [], []
    for r in row_list:
        t = _t(r["t"]).astimezone(UTC)
        if t > now.astimezone(UTC):
            continue
        tr = _nearest(truth, t)
        if tr is None or tr.get("hs") is None:
            continue
        if r.get("mhs") is not None:
            mop_err.append(abs(r["mhs"] - tr["hs"]))
        if r.get("ohs") is not None:
            our_err.append(abs(r["ohs"] - tr["hs"]))
    n = min(len(mop_err), len(our_err))
    return {"n": n, "mop_mae_m": _mean(mop_err[:n]) if n else None, "model_mae_m": _mean(our_err[:n]) if n else None}


def by_break(records):
    out = {}
    for r in rows(records):
        out.setdefault(r["slug"], []).append(r)
    return out


def _f(v, fmt):
    return "–" if v is None else fmt % v


def _ft(m):
    return "–" if m is None else "%.1f ft" % (m * M_TO_FT)


def format_report(records, truth_by_site=None, now=None):
    """Markdown: one row per break. `truth_by_site` is {site: nowcast rows}; without it the error columns are blank."""
    groups = by_break(records)
    if not groups:
        return "## CDIP MOP vs the app's model\n\nNo MOP records logged yet.\n"
    now = now or datetime.datetime.now(UTC)
    lines = ["## CDIP MOP vs the app's model", "",
             "Same hours, daylight only. Size is MOP's wave height divided by the app model's (1.00 = same); "
             "period and direction are MOP minus the app model (direction: + is clockwise). "
             "Error is mean absolute wave-height error against the MOP nowcast, in feet (the nowcast leans toward MOP). "
             "Two differences are expected and are not errors: MOP gives the *peak* period where the app model gives the swell's mean period "
             "(so MOP reads longer), and MOP's direction is measured nearshore, after the swell has bent toward the beach.", "",
             "| Break | Rows | Size ratio | Period diff | Dir diff | Dir off by | Error: MOP | Error: app | Past rows |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for slug in sorted(groups):
        rl = groups[slug]
        d = difference(rl)
        err = error_vs_truth(rl, (truth_by_site or {}).get(rl[0]["site"], []), now)
        flag = " (thin)" if d["n"] < MIN_N else ""
        lines.append("| %s%s | %d | %s | %s | %s | %s | %s | %s | %d |" % (
            slug, flag, d["n"], _f(d["size_ratio"], "%.2f"), _f(d["period_diff_s"], "%+.1f s"),
            _f(d["dir_diff_deg"], "%+.0f°"), _f(d["dir_abs_deg"], "%.0f°"),
            _ft(err["mop_mae_m"]), _ft(err["model_mae_m"]), err["n"]))
    return "\n".join(lines) + "\n"
