from pathlib import Path

from monitor import classify
from monitor.classify import (
    STATE_OPEN,
    STATE_CLOSED,
    STATE_UNKNOWN,
    normalise,
    classify as classify_html,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_normalise_strips_tags_decodes_entities_and_lowercases():
    text = normalise("<p>All our <b>GP</b> appointments are booked&nbsp;today</p>")
    assert "<" not in text and ">" not in text
    assert "booked today" in text  # entity collapsed, lower-cased


def test_closed_page_detected_via_text_and_structural_markers():
    result = classify_html(_load("closed.html"))
    assert result.state == STATE_CLOSED
    # Both visible-text markers and at least one structural marker fired.
    assert "booked today" in result.markers
    assert "from 7am tomorrow" in result.markers
    assert "serviceclosed" in result.markers


def test_closed_page_not_misread_as_open_despite_child_and_problem_words():
    # The closed page contains "child" and "problem" in the paeds banner;
    # those must NOT trigger an open verdict.
    result = classify_html(_load("closed.html"))
    assert result.state == STATE_CLOSED


def test_open_clinical_page_detected():
    result = classify_html(_load("open.html"))
    assert result.state == STATE_OPEN
    assert "health problem" in result.markers
    assert "adult" in result.routes
    assert "child" in result.routes


def test_admin_open_page_detected_via_admin_signals():
    result = classify_html(_load("admin_open.html"))
    assert result.state == STATE_OPEN
    assert "sick note" in result.markers or "test result" in result.markers


def test_unknown_page_is_unknown_not_guessed():
    result = classify_html(_load("unknown.html"))
    assert result.state == STATE_UNKNOWN
    assert result.markers == ()


def test_wording_variant_still_closed():
    # A layout/copy change that keeps "fully booked ... try again from 7am".
    html = '<div>Today is fully booked. Please try again from 7am tomorrow.</div>'
    result = classify_html(html)
    assert result.state == STATE_CLOSED
    assert "try again from 7am" in result.markers


def test_content_fingerprint_ignores_volatile_comment_and_asset_hashes():
    from monitor.classify import content_fingerprint
    a = '<html><!-- ec2 server name: tomcat03 --><body>' \
        '<script src="/assets/app-0993e8e58ef26218aff90cb9f9c7510e.js"></script>' \
        '<div>All our GP appointments are booked today.</div></body></html>'
    b = a.replace("tomcat03", "tomcat04").replace(
        "0993e8e58ef26218aff90cb9f9c7510e", "b4f843a325943b19b10d30881d4e2cd6")
    # Only the load-balancer comment and an asset-hash differ -> same fingerprint.
    assert content_fingerprint(a) == content_fingerprint(b)


def test_content_fingerprint_masks_visible_clock_time():
    from monitor.classify import content_fingerprint
    a = "<div>Queue updated at 08:14</div>"
    b = "<div>Queue updated at 08:57</div>"
    # A visible clock that ticks must not create a new page identity.
    assert content_fingerprint(a) == content_fingerprint(b)


def test_content_fingerprint_distinguishes_real_content_change():
    from monitor.classify import content_fingerprint
    closed = "<div>All our GP appointments are booked today.</div>"
    opened = "<div>Get help for a health problem.</div>"
    assert content_fingerprint(closed) != content_fingerprint(opened)


def test_content_fingerprint_masks_iso_datetimes_including_tz():
    from monitor.classify import content_fingerprint, stable_text
    variants = [
        "<div>updated 2026-07-22T08:14Z</div>",
        "<div>updated 2026-07-22T08:59Z</div>",
        "<div>updated 2026-07-22T08:14:00Z</div>",
        "<div>updated 2026-07-22T08:14:00+01:00</div>",
        "<div>updated 2026-07-22T09:30:00.123+01:00</div>",
    ]
    fps = {content_fingerprint(v) for v in variants}
    # All differ only by a volatile ISO datetime -> one identity.
    assert len(fps) == 1
    # And the timestamp is actually gone from the stable text (no leaked digits).
    assert "2026" not in stable_text(variants[0])
    assert "08:14" not in stable_text(variants[0])


def test_content_fingerprint_keeps_bare_date_unmasked():
    from monitor.classify import stable_text
    # A bare date (no time) is meaningful copy, not volatile -> not masked.
    assert "2026-07-22" in stable_text("<div>as at 2026-07-22</div>")
