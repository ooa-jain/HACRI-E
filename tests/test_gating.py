"""
End-to-end gating test using mongomock-motor.

Verifies the server-side Post gating: a user without a submitted Pre
must be rejected with 403 when trying to POST /survey/post.
"""

from __future__ import annotations

from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app import db


@pytest_asyncio.fixture
async def app_with_mock():
    """Replace the app's Mongo client with an in-memory mongomock-motor client."""
    mock = AsyncMongoMockClient()
    db._set_client_for_tests(mock)
    try:
        # Import AFTER patching so any module-level caches are correct
        from app.main import app

        # Initialise indexes WITHOUT the unique email constraint — mongomock's
        # upsert + $setOnInsert interacts badly with unique indexes (it raises
        # DuplicateKeyError even on the existing doc, which is a mongomock
        # limitation, not the real Mongo behaviour).
        await db.init_indexes(allow_duplicate_email=True)
        yield app
    finally:
        db._reset_clients_for_tests()


@pytest_asyncio.fixture
async def client(app_with_mock) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app_with_mock)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _make_pre_payload(name: str, email: str) -> dict:
    """Build a complete pre-submission payload with all Likert items = 3."""
    from app.hacri_e2_compat import SCHEMA
    from app.sections import (
        PRE_BACKGROUND,
        PRE_E11_OPTIONS,
    )

    data: dict = {
        "csrf": "test-csrf-token",
        # Section A
        **{entry[0]: entry[3][0] for entry in PRE_BACKGROUND},
        # Likert items
        **{k: "3" for k in SCHEMA},
        # B11 free text
        "B11": "AI is machines that learn.",
        # C1 multi — pick one
        "C1": "ChatGPT or similar chatbots",
        # C3 multi
        "C3": "Researching topics",
        # E11 scenario
        "E11": PRE_E11_OPTIONS[0],
        "E11_reason": "It's clearly my own work.",
        # H1, H3 scales
        "H1": "3",
        "H3": "3",
        # H2 checkboxes
        "H2": ["Workshops / bootcamps"],
        # H4 select
        "H4": "Yes",
        # H5 free text
        "H5": "How large language models work.",
        # H6 free text
        "H6": "Adaptability and critical thinking.",
    }
    return data


def _make_post_payload(name: str, email: str) -> dict:
    from app.hacri_e2_compat import SCHEMA
    from app.sections import POST_REFLECTION

    data: dict = {
        "csrf": "test-csrf-token",
        **{k: "3" for k in SCHEMA if k[0] in "BDEFG"},
        "H1": POST_REFLECTION[0][3][0],   # first option of H1
        "H2": "3",
        "H3": POST_REFLECTION[2][3][0],   # first option of H3
        "H4": "I plan to use ChatGPT for research.",
    }
    return data


async def _login_and_get_csrf(client: AsyncClient, email: str, name: str) -> str:
    """POST /start and return the CSRF token cookie value."""
    from app.deps import make_csrf_token

    csrf = make_csrf_token()
    client.cookies.set("hacri_csrf", csrf)
    resp = await client.post(
        "/start",
        data={"name": name, "email": email, "csrf": csrf},
        follow_redirects=False,
    )
    assert resp.status_code in (303, 307), f"start failed: {resp.status_code} {resp.text}"
    return csrf


@pytest.mark.asyncio
async def test_full_flow_pre_then_post_succeeds(client: AsyncClient):
    """Happy path: pre → post → results."""
    name = "Alice"
    email = "alice@example.com"
    csrf = await _login_and_get_csrf(client, email, name)
    client.cookies.set("hacri_session", _mint_session_cookie(email, name))

    payload = _make_pre_payload(name, email)
    payload["csrf"] = csrf
    resp = await client.post("/survey/pre", data=payload, follow_redirects=False)
    assert resp.status_code in (303, 307), f"pre submit: {resp.status_code} {resp.text}"
    # Should land on /survey/pre/done
    assert "/survey/pre/done" in resp.headers["location"]

    # Now Post
    payload = _make_post_payload(name, email)
    payload["csrf"] = csrf
    resp = await client.post("/survey/post", data=payload, follow_redirects=False)
    assert resp.status_code in (303, 307), f"post submit: {resp.status_code} {resp.text}"
    # Should land on /results/{slug}
    assert "/results/" in resp.headers["location"]


