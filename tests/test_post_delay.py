"""
Per-department post-survey delay.

Each department decides how many days after a student finishes the baseline
their post survey opens. Without its own number, a department follows the
portal-wide setting.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app import db

DEPT = "Department of Law"
DEPT_SLUG = "department-of-law"
OTHER = "Department of Commerce"


@pytest_asyncio.fixture
async def app_with_mock():
    db._set_client_for_tests(AsyncMongoMockClient())
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


@pytest_asyncio.fixture
async def admin(app_with_mock) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app_with_mock)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.cookies.set("survey_admin_session", "1")
        yield ac


async def _add_student(email: str, *, program: str, days_ago: float = 0) -> None:
    when = datetime.now(timezone.utc) - timedelta(days=days_ago)
    await db.get_db()["users"].insert_one({
        "email": email, "name": email.split("@")[0].title(), "program": program,
        "ug_or_pg": "ug", "status": db.STATUS_PRE_DONE,
        "created_at": when, "pre_submitted_at": when,
    })


async def _set_portal_delay(days: int) -> None:
    await db.get_db()[db.FLAGS].update_one(
        {"key": db.FLAG_POST_DELAY},
        {"$set": {"key": db.FLAG_POST_DELAY, "value": days}},
        upsert=True,
    )


@pytest.mark.asyncio
async def test_department_delay_overrides_the_portal_setting(app_with_mock):
    await _set_portal_delay(7)

    # No department number yet — everyone waits the portal's seven days.
    assert await db.get_dept_post_delay(DEPT) is None
    assert await db.effective_post_delay(DEPT) == 7

    await db.set_dept_post_delay(DEPT, 2)
    assert await db.get_dept_post_delay(DEPT) == 2
    assert await db.effective_post_delay(DEPT) == 2
    assert await db.effective_post_delay(OTHER) == 7          # untouched
    assert await db.list_dept_post_delays() == {DEPT: 2}

    # Zero is a real answer — this department opens the post survey at once.
    await db.set_dept_post_delay(DEPT, 0)
    assert await db.effective_post_delay(DEPT) == 0

    # Clearing it hands the department back to the portal-wide setting.
    await db.set_dept_post_delay(DEPT, None)
    assert await db.get_dept_post_delay(DEPT) is None
    assert await db.effective_post_delay(DEPT) == 7
    assert await db.list_dept_post_delays() == {}


@pytest.mark.asyncio
async def test_post_link_waits_out_the_departments_own_delay(client: AsyncClient):
    """The department link tells the student when their survey opens."""
    email = "early@example.com"
    await _add_student(email, program=DEPT, days_ago=1)
    await db.set_dept_post_delay(DEPT, 5)

    early = await client.post(f"/post/{DEPT_SLUG}", data={"email": email},
                              follow_redirects=False)
    assert early.status_code == 403
    assert "not open yet" in early.text.lower()

    user = await db.get_db()["users"].find_one({"email": email})
    assert "post_link_at" not in user       # access was not granted

    # Same student, once the five days have passed.
    await db.get_db()["users"].update_one(
        {"email": email},
        {"$set": {"pre_submitted_at": datetime.now(timezone.utc) - timedelta(days=6)}},
    )
    ready = await client.post(f"/post/{DEPT_SLUG}", data={"email": email},
                              follow_redirects=False)
    assert ready.status_code == 200
    assert "welcome back" in ready.text.lower()


@pytest.mark.asyncio
async def test_department_delay_beats_the_portal_delay_on_the_link(client: AsyncClient):
    """A department that opens sooner is not held back by the portal number."""
    await _set_portal_delay(30)
    email = "quick@example.com"
    await _add_student(email, program=DEPT, days_ago=3)
    await db.set_dept_post_delay(DEPT, 1)

    resp = await client.post(f"/post/{DEPT_SLUG}", data={"email": email},
                             follow_redirects=False)
    assert resp.status_code == 200
    assert "welcome back" in resp.text.lower()


@pytest.mark.asyncio
async def test_post_survey_page_respects_the_department_delay(client: AsyncClient):
    email = "gated@example.com"
    await _add_student(email, program=DEPT, days_ago=2)
    await db.set_dept_post_delay(DEPT, 10)

    from app.deps import _sign
    client.cookies.set("hacri_session", _sign({"email": email, "name": "Gated"}))

    # The waiting page, with the date it opens — not the questionnaire.
    page = await client.get("/survey/post", follow_redirects=False)
    assert page.status_code == 200
    opens_on = (datetime.now(timezone.utc) + timedelta(days=8)).strftime("%d %b %Y")
    assert opens_on in page.text

    # Once the department's own wait is dropped, the survey opens.
    await db.set_dept_post_delay(DEPT, 1)
    page = await client.get("/survey/post", follow_redirects=False)
    assert page.status_code == 200
    assert opens_on not in page.text


@pytest.mark.asyncio
async def test_admin_sets_and_clears_a_departments_delay(admin: AsyncClient):
    await _set_portal_delay(7)
    await _add_student("someone@example.com", program=DEPT)

    body = {"dept": DEPT, "days": 3}
    saved = await admin.post("/admin/api/survey/post-delay", json=body)
    assert saved.status_code == 200
    assert saved.json()["post_delay_days"] == 3
    assert saved.json()["effective_delay_days"] == 3
    assert await db.get_dept_post_delay(DEPT) == 3

    # The admin table reads the numbers back.
    links = (await admin.get("/admin/api/survey/post-links")).json()
    assert links["portal_delay_days"] == 7
    row = next(r for r in links["links"] if r["dept"] == DEPT)
    assert row["post_delay_days"] == 3
    assert row["effective_delay_days"] == 3

    # Blank clears it, and the portal-wide number applies again.
    cleared = await admin.post("/admin/api/survey/post-delay",
                               json={"dept": DEPT, "days": ""})
    assert cleared.status_code == 200
    assert cleared.json()["post_delay_days"] is None
    assert cleared.json()["effective_delay_days"] == 7

    links = (await admin.get("/admin/api/survey/post-links")).json()
    row = next(r for r in links["links"] if r["dept"] == DEPT)
    assert row["post_delay_days"] is None
    assert row["effective_delay_days"] == 7


@pytest.mark.asyncio
async def test_delay_endpoint_is_guarded_and_validated(client: AsyncClient, admin: AsyncClient):
    signed_out = await client.post("/admin/api/survey/post-delay",
                                   json={"dept": DEPT, "days": 3})
    assert signed_out.status_code == 403

    assert (await admin.post("/admin/api/survey/post-delay",
                             json={"dept": "", "days": 3})).status_code == 400
    assert (await admin.post("/admin/api/survey/post-delay",
                             json={"dept": DEPT, "days": "soon"})).status_code == 400

    # Out-of-range numbers are clamped rather than refused.
    high = await admin.post("/admin/api/survey/post-delay",
                            json={"dept": DEPT, "days": 4000})
    assert high.json()["post_delay_days"] == 365
    low = await admin.post("/admin/api/survey/post-delay",
                           json={"dept": DEPT, "days": -5})
    assert low.json()["post_delay_days"] == 0


@pytest.mark.asyncio
async def test_shared_pages_state_the_wait(admin: AsyncClient, client: AsyncClient):
    await _add_student("shared@example.com", program=DEPT)
    await db.set_dept_post_delay(DEPT, 4)

    from app.routes.shared_analysis import get_dept_token, get_directory_token

    report = await client.get("/shared/analysis", params={
        "dept": DEPT, "token": get_dept_token(DEPT, "post"), "type": "post"})
    assert report.status_code == 200
    assert "4 days after a student completes the baseline" in report.text

    directory = await client.get("/shared/departments",
                                 params={"token": get_directory_token()})
    assert directory.status_code == 200
    assert "opens 4 days after the baseline" in directory.text
