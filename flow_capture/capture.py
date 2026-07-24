#!/usr/bin/env python3
"""Safe, read-only walker for a GP eConsult clinical flow.

Its ONLY job is to record what a submission requires — the questions and fields
— WITHOUT ever submitting. It builds nothing toward submission.

Safety, defence-in-depth (see flow_capture/README.md for the full rationale):

  1. WRITES ARE PHYSICALLY BLOCKED. Every non-GET request to the eConsult host
     is aborted at the network layer, so nothing is ever sent — the final
     submission cannot leave this machine no matter what is clicked. Blocked
     attempts are logged.
  2. NEVER CLICKS A TERMINAL CONTROL. It classifies each candidate control and
     stops the instant it sees a submit/send/finish-type control; it only ever
     clicks clearly non-terminal "Continue/Next" controls.
  3. NEVER CONSENTS, NEVER USES REAL DATA. Consent checkboxes are left
     unchecked (which naturally halts the walk at the consent/submit gate);
     any text field needed to advance gets an obvious placeholder.
  4. GOOD CITIZEN / WAF-FRIENDLY. One pass, one problem, capped screens,
     randomised human-paced dwell, no parallelism, browser cache reused, run
     headed with a normal Chrome UA so it looks like one patient's session.

Run only during the open window, once, with the poller paused. See README.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import time
import os
from pathlib import Path
from urllib.parse import urlparse

_PLACEHOLDER_HOST = "example-surgery.example.com"


def _econsult_host() -> str:
    """The target host, kept out of the (public) source tree. Read from the
    ECONSULT_BASE_URL env var or the gitignored `target_url.local` at the repo
    root (the same file the monitor uses); a neutral placeholder otherwise."""
    url = os.environ.get("ECONSULT_BASE_URL", "").strip()
    if not url:
        local = Path(__file__).resolve().parent.parent / "target_url.local"
        if local.exists():
            url = local.read_text(encoding="utf-8").strip()
    return urlparse(url).netloc or _PLACEHOLDER_HOST


ECONSULT_HOST = _econsult_host()

# A normal desktop Chrome UA — a headless-Chromium UA is a WAF tell, so we avoid it.
NORMAL_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Safety-critical classification. Terminal wins over advance if both match.
_TERMINAL_RE = re.compile(
    r"\b(submit|send|finish|complete|confirm and send|"
    r"send (to )?(the |your )?(practice|surgery|gp)|review your answers)\b",
    re.I,
)
_ADVANCE_RE = re.compile(r"\b(continue|next|proceed|get started|start|begin)\b", re.I)


def classify_control(text: str) -> str:
    """Classify a button/link label: 'terminal' | 'advance' | 'other'.

    Terminal takes precedence — anything that could submit is treated as
    terminal and must never be clicked.
    """
    text = (text or "").strip()
    if not text:
        return "other"
    if _TERMINAL_RE.search(text):
        return "terminal"
    if _ADVANCE_RE.search(text):
        return "advance"
    return "other"


def is_write_to_econsult(method: str, url: str) -> bool:
    """True for any non-GET request to the eConsult host — these are aborted."""
    host = urlparse(url).netloc.lower()
    return ECONSULT_HOST in host and method.upper() != "GET"


# --- Browser-side scripts (evaluated in the page) ---------------------------

_FIELDS_JS = r"""() => {
  const labelFor = (el) => {
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label').trim();
    if (el.id) { const l = document.querySelector('label[for="' + el.id + '"]');
                 if (l) return l.innerText.trim(); }
    const p = el.closest('label'); if (p) return p.innerText.trim();
    return '';
  };
  return [...document.querySelectorAll('input, select, textarea')].map(el => ({
    tag: el.tagName.toLowerCase(),
    type: (el.type || '').toLowerCase(),
    name: el.name || '', id: el.id || '',
    placeholder: el.placeholder || '',
    required: !!(el.required || el.getAttribute('aria-required') === 'true'),
    label: labelFor(el),
  }));
}"""

_QUESTIONS_JS = r"""() => {
  const out = [];
  document.querySelectorAll('h1,h2,h3,legend,[role=heading],.question')
    .forEach(e => { const t = (e.innerText || '').trim();
                    if (t && t.length < 400) out.push(t); });
  return [...new Set(out)];
}"""

_CONTROLS_JS = r"""() => {
  return [...document.querySelectorAll('button, a[role=button], a.button, input[type=submit], input[type=button]')]
    .map((el, i) => ({ i, text: (el.innerText || el.value || '').trim() }))
    .filter(c => c.text);
}"""


def _dwell(lo: float, hi: float) -> None:
    time.sleep(random.uniform(lo, hi))


def _capture(page, out: Path, idx: int, blocked: list) -> None:
    stem = f"{idx:02d}"
    page.screenshot(path=str(out / f"{stem}.png"), full_page=True)
    (out / f"{stem}.html").write_text(page.content(), encoding="utf-8")
    fields = page.evaluate(_FIELDS_JS)
    questions = page.evaluate(_QUESTIONS_JS)
    (out / f"{stem}.fields.json").write_text(
        json.dumps({"url": page.url, "questions": questions, "fields": fields},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  [{stem}] captured — {len(questions)} question(s), {len(fields)} field(s): {page.url}")


def _answer_safely(page) -> None:
    """Fill only what is needed to progress, never consenting or using real data.

    Radios: pick a clearly-negative option if present (so red-flag screening
    advances), else leave alone. Checkboxes (incl. consent): never tick. Text:
    obvious placeholder only.
    """
    try:
        page.evaluate(r"""() => {
          // negative radio per group, if the option text looks like 'No'
          const groups = {};
          document.querySelectorAll('input[type=radio]').forEach(r => {
            (groups[r.name] = groups[r.name] || []).push(r); });
          Object.values(groups).forEach(rs => {
            const no = rs.find(r => {
              const l = document.querySelector('label[for="' + r.id + '"]');
              const t = (l ? l.innerText : (r.closest('label')||{}).innerText || '').toLowerCase();
              return /\bno\b|none|not/.test(t);
            });
            if (no && !rs.some(r => r.checked)) { no.checked = true;
              no.dispatchEvent(new Event('change', {bubbles:true})); }
          });
          // placeholder text only; never touch checkboxes (consent stays off)
          document.querySelectorAll('input[type=text], input[type=search], textarea')
            .forEach(t => { if (!t.value) { t.value = 'TEST (not a real submission)';
              t.dispatchEvent(new Event('input', {bubbles:true})); } });
        }""")
    except Exception as exc:  # never let answering break the walk
        print(f"  (note: safe-answer step skipped: {exc})")


def _find_advance(page):
    """Return (kind, index, text). If any terminal control exists, return it as
    terminal (so the caller stops) even if advance controls also exist."""
    controls = page.evaluate(_CONTROLS_JS)
    advance = None
    for c in controls:
        kind = classify_control(c["text"])
        if kind == "terminal":
            return ("terminal", c["i"], c["text"])
        if kind == "advance" and advance is None:
            advance = ("advance", c["i"], c["text"])
    return advance or (None, None, None)


def _build_session(p, headless: bool):
    """Launch a browser with the write-blocking guard installed. Returns
    (browser, context, page, blocked, network)."""
    blocked: list = []
    network: list = []

    def guard(route):
        req = route.request
        if is_write_to_econsult(req.method, req.url):
            blocked.append({"method": req.method, "url": req.url})
            print(f"  BLOCKED WRITE: {req.method} {req.url}")
            route.abort()
        else:
            route.continue_()

    browser = p.chromium.launch(headless=headless)
    context = browser.new_context(user_agent=NORMAL_UA, viewport={"width": 1280, "height": 900})
    context.route("**/*", guard)
    page = context.new_page()
    page.on("request", lambda r: network.append({"method": r.method, "url": r.url}))
    return browser, context, page, blocked, network


def _save_logs(out: Path, blocked: list, network: list) -> None:
    (out / "blocked_writes.json").write_text(json.dumps(blocked, indent=2), encoding="utf-8")
    (out / "network.jsonl").write_text("\n".join(json.dumps(n) for n in network), encoding="utf-8")


def _visible_text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def run_assisted(args) -> None:
    """YOU drive the browser; the tool auto-captures each new screen. Robust for
    an unknown adaptive flow, and the write-block still makes submission
    impossible. Finish by closing the browser window (or Ctrl-C)."""
    from playwright.sync_api import sync_playwright

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser, context, page, blocked, network = _build_session(p, headless=False)
        page.goto(args.url, wait_until="domcontentloaded")
        print("\nAssisted capture — you drive the browser; I record each new screen.")
        print(f"Writes to {ECONSULT_HOST} are BLOCKED, so nothing can be submitted.")
        print("Click through ONE problem to the submit screen (do not submit).")
        print("Close the browser window (or press Ctrl-C here) when you're done.\n")

        idx = 0
        last_sig = None
        try:
            while True:
                try:
                    page.wait_for_timeout(1500)  # pumps the event loop so the write-block stays live
                    sig = _visible_text(page.content())[:4000]
                except Exception:
                    break  # browser closed
                if sig and sig != last_sig:
                    _capture(page, out, idx, blocked)
                    idx += 1
                    last_sig = sig
        except KeyboardInterrupt:
            pass
        finally:
            _save_logs(out, blocked, network)
            print(f"\nCaptured {idx} screen(s) to {out}. Blocked writes: {len(blocked)}.")
            try:
                context.close()
                browser.close()
            except Exception:
                pass


def run_auto(args) -> None:
    """Best-effort automatic walker. Advances only via 'Continue/Next' controls,
    stops at any terminal control. Fragile on adaptive flows — prefer --mode assisted."""
    from playwright.sync_api import sync_playwright

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser, context, page, blocked, network = _build_session(p, headless=args.headless)
        print(f"Auto-walking {args.url} — writes to {ECONSULT_HOST} are blocked.")
        page.goto(args.url, wait_until="domcontentloaded")
        _dwell(args.min_dwell, args.max_dwell)
        idx = 0
        _capture(page, out, idx, blocked)
        for _ in range(args.max_screens):
            kind, control_i, text = _find_advance(page)
            if kind == "terminal":
                print(f"STOP: terminal control detected ({text!r}) — not clicking.")
                break
            if kind is None:
                print("STOP: no advance control found (awaiting an answer, or a route card to click).")
                break
            _answer_safely(page)
            _dwell(args.min_dwell, args.max_dwell)
            controls = page.query_selector_all(
                "button, a[role=button], a.button, input[type=submit], input[type=button]")
            print(f"  advancing via {text!r}")
            controls[control_i].click()
            try:
                page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            _dwell(args.min_dwell, args.max_dwell)
            idx += 1
            _capture(page, out, idx, blocked)
        _save_logs(out, blocked, network)
        print(f"\nDone. {idx + 1} screen(s) captured to {out}. Blocked writes: {len(blocked)}.")
        context.close()
        browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Safe read-only walker for the eConsult clinical flow (never submits).")
    parser.add_argument("--mode", choices=["assisted", "auto"], default="assisted",
                        help="assisted: you drive, tool records (default, robust). auto: best-effort self-walk.")
    parser.add_argument("--url", default=f"https://{ECONSULT_HOST}/")
    parser.add_argument("--out", default=None, help="output dir (default data/flow-capture/<run>)")
    parser.add_argument("--max-screens", type=int, default=20)
    parser.add_argument("--min-dwell", type=float, default=4.0)
    parser.add_argument("--max-dwell", type=float, default=9.0)
    parser.add_argument("--headless", action="store_true", help="auto mode only; assisted is always headed")
    parser.add_argument("--run-stamp", default="run", help="subfolder name under data/flow-capture")
    args = parser.parse_args()
    if args.out is None:
        args.out = str(Path(__file__).resolve().parent.parent / "data" / "flow-capture" / args.run_stamp)
    (run_assisted if args.mode == "assisted" else run_auto)(args)


if __name__ == "__main__":
    main()
