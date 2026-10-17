"""Notification sinks. Console always; ntfy / webhook / macOS are opt-in via env."""
import json
import os
import platform
import subprocess

from . import http


def _ascii(text):
    """HTTP header values must be latin-1; strip anything outside ASCII (e.g. emoji)."""
    return text.encode("ascii", "ignore").decode("ascii").strip() or "Surf alert"


def _publish_public():
    """Public (website opt-in) topics are only posted to when explicitly enabled —
    the cloud workflow sets this, local test runs don't."""
    return os.environ.get("SURF_PUBLISH_PUBLIC", "").strip().lower() in ("1", "true", "yes")


def _ntfy(title, body, public_topics=(), click=None, private=True):
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    topics = []
    private_topic = os.environ.get("NTFY_TOPIC", "").strip()
    if private and private_topic:
        topics.append(private_topic)
    if public_topics and _publish_public():
        topics.extend(t for t in public_topics if t)
    headers = {"Title": _ascii(title), "Tags": "ocean", "Priority": "high"}
    if click:
        headers["Click"] = click
    for topic in topics:
        try:
            http.post("%s/%s" % (server, topic), body=body, headers=headers)
        except Exception as e:  # noqa: BLE001 - best effort
            print("  ! ntfy failed (%s): %s" % (topic, e))


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


def send_to_topic(topic, title, body, click=None):
    """One person's alert, to their own private ntfy topic and nowhere else: not the owner's phone,
    Slack or Mac, and not the public topics. Returns True if ntfy took it."""
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    headers = {"Title": _ascii(title), "Tags": "ocean", "Priority": "high"}
    if click:
        headers["Click"] = click
    print("\n>>> NOTIFY (profile ...%s): %s\n%s\n" % (topic[-4:], title, body))
    try:
        http.post("%s/%s" % (server, topic), body=body, headers=headers)
        return True
    except Exception as e:  # noqa: BLE001 - best effort; the next hourly run tries again
        print("  ! ntfy failed (profile ...%s): %s" % (topic[-4:], e))
        return False


def send(title, body, public_topics=(), click=None, private=True):
    """`private=False` is for something that concerns only the public topics (a break that
    isn't one of the owner's own): it never reaches the owner's phone, Slack or Mac."""
    print("\n>>> NOTIFY%s: %s\n%s\n" % ("" if private else " (public only)", title, body))
    _ntfy(title, body, public_topics=public_topics, click=click, private=private)
    if private:
        _webhook(title, body)
        _macos(title, body)
