import pytest
import pytest_asyncio
from typing import AsyncIterator
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app import db
from app.db import STATUS_PRE_DONE

@pytest_asyncio.fixture
async def app_with_mock():
    mock = AsyncMongoMockClient()
    db._set_client_for_tests(mock)
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

@pytest.mark.asyncio
async def test_alert_reminders(client: AsyncClient):
    # Insert testing users
    from app.db import get_db
    database = get_db()
    
    # 1. Registered but not started pre-survey
    await database["users"].insert_one({
        "email": "notstarted@example.com",
        "name": "Not Started Student",
        "program": "Dept of AI",
        "status": "not_started",
    })
    
    # 2. Completed pre-survey, pending post-survey
    await database["users"].insert_one({
        "email": "predone@example.com",
        "name": "Pre Done Student",
        "program": "Dept of AI",
        "status": STATUS_PRE_DONE,
    })
    
    # 3. Done with both
    await database["users"].insert_one({
        "email": "bothdone@example.com",
        "name": "Both Done Student",
        "program": "Dept of Law",
        "status": "post_done",
    })

    # Unauthorized access check
    resp_unauth = await client.post("/admin/api/alert/pre-pending")
    assert resp_unauth.status_code == 403

    # Authenticate as survey admin
    client.cookies.set("survey_admin_session", "1")

    # Call pre-pending reminder (Baseline). Sending happens in a background task
    # over a single (dry-run) SMTP batch; the response reports the queued count
    # and a task id whose live progress can be polled.
    resp_pre = await client.post("/admin/api/alert/pre-pending?dept=Dept of AI")
    assert resp_pre.status_code == 200
    res_data = resp_pre.json()
    assert res_data["total_pending"] == 1
    status_pre = await client.get(f"/admin/api/alert/status/{res_data['task_id']}")
    assert status_pre.status_code == 200
    sd = status_pre.json()
    assert sd["status"] == "completed"
    assert sd["sent"] == 1
    assert sd["failed"] == 0

    # Call post-pending reminder (Post-Workshop)
    resp_post = await client.post("/admin/api/alert/post-pending?dept=Dept of AI")
    assert resp_post.status_code == 200
    res_data = resp_post.json()
    assert res_data["total_pending"] == 1
    status_post = await client.get(f"/admin/api/alert/status/{res_data['task_id']}")
    assert status_post.status_code == 200
    sd = status_post.json()
    assert sd["status"] == "completed"
    assert sd["sent"] == 1
    assert sd["failed"] == 0

    # The recipient's reminder count should have been incremented.
    updated = await database["users"].find_one({"email": "notstarted@example.com"})
    assert updated.get("pre_reminder_count", 0) == 1


@pytest.mark.asyncio
async def test_auto_reminder_worker(app_with_mock):
    """Daily recurring reminders: first send after the delay, then re-send once
    per day until the student completes the survey (dry-run send in tests)."""
    from datetime import datetime, timezone, timedelta  # noqa: F401
    from app.db import get_db, STATUS_PRE_DONE, FLAGS
    from app.routes.admin import process_auto_reminders

    database = get_db()

    # Enable auto reminders: first reminder after 5 days, then every 1 day.
    await database[FLAGS].insert_one({"key": "auto_reminders_enabled", "enabled": True})
    await database[FLAGS].insert_one({"key": "auto_reminder_delay_days", "value": "5"})
    await database[FLAGS].insert_one({"key": "auto_reminder_repeat_days", "value": "1"})

    now = datetime.now(timezone.utc)

    # Registered 6 days ago, never reminded → DUE (first reminder).
    await database["users"].insert_one({
        "email": "eligible@example.com", "name": "Eligible Student",
        "created_at": now - timedelta(days=6), "status": "not_started",
    })
    # Registered 2 days ago → NOT yet due (inside the 5-day delay).
    await database["users"].insert_one({
        "email": "toonew@example.com", "name": "Young Student",
        "created_at": now - timedelta(days=2), "status": "not_started",
    })
    # Registered 6 days ago, reminded 3h ago → NOT due (within the daily window).
    await database["users"].insert_one({
        "email": "recent@example.com", "name": "Recent Student",
        "created_at": now - timedelta(days=6), "status": "not_started",
        "pre_reminder_sent_at": now - timedelta(hours=3), "pre_reminder_count": 1,
    })
    # Registered 6 days ago, reminded 2 days ago → DUE again (daily resend).
    await database["users"].insert_one({
        "email": "yesterday@example.com", "name": "Yesterday Student",
        "created_at": now - timedelta(days=6), "status": "not_started",
        "pre_reminder_sent_at": now - timedelta(days=2), "pre_reminder_count": 1,
    })
    # Completed baseline already (no pre_submitted_at) → not a pre candidate.
    await database["users"].insert_one({
        "email": "predone@example.com", "name": "Pre Done Student",
        "created_at": now - timedelta(days=6), "status": STATUS_PRE_DONE,
    })

    result = await process_auto_reminders()

    # Exactly the two DUE baseline students should have been reminded.
    assert result["enabled"] is True
    assert result["pre"]["sent"] == 2
    assert result["pre"]["failed"] == 0
    assert result["post"]["sent"] == 0

    # First-time reminder recorded a stamp and a count.
    u = await database["users"].find_one({"email": "eligible@example.com"})
    assert isinstance(u.get("pre_reminder_sent_at"), datetime)
    assert u.get("pre_reminder_count") == 1

    # Daily resend bumped the count and refreshed the stamp.
    y = await database["users"].find_one({"email": "yesterday@example.com"})
    assert y.get("pre_reminder_count") == 2
    stamp = y.get("pre_reminder_sent_at")
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    assert stamp > now - timedelta(minutes=1)

    # Recently reminded and too-new students were left untouched.
    r = await database["users"].find_one({"email": "recent@example.com"})
    assert r.get("pre_reminder_count") == 1
    tn = await database["users"].find_one({"email": "toonew@example.com"})
    assert tn.get("pre_reminder_sent_at") is None


