"""
Career interest — how many students lean toward higher education, starting a
business, or a career, read from the answers that hint at it.

Five BBA students and one Law student, by hand:

  A  avatar Startup Founder · expects entrepreneurship + placement · PRaiSE Entrepreneurship
  B  avatar Academic Achiever · expects research
  C  avatar "🚀 Startup Founder" (emoji kept) · PRaiSE Social Good
  D  avatar Future CEO · expects placement
  E  avatar Still Figuring It Out
  L  (Law) avatar Corporate Leader

So among the five BBA students, all five answered:
  entrepreneur      A, C          = 2   (avatar 2 · PRaiSE 1 · expects 1)
  career            A, D          = 2   (avatar CEO 1 · placement 2)
  higher education  B             = 1
  none of the three E             = 1
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app import db
from app.career_interest import career_interest, career_interest_report


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
async def admin_client(app_with_mock) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app_with_mock), base_url="http://test") as ac:
        ac.cookies.set("survey_admin_session", "1")
        yield ac


@pytest_asyncio.fixture
async def client(app_with_mock) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app_with_mock), base_url="http://test") as ac:
        yield ac


# (email, program, avatar, expectations, PRaiSE pillar)
PEOPLE = [
    ("a@x.com", "BBA", "Startup Founder",
     ["Innovation & entrepreneurship exposure", "Career support & placement prep"], "Entrepreneurship"),
    ("b@x.com", "BBA", "Academic Achiever", ["Internship & research opportunities"], None),
    ("c@x.com", "BBA", "🚀 Startup Founder", [], "Social Good"),
    ("d@x.com", "BBA", "Future CEO", ["💼 Career support & placement prep"], None),
    ("e@x.com", "BBA", "Still Figuring It Out", [], None),
    ("l@x.com", "Department of Law", "Corporate Leader", [], None),
]


async def _seed() -> None:
    now = datetime.now(timezone.utc)
    for email, program, avatar, expects, praise in PEOPLE:
        await db.get_db()["users"].insert_one({
            "email": email, "name": email[0].upper(), "program": program, "ug_or_pg": "ug",
            "location": "Bangalore", "status": db.STATUS_POST_DONE if praise else None,
            "created_at": now})
        await db.get_db()["orientation_responses"].insert_one({
            "email": email, "submitted_at": now,
            "data": {"location": "Bangalore", "q41": avatar, "q33": expects}})
        if praise:
            await db.get_db()["post_responses"].insert_one({
                "email": email, "submitted_at": now, "fields": {"praise_initiative": praise}})


def _by_key(report):
    return {g["key"]: g for g in report["groups"]}


@pytest.mark.asyncio
async def test_bba_students_are_counted_by_the_answers_that_hint_at_each_interest(app_with_mock):
    await _seed()
    r = await career_interest(dept="BBA")
    g = _by_key(r)

    assert (r["students"], r["answered"], r["none"], r["unsure"]) == (5, 5, 1, 1)
    assert (g["entrepreneur"]["count"], g["career"]["count"], g["higher_education"]["count"]) == (2, 2, 1)
    assert g["entrepreneur"]["pct"] == 40.0
    # Each interest says exactly which answers were counted.
    assert {s["label"]: s["count"] for s in g["entrepreneur"]["signals"]} == {
        "Avatar: Startup Founder": 2,
        "Chose the Entrepreneurship PRaiSE pillar": 1,
        "Expects innovation & entrepreneurship exposure": 1}
    assert {s["label"]: s["count"] for s in g["career"]["signals"]}[
        "Expects career support & placement prep"] == 2      # with and without the emoji
    # Higher education is flagged as the weak proxy it is.
    assert g["higher_education"]["proxy"] and not g["career"]["proxy"]
    assert r["avatars"][0] == {"label": "Startup Founder", "count": 2}


@pytest.mark.asyncio
async def test_a_student_can_count_under_more_than_one_interest(app_with_mock):
    await _seed()
    g = _by_key(await career_interest(dept="BBA"))
    # A is in both entrepreneur and career, so the counts add past the students.
    assert g["entrepreneur"]["count"] + g["career"]["count"] + g["higher_education"]["count"] == 5
    assert 2 + 2 + 1 > 4        # the four students who lean any way


@pytest.mark.asyncio
async def test_the_department_and_campus_narrow_the_count(app_with_mock):
    await _seed()
    everyone = await career_interest()
    assert everyone["students"] == 6 and everyone["scope"]["dept"] == "All departments"
    assert _by_key(everyone)["career"]["count"] == 3            # A, D and the Law student
    assert sorted(everyone["departments"]) == ["BBA", "Department of Law"]

    law = await career_interest(dept="Department of Law")
    assert (law["students"], _by_key(law)["career"]["count"]) == (1, 1)
    assert (await career_interest(campus="Kochi", dept="BBA"))["students"] == 0


def test_answers_stored_the_older_ways_still_count():
    """q41 is sometimes a list or {text: …}; nobody answered is not a zero."""
    students = [
        {"orientation": {"q41": ["Startup Founder"]}, "post": None},
        {"orientation": {"q41": {"text": "Future CEO"}}, "post": None},
        {"orientation": None, "post": None},                     # answered nothing
    ]
    r = career_interest_report(students, scope={"campus": "x", "dept": "y"})
    g = _by_key(r)
    assert (r["students"], r["answered"]) == (3, 2)
    assert (g["entrepreneur"]["count"], g["career"]["count"]) == (1, 1)
    assert g["entrepreneur"]["pct"] == 50.0                      # of the 2 who answered

    empty = career_interest_report([], scope={"campus": "x", "dept": "y"})
    assert empty["answered"] == 0 and all(x["pct"] == 0.0 for x in empty["groups"])


@pytest.mark.asyncio
async def test_the_endpoint_is_admin_only_and_the_tab_is_on_the_outcome_page(client, admin_client):
    await _seed()
    assert (await client.get("/admin/api/career-interest")).status_code == 403
    r = await admin_client.get("/admin/api/career-interest", params={"dept": "BBA"})
    assert r.status_code == 200 and r.json()["answered"] == 5
    assert "@x.com" not in r.text                     # counts only, never who

    from pathlib import Path
    tpl = Path("app/templates/admin_survey.html").read_text()
    assert 'data-tab="career" onclick="setCohortTab(\'career\')">Career interest' in tpl
    assert 'id="cohort-view-career"' in tpl and 'id="cohort-view-report"' in tpl
    assert "/admin/api/career-interest?" in tpl and "/bba/i.test(x)" in tpl
