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

    # Call pre-pending reminder (Baseline)
    resp_pre = await client.post("/admin/api/alert/pre-pending?dept=Dept of AI")
    assert resp_pre.status_code == 200
    res_data = resp_pre.json()
    assert res_data["sent"] == 1
    assert res_data["total_pending"] == 1

    # Call post-pending reminder (Post-Workshop)
    resp_post = await client.post("/admin/api/alert/post-pending?dept=Dept of AI")
    assert resp_post.status_code == 200
    res_data = resp_post.json()
    assert res_data["sent"] == 1
    assert res_data["total_pending"] == 1


@pytest.mark.asyncio
async def test_auto_reminder_worker(app_with_mock):
    import asyncio
    from unittest.mock import AsyncMock, patch
    from datetime import datetime, timezone, timedelta
    from app.db import get_db, STATUS_PRE_DONE, FLAGS
    from app.routes.admin import run_auto_reminder_worker

    database = get_db()
    
    # Enable auto reminders in DB flags
    await database[FLAGS].insert_one({"key": "auto_reminders_enabled", "enabled": True})
    await database[FLAGS].insert_one({"key": "auto_reminder_delay_days", "value": "5"})

    now = datetime.now(timezone.utc)
    # User 1: Registered 6 days ago (should receive reminder)
    await database["users"].insert_one({
        "email": "eligible@example.com",
        "name": "Eligible Student",
        "created_at": now - timedelta(days=6),
        "status": "not_started"
    })
    
    # User 2: Registered 2 days ago (not eligible yet)
    await database["users"].insert_one({
        "email": "noteligible@example.com",
        "name": "Young Student",
        "created_at": now - timedelta(days=2),
        "status": "not_started"
    })

    # User 3: Registered 6 days ago but already sent pre reminder
    await database["users"].insert_one({
        "email": "alreadysent@example.com",
        "name": "Sent Student",
        "created_at": now - timedelta(days=6),
        "status": "not_started",
        "pre_reminder_sent_at": now - timedelta(days=1)
    })

    # User 4: Registered 6 days ago and already completed pre-survey
    await database["users"].insert_one({
        "email": "predone_eligible@example.com",
        "name": "Pre Done Eligible Student",
        "created_at": now - timedelta(days=6),
        "status": STATUS_PRE_DONE
    })

    # Mock emailer.send_pre_reminder_email
    mock_send = AsyncMock()
    with patch("app.emailer.send_pre_reminder_email", mock_send):
        # We want run_auto_reminder_worker to run once and then exit.
        # We can patch asyncio.sleep to raise a CancelledError or stop execution.
        with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
            try:
                await run_auto_reminder_worker()
            except asyncio.CancelledError:
                pass
    
    # It should have sent exactly 1 email (to eligible@example.com)
    assert mock_send.call_count == 1
    args, kwargs = mock_send.call_args
    assert args[0] == "eligible@example.com"
    assert args[1] == "Eligible Student"

    # The database record should be updated with pre_reminder_sent_at
    u = await database["users"].find_one({"email": "eligible@example.com"})
    assert u.get("pre_reminder_sent_at") is not None

