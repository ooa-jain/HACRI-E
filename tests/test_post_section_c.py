"""
Section C in Survey 2 — "AI Usage at University".

It mirrors the baseline's Section C question for question, so each answer can
be read against its "before university" counterpart.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app import db
from app.sections import POST_USAGE, PRE_USAGE


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


def test_post_section_c_mirrors_the_baseline():
    """Same keys, same kinds — only the time frame differs."""
    assert [k for k, *_ in POST_USAGE] == [k for k, *_ in PRE_USAGE]
    assert [kind for _, _, kind, _ in POST_USAGE] == [kind for _, _, kind, _ in PRE_USAGE]

    pre = {k: label for k, label, *_ in PRE_USAGE}
    post = {k: label for k, label, *_ in POST_USAGE}
    for key in pre:
        assert pre[key] != post[key], f"{key} should be reworded for university"
    assert "school" not in " ".join(post.values()).lower()

    # Option lists stay identical wherever the choices are comparable.
    pre_opts = {k: opts for k, _, kind, opts in PRE_USAGE if kind == "select"}
    post_opts = {k: opts for k, _, kind, opts in POST_USAGE if kind == "select"}
    assert pre_opts == post_opts


def test_section_c_is_not_scored():
    """C must stay out of the literacy/readiness scores, as in the baseline."""
    from app.hacri_e2_compat import SCHEMA
    assert not [k for k in SCHEMA if k.startswith("C")]


@pytest.mark.asyncio
async def test_section_c_renders_in_survey_2(client: AsyncClient):
    from app.deps import make_csrf_token
    from tests.test_gating import _make_pre_payload, _mint_session_cookie

    email, name = "cee@example.com", "Cee"
    csrf = make_csrf_token()
    client.cookies.set("hacri_csrf", csrf)
    await client.post("/start", data={"name": name, "email": email, "csrf": csrf},
                      follow_redirects=False)
    client.cookies.set("hacri_session", _mint_session_cookie(email, name))
    payload = _make_pre_payload(name, email)
    payload["csrf"] = csrf
    await client.post("/survey/pre", data=payload, follow_redirects=False)

    page = await client.get("/survey/post")
    assert page.status_code == 200
    assert "Section C" in page.text
    assert "AI Usage at University" in page.text
    for key, label, *_ in POST_USAGE:
        assert label in page.text, f"{key} missing from Survey 2"

    # The stepper offers C between B and D.
    labels = page.text.split('wizard-step-label">')[1:]
    labels = [chunk.split("<")[0] for chunk in labels]
    assert labels.index("Literacy") < labels.index("Experience") < labels.index("Attitudes")


@pytest.mark.asyncio
async def test_section_c_answers_are_saved_with_the_post_response(client: AsyncClient):
    from app.deps import make_csrf_token
    from tests.test_gating import _make_post_payload, _make_pre_payload, _mint_session_cookie

    email, name = "usage@example.com", "Usage"
    csrf = make_csrf_token()
    client.cookies.set("hacri_csrf", csrf)
    await client.post("/start", data={"name": name, "email": email, "csrf": csrf},
                      follow_redirects=False)
    client.cookies.set("hacri_session", _mint_session_cookie(email, name))
    pre = _make_pre_payload(name, email)
    pre["csrf"] = csrf
    await client.post("/survey/pre", data=pre, follow_redirects=False)

    post = _make_post_payload(name, email)
    post["csrf"] = csrf
    post["C1"] = ["ChatGPT or similar chatbots", "AI-powered search (e.g. Perplexity)"]
    post["C2"] = "Daily"
    post["C3"] = ["Researching topics"]
    post["C4"] = "Often"
    post["C5"] = "Sometimes"
    resp = await client.post("/survey/post", data=post, follow_redirects=False)
    assert resp.status_code in (303, 307), resp.text[:400]

    doc = await db.get_db()["post_responses"].find_one({"email": email})
    fields = doc["fields"]
    assert fields["C1"] == ["ChatGPT or similar chatbots", "AI-powered search (e.g. Perplexity)"]
    assert fields["C2"] == "Daily"
    assert fields["C3"] == ["Researching topics"]
    assert fields["C4"] == "Often"
    assert fields["C5"] == "Sometimes"


@pytest.mark.asyncio
async def test_admin_detail_shows_section_c_for_both_surveys(client: AsyncClient):
    from app.hacri_e2_compat import SCHEMA

    now = datetime.now(timezone.utc)
    email = "both@example.com"
    await db.get_db()["users"].insert_one({
        "email": email, "name": "Both", "program": "Department of Law", "ug_or_pg": "ug",
        "status": db.STATUS_POST_DONE, "created_at": now,
        "pre_submitted_at": now, "post_submitted_at": now,
    })
    await db.get_db()["pre_responses"].insert_one({
        "email": email, "submitted_at": now,
        "fields": {**{k: 3 for k in SCHEMA}, "C2": "Rarely"}})
    await db.get_db()["post_responses"].insert_one({
        "email": email, "submitted_at": now,
        "fields": {**{k: 4 for k in SCHEMA}, "C2": "Daily"}})

    client.cookies.set("survey_admin_session", "1")
    d = (await client.get(f"/admin/api/survey/student/{email}")).json()

    pre_c = next(s for s in d["pre_sections"] if s["title"].startswith("C —"))
    post_c = next(s for s in d["post_sections"] if s["title"].startswith("C —"))
    assert "Prior AI Usage" in pre_c["title"]
    assert "AI Usage at University" in post_c["title"]

    # The same question, before and after — visibly comparable.
    assert next(r["value"] for r in pre_c["rows"] if r["key"] == "C2") == "Rarely"
    assert next(r["value"] for r in post_c["rows"] if r["key"] == "C2") == "Daily"
