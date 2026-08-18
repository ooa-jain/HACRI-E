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


# ── Department links ─────────────────────────────────────────────────────────
#
# Each department is sent its own link. It opens that department alone: the
# report is theirs, the comparison is the campus average, and no other
# department's scoreboard travels with it.


def _dept_link(campus: str, dept: str) -> dict:
    return {"campus": campus, "dept": dept, "token": get_orientation_token(campus, dept)}


@pytest.mark.asyncio
async def test_admin_hands_out_one_link_per_department(app_with_mock):
    await _seed()
    transport = ASGITransport(app=app_with_mock)
    async with AsyncClient(transport=transport, base_url="http://test") as admin:
        admin.cookies.set("survey_admin_session", "1")
        body = (await admin.get("/admin/api/orientation/dept-share-links",
                                params={"campus": "Bangalore"})).json()

    assert body["campus"] == "Bangalore"
    assert [row["dept"] for row in body["links"]] == [
        "Department of Commerce", "Department of Law",
    ]
    for row in body["links"]:
        assert "dept=" in row["url"] and "token=" in row["url"]
    # A department's link is not its campus's link, nor its neighbour's.
    tokens = {row["url"].split("token=")[1] for row in body["links"]}
    assert len(tokens) == 2
    assert get_orientation_token("Bangalore") not in tokens

    async with AsyncClient(transport=transport, base_url="http://test") as anon:
        r = await anon.get("/admin/api/orientation/dept-share-links")
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_a_department_link_opens_that_department_alone(client):
    await _seed()
    params = _dept_link("Bangalore", "Department of Law")

    page = await client.get("/shared/orientation", params=params)
    assert page.status_code == 200
    assert "Department of Law" in page.text

    body = (await client.get("/shared/orientation/data", params=params)).json()
    assert body["locked"] is True
    assert body["dept"] == "Department of Law"
    assert body["report"]["count"] == 1                      # Asha only
    assert body["report"]["headline"]["vibe"] == 9.0
    # Its own row, and the campus average to read it against — nobody else's.
    assert [d["dept"] for d in body["departments"]["departments"]] == ["Department of Law"]
    assert body["departments"]["overall"]["filled"] == 2      # the whole campus
    assert body["dept_options"] == ["Department of Law"]

    deck = await client.get("/shared/orientation/ppt", params=params)
    assert deck.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [
    # Its own token pointed at the department next door.
    {"campus": "Bangalore", "dept": "Department of Commerce",
     "token": get_orientation_token("Bangalore", "Department of Law")},
    # The same department, but on the campus it was not minted for.
    {"campus": "Kochi", "dept": "Department of Law",
     "token": get_orientation_token("Bangalore", "Department of Law")},
    # A department token stripped back to the whole campus.
    {"campus": "Bangalore", "token": get_orientation_token("Bangalore", "Department of Law")},
])
async def test_a_department_link_cannot_be_edited_into_another(client, params):
    await _seed()
    for path in ("/shared/orientation", "/shared/orientation/data", "/shared/orientation/ppt"):
        assert (await client.get(path, params=params)).status_code == 403


@pytest.mark.asyncio
async def test_the_campus_link_still_filters_freely(client):
    """The campus link keeps its picker: dept is a filter, not a lock."""
    await _seed()
    params = {**_link("Bangalore"), "dept": "Department of Commerce"}
    body = (await client.get("/shared/orientation/data", params=params)).json()

    assert body["locked"] is False
    assert body["report"]["count"] == 1
    assert {d["dept"] for d in body["departments"]["departments"]} == {
        "Department of Law", "Department of Commerce",
    }
