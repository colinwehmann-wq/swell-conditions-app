#!/usr/bin/env python3
"""Print how the CDIP MOP nearshore forecast compares with the app's wave model, break by break.

  python3 tools/mop_report.py                  # reads ./forecast-log
  python3 tools/mop_report.py path/to/log-dir

Markdown on stdout, so it also works as a GitHub Actions step summary. It fetches each logged break's
recent MOP nowcast to judge the forecasts that have already come true; if CDIP can't be reached the
size, period and direction comparison still prints.
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sources import cdip, mop_compare, verify  # noqa: E402
from sources.timeutil import UTC  # noqa: E402

NOWCAST_HOURS = 24 * 14        # how far back to fetch the nowcast: longer than the log's span matters little


def truth_for(records, now):
    """{MOP site: recent nowcast rows} for every site with a logged forecast hour that has already passed,
    so the early days (nothing to judge yet) cost no requests. A site that fails is left out."""
    out = {}
    sites = {r["site"] for r in records if r.get("k") == "mp"
             and any(datetime.datetime.fromisoformat(row["t"]) <= now for row in r["rows"])}
    for site in sorted(sites):
        try:
            out[site] = cdip.fetch_recent(site, NOWCAST_HOURS)
        except Exception as e:  # noqa: BLE001
            print("  ! %s nowcast: %s" % (site, e), file=sys.stderr)
    return out


def main(argv):
    log_dir = argv[1] if len(argv) > 1 else "forecast-log"
    records = verify.load(log_dir)
    now = datetime.datetime.now(UTC)
    print(mop_compare.format_report(records, truth_for(records, now), now))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
