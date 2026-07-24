"""One poll = fetch -> classify -> append. Snapshots every distinct page once."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import classify as classify_mod
from . import config
from . import fetch as fetch_mod
from . import store


def build_timestamps(now_utc: datetime | None = None) -> tuple[str, str, str]:
    """Return (utc_iso, local_iso, '+HH:MM').

    Storing UTC, local, and the offset together is what later distinguishes a
    UTC-scheduled reset from a local one at the DST boundary.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    now_local = now_utc.astimezone()  # system local timezone
    raw_offset = now_local.strftime("%z") or "+0000"  # e.g. '+0100'
    utc_offset = f"{raw_offset[:3]}:{raw_offset[3:]}"  # -> '+01:00'
    return now_utc.isoformat(), now_local.isoformat(), utc_offset


def poll_once(
    route_path: str,
    *,
    log_path: Path = config.LOG_PATH,
    fetcher: Callable = fetch_mod.fetch,
    now_utc: datetime | None = None,
    snapshot_dir: Path = config.SNAPSHOT_DIR,
) -> dict[str, Any]:
    """Fetch one route, classify it, append a record, snapshot if new. Returns the record."""
    url = config.BASE_URL.rstrip("/") + route_path
    result = fetcher(url, config.USER_AGENT, config.REQUEST_TIMEOUT)
    verdict = classify_mod.classify(result.body)

    # Content identity masks volatile tokens (server-name comment, asset hashes,
    # clock times) so per-request/deploy noise does not change it.
    content_key = classify_mod.content_fingerprint(result.body) if result.body else None

    ts_utc, ts_local, utc_offset = build_timestamps(now_utc)
    obs: dict[str, Any] = {
        "ts_utc": ts_utc,
        "ts_local": ts_local,
        "utc_offset": utc_offset,
        "state": verdict.state,
        "route": route_path,
        "routes_present": list(verdict.routes),
        "http_status": result.status,
        "latency_ms": result.latency_ms,
        "matched_markers": list(verdict.markers),
        "content_sha256": content_key,
        "notes": result.error or "",
    }

    # Keep a copy of every DISTINCT page we ever see (any state), so a state we
    # cannot yet observe is captured the first time it appears. First writer wins.
    if result.body and content_key:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot = snapshot_dir / f"{content_key}.html"
        if not snapshot.exists():
            snapshot.write_text(result.body, encoding="utf-8")

    store.append(obs, log_path)
    return obs


def main() -> None:
    obs = poll_once(config.CLINICAL_PATH)
    print(f"{obs['ts_local']}  {obs['state']}  markers={obs['matched_markers']}")


if __name__ == "__main__":
    main()
