"""
Admin student lookup — the header search bar and the detail panel behind it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app import db


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
        ac.cookies.set("survey_admin_session", "1")
        yield ac


async def _seed() -> None:
    from app.hacri_e2_compat import SCHEMA

    now = datetime.now(timezone.utc)
    people = [
        ("priya.sharma@example.com", "Priya Sharma", "Department of Law", db.STATUS_POST_DONE),
        ("rahul.k@example.com", "Rahul Kumar", "Department of Commerce", db.STATUS_PRE_DONE),
        ("anita@example.com", "Anita Rao", "Department of Law", None),
    ]
    for email, name, program, status in people:
        await db.get_db()["users"].insert_one({
            "email": email, "name": name, "program": program, "ug_or_pg": "ug",
            "status": status, "created_at": now, "pre_submitted_at": now if status else None,
            "post_reminder_sent_at": now, "post_reminder_count": 2,
        })
        if status:
            await db.get_db()["pre_responses"].insert_one({
                "email": email, "name": name, "submitted_at": now,
                "fields": {**{k: 3 for k in SCHEMA}, "A1": "18-20", "H5": "How AI reasons"},
            })
        if status == db.STATUS_POST_DONE:
            await db.get_db()["post_responses"].insert_one({
                "email": email, "name": name, "submitted_at": now,
                "fields": {**{k: 4 for k in SCHEMA}, "father_name": "Mr Sharma",
                           "father_occupation": "Salaried", "praise_initiative": "Societal Impact"},
            })


@pytest.mark.asyncio
async def test_search_finds_by_name_email_and_department(client: AsyncClient):
    await _seed()

    by_name = (await client.get("/admin/api/survey/search?q=priya")).json()
    assert [r["email"] for r in by_name["results"]] == ["priya.sharma@example.com"]

    by_email = (await client.get("/admin/api/survey/search?q=rahul.k@")).json()
    assert by_email["results"][0]["name"] == "Rahul Kumar"

    by_dept = (await client.get("/admin/api/survey/search?q=department of law")).json()
    assert {r["email"] for r in by_dept["results"]} == {"priya.sharma@example.com", "anita@example.com"}


@pytest.mark.asyncio
async def test_search_is_case_insensitive_and_needs_two_characters(client: AsyncClient):
    await _seed()

    assert (await client.get("/admin/api/survey/search?q=PRIYA")).json()["total"] == 1
    # One character would match nearly everyone — not worth a round trip.
    assert (await client.get("/admin/api/survey/search?q=p")).json()["results"] == []


@pytest.mark.asyncio
async def test_search_ranks_an_exact_email_first(client: AsyncClient):
    await _seed()
    await db.get_db()["users"].insert_one({
        "email": "zz@example.com", "name": "anita@example.com lookalike",
        "program": "Department of Design", "ug_or_pg": "ug", "status": None,
        "created_at": datetime.now(timezone.utc),
    })

    results = (await client.get("/admin/api/survey/search?q=anita@example.com")).json()["results"]
    assert results[0]["email"] == "anita@example.com"


@pytest.mark.asyncio
async def test_search_requires_admin(app_with_mock):
    transport = ASGITransport(app=app_with_mock)
    async with AsyncClient(transport=transport, base_url="http://test") as anon:
        assert (await anon.get("/admin/api/survey/search?q=priya")).status_code == 403
        assert (await anon.get("/admin/api/survey/student/priya.sharma@example.com")).status_code == 403


@pytest.mark.asyncio
async def test_student_detail_returns_profile_scores_and_answers(client: AsyncClient):
    await _seed()

    d = (await client.get("/admin/api/survey/student/priya.sharma@example.com")).json()

    assert d["name"] == "Priya Sharma"
    assert d["program"] == "Department of Law"
    assert d["status"] == db.STATUS_POST_DONE
    assert d["created_at"] and d["pre_at"] and d["post_at"]

    # Scores on both halves, plus the movement between them.
    assert d["scores"]["pre"]["lit"] is not None
    assert d["scores"]["post"]["lit"] is not None
    assert d["scores"]["delta_lit"] == pytest.approx(1.0)
    assert d["scores"]["movement"]

    # Email tracking is carried through.
    assert d["email_activity"]["post_reminder_count"] == 2

    # Answers arrive grouped, with real wording where the instrument has it.
    pre_titles = [s["title"] for s in d["pre_sections"]]
    assert any(t.startswith("A —") for t in pre_titles)
    assert any(t.startswith("B —") for t in pre_titles)
    background = next(s for s in d["pre_sections"] if s["title"].startswith("A —"))
    assert any(r["label"].startswith("What is your age") and r["value"] == "18-20"
               for r in background["rows"])

    post_titles = [s["title"] for s in d["post_sections"]]
    assert any(t.startswith("A —") for t in post_titles)
    family = next(s for s in d["post_sections"] if s["title"].startswith("A —"))
    assert any(r["label"] == "Father's name" and r["value"] == "Mr Sharma" for r in family["rows"])


@pytest.mark.asyncio
async def test_student_detail_handles_a_student_who_started_nothing(client: AsyncClient):
    await _seed()

    d = (await client.get("/admin/api/survey/student/anita@example.com")).json()
    assert d["status"] == "not_started"
    assert d["pre_sections"] == [] and d["post_sections"] == []
    assert d["scores"]["pre"] is None and d["scores"]["delta_lit"] is None


@pytest.mark.asyncio
async def test_student_detail_404s_for_an_unknown_email(client: AsyncClient):
    await _seed()
    resp = await client.get("/admin/api/survey/student/ghost@example.com")
    assert resp.status_code == 404
