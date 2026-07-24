from datetime import datetime, timezone

from monitor import poll, store
from monitor.fetch import FetchResult


def _fake_fetcher(body: str, status: int = 200):
    def _f(url, user_agent, timeout=15):
        return FetchResult(status, body, 12, url, None)
    return _f


def test_build_timestamps_formats_offset_with_colon():
    fixed = datetime(2026, 7, 22, 19, 9, 54, tzinfo=timezone.utc)
    ts_utc, ts_local, offset = poll.build_timestamps(fixed)
    assert ts_utc == "2026-07-22T19:09:54+00:00"
    # Offset is +HH:MM and both local + utc are present (DST-disambiguation).
    assert len(offset) == 6 and offset[3] == ":"


def test_poll_once_writes_closed_record(tmp_path):
    log = tmp_path / "obs.jsonl"
    body = ('<div id="serviceClosed">All our GP appointments are booked today. '
            'Submit a request again from 7am tomorrow.</div>')
    obs = poll.poll_once(
        "/",
        log_path=log,
        fetcher=_fake_fetcher(body),
        now_utc=datetime(2026, 7, 22, 6, 0, tzinfo=timezone.utc),
        snapshot_dir=tmp_path / "snaps",
    )
    assert obs["state"] == "closed"
    assert obs["route"] == "/"
    assert obs["content_sha256"] is not None
    records = store.read_all(log)
    assert len(records) == 1
    assert records[0]["state"] == "closed"
    assert records[0]["ts_utc"].startswith("2026-07-22T06:00")


def test_poll_once_snapshots_distinct_pages_and_dedupes(tmp_path):
    log = tmp_path / "obs.jsonl"
    snaps = tmp_path / "snaps"
    now = datetime(2026, 7, 22, 6, 0, tzinfo=timezone.utc)

    body_a = (
        '<html><body><!-- ec2 server name: tomcat03 -->'
        '<div id="serviceClosed">booked today. submit again from 7am tomorrow.</div>'
        "</body></html>"
    )
    # Same visible content, only the volatile load-balancer comment differs.
    body_a2 = body_a.replace("tomcat03", "tomcat02")
    body_b = "<html><body><h2>get help for a health problem</h2></body></html>"

    o1 = poll.poll_once("/", log_path=log, fetcher=_fake_fetcher(body_a), now_utc=now, snapshot_dir=snaps)
    o2 = poll.poll_once("/", log_path=log, fetcher=_fake_fetcher(body_a2), now_utc=now, snapshot_dir=snaps)
    o3 = poll.poll_once("/", log_path=log, fetcher=_fake_fetcher(body_b), now_utc=now, snapshot_dir=snaps)

    # a and a2 differ only by the volatile comment -> identical fingerprint -> one snapshot.
    assert o1["content_sha256"] == o2["content_sha256"]
    assert o1["content_sha256"] != o3["content_sha256"]
    files = sorted(p.name for p in snaps.glob("*.html"))
    assert len(files) == 2  # {a, a2} collapse to one; b is the second
    # First writer wins: the kept raw body is the first one seen (tomcat03).
    kept = (snaps / f"{o1['content_sha256']}.html").read_text(encoding="utf-8")
    assert "tomcat03" in kept
    # Every poll is still logged, even the deduplicated one.
    assert len(store.read_all(log)) == 3


def test_poll_once_records_error_note_on_failed_fetch(tmp_path):
    log = tmp_path / "obs.jsonl"

    def _broken(url, user_agent, timeout=15):
        return FetchResult(None, "", 5, url, "Connection refused")

    obs = poll.poll_once(
        "/",
        log_path=log,
        fetcher=_broken,
        now_utc=datetime(2026, 7, 22, 6, 0, tzinfo=timezone.utc),
        snapshot_dir=tmp_path / "snaps",
    )
    assert obs["state"] == "unknown"  # empty body -> unknown
    assert obs["notes"] == "Connection refused"
    assert obs["content_sha256"] is None  # no body, no hash
