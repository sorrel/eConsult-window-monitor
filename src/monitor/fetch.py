"""Polite, read-only HTTP GET with robots.txt awareness.

Single request, follows redirects, no cookies persisted, never executes
JavaScript, and never raises — failures come back as a FetchResult with an
error string so the poll loop can log and carry on.
"""
from __future__ import annotations

import time
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass


@dataclass(frozen=True)
class FetchResult:
    status: int | None
    body: str
    latency_ms: int
    final_url: str
    error: str | None


def _opener(user_agent: str) -> urllib.request.OpenerDirector:
    # Default opener follows redirects and does NOT persist cookies.
    opener = urllib.request.build_opener()
    opener.addheaders = [("User-Agent", user_agent)]
    return opener


def robots_allows(base_url: str, path: str, user_agent: str, timeout: int = 15) -> bool:
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(base_url.rstrip("/") + "/robots.txt")
    try:
        parser.read()
    except Exception:
        return True  # no readable robots.txt -> treat as allowed
    return parser.can_fetch(user_agent, base_url.rstrip("/") + path)


def fetch(url: str, user_agent: str, timeout: int = 15) -> FetchResult:
    opener = _opener(user_agent)
    start = time.monotonic()
    try:
        with opener.open(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            latency_ms = int((time.monotonic() - start) * 1000)
            return FetchResult(resp.status, body, latency_ms, resp.geturl(), None)
    except urllib.error.HTTPError as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return FetchResult(exc.code, body, latency_ms, url, f"HTTPError {exc.code}")
    except Exception as exc:  # connection refused, timeout, DNS, etc.
        latency_ms = int((time.monotonic() - start) * 1000)
        return FetchResult(None, "", latency_ms, url, str(exc))


def main() -> int:
    """`python -m monitor.fetch <url>` — one fetch, reported in a line.

    Prints 'ok <status> <latency>ms' and exits 0, or 'fail <error>' and exits 1.
    The body is never printed. Exists so the daemon can ask a *fresh process*
    whether the page is reachable at a moment when its own fetches are failing
    (see daemon._fresh_process_can_fetch); it writes nothing to the log.
    """
    import sys

    from . import config

    url = sys.argv[1] if len(sys.argv) > 1 else config.BASE_URL.rstrip("/") + config.CLINICAL_PATH
    result = fetch(url, config.USER_AGENT, config.REQUEST_TIMEOUT)
    if result.error or result.status is None:
        print(f"fail {result.error or 'no response'}")
        return 1
    print(f"ok {result.status} {result.latency_ms}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
