"""Notification sinks. Console always; ntfy / webhook / macOS are opt-in via env."""
import json
import os
import platform
import subprocess

from . import http


def _ascii(text):
    """HTTP header values must be latin-1; strip anything outside ASCII (e.g. emoji)."""
    return text.encode("ascii", "ignore").decode("ascii").strip() or "Surf alert"


def _ntfy(title, body):
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        return
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    try:
        http.post("%s/%s" % (server, topic), body=body,
                  headers={"Title": _ascii(title), "Tags": "ocean", "Priority": "high"})
    except Exception as e:  # noqa: BLE001 - best effort
        print("  ! ntfy failed: %s" % e)


def _webhook(title, body):
    url = os.environ.get("SURF_WEBHOOK_URL", "").strip()
    if not url:
        return
    try:
        http.post(url, body=json.dumps({"title": title, "text": body, "username": "surf-check"}),
                  headers={"Content-Type": "application/json"})
    except Exception as e:  # noqa: BLE001
        print("  ! webhook failed: %s" % e)


def _macos(title, body):
    if os.environ.get("SURF_MACOS_NOTIFY", "").strip() not in ("1", "true", "yes"):
        return
    if platform.system() != "Darwin":
        return
    first = body.strip().splitlines()[0] if body.strip() else ""
    script = 'display notification %s with title %s' % (json.dumps(first), json.dumps(title))
    try:
        subprocess.run(["osascript", "-e", script], check=False, capture_output=True)
    except Exception:  # noqa: BLE001
        pass


def send(title, body):
    print("\n>>> NOTIFY: %s\n%s\n" % (title, body))
    _ntfy(title, body)
    _webhook(title, body)
    _macos(title, body)
