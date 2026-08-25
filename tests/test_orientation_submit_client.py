"""
The orientation form's submit path, as shipped to the student's browser.

There is no browser here to run it in, so these read the template. That is
enough for the failure that mattered: a 400ms timer navigated the page to the
AI survey whether or not the POST had finished, and assigning window.location
cancels an in-flight fetch. Students on any connection slower than 400ms —
most phones, carrying forty-one answers — saw a successful-looking redirect
while their answers were discarded. Nothing surfaced it at either end.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

FORM = Path(__file__).resolve().parents[1] / "app" / "templates" / "orientation.html"


@pytest.fixture(scope="module")
def submit_js() -> str:
    source = FORM.read_text(encoding="utf-8")
    start = source.index("async function submitForm()")
    return source[start:source.index("\nfunction showThanks()", start)]


def test_nothing_navigates_away_on_a_timer(submit_js):
    """The bug itself: a setTimeout that redirects, racing the request."""
    timers = re.findall(r"setTimeout\s*\((.*?),\s*(\d+)\s*\)", submit_js, re.S)
    for body, delay in timers:
        assert "location" not in body and "navToNext" not in body, (
            f"a {delay}ms timer navigates the page while the submit is in flight"
        )


def test_the_request_survives_the_page_going_away(submit_js):
    """keepalive is the guarantee the timer was reaching for."""
    assert "keepalive: true" in submit_js


def test_the_redirect_waits_for_the_server_to_confirm_the_save(submit_js):
    """navToNext may only run after res.ok — never on the way in."""
    fetch_at = submit_js.index("fetch('/api/orientation/submit'")
    ok_at = submit_js.index("if (res.ok)")
    # Calls only — the declaration sits at the top of the function by nature.
    calls = [m.start() for m in re.finditer(r"(?<!function )navToNext\(", submit_js)]
    assert calls, "nothing ever navigates onward"
    for at in calls:
        assert at > fetch_at, "the page leaves before the POST is sent"
    assert min(at for at in calls if at > ok_at) > ok_at


def test_a_failed_submit_tells_the_student_instead_of_moving_on(submit_js):
    """Silently continuing to the next survey is what hid this for a whole
    intake. A student whose answers did not save has to be told."""
    assert "fail(" in submit_js
    for probe in ("could not reach the server", "timed out", "session has expired"):
        assert probe in submit_js, f"no message for: {probe}"


def test_the_student_can_retry_without_retyping_anything():
    source = FORM.read_text(encoding="utf-8")
    assert 'id="submitError"' in source
    assert 'onclick="submitForm()"' in source.split('id="submitError"')[1][:800]
    # The answers stay in localStorage, so a retry re-sends the same payload.
    assert "localStorage.setItem(STORAGE_KEY" in source


def test_a_slow_connection_is_given_a_realistic_amount_of_time(submit_js):
    watchdogs = re.findall(r"setTimeout\(\(\)\s*=>\s*giveUp\.abort\(\),\s*(\d+)\)", submit_js)
    assert watchdogs, "no watchdog at all — a dead connection would hang forever"
    assert all(int(ms) >= 15000 for ms in watchdogs), (
        "the give-up point is short enough to abort real submissions"
    )
