"""
Where a student ends up after pressing submit on the orientation form.

"They click submit and nothing comes" had three causes and none of them was
mail. The form sends no email at all. What it did was save the answers and
then hand the student to a page that could bounce them somewhere unrelated,
without ever confirming the form had landed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app import db, deps


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    db._set_client_for_tests(AsyncMongoMockClient())
    try:
        from app.main import app
        await db.init_indexes(allow_duplicate_email=True)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        db._reset_clients_for_tests()


def _session(client: AsyncClient, email: str, name: str = "Rahul") -> None:
    client.cookies.set("hacri_session", deps._sign({"email": email, "name": name}))


async def _register(email: str, status: str = db.STATUS_PRE_DONE) -> None:
    now = datetime.now(timezone.utc)
    await db.get_db()["users"].insert_one({
        "email": email, "name": "Rahul", "program": "Department of Law",
        "ug_or_pg": "ug", "location": "Bangalore", "status": status,
        "created_at": now, "pre_submitted_at": now,
    })


@pytest.mark.asyncio
async def test_a_capitalised_address_still_finds_the_student(client):
    """Registration stores the address as given and the session carries what
    the student typed, so the two need not match on case. An exact-match
    lookup decided the student did not exist and sent them to the landing
    page — the whole form filled in, and the home page in return."""
    await _register("Rahul.M@jainuniversity.ac.in")
    _session(client, "rahul.m@jainuniversity.ac.in")

    r = await client.get("/survey/post", follow_redirects=False)
    assert r.status_code != 303 or "/results/" in r.headers.get("location", ""), (
        f"bounced to {r.headers.get('location')!r} — the student was not found"
    )


@pytest.mark.asyncio
async def test_the_orientation_answers_are_saved_under_the_normalised_address(client):
    """The same casing mismatch is what fills the report's unmatched-reply
    bucket: the answer is stored, but under an address no user record matches,
    so it belongs to no department."""
    await _register("Rahul.M@jainuniversity.ac.in")
    _session(client, "rahul.m@jainuniversity.ac.in")
    await db.set_flag(db.FLAG_ORIENTATION, True)

    r = await client.post("/api/orientation/submit",
                          json={"q2": 8, "location": "📍 Bangalore"})
    assert r.status_code == 200 and r.json()["ok"] is True

    doc = await db.get_db()["orientation_responses"].find_one({})
    assert doc["email"] == "rahul.m@jainuniversity.ac.in"

    user = await db.get_db()["users"].find_one(
        {"email": {"$in": ["Rahul.M@jainuniversity.ac.in",
                           "rahul.m@jainuniversity.ac.in"]}})
    assert user is not None
    assert user.get("orientation_submitted") is True, (
        "the answer saved but the student was never marked as having answered"
    )


# ── The AI survey wizard ─────────────────────────────────────────────────────
#
# The same complaint, a different form and a different cause. The AI surveys
# are wizards: one step visible, the rest `display:none`. Every step holds
# `required` controls, so on submit the browser found a required control it
# could not focus — one in a hidden step — and refused the submission without
# drawing anything. No alert, no jump, no console message a student would see:
# the button simply did nothing.
#
# The form therefore carries `novalidate` and validates every step itself,
# opening the first incomplete one. These guard both halves, because losing
# either brings back a dead button.

import re
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"
WIZARDS = ("pre_survey.html", "post_survey.html")


@pytest.mark.parametrize("name", WIZARDS)
def test_the_survey_form_turns_off_native_validation(name):
    """Without this the browser blocks the submit and shows the student
    nothing, because the control it objects to is on a hidden step."""
    source = (TEMPLATES / name).read_text()
    form = re.search(r"<form[^>]*id=\"survey-form\"[^>]*>", source)
    assert form, f"{name} has no survey form"
    assert "novalidate" in form.group(0), (
        f"{name}: the form must be novalidate — a required control on a "
        f"hidden step otherwise kills the submit silently")


@pytest.mark.parametrize("name", WIZARDS)
def test_the_survey_checks_every_step_on_submit(name):
    """Checking only the visible step would let the browser refuse the
    submission over a step the student cannot see."""
    source = (TEMPLATES / name).read_text()

    assert "function validateSection(stepIndex, report = true)" in source, (
        f"{name}: validation must be able to run against any step, not just "
        f"the visible one")

    submit = source.split("form.addEventListener('submit'", 1)
    assert len(submit) == 2, f"{name} has no submit handler"
    handler = submit[1][:700]
    assert "for (let step = 0; step < totalSteps; step++)" in handler, (
        f"{name}: the submit handler must sweep every step")
    assert "validateSection(step, false)" in handler, (
        f"{name}: the sweep must check hidden steps without trying to focus "
        f"them")
    assert "showStep(step)" in handler, (
        f"{name}: an incomplete step must be opened so the student can see "
        f"what is missing")


@pytest.mark.parametrize("name", WIZARDS)
def test_the_survey_never_blocks_the_submit_without_saying_why(name):
    """Every path that stops the submit has to leave a mark on screen."""
    source = (TEMPLATES / name).read_text()
    # preventDefault is reached only from inside the sweep, which always goes
    # on to open the offending step and report against it.
    assert source.count("e.preventDefault()") == 1, (
        f"{name}: more than one way to block the submit — each needs its own "
        f"visible explanation")
