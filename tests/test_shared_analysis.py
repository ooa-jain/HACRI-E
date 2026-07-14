"""
Tests for shared department-wise analysis page and export endpoints.
"""
from __future__ import annotations
from typing import AsyncIterator
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app import db
from app.db import get_db, STATUS_POST_DONE
from app.routes.shared_analysis import get_dept_token

@pytest_asyncio.fixture
async def app_with_mock():
    """Replace the app's Mongo client with an in-memory mongomock-motor client."""
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
async def test_shared_analysis_access_and_exports(client: AsyncClient):
    db = get_db()
    dept = "Department of Physics"
    
    # 1. Insert fake users in this department
    await db["users"].insert_one({
        "email": "phys.student@example.com",
        "name": "Physics Student",
        "program": dept,
        "status": STATUS_POST_DONE,
    })
    
    # Generate valid token
    valid_token = get_dept_token(dept)
    invalid_token = "wrongtoken123"
    
    # 2. Access /shared/analysis with INVALID token -> 403 Forbidden
    resp = await client.get(f"/shared/analysis?dept={dept}&token={invalid_token}")
    assert resp.status_code == 403
    
    # 3. Access /shared/analysis with VALID token -> 200 OK
    resp_ok = await client.get(f"/shared/analysis?dept={dept}&token={valid_token}")
    assert resp_ok.status_code == 200
    assert "Physics" in resp_ok.text
    
    # 4. Access /shared/analysis/export-excel with INVALID token -> 403
    resp_excel_fail = await client.get(f"/shared/analysis/export-excel?dept={dept}&token={invalid_token}")
    assert resp_excel_fail.status_code == 403
    
    # 5. Access /shared/analysis/export-excel with VALID token -> 200 OK
    resp_excel_ok = await client.get(f"/shared/analysis/export-excel?dept={dept}&token={valid_token}")
    assert resp_excel_ok.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in resp_excel_ok.headers["content-type"]
    
    # 6. Access /shared/analysis/download-ppt with INVALID token -> 403
    resp_ppt_fail = await client.get(f"/shared/analysis/download-ppt?dept={dept}&token={invalid_token}")
    assert resp_ppt_fail.status_code == 403
    
    # 7. Access /shared/analysis/download-ppt with VALID token -> 200 OK
    resp_ppt_ok = await client.get(f"/shared/analysis/download-ppt?dept={dept}&token={valid_token}")
    assert resp_ppt_ok.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.presentationml.presentation" in resp_ppt_ok.headers["content-type"]

    # 8. Test charts endpoints with invalid token -> 403
    for chart_type in ["cohort", "histograms", "h1_histogram"]:
        r = await client.get(f"/shared/analysis/charts/{chart_type}.png?dept={dept}&token={invalid_token}")
        assert r.status_code == 403

    # 9. Test charts endpoints with valid token -> 200 OK
    for chart_type in ["cohort", "histograms", "h1_histogram"]:
        r = await client.get(f"/shared/analysis/charts/{chart_type}.png?dept={dept}&token={valid_token}")
        assert r.status_code == 200
        assert "image/png" in r.headers["content-type"]
