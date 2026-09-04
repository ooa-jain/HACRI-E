"""
Signing in takes two steps, and an address can be shut out by hand.

The password alone used to open the admin portal, which put every student's
contact details behind one string that lives in a .env file. It is now the
first of two steps: get it right and a code goes to the admin mailbox, and
only that code finishes the sign-in.
"""

from __future__ import annotations

from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app import db
from app.settings import settings

# The portal answers behind ADMIN_PATH, so that is the door to knock on.
ADMIN = settings.admin_path

SURVEY = settings.survey_admin_username
SURVEY_PW = settings.survey_admin_password
ORI = settings.orientation_admin_username
ORI_PW = settings.orientation_admin_password

FROM = {"X-Forwarded-For": "203.0.113.44"}


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


async def _password_step(client, username=SURVEY, password=SURVEY_PW, **kw):
    return await client.post(ADMIN + "/login",
                             data={"username": username, "password": password},
                             headers=FROM, follow_redirects=False, **kw)


async def _code_step(client, code, username=SURVEY, **kw):
    return await client.post(
        ADMIN + "/login",
        data={"username": username, "password": code, "stage": "otp"},
        headers=FROM, follow_redirects=False, **kw)


async def _issued_code(username=SURVEY) -> str:
    doc = await db.get_db()["admin_otps"].find_one({"username": username})
    assert doc, "no code was issued"
    return doc["otp"]


# ── The password is only the first step ──────────────────────────────────────

@pytest.mark.asyncio
async def test_the_right_password_asks_for_the_code_instead_of_signing_in(client):
    resp = await _password_step(client)

    assert resp.status_code == 200
    assert "Enter one-time password" in resp.text
    # Nothing that opens the portal has been handed out yet.
    assert "survey_admin_session" not in resp.cookies
    assert "admin_login_pending" in resp.cookies


@pytest.mark.asyncio
async def test_the_code_finishes_the_sign_in(client):
    await _password_step(client)
    resp = await _code_step(client, await _issued_code())

    assert resp.status_code == 303
    assert resp.headers["location"] == ADMIN + "/survey"
    assert resp.cookies.get("survey_admin_session") == "1"

    # Both halves are named in the log, so a sign-in can be told from a try.
    ev = (await db.list_login_events())[0]
    assert ev["outcome"] == db.LOGIN_OK
    assert "password and emailed code" in ev["note"]


@pytest.mark.asyncio
async def test_the_orientation_portal_takes_the_same_two_steps(client):
    await _password_step(client, username=ORI, password=ORI_PW)
    resp = await _code_step(client, await _issued_code(ORI), username=ORI)

    assert resp.status_code == 303
    assert resp.headers["location"] == ADMIN + "/orientation"
    assert resp.cookies.get("orientation_admin_session") == "1"


@pytest.mark.asyncio
async def test_a_code_on_its_own_is_not_a_login(client):
    """The whole point of a second step is that it is a *second* step."""
    await _password_step(client)
    code = await _issued_code()

    # A browser that never passed the password carries no pending cookie.
    async with AsyncClient(transport=ASGITransport(app=client._transport.app),
                           base_url="http://test") as stranger:
        resp = await stranger.post(
            ADMIN + "/login",
            data={"username": SURVEY, "password": code, "stage": "otp"},
            headers=FROM, follow_redirects=False)

    assert resp.status_code == 401
    assert "survey_admin_session" not in resp.cookies
    assert "timed out" in resp.text.lower()


@pytest.mark.asyncio
async def test_the_wrong_code_gets_nowhere(client):
    await _password_step(client)
    resp = await _code_step(client, "000000")

    assert resp.status_code == 401
    assert "survey_admin_session" not in resp.cookies
    assert "not right" in resp.text
    # Still on the code step, so the admin can try the real one.
    assert "Enter one-time password" in resp.text
    assert (await db.list_login_events())[0]["note"] == "wrong code"


@pytest.mark.asyncio
async def test_the_wrong_password_never_reaches_the_code_step(client):
    resp = await _password_step(client, password="not-the-password")

    assert resp.status_code == 401
    assert "Enter one-time password" not in resp.text
    assert await db.get_db()["admin_otps"].find_one({"username": SURVEY}) is None


@pytest.mark.asyncio
async def test_a_code_cannot_be_requested_with_a_username_alone(client):
    """Resending is for a browser that already passed the password."""
    resp = await client.post(ADMIN + "/survey/request-otp",
                             data={"username": SURVEY}, headers=FROM,
                             follow_redirects=False)

    assert resp.status_code == 401
    assert await db.get_db()["admin_otps"].find_one({"username": SURVEY}) is None

    # After the password, the same button sends a fresh code.
    await _password_step(client)
    again = await client.post(ADMIN + "/survey/request-otp",
                              data={"username": SURVEY}, headers=FROM,
                              follow_redirects=False)
    assert again.status_code == 200
    assert "Enter one-time password" in again.text


