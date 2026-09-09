"""Tiny stdlib HTTP helpers with a timeout and a couple of retries."""
import json
import time
import urllib.error
import urllib.request

_UA = {"User-Agent": "swell-conditions-app/1.0 (personal surf checker)"}


def get(url, timeout=25, tries=3):
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except OSError as e:  # URLError, socket.timeout, ConnectionError all subclass this
            last = e
            time.sleep(1.0 + attempt)
    raise RuntimeError("GET failed after %d tries: %s (%s)" % (tries, url, last))


def get_json(url, timeout=25, tries=3):
    return json.loads(get(url, timeout, tries))


def post(url, body="", headers=None, timeout=15):
    data = body.encode("utf-8") if isinstance(body, str) else body
    hdrs = dict(_UA)
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")
