"""Append-only JSONL persistence for observations. One JSON object per poll.

Plain text: greppable, diff-able, and inspectable without any tooling. Each line
is a self-contained JSON object, so a truncated write can lose at most the last
line and never corrupts earlier records.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Field order written to each JSON line — stable, so the log reads consistently.
FIELDS: tuple[str, ...] = (
    "ts_utc", "ts_local", "utc_offset", "state", "route", "routes_present",
    "http_status", "latency_ms", "matched_markers", "content_sha256", "notes",
)


def append_json(obj: dict[str, Any], path: Path) -> None:
    """Append any object as one JSON line, creating the parent dir if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(obj, ensure_ascii=False) + "\n")


def append(obs: dict[str, Any], log_path: Path) -> None:
    """Append one observation (poll record) as a JSON line, in stable field order."""
    append_json({key: obs.get(key) for key in FIELDS}, log_path)


def rewrite(records: list[dict[str, Any]], path: Path) -> None:
    """Atomically replace the file with exactly these records (write temp, rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    tmp.replace(path)


def read_all(log_path: Path) -> list[dict[str, Any]]:
    """Read every observation in order. Missing file -> []. Blank lines skipped."""
    if not log_path.exists():
        return []
    records: list[dict[str, Any]] = []
    with log_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records
