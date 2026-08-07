"""
Department-wise post-survey links (/post/<dept-slug>).

A student who opens their department's link and types their registered email
should land straight on the post survey — but only when the email belongs to
that department and already has a completed baseline survey.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app import db

DEPT = "Department of Computer Science and Engineering"
DEPT_SLUG = "department-of-computer-science-and-engineering"


@pytest_asyncio.fixture
async def app_with_mock():
    mock = AsyncMongoMockClient()
    db._set_client_for_tests(mock)
    try:
        from app.main import app
        await db.init_indexes(allow_duplicate_email=True)
        yield app
    finally:
        db._reset_clients_for_tests()


@pytest_asyncio.fixture
async def client(app_with_mock) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app_with_mock)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _add_user(email: str, *, program: str, status: str | None) -> None:
    now = datetime.now(timezone.utc)
    await db.get_db()["users"].insert_one({
        "email": email, "name": email.split("@")[0], "program": program,
        "ug_or_pg": "ug", "status": status, "created_at": now,
        "pre_submitted_at": now if status else None,
    })


def test_dept_slug_roundtrip():
    from app.routes.post_link import dept_slug

    assert dept_slug(DEPT) == DEPT_SLUG
    assert dept_slug("Department of Art and Design (Interior Design)") == \
        "department-of-art-and-design-interior-design"
    assert dept_slug("") == "no-department"


@pytest.mark.asyncio
async def test_entry_page_renders_for_known_department(client: AsyncClient):
    await _add_user("known@example.com", program=DEPT, status=db.STATUS_PRE_DONE)

    resp = await client.get(f"/post/{DEPT_SLUG}")
    assert resp.status_code == 200
    assert DEPT in resp.text

    # The all-departments link always exists.
    assert (await client.get("/post/all")).status_code == 200

    # A department nobody has registered under yet still renders, named from the
    # official list, so a freshly generated link is never a dead end.
    fresh = await client.get("/post/department-of-law")
    assert fresh.status_code == 200
    assert "Department of Law" in fresh.text

    # An unrecognised slug falls back to a readable label rather than erroring.
    odd = await client.get("/post/some-made-up-place")
    assert odd.status_code == 200
    assert "Some Made Up Place" in odd.text


@pytest.mark.asyncio
async def test_pre_done_student_reaches_post_survey(client: AsyncClient):
    email = "ready@example.com"
    await _add_user(email, program=DEPT, status=db.STATUS_PRE_DONE)

    resp = await client.post(f"/post/{DEPT_SLUG}", data={"email": email},
                             follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/survey/post"

    # Access was recorded, so the post survey stays open for them.
    user = await db.get_db()["users"].find_one({"email": email})
    assert user["post_link_at"] is not None
    assert user["post_link_dept"] == DEPT

    from app.routes.surveys import _has_post_access
    assert _has_post_access(user) is True


@pytest.mark.asyncio
async def test_email_is_matched_case_insensitively(client: AsyncClient):
    await _add_user("mixed@example.com", program=DEPT, status=db.STATUS_PRE_DONE)

    resp = await client.post(f"/post/{DEPT_SLUG}", data={"email": "  Mixed@Example.com "},
                             follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/survey/post"


@pytest.mark.asyncio
async def test_student_without_baseline_is_told_to_finish_it(client: AsyncClient):
    email = "nopre@example.com"
    await _add_user(email, program=DEPT, status=None)

    resp = await client.post(f"/post/{DEPT_SLUG}", data={"email": email},
                             follow_redirects=False)
    assert resp.status_code == 403
    assert "baseline survey" in resp.text.lower()

    user = await db.get_db()["users"].find_one({"email": email})
    assert "post_link_at" not in user


@pytest.mark.asyncio
async def test_student_from_another_department_is_refused(client: AsyncClient):
    other = "Department of Law"
    email = "lawyer@example.com"
    await _add_user(email, program=other, status=db.STATUS_PRE_DONE)

    resp = await client.post(f"/post/{DEPT_SLUG}", data={"email": email},
                             follow_redirects=False)
    assert resp.status_code == 403
    assert other in resp.text

    # …but the all-departments link accepts them.
    resp_all = await client.post("/post/all", data={"email": email}, follow_redirects=False)
    assert resp_all.status_code == 303
    assert resp_all.headers["location"] == "/survey/post"


@pytest.mark.asyncio
async def test_unknown_email_is_refused(client: AsyncClient):
    await _add_user("someone@example.com", program=DEPT, status=db.STATUS_PRE_DONE)

    resp = await client.post(f"/post/{DEPT_SLUG}", data={"email": "ghost@example.com"},
                             follow_redirects=False)
    assert resp.status_code == 404
    assert "could not find this email" in resp.text.lower()


@pytest.mark.asyncio
async def test_finished_student_goes_to_results(client: AsyncClient):
    email = "done@example.com"
    await _add_user(email, program=DEPT, status=db.STATUS_POST_DONE)

    resp = await client.post(f"/post/{DEPT_SLUG}", data={"email": email},
                             follow_redirects=False)
    assert resp.status_code == 303
    assert "/results/" in resp.headers["location"]


@pytest.mark.asyncio
async def test_link_opens_post_survey_while_it_is_closed_to_everyone_else(client: AsyncClient):
    """The department link is an invitation: it works even with the post survey off."""
    email = "invited@example.com"
    await _add_user(email, program=DEPT, status=db.STATUS_PRE_DONE)
    await db.set_flag("post_survey_enabled", False)

    resp = await client.post(f"/post/{DEPT_SLUG}", data={"email": email},
                             follow_redirects=False)
    assert resp.status_code == 303

    page = await client.get("/survey/post", follow_redirects=False)
    assert page.status_code == 200
    assert "not open" not in page.text.lower()


@pytest.mark.asyncio
async def test_admin_post_links_endpoint(client: AsyncClient):
    await _add_user("a@example.com", program=DEPT, status=db.STATUS_PRE_DONE)
    await _add_user("b@example.com", program=DEPT, status=db.STATUS_POST_DONE)
    await _add_user("c@example.com", program="Department of Law", status=None)

    assert (await client.get("/admin/api/survey/post-links")).status_code == 403

    client.cookies.set("survey_admin_session", "1")
    data = (await client.get("/admin/api/survey/post-links")).json()

    assert data["all_url"].endswith("/post/all")
    by_dept = {row["dept"]: row for row in data["links"]}
    assert by_dept[DEPT]["url"].endswith("/post/" + DEPT_SLUG)
    assert by_dept[DEPT]["registered"] == 2
    assert by_dept[DEPT]["pre_done"] == 2
    assert by_dept[DEPT]["post_done"] == 1
    assert by_dept[DEPT]["pending_post"] == 1
    assert data["totals"]["registered"] == 3


@pytest.mark.asyncio
async def test_link_works_when_the_baseline_survey_is_switched_off(client: AsyncClient):
    """With no baseline survey running, nobody has one — don't demand it."""
    email = "nobaseline@example.com"
    await _add_user(email, program=DEPT, status=None)
    await db.set_flag(db.FLAG_PRE_SURVEY, False)

    resp = await client.post(f"/post/{DEPT_SLUG}", data={"email": email},
                             follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/survey/post"


# ── Outcome Survey 1 (baseline) department links ────────────────────────────

@pytest.mark.asyncio
async def test_baseline_link_locks_the_department(client: AsyncClient):
    resp = await client.get("/pre/department-of-law")
    assert resp.status_code == 200
    # Registration form, with the department fixed rather than selectable.
    assert 'name="program" value="Department of Law"' in resp.text
    assert "Select department..." not in resp.text
    assert "Outcome Survey 1" in resp.text


@pytest.mark.asyncio
async def test_baseline_link_registers_the_student_under_that_department(client: AsyncClient):
    """The locked department is what actually gets stored on the user."""
    from app.deps import make_csrf_token

    csrf = make_csrf_token()
    client.cookies.set("hacri_csrf", csrf)
    page = await client.get("/pre/department-of-law")
    assert "Department of Law" in page.text

    resp = await client.post("/start", follow_redirects=False, data={
        "name": "Riya", "email": "Riya@example.com", "csrf": csrf,
        "program": "Department of Law", "ug_or_pg": "ug",
    })
    assert resp.status_code in (303, 307)

    user = await db.get_db()["users"].find_one({"email": "riya@example.com"})
    assert user["program"] == "Department of Law"

    # …and that student now passes their own department's post link once the
    # baseline is done, with no department mismatch.
    await db.get_db()["users"].update_one(
        {"email": "riya@example.com"}, {"$set": {"status": db.STATUS_PRE_DONE}})
    opened = await client.post("/post/department-of-law",
                               data={"email": "riya@example.com"}, follow_redirects=False)
    assert opened.status_code == 303
    assert opened.headers["location"] == "/survey/post"


@pytest.mark.asyncio
async def test_baseline_all_link_is_the_normal_registration_page(client: AsyncClient):
    resp = await client.get("/pre/all")
    assert resp.status_code == 200
    assert "Select department..." in resp.text


@pytest.mark.asyncio
async def test_admin_links_cover_every_official_department(client: AsyncClient):
    """Links exist before anyone registers — that is when they are handed out."""
    from app.departments import DEPARTMENTS

    client.cookies.set("survey_admin_session", "1")
    data = (await client.get("/admin/api/survey/post-links")).json()

    by_dept = {row["dept"]: row for row in data["links"]}
    assert set(DEPARTMENTS) <= set(by_dept)

    law = by_dept["Department of Law"]
    assert law["pre_url"].endswith("/pre/department-of-law")
    assert law["post_url"].endswith("/post/department-of-law")
    assert law["registered"] == 0
    assert data["pre_all_url"].endswith("/")