@pytest.mark.asyncio
async def test_post_blocked_without_pre(client: AsyncClient):
    """A user with no Pre submission must get 403/redirect when accessing Post."""
    name = "Bob"
    email = "bob@example.com"
    csrf = await _login_and_get_csrf(client, email, name)
    client.cookies.set("hacri_session", _mint_session_cookie(email, name))

    # Try POST /survey/post directly without pre
    payload = _make_post_payload(name, email)
    payload["csrf"] = csrf
    resp = await client.post("/survey/post", data=payload, follow_redirects=False)
    assert resp.status_code in (303, 307), f"expected 303/307, got {resp.status_code}"
    assert "/survey/pre" in resp.headers["location"]


@pytest.mark.asyncio
async def test_post_blocked_without_session(client: AsyncClient):
    """No session at all → 401 from get_current_session."""
    payload = _make_post_payload("X", "x@example.com")
    payload["csrf"] = "irrelevant"
    resp = await client.post("/survey/post", data=payload, follow_redirects=False)
    # 307 redirect to / for an unauthenticated request
    assert resp.status_code in (303, 307), f"got {resp.status_code}"


@pytest.mark.asyncio
async def test_idempotent_pre_resubmit(client: AsyncClient):
    """Submitting Pre twice should not change the user's status."""
    name = "Carol"
    email = "carol@example.com"
    csrf = await _login_and_get_csrf(client, email, name)
    client.cookies.set("hacri_session", _mint_session_cookie(email, name))

    payload = _make_pre_payload(name, email)
    payload["csrf"] = csrf
    resp1 = await client.post("/survey/pre", data=payload, follow_redirects=False)
    assert resp1.status_code in (303, 307)

    resp2 = await client.post("/survey/pre", data=payload, follow_redirects=False)
    assert resp2.status_code in (303, 307)

    user = await db.get_user(email)
    assert user is not None
    assert user["status"] == "pre_done"


@pytest.mark.asyncio
async def test_orientation_completed_gating_behavior(client: AsyncClient):
    """Test that when orientation is completed, the pre-done page hides the orientation link,
    and submitting the pre-survey redirects to /survey/pre/done directly even if orientation is enabled."""
    from app.db import set_flag, FLAG_ORIENTATION
    from app.db import get_db

    name = "Dave"
    email = "dave@example.com"
    csrf = await _login_and_get_csrf(client, email, name)
    client.cookies.set("hacri_session", _mint_session_cookie(email, name))

    # Enable orientation flag
    await set_flag(FLAG_ORIENTATION, True)

    # 1. Without orientation completed: pre submit should redirect to /survey/pre/done
    payload = _make_pre_payload(name, email)
    payload["csrf"] = csrf
    resp = await client.post("/survey/pre", data=payload, follow_redirects=False)
    assert resp.status_code in (303, 307)
    assert "/survey/pre/done" in resp.headers["location"]

    resp_done = await client.get("/survey/pre/done")
    assert resp_done.status_code == 200
    assert "Continue to Orientation Survey" in resp_done.text

    # Now simulate user completing orientation
    await get_db()["users"].update_one({"email": email}, {"$set": {"orientation_submitted": True}})
    # And save some fake responses in orientation_responses
    await get_db()["orientation_responses"].insert_one({
        "email": email,
        "submitted_at": "2026-06-25T01:10:00Z",
        "data": {"q2": 8, "school": "School of Commerce"}
    })

    # 2. With orientation completed: pre submit should redirect to /survey/pre/done directly
    resp2 = await client.post("/survey/pre", data=payload, follow_redirects=False)
    assert resp2.status_code in (303, 307)
    assert "/survey/pre/done" in resp2.headers["location"]

    # 3. GET /survey/pre/done should not show the orientation Continue button
    resp3 = await client.get("/survey/pre/done")
    assert resp3.status_code == 200
    assert "Continue to Orientation Survey" not in resp3.text
    assert "You're all done for now" in resp3.text

    # 4. GET /orientation should return already_done=True and saved_responses
    resp4 = await client.get("/orientation")
    assert resp4.status_code == 200
    assert "window._ALREADY_DONE  = true" in resp4.text
    assert "School of Commerce" in resp4.text


