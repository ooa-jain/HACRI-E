"""
The shareable Deeksharambh orientation report — the link an admin copies out
of the dashboard and sends to people who have no login.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app import db
from app.routes.shared_analysis import get_orientation_token


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
    now = datetime.now(timezone.utc)
    people = [
        ("asha@x.com", "Asha", "Department of Law", "Bangalore", 9, 10),
        ("bilal@x.com", "Bilal", "Department of Commerce", "Bangalore", 7, 6),
        ("chitra@x.com", "Chitra", "Department of Law", "Kochi", 5, 3),
    ]
    for i, (email, name, program, campus, vibe, nps) in enumerate(people):
        await db.get_db()["users"].insert_one({
            "email": email, "name": name, "program": program, "ug_or_pg": "ug",
            "location": campus, "status": db.STATUS_PRE_DONE, "created_at": now,
            "pre_submitted_at": now, "orientation_submitted": True,
        })
        await db.get_db()["orientation_responses"].insert_one({
            "email": email, "name": name, "submitted_at": now - timedelta(hours=i),
            "data": {
                "location": f"📍 {campus}", "q2": vibe, "q34": nps, "q29": 8,
                "q11": ["🚶 Campus Tour"], "q3": "🙂 Yes, mostly",
            },
        })


def _link(campus: str = "") -> dict:
    return {"campus": campus, "token": get_orientation_token(campus)}


@pytest.mark.asyncio
async def test_admin_hands_out_one_link_per_campus(app_with_mock):
    transport = ASGITransport(app=app_with_mock)
    async with AsyncClient(transport=transport, base_url="http://test") as admin:
        admin.cookies.set("survey_admin_session", "1")
        links = (await admin.get("/admin/api/orientation/share-links")).json()["links"]

    assert [row["campus"] for row in links] == ["All campuses", "Bangalore", "Kochi"]
    for row in links:
        assert row["url"].startswith("http://test/shared/orientation?campus=")
        assert "token=" in row["url"]
    # Every campus gets its own token.
    assert len({row["url"].split("token=")[1] for row in links}) == 3

    async with AsyncClient(transport=transport, base_url="http://test") as anon:
        assert (await anon.get("/admin/api/orientation/share-links")).status_code == 403


@pytest.mark.asyncio
async def test_the_page_opens_with_no_login(client):
    await _seed()
    r = await client.get("/shared/orientation", params=_link("Bangalore"))
    assert r.status_code == 200
    assert "Deeksharambh 2026" in r.text
    assert "Bangalore" in r.text
    # The shell defers to the data endpoint, which re-checks the token.
    assert "/shared/orientation/data" in r.text


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [
    {"campus": "Bangalore", "token": "deadbeefdeadbeef"},
    {"campus": "Bangalore", "token": ""},
    # A Kochi link must not open Bangalore, or the other way round.
    {"campus": "Kochi", "token": get_orientation_token("Bangalore")},
    {"campus": "", "token": get_orientation_token("Bangalore")},
])
async def test_a_wrong_or_edited_token_is_refused(client, params):
    await _seed()
    for path in ("/shared/orientation", "/shared/orientation/data", "/shared/orientation/ppt"):
        assert (await client.get(path, params=params)).status_code == 403


@pytest.mark.asyncio
async def test_the_data_is_scoped_to_the_link_campus(client):
    await _seed()
    body = (await client.get("/shared/orientation/data", params=_link("Kochi"))).json()

    assert body["campus"] == "Kochi"
    assert body["report"]["count"] == 1
    assert body["report"]["headline"]["vibe"] == 5.0
    assert [d["dept"] for d in body["departments"]["departments"]] == ["Department of Law"]
    assert body["dept_options"] == ["Department of Law"]


@pytest.mark.asyncio
async def test_a_department_narrows_the_report_but_not_the_comparison(client):
    await _seed()
    body = (await client.get("/shared/orientation/data",
                             params={**_link("Bangalore"), "dept": "Department of Law"})).json()

    assert body["report"]["count"] == 1                       # Asha only
    assert body["report"]["headline"]["vibe"] == 9.0
    # The leaderboard still covers the whole campus, or there is nothing to
    # compare that department against.
    assert {d["dept"] for d in body["departments"]["departments"]} == {
        "Department of Law", "Department of Commerce",
    }


@pytest.mark.asyncio
async def test_the_shared_payload_names_nobody(client):
    await _seed()
    r = await client.get("/shared/orientation/data", params=_link(""))
    assert r.status_code == 200
    body = r.text
    for private in ("asha@x.com", "bilal@x.com", "chitra@x.com", "Asha", "Bilal", "Chitra"):
        assert private not in body


@pytest.mark.asyncio
async def test_the_deck_downloads_from_the_shared_link(client):
    await _seed()
    r = await client.get("/shared/orientation/ppt", params=_link("Bangalore"))
    assert r.status_code == 200
    assert "presentationml" in r.headers["content-type"]

    from io import BytesIO
    from pptx import Presentation

    assert len(Presentation(BytesIO(r.content)).slides) >= 8


@pytest.mark.asyncio
async def test_the_renderer_and_its_stylesheet_are_served(client):
    for path in ("/static/js/orientation_report.js", "/static/css/orientation_report.css"):
        r = await client.get(path)
        assert r.status_code == 200
        assert len(r.content) > 1000


# ── One link per department ──────────────────────────────────────────────────
# The same report signed for a single department, so a head of department can
# be sent theirs without it opening anybody else's.
LAW = "Department of Law"
COMMERCE = "Department of Commerce"


def _dept_link(campus: str, dept: str) -> dict:
    return {"campus": campus, "dept": dept,
            "token": get_orientation_token(campus, dept)}


@pytest.mark.asyncio
async def test_admin_hands_out_one_link_per_department(app_with_mock):
    await _seed()
    transport = ASGITransport(app=app_with_mock)
    async with AsyncClient(transport=transport, base_url="http://test") as admin:
        admin.cookies.set("survey_admin_session", "1")
        body = (await admin.get("/admin/api/orientation/dept-share-links",
                                params={"campus": "Bangalore"})).json()

        async with AsyncClient(transport=transport, base_url="http://test") as anon:
            assert (await anon.get("/admin/api/orientation/dept-share-links")).status_code == 403

    assert body["campus"] == "Bangalore"
    # Ranked the way the leaderboard ranks them: best vibe first.
    assert [row["dept"] for row in body["links"]] == [LAW, COMMERCE]

    law = body["links"][0]
    assert (law["filled"], law["eligible"], law["vibe"]) == (1, 1, 9.0)
    assert law["url"].startswith("http://test/shared/orientation?")
    # Every department gets its own token, and none of them is the campus one.
    tokens = {row["url"].split("token=")[1].split("&")[0] for row in body["links"]}
    assert len(tokens) == 2
    assert get_orientation_token("Bangalore") not in tokens


@pytest.mark.asyncio
async def test_a_department_link_opens_that_department(client):
    await _seed()
    link = _dept_link("Bangalore", LAW)

    page = await client.get("/shared/orientation", params=link)
    assert page.status_code == 200
    assert LAW in page.text
    assert "Vibe scorecard" in page.text

    body = (await client.get("/shared/orientation/data", params=link)).json()
    assert body["locked"] is True
    assert body["dept"] == LAW
    assert body["report"]["count"] == 1               # Asha, not Bilal
    assert body["report"]["headline"]["vibe"] == 9.0

    assert (await client.get("/shared/orientation/ppt", params=link)).status_code == 200


@pytest.mark.asyncio
async def test_a_department_link_names_no_other_department(client):
    await _seed()
    body = (await client.get("/shared/orientation/data",
                             params=_dept_link("Bangalore", LAW))).json()

    assert body["dept_options"] == [LAW]
    assert [row["dept"] for row in body["departments"]["departments"]] == [LAW]
    assert COMMERCE not in (await client.get(
        "/shared/orientation/data", params=_dept_link("Bangalore", LAW))).text


@pytest.mark.asyncio
async def test_the_scorecard_reads_the_department_against_its_campus(client):
    await _seed()
    card = (await client.get("/shared/orientation/data",
                             params=_dept_link("Bangalore", LAW))).json()["scorecard"]

    assert card["dept"] == LAW
    assert (card["rank"], card["of"]) == (1, 2)       # best vibe of the two
    assert card["department"]["filled"] == 1
    assert card["campus_overall"]["filled"] == 2      # the campus it is judged against

    metrics = {m["key"]: m for m in card["metrics"]}
    # Law rated the week 9, the campus averaged 8 — a point above.
    assert (metrics["vibe"]["value"], metrics["vibe"]["campus"]) == (9.0, 8.0)
    assert metrics["vibe"]["delta"] == 1.0
    # Both of Law's students would recommend JAIN; half the campus would not.
    assert (metrics["nps"]["value"], metrics["nps"]["campus"]) == (100.0, 0.0)
    # Nobody answered the bridge-course question, so it stays blank rather
    # than reading as a zero.
    assert metrics["bridge"]["value"] is None
    assert metrics["bridge"]["delta"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [
    # One department's token must not open another's.
    {**_dept_link("Bangalore", LAW), "dept": COMMERCE},
    # Nor the whole campus.
    {"campus": "Bangalore", "token": get_orientation_token("Bangalore", LAW)},
    # Nor the same department on another campus.
    {**_dept_link("Bangalore", LAW), "campus": "Kochi"},
])
async def test_a_department_token_unlocks_nothing_else(client, params):
    await _seed()
    for path in ("/shared/orientation", "/shared/orientation/data", "/shared/orientation/ppt"):
        assert (await client.get(path, params=params)).status_code == 403


@pytest.mark.asyncio
async def test_a_campus_link_is_unchanged_by_all_this(client):
    """The links already handed out keep working, and keep the run of the campus."""
    await _seed()
    body = (await client.get("/shared/orientation/data",
                             params={**_link("Bangalore"), "dept": COMMERCE})).json()

    assert body["locked"] is False
    assert "scorecard" not in body
    assert body["report"]["count"] == 1
    # Free to look at any department, and at the leaderboard behind it.
    assert {d["dept"] for d in body["departments"]["departments"]} == {LAW, COMMERCE}
