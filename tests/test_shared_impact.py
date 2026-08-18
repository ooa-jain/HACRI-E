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
    # The hero opens on the whole cohort, then names the two populations it
    # measures over.
    assert "students registered so far" in body
    assert "came back for the post survey" in body
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


@pytest.mark.asyncio
async def test_outcome_counts_more_people_than_impact(client: AsyncClient):
    await _seed()
    from app.vibe_report import vibe_report

    report = await vibe_report()
    # Outcome describes everyone who filled the baseline; Impact only those
    # who came back. Four filled the baseline, three returned.
    assert report["outcome_count"] == 4
    assert report["count"] == 3
    assert report["outcome_count"] > report["count"]

    # And the baseline departments cover the wider group.
    outcome_counts = {d["dept"]: d["count"] for d in report["outcome_departments"]}
    assert outcome_counts == {DESIGN: 2, LAW: 2}


@pytest.mark.asyncio
async def test_the_movement_plots_one_pair_per_student(client: AsyncClient):
    await _seed()
    from app.vibe_report import vibe_report

    move = (await vibe_report())["movement"]
    assert len(move["points"]) == 3
    # Every seeded student answered 3 at baseline and 4 after, so all moved up.
    assert move["gained"] == 3
    assert move["held"] == 0 and move["slipped"] == 0
    for p in move["points"]:
        assert p["x1"] > p["x0"] and p["up"] is True


@pytest.mark.asyncio
async def test_registered_total_is_everyone_on_the_portal(client: AsyncClient):
    await _seed()
    from app.vibe_report import vibe_report

    # Unaffected by the campus scope: it is the headline the page opens with.
    assert (await vibe_report())["registered_total"] == 5
    assert (await vibe_report(campus="Kochi"))["registered_total"] == 5


@pytest.mark.asyncio
async def test_the_page_opens_every_deeksharambh_report(client):
    """One link shared, every orientation report reachable behind it.

    The page carries the campus's own Deeksharambh link and one per
    department, each signed for what it opens — and each has to actually
    open, or the page is handing out dead links.
    """
    import re

    await _seed()
    page = (await client.get("/shared/impact", params={"campus": "", "token": _token()})).text

    # Jinja escapes the ampersands in an attribute, as HTML requires; a browser
    # decodes them again, so the test does too.
    import html as html_lib

    links = [html_lib.unescape(url) for url in
             re.findall(r'href="(http://test/shared/orientation\?[^"]+)"', page)]
    assert links, "the impact page lists no Deeksharambh links"

    # The campus link, plus the two departments that finished both surveys.
    assert any("dept=" not in url for url in links)
    assert sum(1 for url in links if "dept=" in url) == 2

    for url in links:
        assert (await client.get(url.replace("http://test", ""))).status_code == 200

    # A department link stripped of its department must not open the campus.
    dept_url = next(url for url in links if "dept=" in url)
    stripped = re.sub(r"&dept=[^&]*", "", dept_url.replace("http://test", ""))
    assert (await client.get(stripped)).status_code == 403
