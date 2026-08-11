"""
Survey admin's orientation report — campus summary, analysis, who filled it,
and mailing that cohort.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app import db
from app.orientation_analysis import normalize_campus, summarize_orientation


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


def _answers(*, campus: str, vibe: int, nps: int) -> dict:
    return {
        "location": f"📍 {campus}",
        "q1": ["🔥 Inspiring", "🚀 Exciting"],
        "q2": vibe,
        "q3": "🙂 Yes, mostly",
        "q8": {"Campus life": "Yes", "Academics": "Somewhat"},
        "q16": 4,
        "q29": 8,
        "q32": 9,
        "q34": nps,
        "q37": ["🎪 Student Club Fair"],
        "q41": "A JAIN Explorer",
    }


async def _seed() -> None:
    """Two Bangalore students who filled it, one Kochi who did, one who hasn't."""
    now = datetime.now(timezone.utc)
    people = [
        ("a@x.com", "Asha", "Department of Law",      "Bangalore", db.STATUS_PRE_DONE,  True,  10, 10),
        ("b@x.com", "Bilal", "Department of Commerce", "Bangalore", db.STATUS_POST_DONE, True,  6,  5),
        ("c@x.com", "Chitra", "Department of Law",     "Kochi",     db.STATUS_PRE_DONE,  True,  8,  9),
        ("d@x.com", "Dev", "Department of Law",        "Bangalore", db.STATUS_PRE_DONE,  False, 0,  0),
        # Never finished the baseline — not part of either cohort.
        ("e@x.com", "Esha", "Department of Law",       "Kochi",     None,                False, 0,  0),
    ]
    for i, (email, name, program, campus, status, filled, vibe, nps) in enumerate(people):
        await db.get_db()["users"].insert_one({
            "email": email, "name": name, "program": program, "ug_or_pg": "ug",
            "location": campus, "status": status, "created_at": now,
            "pre_submitted_at": now if status else None,
            "orientation_submitted": filled,
        })
        if filled:
            await db.get_db()["orientation_responses"].insert_one({
                "email": email, "name": name,
                "submitted_at": now - timedelta(hours=i),
                "data": _answers(campus=campus, vibe=vibe, nps=nps),
            })


# ── The analysis itself ───────────────────────────────────────────────────────
@pytest.mark.parametrize("raw, expected", [
    ("📍 Bangalore", "Bangalore"),
    ("bangalore", "Bangalore"),
    ("  Kochi ", "Kochi"),
    ("📍Kochi", "Kochi"),
    ("", ""),
    (None, ""),
    ("Mysuru", ""),
])
def test_normalize_campus(raw, expected):
    assert normalize_campus(raw) == expected


def test_summarize_counts_scales_multis_and_nps():
    records = [
        _answers(campus="Bangalore", vibe=10, nps=10),
        _answers(campus="Bangalore", vibe=6, nps=5),
    ]
    out = summarize_orientation(records)

    assert out["count"] == 2
    assert out["headline"]["vibe"] == 8.0          # (10 + 6) / 2
    assert out["headline"]["belonging"] == 8.0
    assert out["headline"]["promoters"] == 1
    assert out["headline"]["detractors"] == 1
    assert out["headline"]["nps"] == 0.0           # 50% promoters − 50% detractors

    questions = {q["key"]: q for s in out["sections"] for q in s["questions"]}
    # Multi-select: both students picked both words.
    assert questions["q1"]["answered"] == 2
    assert questions["q1"]["options"][0]["count"] == 2
    # Single choice.
    assert questions["q3"]["options"][0] == {"label": "🙂 Yes, mostly", "count": 2, "pct": 100.0}
    # Matrix keeps one distribution per statement.
    rows = {r["label"]: r for r in questions["q8"]["rows"]}
    assert rows["Campus life"]["options"][0]["label"] == "Yes"


def test_summarize_empty_cohort_is_safe():
    out = summarize_orientation([])
    assert out["count"] == 0
    assert out["sections"] == []
    assert out["headline"]["vibe"] is None
    assert out["headline"]["nps"] is None


def test_summarize_ignores_unanswered_questions():
    out = summarize_orientation([{"q2": 7}])
    keys = {q["key"] for s in out["sections"] for q in s["questions"]}
    assert keys == {"q2"}


# ── The admin endpoints ───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_campus_summary_splits_bangalore_and_kochi(client):
    await _seed()
    r = await client.get("/admin/api/orientation/campuses")
    assert r.status_code == 200
    body = r.json()

    cards = {c["campus"]: c for c in body["campuses"]}
    assert cards["Bangalore"]["filled"] == 2
    assert cards["Bangalore"]["pending"] == 1        # Dev
    assert cards["Kochi"]["filled"] == 1
    assert cards["Kochi"]["pending"] == 0            # Esha never did the baseline
    assert body["all"]["filled"] == 3
    assert body["all"]["pending"] == 1
    assert cards["Bangalore"]["vibe"] == 8.0