@pytest.mark.asyncio
async def test_a_code_is_spent_once(client):
    await _password_step(client)
    code = await _issued_code()
    assert (await _code_step(client, code)).status_code == 303

    await _password_step(client)
    assert (await _code_step(client, code)).status_code == 401


@pytest.mark.asyncio
async def test_the_escape_hatch_can_be_opened_when_mail_is_down(client, monkeypatch):
    """ADMIN_REQUIRE_OTP=false is how you get back in when mail breaks."""
    from app.routes import admin as admin_routes
    monkeypatch.setattr(admin_routes.settings, "admin_require_otp", False)

    resp = await _password_step(client)
    assert resp.status_code == 303
    assert resp.cookies.get("survey_admin_session") == "1"
    assert "ADMIN_REQUIRE_OTP is off" in (await db.list_login_events())[0]["note"]


# ── Blocking an address by hand ──────────────────────────────────────────────

@pytest_asyncio.fixture
async def admin(client) -> AsyncClient:
    client.cookies.set("survey_admin_session", "1")
    return client


@pytest.mark.asyncio
async def test_a_blocked_address_is_turned_away_at_the_password_step(admin):
    resp = await admin.post("/admin/api/security/block",
                            json={"ip": "203.0.113.44", "reason": "scanner"})
    assert resp.status_code == 200
    assert resp.json()["blocked"] is True

    # Even the right password gets nowhere from that address.
    refused = await _password_step(admin)
    assert refused.status_code == 429
    assert "blocked by an administrator" in refused.text
    assert await db.get_db()["admin_otps"].find_one({"username": SURVEY}) is None
    assert (await db.list_login_events())[0]["outcome"] == db.LOGIN_LOCKED

    # Another address is unaffected.
    other = await admin.post(ADMIN + "/login",
                             data={"username": SURVEY, "password": SURVEY_PW},
                             headers={"X-Forwarded-For": "198.51.100.7"},
                             follow_redirects=False)
    assert other.status_code == 200


@pytest.mark.asyncio
async def test_a_block_can_be_lifted(admin):
    await admin.post("/admin/api/security/block", json={"ip": "203.0.113.44"})
    assert await db.is_locked_out("203.0.113.44") is True

    lifted = await admin.post("/admin/api/security/block",
                              json={"ip": "203.0.113.44", "action": "unblock"})
    assert lifted.status_code == 200
    assert lifted.json()["lifted"] is True
    assert await db.is_locked_out("203.0.113.44") is False
    assert (await _password_step(admin)).status_code == 200


@pytest.mark.asyncio
async def test_a_timed_block_expires_on_its_own(admin):
    from datetime import datetime, timedelta, timezone

    await admin.post("/admin/api/security/block",
                     json={"ip": "203.0.113.44", "hours": 24})
    assert await db.is_locked_out("203.0.113.44") is True

    # Wind its end back past now: it stops applying and stops being listed.
    await db.get_db()[db.IP_BLOCKS].update_one(
        {"ip": "203.0.113.44"},
        {"$set": {"until": datetime.now(timezone.utc) - timedelta(minutes=1)}})

    assert await db.is_locked_out("203.0.113.44") is False
    assert await db.list_ip_blocks() == []


@pytest.mark.asyncio
async def test_you_cannot_block_the_address_you_are_on(admin):
    resp = await admin.post("/admin/api/security/block",
                            json={"ip": "127.0.0.1"})     # no proxy header here
    assert resp.status_code == 400
    assert "lock you out" in resp.json()["detail"]
    assert await db.list_ip_blocks() == []


@pytest.mark.asyncio
async def test_blocking_needs_an_admin_session(client):
    resp = await client.post("/admin/api/security/block", json={"ip": "203.0.113.44"})
    assert resp.status_code == 403
    assert await db.is_locked_out("203.0.113.44") is False


@pytest.mark.asyncio
async def test_the_security_page_shows_the_block_and_who_it_covers(admin):
    await _password_step(admin, password="wrong")     # one failure to list
    await admin.post("/admin/api/security/block",
                     json={"ip": "203.0.113.44", "reason": "SQL injection attempts"})

    body = (await admin.get("/admin/api/security/logins")).json()
    summary = body["summary"]

    assert summary["blocked_by_hand"] == 1
    assert summary["blocks"][0]["ip"] == "203.0.113.44"
    assert summary["blocks"][0]["reason"] == "SQL injection attempts"
    assert summary["blocks"][0]["forever"] is True

    row = next(o for o in summary["offenders"] if o["ip"] == "203.0.113.44")
    assert row["blocked_by_hand"] is True
    assert row["locked"] is True


@pytest.mark.asyncio
async def test_an_address_blocked_before_it_came_back_is_still_listed(admin):
    """That it stopped trying is the point of the block, not a reason to hide it."""
    await admin.post("/admin/api/security/block", json={"ip": "198.51.100.99"})

    summary = (await admin.get("/admin/api/security/logins")).json()["summary"]
    assert [o["ip"] for o in summary["offenders"]] == ["198.51.100.99"]
    assert summary["locked"] == 1