@pytest.mark.asyncio
async def test_custom_segment_alert(client: AsyncClient):
    """Custom send picks the right reminder kind per student and skips finished ones."""
    from app.db import get_db, STATUS_PRE_DONE
    database = get_db()

    await database["users"].insert_one({
        "email": "clickpre@example.com", "name": "Clicked Pre",
        "program": "Dept of AI", "status": "not_started",
    })
    await database["users"].insert_one({
        "email": "clickpost@example.com", "name": "Clicked Post",
        "program": "Dept of AI", "status": STATUS_PRE_DONE,
    })
    await database["users"].insert_one({
        "email": "alldone@example.com", "name": "All Done",
        "program": "Dept of AI", "status": "post_done",
    })

    client.cookies.set("survey_admin_session", "1")
    resp = await client.post("/admin/api/alert/custom", json={
        "emails": ["clickpre@example.com", "clickpost@example.com", "alldone@example.com"],
    })
    assert resp.status_code == 200
    d = resp.json()
    assert d["total_pending"] == 2  # post_done student skipped

    status = (await client.get(f"/admin/api/alert/status/{d['task_id']}")).json()
    assert status["status"] == "completed"
    assert status["sent"] == 2

    # Kind chosen per student: not_started got a PRE stamp, pre_done a POST stamp.
    u1 = await database["users"].find_one({"email": "clickpre@example.com"})
    assert u1.get("pre_reminder_count") == 1 and not u1.get("post_reminder_count")
    u2 = await database["users"].find_one({"email": "clickpost@example.com"})
    assert u2.get("post_reminder_count") == 1 and not u2.get("pre_reminder_count")
    u3 = await database["users"].find_one({"email": "alldone@example.com"})
    assert not u3.get("pre_reminder_count") and not u3.get("post_reminder_count")


@pytest.mark.asyncio
async def test_auto_reminder_disabled_sends_nothing(app_with_mock):
    from datetime import datetime, timezone, timedelta
    from app.db import get_db
    from app.routes.admin import process_auto_reminders

    database = get_db()
    now = datetime.now(timezone.utc)
    await database["users"].insert_one({
        "email": "eligible@example.com", "name": "Eligible Student",
        "created_at": now - timedelta(days=6), "status": "not_started",
    })

    result = await process_auto_reminders()
    assert result["enabled"] is False
    u = await database["users"].find_one({"email": "eligible@example.com"})
    assert u.get("pre_reminder_sent_at") is None


@pytest.mark.asyncio
async def test_survey_users_api_timestamps(client: AsyncClient):
    from app.db import get_db
    from datetime import datetime, timezone
    database = get_db()
    
    # Insert a user with explicit registration and submission times
    created_val = datetime(2026, 7, 20, 10, 0, 0, tzinfo=timezone.utc)
    pre_val = datetime(2026, 7, 20, 11, 0, 0, tzinfo=timezone.utc)
    post_val = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)
    
    await database["users"].insert_one({
        "email": "timeline_student@example.com",
        "name": "Timeline Student",
        "program": "Dept of CS",
        "status": "post_done",
        "created_at": created_val,
        "pre_submitted_at": pre_val,
        "post_submitted_at": post_val,
    })

    # Unauthorized access check
    resp_unauth = await client.get("/admin/api/survey/users")
    assert resp_unauth.status_code == 403

    # Authenticate as survey admin
    client.cookies.set("survey_admin_session", "1")

    # Get users list for Dept of CS
    resp = await client.get("/admin/api/survey/users?dept=Dept of CS")
    assert resp.status_code == 200
    users_list = resp.json()
    assert len(users_list) == 1
    
    student = users_list[0]
    assert student["email"] == "timeline_student@example.com"
    assert "created_at" in student
    assert "created_at_iso" in student
    assert "pre_submitted_at_iso" in student
    assert "post_submitted_at_iso" in student
    
    # Verify ISO formatting correctness
    assert student["created_at_iso"].startswith("2026-07-20T10:00:00")
    assert student["pre_submitted_at_iso"].startswith("2026-07-20T11:00:00")
    assert student["post_submitted_at_iso"].startswith("2026-07-20T12:00:00")