@pytest.mark.asyncio
async def test_report_is_scoped_to_the_chosen_campus(client):
    await _seed()
    r = await client.get("/admin/api/orientation/report", params={"campus": "Kochi"})
    body = r.json()

    assert body["campus"] == "Kochi"
    assert body["count"] == 1
    assert body["coverage"] == {"filled": 1, "pending": 0, "eligible": 1, "pct": 100.0}
    assert body["headline"]["vibe"] == 8.0
    assert [d["dept"] for d in body["departments"]] == ["Department of Law"]


@pytest.mark.asyncio
async def test_report_follows_the_department_filter(client):
    await _seed()
    r = await client.get("/admin/api/orientation/report",
                         params={"campus": "Bangalore", "dept": "Department of Law"})
    body = r.json()
    assert body["count"] == 1                       # Asha only; Bilal is Commerce
    assert body["coverage"]["pending"] == 1         # Dev is Law too


@pytest.mark.asyncio
async def test_filled_and_pending_lists(client):
    await _seed()

    filled = (await client.get("/admin/api/orientation/students",
                               params={"campus": "Bangalore", "group": "filled"})).json()
    assert [s["name"] for s in filled["students"]] == ["Asha", "Bilal"]  # newest first
    assert filled["students"][0]["answered"] > 5
    assert filled["students"][0]["vibe"] == 10

    pending = (await client.get("/admin/api/orientation/students",
                                params={"campus": "Bangalore", "group": "pending"})).json()
    assert [s["name"] for s in pending["students"]] == ["Dev"]
    assert pending["filled"] == 2


@pytest.mark.asyncio
async def test_mail_queues_one_message_per_student(client, monkeypatch):
    await _seed()

    sent: list[tuple[str, str]] = []

    class FakeSender:
        async def __aenter__(self): return self
        async def __aexit__(self, *exc): return None
        async def send(self, msg): sent.append((msg["To"], msg["Subject"]))

    from app import emailer
    monkeypatch.setattr(emailer, "SmtpBatchSender", FakeSender)

    r = await client.post(
        "/admin/api/orientation/mail",
        params={"campus": "Bangalore", "group": "filled"},
        json={"subject": "Thank you", "message": "First para.\n\nSecond para."},
    )
    assert r.status_code == 200
    assert r.json()["total"] == 2

    # BackgroundTasks run once the response is delivered.
    assert [subject for _, subject in sent] == ["Thank you", "Thank you"]
    assert {addr for addr, _ in sent} == {"Asha <a@x.com>", "Bilal <b@x.com>"}

    task = await db.get_db()["admin_tasks"].find_one({"_id": r.json()["task_id"]})
    assert (task["status"], task["sent"], task["failed"]) == ("completed", 2, 0)

    user = await db.get_db()["users"].find_one({"email": "a@x.com"})
    assert user["orientation_mail_count"] == 1


@pytest.mark.asyncio
async def test_mail_needs_a_subject_and_a_body(client):
    await _seed()
    r = await client.post("/admin/api/orientation/mail",
                          params={"campus": "Bangalore"}, json={"subject": "Hi"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_mail_refuses_an_empty_cohort(client):
    await _seed()
    r = await client.post("/admin/api/orientation/mail",
                          params={"campus": "Kochi", "group": "pending"},
                          json={"subject": "Hi", "message": "There"})
    assert r.status_code == 400
    assert r.json()["total"] == 0


@pytest.mark.asyncio
async def test_orientation_endpoints_need_the_survey_admin_cookie(app_with_mock):
    transport = ASGITransport(app=app_with_mock)
    async with AsyncClient(transport=transport, base_url="http://test") as anon:
        for path in ("/admin/api/orientation/campuses",
                     "/admin/api/orientation/report",
                     "/admin/api/orientation/students"):
            assert (await anon.get(path)).status_code == 403
        assert (await anon.post("/admin/api/orientation/mail",
                                json={"subject": "a", "message": "b"})).status_code == 403

    # The orientation admin's cookie is not enough either — this report lives in
    # the survey admin.
    async with AsyncClient(transport=transport, base_url="http://test") as ori:
        ori.cookies.set("orientation_admin_session", "1")
        assert (await ori.get("/admin/api/orientation/report")).status_code == 403


@pytest.mark.asyncio
async def test_mail_body_becomes_paragraphs_and_carries_a_resume_link():
    from app import emailer

    msg = emailer.build_orientation_message(
        "a@x.com", "Asha", "Subject here", "First para.\n\nSecond para.",
        link="http://test/resume/abc?src=reminder", link_label="Open my survey",
        campus="Bangalore",
    )
    html = ""
    text = ""
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            html = part.get_payload(decode=True).decode()
        if part.get_content_type() == "text/plain":
            text = part.get_payload(decode=True).decode()

    assert msg["To"] == "Asha <a@x.com>"
    assert "<p" in html and "First para." in html and "Second para." in html
    assert "http://test/resume/abc?src=reminder" in html
    assert "Bangalore" in html
    assert text.startswith("Dear Asha,")
    assert "Open my survey: http://test/resume/abc?src=reminder" in text
