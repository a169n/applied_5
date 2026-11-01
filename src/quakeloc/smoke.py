"""Black-box smoke test of a running service. Stdlib only, so it runs in the runtime image."""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request


def _http_get(url):
    def get(path):
        try:
            with urllib.request.urlopen(url + path, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    return get


def wait_ready(get, timeout_s=120.0, interval_s=2.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            if get("/ready")[0] == 200:
                return True
        except OSError:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval_s)


def check(get, expected_sha=None) -> list[str]:
    """Return the list of failures; empty means the service passed."""
    failures = []
    status, version = get("/version")
    if status != 200:
        failures.append(f"/version returned {status}")
    elif expected_sha and version["git_sha"] != expected_sha:
        failures.append(f"/version git_sha {version['git_sha']} != expected {expected_sha}")

    status, demo = get("/demo")
    if status != 200 or demo["error_km"] >= 1.0:
        failures.append(f"/demo failed: status {status}, body {demo}")

    status, events = get("/events")
    if status != 200:
        failures.append(f"/events returned {status}")
    elif not events:
        print("SKIP: no snapshot")
    elif not any(get(f"/events/{e['id']}/locate")[0] == 200 for e in events):
        failures.append("no event in the snapshot could be located")
    return failures


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args(argv)
    get = _http_get(args.url.rstrip("/"))
    if not wait_ready(get, args.timeout):
        print(f"FAIL: {args.url} not ready after {args.timeout} s", file=sys.stderr)
        return 1
    failures = check(get, os.environ.get("GIT_SHA"))
    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    if not failures:
        print("OK")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
