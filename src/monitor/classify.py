"""Pure classification of the eConsult page state from its HTML.

Keys off text CONTENT, not DOM structure. Visible-text markers are matched
against the tag-stripped visible text; structural markers (element ids / CSS
classes that live inside tags) are matched against the raw lower-cased HTML.
Anything unrecognised is UNKNOWN and never guessed.
"""
from __future__ import annotations

import hashlib
import html as html_module
import re
from dataclasses import dataclass

STATE_OPEN = "open"
STATE_CLOSED = "closed"
STATE_UNKNOWN = "unknown"


@dataclass(frozen=True)
class Classification:
    state: str
    markers: tuple[str, ...]
    routes: tuple[str, ...]


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def normalise(raw_html: str) -> str:
    """Tag-stripped, entity-decoded, lower-cased, whitespace-collapsed text."""
    text = _TAG_RE.sub(" ", raw_html)
    text = html_module.unescape(text)
    text = text.lower()
    return _WS_RE.sub(" ", text).strip()


# Closed markers found in the visible text.
_CLOSED_TEXT_MARKERS: tuple[str, ...] = (
    "booked today",
    "from 7am tomorrow",
    "try again from 7am",
)
# Closed markers that live inside tags (id / class) -> matched on raw HTML.
_CLOSED_STRUCT_MARKERS: tuple[str, ...] = (
    "serviceclosed",
    "service-closed-header",
)
# Any of these in the visible text signals a live route (clinical or admin).
# Chosen so they are ABSENT on the observed closed clinical page.
_OPEN_SIGNALS: tuple[str, ...] = (
    "health problem",
    "sick note",
    "test result",
    "medication query",
    "medication",
)
# Best-effort route metadata (recorded regardless of state).
_ROUTE_MARKERS: dict[str, str] = {
    "adult": "adult health problem",
    "child": "child health problem",
    "admin_sicknote": "sick note",
    "admin_testresult": "test result",
    "admin_medication": "medication",
}


def classify(raw_html: str) -> Classification:
    raw_lower = raw_html.lower()
    text = normalise(raw_html)

    closed_hits = tuple(m for m in _CLOSED_TEXT_MARKERS if m in text)
    closed_hits += tuple(m for m in _CLOSED_STRUCT_MARKERS if m in raw_lower)
    routes = tuple(name for name, phrase in _ROUTE_MARKERS.items() if phrase in text)

    if closed_hits:
        return Classification(STATE_CLOSED, closed_hits, routes)

    open_hits = tuple(s for s in _OPEN_SIGNALS if s in text)
    if open_hits:
        return Classification(STATE_OPEN, open_hits, routes)

    return Classification(STATE_UNKNOWN, (), routes)


# --- Content fingerprint for snapshot dedup (NOT used for detection) ---------
# Mask volatile tokens BEFORE hashing so per-request/deploy noise does not create
# a new page identity. Order matters: ISO datetimes before bare clock times.
_VOLATILE_SUBS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\b[0-9a-f]{16,}\b"), "<hex>"),                        # asset/build hashes, ids (text is lower-cased)
    # ISO datetime, incl. optional seconds/fraction and Z or ±HH:MM offset.
    (re.compile(
        r"\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:z|[+-]\d{2}:?\d{2})?"
    ), "<ts>"),
    (re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b"), "<time>"),            # clock HH:MM[:SS]
)


def stable_text(raw_html: str) -> str:
    """normalise() with volatile tokens masked, for stable page identity."""
    text = normalise(raw_html)
    for pattern, replacement in _VOLATILE_SUBS:
        text = pattern.sub(replacement, text)
    return text


def content_fingerprint(raw_html: str) -> str:
    """sha256 of the stable text — the snapshot filename and content_sha256."""
    return hashlib.sha256(stable_text(raw_html).encode("utf-8", errors="replace")).hexdigest()
