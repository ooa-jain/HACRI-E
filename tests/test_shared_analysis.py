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


@pytest.mark.asyncio
async def test_shared_departments_directory(client: AsyncClient):
    db = get_db()
    dept = "Department of Chemistry"
    
    # Insert a user to make the department active
    await db["users"].insert_one({
        "email": "chem.student@example.com",
        "name": "Chemistry Student",
        "program": dept,
        "status": STATUS_POST_DONE,
    })
    
    # The directory is a generated link now — the bare URL is refused.
    assert (await client.get("/shared/departments")).status_code == 422

    from app.routes.shared_analysis import get_directory_token
    resp = await client.get(f"/shared/departments?token={get_directory_token()}")
    assert resp.status_code == 200
    assert "Department of Chemistry" in resp.text
    
    # Verify pre/post survey link components are present in the page
    token_pre = get_dept_token(dept, "pre")
    token_post = get_dept_token(dept, "post")
    
    assert f"token={token_pre}" in resp.text
    assert f"token={token_post}" in resp.text


@pytest.mark.asyncio
async def test_overall_department_analysis(client: AsyncClient):
    db = get_db()
    
    # 1. Add users from two departments with pre-survey responses
    await db["users"].insert_one({
        "email": "user1@dept1.com", "name": "User One", "program": "Engineering", "status": STATUS_POST_DONE
    })
    await db["users"].insert_one({
        "email": "user2@dept2.com", "name": "User Two", "program": "Business", "status": STATUS_POST_DONE
    })
    
    sample_fields_high = {"B1": 5, "B2": 5, "D1a": 5, "D1b": 5}
    sample_fields_low = {"B1": 1, "B2": 1, "D1a": 1, "D1b": 1}

    await db["pre_responses"].insert_one({"email": "user1@dept1.com", "fields": sample_fields_high})
    await db["pre_responses"].insert_one({"email": "user2@dept2.com", "fields": sample_fields_low})

    # 2. Verify Overall Token Access
    token_overall_pre = get_dept_token("Overall", "pre")
    token_overall_post = get_dept_token("Overall", "post")

    resp_pre = await client.get(f"/shared/analysis?dept=Overall&token={token_overall_pre}&type=pre")
    assert resp_pre.status_code == 200
    assert "Overall" in resp_pre.text
    assert "Department-Wise AI Literacy & AI Readiness Bar Graph" in resp_pre.text

    resp_post = await client.get(f"/shared/analysis?dept=Overall&token={token_overall_post}&type=post")
    assert resp_post.status_code == 200

    # 3. Test Admin Dept Analysis API with cookie auth
    client.cookies.set("survey_admin_session", "1")
    resp_api = await client.get("/admin/api/survey/dept-analysis")
    assert resp_api.status_code == 200
    data = resp_api.json()
    
    assert data["overall"]["dept"] == "Overall"
    assert data["overall"]["registered"] == 2
    assert "rankings" in data
    assert data["rankings"]["lit_pre"]["highest"]["dept"] == "Engineering"
    assert data["rankings"]["lit_pre"]["lowest"]["dept"] == "Business"


@pytest.mark.asyncio
async def test_calendar_date_analysis(client: AsyncClient):
    db = get_db()
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    await db["users"].insert_one({
        "email": "student1@eng.com", "name": "Eng Student", "program": "Engineering", "status": STATUS_POST_DONE
    })
    await db["pre_responses"].insert_one({
        "email": "student1@eng.com", "submitted_at": now, "fields": {"B1": 4}
    })

    client.cookies.set("survey_admin_session", "1")
    resp = await client.get("/admin/api/survey/date-analysis")
    assert resp.status_code == 200
    data = resp.json()

    assert "overall" in data
    assert "departments" in data
    assert "highlights" in data
    assert data["overall"]["total_responses"] == 1
    assert data["overall"]["today_total"] == 1
    assert data["departments"][0]["dept"] == "Engineering"
    assert data["departments"][0]["start_date"] == now.strftime("%Y-%m-%d")
    assert data["departments"][0]["max_day"]["total"] == 1


