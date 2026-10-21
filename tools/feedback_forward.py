#!/usr/bin/env python3
"""Forward new feedback from the site to the owner's phone.

  python3 tools/feedback_forward.py              # the scheduled job: fetch anything new, send one notification
  python3 tools/feedback_forward.py --dry-run    # print how many are new; send nothing and remember nothing

Feedback is submitted on the site (the "How was it?" buttons on each break and the Send feedback page), stored by the
profile service (worker/), and read here with PROFILES_ADMIN_KEY. One notification per run goes to the owner's private
phone topic (NTFY_TOPIC), listing everything new. The time of the newest item sent is remembered in
.feedback-state.json so nothing is sent twice.

This repository is public, and so are its Actions logs. Feedback can hold a person's words and an email address, so
nothing here ever prints it: the log only ever says how many items there were.
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config  # noqa: E402
from sources import http, notify  # noqa: E402

STATE_PATH = os.path.join(ROOT, ".feedback-state.json")
PAGE = 50
MAX_PAGES = 5            # a runaway cannot loop forever; whatever is left goes out next run
MAX_LISTED = 8
NOTE_CHARS = 160

VOTE_WORDS = {"better": "better than rated", "right": "about right", "worse": "worse than rated"}


def fetch_page(api, key, after):
    url = api.rstrip("/") + "/api/admin/feedback?limit=%d" % PAGE + ("&after=" + after if after else "")
    return http.get_json(url, headers={"Authorization": "Bearer " + key})


def load_state(path):
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path, state):
    try:
        with open(path, "w") as f:
            json.dump(state, f)
    except OSError as e:
        print("  ! could not write state: %s" % e, file=sys.stderr)


def describe(item):
    """One line for one piece of feedback."""
    if item.get("kind") == "break":
        what = "%s: %s" % (item.get("name") or item.get("slug") or "a break", VOTE_WORDS.get(item.get("vote"), "a note"))
        if item.get("shown_rating") is not None:
            what += " (it showed %.1f%s)" % (item["shown_rating"], " " + item["shown_label"] if item.get("shown_label") else "")
    else:
        what = "General"
    note = (item.get("note") or "").replace("\n", " ")
    if len(note) > NOTE_CHARS:
        note = note[:NOTE_CHARS - 1] + "…"
    line = "- " + what + (' - "%s"' % note if note else "")
    if item.get("contact"):
        line += " [reply: %s]" % item["contact"]
    return line


def format_items(items):
    """(title, body) for a batch of feedback."""
    title = "Swell feedback: %d new" % len(items)
    lines = [describe(i) for i in items[:MAX_LISTED]]
    if len(items) > MAX_LISTED:
        lines.append("+%d more" % (len(items) - MAX_LISTED))
    return title, "\n".join(lines)


def collect(api, key, after, fetch=fetch_page):
    """Everything newer than `after`, oldest first, and the time of the newest."""
    items, last = [], after
    for _ in range(MAX_PAGES):
        page = fetch(api, key, last)
        got = page.get("items", [])
        if not got:
            break
        items.extend(got)
        last = page.get("last") or got[-1]["t"]
        if len(got) < PAGE:
            break
    return items, last


def run(args, fetch=fetch_page, send=notify.send_private_quiet):
    key = os.environ.get("PROFILES_ADMIN_KEY", "").strip()
    if not key:
        print("PROFILES_ADMIN_KEY is not set; nothing to do.")
        return 0
    api = args.api or os.environ.get("PROFILES_API", "").strip() or config.PROFILES_API
    state = load_state(args.state)
    try:
        items, last = collect(api, key, state.get("after", ""), fetch)
    except Exception as e:  # noqa: BLE001
        print("could not read feedback: %s" % e, file=sys.stderr)
        return 1

    print("%d new feedback item%s" % (len(items), "" if len(items) == 1 else "s"))
    if not items or args.dry_run:
        return 0
    if not os.environ.get("NTFY_TOPIC", "").strip():
        print("NTFY_TOPIC is not set, so it was not forwarded (it will be sent once it is).")
        return 0

    title, body = format_items(items)
    if send(title, body, click=config.SITE_URL):
        state["after"] = last
        save_state(args.state, state)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", help="the profile service's address (default: PROFILES_API or config.PROFILES_API)")
    ap.add_argument("--state", default=STATE_PATH, help="where the time of the last item sent is remembered")
    ap.add_argument("--dry-run", action="store_true", help="count what is new; send and remember nothing")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
