"""
The shareable impact page.

Its whole point is the population it counts: students who finished both
surveys. A student who did the baseline alone is not a blank row in these
figures — they are outside them, because "before" and "after" only compare if
they describe the same people.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app import db

DESIGN = "Department of Design"
LAW = "Department of Law"


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


async def _seed() -> None:
    from app.hacri_e2_compat import SCHEMA

    now = datetime.now(timezone.utc)
    # email, dept, status, campus, orientation, father's occupation
    people = [
        ("both1@x.com",  DESIGN, db.STATUS_POST_DONE, "Bangalore", True,  "Salaried"),
        ("both2@x.com",  DESIGN, db.STATUS_POST_DONE, "Bangalore", False, "Entrepreneur"),
        ("both3@x.com",  LAW,    db.STATUS_POST_DONE, "Kochi",     True,  ""),
        ("preonly@x.com", LAW,   db.STATUS_PRE_DONE,  "Bangalore", True,  ""),
        ("nothing@x.com", LAW,   None,                "Kochi",     False, ""),
    ]
    for email, program, status, campus, orientation, occupation in people:
        await db.get_db()["users"].insert_one({
            "email": email, "name": email.split("@")[0].title(), "program": program,
            "ug_or_pg": "ug", "status": status, "location": campus, "created_at": now,
            "pre_submitted_at": now if status else None,
            "post_submitted_at": now if status == db.STATUS_POST_DONE else None,
            "orientation_submitted": orientation,
        })
        if status:
            await db.get_db()["pre_responses"].insert_one(
                {"email": email, "submitted_at": now, "fields": {k: 3 for k in SCHEMA}})
        if status == db.STATUS_POST_DONE:
            fields = {k: 4 for k in SCHEMA}
            if occupation:
                fields["father_occupation"] = occupation
            await db.get_db()["post_responses"].insert_one(
                {"email": email, "submitted_at": now + timedelta(hours=1), "fields": fields})
        if orientation:
            await db.get_db()["orientation_responses"].insert_one(
                {"email": email, "submitted_at": now, "data": {}})


def _token(campus: str = "") -> str:
    from app.routes.shared_analysis import get_vibe_token
    return get_vibe_token(campus)


@pytest.mark.asyncio
async def test_the_page_needs_its_token(client: AsyncClient):
    await _seed()
    assert (await client.get("/shared/impact?token=nonsense")).status_code == 403
    assert (await client.get(f"/shared/impact?token={_token()}")).status_code == 200


@pytest.mark.asyncio
async def test_a_campus_token_does_not_open_another_campus(client: AsyncClient):
    await _seed()
    r = await client.get(f"/shared/impact?campus=Bangalore&token={_token('Kochi')}")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_only_students_who_finished_both_are_counted(client: AsyncClient):
    await _seed()
    from app.vibe_report import vibe_report

    report = await vibe_report()
    # Five registered, three finished both. The baseline-only student and the
    # one who never started are not in the count.
    assert report["registered"] == 5
    assert report["count"] == 3

    names = {p["name"] for p in report["praise"]}
    assert "Preonly" not in names
    assert "Nothing" not in names
    assert len(names) == 3


@pytest.mark.asyncio
async def test_department_counts_are_distinct_students(client: AsyncClient):
    await _seed()
    from app.vibe_report import vibe_report

    report = await vibe_report()
    counts = {d["dept"]: d["count"] for d in report["departments"]}
    # Design finished two; Law finished one of its three.
    assert counts == {DESIGN: 2, LAW: 1}
    assert sum(counts.values()) == report["count"]


@pytest.mark.asyncio
async def test_a_campus_report_counts_only_that_campus(client: AsyncClient):
    await _seed()
    from app.vibe_report import vibe_report

    kochi = await vibe_report(campus="Kochi")
    assert kochi["campus"] == "Kochi"
    assert kochi["count"] == 1          # both3 only
    assert kochi["registered"] == 2     # both3 and the one who never started

    bangalore = await vibe_report(campus="Bangalore")
    assert bangalore["count"] == 2


@pytest.mark.asyncio
async def test_orientation_and_parents_come_from_the_finished_cohort(client: AsyncClient):
    await _seed()
    from app.vibe_report import vibe_report

    report = await vibe_report()
    # preonly@x.com attended the orientation but is outside the population.
    assert report["orientation"] == 2
    assert report["parents"] == {
        "answered": 2, "salaried": 1, "entrepreneur": 1, "homemaker": 0,
    }


@pytest.mark.asyncio
async def test_the_page_names_the_people_it_counted(client: AsyncClient):
    await _seed()
    r = await client.get(f"/shared/impact?token={_token()}")
    assert r.status_code == 200
    body = r.text
    assert "students finished both surveys" in body
    assert "Both1" in body and "Both2" in body
    assert "Preonly" not in body


@pytest.mark.asyncio
async def test_outcome_and_impact_are_scored_separately(client: AsyncClient):
    await _seed()
    from app.vibe_report import vibe_report

    report = await vibe_report()
    # The seed answers every baseline item 3 and every post item 4, so the
    # page should show the move rather than one blended average.
    assert report["outcome"]["literacy"] == 3
    assert report["impact"]["literacy"] == 4
    assert report["lift"]["literacy"] == 1
