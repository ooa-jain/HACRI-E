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
