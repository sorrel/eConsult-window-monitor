"""Shared observation-record type and helpers used by the read side.

A record is one poll's JSON object (see ``store.FIELDS`` for the field order).
Kept here so ``analyse`` and ``rollup`` share one definition rather than each
carrying its own copy.
"""
from __future__ import annotations

from typing import Any

Record = dict[str, Any]


def day(ts_local: str) -> str:
    """The local ISO date prefix of a timestamp, e.g. '2026-07-22'."""
    return ts_local[:10]
