#!/usr/bin/env python3
"""Print how accurate the logged wave forecasts have been, by model and lead time.

  python3 tools/skill_report.py                  # reads ./forecast-log
  python3 tools/skill_report.py path/to/log-dir

Markdown on stdout, so it also works as a GitHub Actions step summary.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sources import skill, verify  # noqa: E402


def main(argv):
    log_dir = argv[1] if len(argv) > 1 else "forecast-log"
    print(skill.format_report(verify.load(log_dir)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