@pytest.mark.asyncio
async def test_unified_admin_login_flow(client: AsyncClient):
    """Test that unified admin login correctly routes users based on their credentials."""
    # 1. Unauthenticated GET /admin redirects to /admin/login
    resp = await client.get("/admin", follow_redirects=False)
    assert resp.status_code in (303, 307)
    assert "/admin/login" in resp.headers["location"]

    # 2. Unauthenticated GET /admin/login returns 200
    resp_login = await client.get("/admin/login")
    assert resp_login.status_code == 200
    assert "Sign In" in resp_login.text

    # 3. GET legacy routes redirect to /admin/login
    for path in ["/admin/survey/login", "/admin/orientation/login"]:
        r = await client.get(path, follow_redirects=False)
        assert r.status_code in (303, 307)
        assert "/admin/login" in r.headers["location"]

    # 4. POST with Survey Admin credentials redirects to /admin/survey
    from app.settings import settings
    resp_survey_login = await client.post(
        "/admin/login",
        data={
            "username": settings.survey_admin_username,
            "password": settings.survey_admin_password
        },
        follow_redirects=False
    )
    assert resp_survey_login.status_code in (303, 307)
    assert "/admin/survey" in resp_survey_login.headers["location"]

    # 5. POST with Orientation Admin credentials redirects to /admin/orientation
    resp_ori_login = await client.post(
        "/admin/login",
        data={
            "username": settings.orientation_admin_username,
            "password": settings.orientation_admin_password
        },
        follow_redirects=False
    )
    assert resp_ori_login.status_code in (303, 307)
    assert "/admin/orientation" in resp_ori_login.headers["location"]

    # 6. POST with invalid credentials returns 401
    resp_invalid = await client.post(
        "/admin/login",
        data={
            "username": "wrong",
            "password": "wrong"
        },
        follow_redirects=False
    )
    assert resp_invalid.status_code == 401
    assert "Invalid credentials" in resp_invalid.text


@pytest.mark.asyncio
async def test_admin_send_results_and_auto_login(client: AsyncClient):
    """Test results page auto-login, scorecard access, and admin results email trigger."""
    email = "auto.login@example.com"
    name = "Auto Login Tester"
    from app.db import get_db, STATUS_POST_DONE
    from app.routes.landing import email_to_slug

    db = get_db()
    # Insert pre and post responses
    await db["users"].insert_one({
        "email": email,
        "name": name,
        "status": STATUS_POST_DONE,
    })
    await db["pre_responses"].insert_one({
        "email": email,
        "fields": {
            "B1": "5", "B2": "5", "B3": "5", "B4": "5", "B5": "5",
            "B6": "5", "B7": "5", "B8": "5", "B9": "5", "B10": "5",
            "D1a": "5", "D1b": "5", "D1c": "5", "D1d": "5",
            "D2a": "1", "D2b": "1", "D2c": "1", "D2d": "1",
            "D3a": "5", "D3b": "5", "D3c": "5", "D3d": "5",
            "D4a": "5", "D4b": "5", "D4c": "5", "D4d": "5",
            "E1": "5", "E2": "5", "E3": "5", "E4": "5", "E5": "5",
            "E6": "5", "E7": "5", "E8": "5", "E9": "5", "E10": "5",
            "F1a": "5", "F1b": "5", "F1c": "5", "F1d": "5",
            "F2a": "5", "F2b": "5", "F2c": "5", "F2d": "5",
            "F3a": "5", "F3b": "5", "F3c": "5", "F3d": "5",
            "F4a": "5", "F4b": "5", "F4c": "5", "F4d": "5",
            "G1a": "5", "G1b": "5", "G1c": "5",
            "G2a": "5", "G2b": "5", "G2c": "5",
            "G3a": "5", "G3b": "5", "G3c": "5",
            "G4a": "5", "G4b": "5", "G4c": "5", "G4d": "5",
        }
    })
    await db["post_responses"].insert_one({
        "email": email,
        "fields": {
            "B1": "5", "B2": "5", "B3": "5", "B4": "5", "B5": "5",
            "B6": "5", "B7": "5", "B8": "5", "B9": "5", "B10": "5",
            "D1a": "5", "D1b": "5", "D1c": "5", "D1d": "5",
            "D2a": "1", "D2b": "1", "D2c": "1", "D2d": "1",
            "D3a": "5", "D3b": "5", "D3c": "5", "D3d": "5",
            "D4a": "5", "D4b": "5", "D4c": "5", "D4d": "5",
            "E1": "5", "E2": "5", "E3": "5", "E4": "5", "E5": "5",
            "E6": "5", "E7": "5", "E8": "5", "E9": "5", "E10": "5",
            "F1a": "5", "F1b": "5", "F1c": "5", "F1d": "5",
            "F2a": "5", "F2b": "5", "F2c": "5", "F2d": "5",
            "F3a": "5", "F3b": "5", "F3c": "5", "F3d": "5",
            "F4a": "5", "F4b": "5", "F4c": "5", "F4d": "5",
            "G1a": "5", "G1b": "5", "G1c": "5",
            "G2a": "5", "G2b": "5", "G2c": "5",
            "G3a": "5", "G3b": "5", "G3c": "5",
            "G4a": "5", "G4b": "5", "G4c": "5", "G4d": "5",
            "H1": "Significantly increased", "H2": 1, "H3": "Understanding what AI is", "H4": "reflect"
        }
    })

    slug = email_to_slug(email)

    # 1. Access results page WITHOUT session cookie -> redirects and issues cookie
    resp1 = await client.get(f"/results/{slug}", follow_redirects=False)
    assert resp1.status_code == 303
    assert f"/results/{slug}" in resp1.headers["location"]
    # Verify set-cookie is returned
    assert "hacri_session" in resp1.headers.get("set-cookie", "")

    # 2. Access with redirection -> 200 OK
    resp2 = await client.get(f"/results/{slug}", follow_redirects=True)
    assert resp2.status_code == 200
    assert "Your HACRI-E Results" in resp2.text

    # 3. Access scorecard CSV -> 200 OK
    resp3 = await client.get(f"/results/{slug}/scorecard.csv")
    assert resp3.status_code == 200
    assert "text/csv" in resp3.headers["content-type"]

    # 4. Trigger send-results as unauthorized -> 403
    resp_unauth = await client.post(f"/admin/api/send-results/{email}")
    assert resp_unauth.status_code == 403

    # 5. Trigger send-results as admin -> 200 OK
    client.cookies.set("survey_admin_session", "1")
    resp_auth = await client.post(f"/admin/api/send-results/{email}")
    assert resp_auth.status_code == 200
    assert resp_auth.json()["ok"] is True


