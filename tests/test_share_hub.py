"""
The share hub: every shareable link in the app, from one call.

They used to sit behind five endpoints across three pages, so the whole set
was never visible at once and it was easy to hand out the wrong one — a campus
report where a department report was meant shows a head of department every
other department's figures.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app import db

LAW = "Department of Law"
COMMERCE = "Department of Commerce"


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


async def _seed() -> None:
    now = datetime.now(timezone.utc)
    for i, dept in enumerate([LAW, COMMERCE] * 3):
        email = f"s{i}@x.com"
        await db.get_db()["users"].insert_one({
            "email": email, "name": f"S{i}", "program": dept, "ug_or_pg": "ug",
            "location": "Bangalore", "status": db.STATUS_PRE_DONE,
            "created_at": now, "pre_submitted_at": now,
            "orientation_submitted": True})
        await db.get_db()["orientation_responses"].insert_one({
            "email": email, "name": f"S{i}", "submitted_at": now,
            "data": {"location": "📍 Bangalore", "q2": 8}})


def _admin(client: AsyncClient) -> None:
    client.cookies.set("survey_admin_session", "1")


@pytest.mark.asyncio
async def test_it_needs_an_admin_session(client):
    """These links open reports with no login of their own, so the list of
    them is not public."""
    assert (await client.get("/admin/api/share-links")).status_code == 403


@pytest.mark.asyncio
async def test_every_kind_of_link_is_in_the_one_payload(client):
    await _seed()
    _admin(client)
    body = (await client.get("/admin/api/share-links")).json()

    titles = [g["title"] for g in body["groups"]]
    assert titles == ["For students", "For the office", "Deeksharambh report",
                      "Student impact page", "Outcome and impact report"]
    assert body["total"] == sum(len(g["links"]) for g in body["groups"])

    urls = [l["url"] for g in body["groups"] for l in g["links"]]
    for path in ("/deeksharambh", "/pre/", "/post/", "/shared/departments",
                 "/shared/orientation", "/shared/impact", "/shared/cohort"):
        assert any(path in u for u in urls), f"no link for {path}"


@pytest.mark.asyncio
async def test_every_link_says_what_it_opens(client):
    """A URL does not tell you whether it is one department or the whole
    campus — the difference is one query parameter."""
    await _seed()
    _admin(client)
    body = (await client.get("/admin/api/share-links")).json()
    for group in body["groups"]:
        assert group["note"].strip()
        for link in group["links"]:
            assert link["label"].strip()
            assert link["sub"].strip(), f"{link['label']} has no description"
            assert link["url"].startswith("http")


@pytest.mark.asyncio
async def test_each_answering_department_gets_its_own_orientation_link(client):
    await _seed()
    _admin(client)
    body = (await client.get("/admin/api/share-links")).json()
    ori = next(g for g in body["groups"] if g["key"] == "orientation")

    labels = [l["label"] for l in ori["links"]]
    assert "All campuses" in labels and "Bangalore" in labels
    assert LAW in labels and COMMERCE in labels

    # A department link is scoped to its own department, and carries a
    # different token from the campus link.
    dept = next(l for l in ori["links"] if l["label"] == LAW)
    campus = next(l for l in ori["links"] if l["label"] == "All campuses")
    assert "dept=" in dept["url"]
    assert "dept=" not in campus["url"]
    assert dept["url"].split("token=")[1] != campus["url"].split("token=")[1]


@pytest.mark.asyncio
async def test_the_deck_and_the_workbook_ride_along_with_the_report_links(client):
    await _seed()
    _admin(client)
    body = (await client.get("/admin/api/share-links")).json()
    ori = next(g for g in body["groups"] if g["key"] == "orientation")

    for link in ori["links"]:
        labels = [d["label"] for d in link["downloads"]]
        assert labels == ["Deck", "Excel"]
        assert "/shared/orientation/ppt" in link["downloads"][0]["url"]
        assert "/shared/orientation/excel" in link["downloads"][1]["url"]

    # The student and impact links have no file behind them, so they offer none.
    students = next(g for g in body["groups"] if g["key"] == "students")
    assert all(not l.get("downloads") for l in students["links"])


@pytest.mark.asyncio
async def test_the_unmatched_bucket_is_not_offered_as_a_department(client):
    """Replies with no student record are filed under "—", which is not a
    department and must not get a share link of its own."""
    now = datetime.now(timezone.utc)
    await db.get_db()["orientation_responses"].insert_one({
        "email": "ghost@x.com", "name": "Ghost", "submitted_at": now,
        "data": {"location": "📍 Bangalore", "q2": 7}})
    _admin(client)
    body = (await client.get("/admin/api/share-links")).json()
    ori = next(g for g in body["groups"] if g["key"] == "orientation")
    assert "—" not in [l["label"] for l in ori["links"]]