@pytest.mark.asyncio
async def test_pre_survey_disabled_flow(client: AsyncClient):
    """Test user navigation flow when pre-survey is disabled, routing straightly to orientation/post."""
    from app.db import set_flag, FLAG_PRE_SURVEY, FLAG_ORIENTATION
    from app.deps import make_csrf_token

    # 1. Disable pre-survey, enable orientation
    await set_flag(FLAG_PRE_SURVEY, False)
    await set_flag(FLAG_ORIENTATION, True)

    csrf = make_csrf_token()
    client.cookies.set("hacri_csrf", csrf)

    # 2. Register -> should redirect straightly to /orientation
    email = "bypass.pre@example.com"
    resp = await client.post(
        "/start",
        data={
            "name": "Bypass Pre Tester",
            "email": email,
            "program": "Engineering",
            "csrf": csrf,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/orientation"

    # 3. Accessing /survey/pre manually should redirect to /orientation
    resp_pre = await client.get("/survey/pre", follow_redirects=False)
    assert resp_pre.status_code == 303
    assert resp_pre.headers["location"] == "/orientation"

    # 4. Accessing /survey/post manually without submitting orientation should redirect to /orientation
    resp_post = await client.get("/survey/post", follow_redirects=False)
    assert resp_post.status_code == 303
    assert resp_post.headers["location"] == "/orientation"

    # 5. Now, disable both pre-survey and orientation
    await set_flag(FLAG_PRE_SURVEY, False)
    await set_flag(FLAG_ORIENTATION, False)

    # 6. Accessing /survey/pre manually should redirect to /survey/post
    resp_pre_post = await client.get("/survey/pre", follow_redirects=False)
    assert resp_pre_post.status_code == 303
    assert resp_pre_post.headers["location"] == "/survey/post"

    # 7. Accessing /survey/post manually should load successfully (200 OK)
    resp_post_ok = await client.get("/survey/post", follow_redirects=False)
    assert resp_post_ok.status_code == 200
    assert "Survey 2" in resp_post_ok.text

    # Cleanup flags for other tests
    await set_flag(FLAG_PRE_SURVEY, True)
    await set_flag(FLAG_ORIENTATION, False)


@pytest.mark.asyncio
async def test_completed_redirects(client: AsyncClient):
    """Test that users who have fully completed the survey (STATUS_POST_DONE) are redirected directly to results."""
    from app.db import get_db, STATUS_POST_DONE
    from app.routes.landing import email_to_slug
    from app.deps import make_csrf_token

    email = "fully.completed.redirect@example.com"
    name = "Redirect Tester"
    slug = email_to_slug(email)

    db = get_db()
    # Insert completed user
    await db["users"].insert_one({
        "email": email,
        "name": name,
        "status": STATUS_POST_DONE,
    })

    # Set up session & CSRF cookies
    session_cookie = _mint_session_cookie(email, name)
    client.cookies.set("hacri_session", session_cookie)
    csrf = make_csrf_token()
    client.cookies.set("hacri_csrf", csrf)

    # 1. Accessing /survey/pre should redirect to /results/{slug}
    resp_pre = await client.get("/survey/pre", follow_redirects=False)
    assert resp_pre.status_code == 303
    assert resp_pre.headers["location"] == f"/results/{slug}"

    # 2. Accessing /survey/post should redirect to /results/{slug}
    resp_post = await client.get("/survey/post", follow_redirects=False)
    assert resp_post.status_code == 303
    assert resp_post.headers["location"] == f"/results/{slug}"

    # 3. Accessing /orientation should redirect to /results/{slug}
    resp_ori = await client.get("/orientation", follow_redirects=False)
    assert resp_ori.status_code == 303
    assert resp_ori.headers["location"] == f"/results/{slug}"

    # 4. Posting to /start (re-registering) should redirect to /results/{slug}
    resp_start = await client.post(
        "/start",
        data={
            "name": name,
            "email": email,
            "program": "Engineering",
            "csrf": csrf,
        },
        follow_redirects=False,
    )
    assert resp_start.status_code == 303
    assert resp_start.headers["location"] == f"/results/{slug}"


def _mint_session_cookie(email: str, name: str) -> str:
    from app.deps import _sign
    return _sign({"email": email, "name": name})


@pytest.mark.asyncio
async def test_post_survey_disabled_gate(client: AsyncClient):
    """Test that post-survey is locked when post_survey_enabled is False."""
    from app.db import get_db, set_flag, STATUS_PRE_DONE
    from app.deps import make_csrf_token

    email = "disabled.post.test@example.com"
    name = "Post Disabled Tester"

    db = get_db()
    await db["users"].insert_one({
        "email": email,
        "name": name,
        "status": STATUS_PRE_DONE,
    })

    # Set up session & cookies
    session_cookie = _mint_session_cookie(email, name)
    client.cookies.set("hacri_session", session_cookie)
    csrf = make_csrf_token()
    client.cookies.set("hacri_csrf", csrf)

    # Disable post survey
    await set_flag("post_survey_enabled", False)

    # 1. GET /survey/post should render post_locked.html (which contains survey closed text)
    resp_get = await client.get("/survey/post")
    assert resp_get.status_code == 200
    assert "Post-Workshop Survey Closed" in resp_get.text

    # 2. POST /survey/post should return 400
    resp_post = await client.post(
        "/survey/post",
        data={"csrf": csrf},
    )
    assert resp_post.status_code == 400
    assert "Post survey is closed" in resp_post.text

    # Clean up
    await set_flag("post_survey_enabled", True)


@pytest.mark.asyncio
async def test_post_survey_delay_gate(client: AsyncClient):
    """Test that post-survey is locked when delay gating is active."""
    from app.db import get_db, set_flag, STATUS_PRE_DONE
    from app.deps import make_csrf_token
    from datetime import datetime, timezone, timedelta

    email = "delay.post.test@example.com"
    name = "Post Delay Tester"

    # Set pre_submitted_at to 1 hour ago
    pre_time = datetime.now(timezone.utc) - timedelta(hours=1)

    db = get_db()
    await db["users"].insert_one({
        "email": email,
        "name": name,
        "status": STATUS_PRE_DONE,
        "pre_submitted_at": pre_time,
    })

    # Set up session & cookies
    session_cookie = _mint_session_cookie(email, name)
    client.cookies.set("hacri_session", session_cookie)
    csrf = make_csrf_token()
    client.cookies.set("hacri_csrf", csrf)

    # Set delay to 1 day (24 hours)
    from app.db import FLAGS, _now
    await get_db()[FLAGS].update_one(
        {"key": "post_delay_days"},
        {"$set": {"key": "post_delay_days", "value": 1, "updated_at": _now()}},
        upsert=True,
    )

    # 1. GET /survey/post should render post_locked.html (which contains Locked text)
    resp_get = await client.get("/survey/post")
    assert resp_get.status_code == 200
    assert "Post-Workshop Survey Locked" in resp_get.text
    assert "Remaining Delay" in resp_get.text

    # 2. POST /survey/post should return 400
    resp_post = await client.post(
        "/survey/post",
        data={"csrf": csrf},
    )
    assert resp_post.status_code == 400
    assert "Post survey is locked due to start delay gating" in resp_post.text

    # Clean up delay setting
    await get_db()[FLAGS].update_one(
        {"key": "post_delay_days"},
        {"$set": {"key": "post_delay_days", "value": 0, "updated_at": _now()}},
        upsert=True,
    )


@pytest.mark.asyncio
async def test_landing_page_post_survey_disabled(client: AsyncClient):
    """Test that when post survey is disabled, the landing page shows closed/waiting text instead of active button."""
    from app.db import get_db, set_flag, STATUS_PRE_DONE
    from app.deps import make_csrf_token

    email = "landing.post.disabled@example.com"
    name = "Landing Post Disabled Tester"

    db = get_db()
    await db["users"].insert_one({
        "email": email,
        "name": name,
        "status": STATUS_PRE_DONE,
    })

    # Set up session & cookies
    session_cookie = _mint_session_cookie(email, name)
    client.cookies.set("hacri_session", session_cookie)
    csrf = make_csrf_token()
    client.cookies.set("hacri_csrf", csrf)

    # 1. With post survey enabled: should show "Continue to Survey 2 →"
    await set_flag("post_survey_enabled", True)
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "Continue to Survey 2" in resp.text

    # 2. With post survey disabled: should NOT show the active button, but the closed/waiting text
    await set_flag("post_survey_enabled", False)
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "Continue to Survey 2" not in resp.text
    assert "Survey 2 is not open yet" in resp.text

    # Clean up
    await set_flag("post_survey_enabled", True)


@pytest.mark.asyncio
async def test_admin_department_filtering(client: AsyncClient):
    """Test that cohort charts and CSV export endpoints correctly handle the department filter."""
    from app.db import get_db, STATUS_POST_DONE
    from app.deps import make_csrf_token

    db = get_db()
    # Insert two users in different departments
    await db["users"].insert_one({
        "email": "cs.student@example.com",
        "name": "CS Student",
        "program": "Department of Computer Science and IT",
        "status": STATUS_POST_DONE,
    })
    await db["users"].insert_one({
        "email": "law.student@example.com",
        "name": "Law Student",
        "program": "Department of Law",
        "status": STATUS_POST_DONE,
    })

    # Set up admin session
    client.cookies.set("survey_admin_session", "1")

    # 1. Access cohort chart without filter -> returns 200 OK (will fall back to placeholder in test if Matplotlib is mocked or there's no data, but endpoint should respond)
    resp_chart = await client.get("/admin/cohort.png")
    assert resp_chart.status_code == 200

    # 2. Access cohort chart with filter -> returns 200 OK
    resp_chart_filtered = await client.get("/admin/cohort.png?dept=Department of Law")
    assert resp_chart_filtered.status_code == 200

    # 3. Access export-cohort CSV without filter -> returns 200 OK
    resp_csv = await client.get("/admin/survey/export-cohort")
    assert resp_csv.status_code == 200
    assert "HACRI_E2_Cohort_Export.csv" in resp_csv.headers["content-disposition"]

    # 4. Access export-cohort CSV with department filter -> returns 200 OK with custom filename
    resp_csv_filtered = await client.get("/admin/survey/export-cohort?dept=Department of Law")
    assert resp_csv_filtered.status_code == 200
    assert "HACRI_E2_Cohort_Export_DepartmentofLaw.csv" in resp_csv_filtered.headers["content-disposition"]