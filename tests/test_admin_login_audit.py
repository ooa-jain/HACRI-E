"""
The admin sign-in log, and the lock-out that comes with it.

The admin portal opens onto every student's contact details and every
department's figures. Nothing recorded who had opened it or who had tried, so
a stolen password left no trace and a guesser had unlimited attempts.
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

REAL_IP = {"X-Forwarded-For": "203.0.113.44, 10.0.0.1",
           "User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/133.0 Safari/537.36"}


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


async def _try_login(client, username="survey", otp="000000", **kw):
    return await client.post(ADMIN + "/login",
                             data={"username": username, "password": otp},
                             headers=REAL_IP, follow_redirects=False, **kw)


# ── What reaches the log ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_failed_attempt_is_recorded_with_its_address(client):
    await _try_login(client, username="survey", otp="123456")

    events = await db.list_login_events()
    assert len(events) == 1
    ev = events[0]
    assert ev["outcome"] == db.LOGIN_BAD
    assert ev["username"] == "survey"
    # The first hop of X-Forwarded-For is the client; the rest are proxies.
    assert ev["ip"] == "203.0.113.44"
    assert "Chrome" in ev["agent"]


@pytest.mark.asyncio
async def test_a_successful_sign_in_is_recorded(client):
    """The password is step one of two, so what it produces is a mailed code."""
    await _try_login(client, username=settings.orientation_admin_username,
                     otp=settings.orientation_admin_password)

    outcomes = [ev["outcome"] for ev in await db.list_login_events()]
    assert db.LOGIN_OTP_SENT in outcomes
    ev = next(e for e in await db.list_login_events()
              if e["outcome"] == db.LOGIN_OTP_SENT)
    assert "Deeksharambh" in ev["portal"]


@pytest.mark.asyncio
async def test_an_unknown_username_is_told_apart_from_a_wrong_code(client):
    await _try_login(client, username="not-an-admin", otp="123456")
    assert (await db.list_login_events())[0]["outcome"] == db.LOGIN_UNKNOWN


@pytest.mark.asyncio
async def test_the_password_that_was_tried_is_never_written_down(client):
    """A log of failed attempts containing the passwords people tried is a
    worse liability than no log at all."""
    secret = "hunter2-do-not-store"
    await _try_login(client, username="survey", otp=secret)

    raw = [doc async for doc in db.get_db()[db.LOGINS].find({})]
    assert raw and secret not in str(raw)


# ── The lock-out ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_address_is_turned_away_after_too_many_failures(client):
    for _ in range(db.LOGIN_FAIL_LIMIT):
        r = await _try_login(client, otp="000000")
        assert r.status_code == 401

    blocked = await _try_login(client, otp="000000")
    assert blocked.status_code == 429
    assert "Too many failed attempts" in blocked.text

    assert (await db.list_login_events())[0]["outcome"] == db.LOGIN_LOCKED


@pytest.mark.asyncio
async def test_the_block_follows_the_address_not_the_username(client):
    """Rotating usernames must not buy more attempts."""
    for i in range(db.LOGIN_FAIL_LIMIT):
        await _try_login(client, username=f"guess{i}", otp="000000")

    r = await _try_login(client, username="survey", otp="000000")
    assert r.status_code == 429


@pytest.mark.asyncio
async def test_a_correct_password_is_refused_while_the_address_is_blocked(client):
    """Checked before the credentials, so a guesser learns nothing from how
    long the answer takes."""
    for _ in range(db.LOGIN_FAIL_LIMIT):
        await _try_login(client, otp="000000")

    r = await _try_login(client, username=settings.orientation_admin_username,
                         otp=settings.orientation_admin_password)
    assert r.status_code == 429
    assert "orientation_admin_session" not in r.cookies


@pytest.mark.asyncio
async def test_another_address_is_unaffected(client):
    for _ in range(db.LOGIN_FAIL_LIMIT + 1):
        await _try_login(client, otp="000000")

    other = await client.post(
        ADMIN + "/login",
        data={"username": settings.orientation_admin_username,
              "password": settings.orientation_admin_password},
        headers={"X-Forwarded-For": "198.51.100.7"}, follow_redirects=False)
    # Not turned away: the password is accepted and the code step opens.
    assert other.status_code == 200
    assert "One-Time Password" in other.text


# ── The page that reads it ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_log_is_not_readable_without_an_admin_session(client):
    assert (await client.get("/admin/api/security/logins")).status_code == 403


@pytest.mark.asyncio
async def test_the_summary_groups_failures_by_address(client):
    for _ in range(3):
        await _try_login(client, username="survey", otp="000000")
    await client.post(ADMIN + "/login", data={"username": "x", "password": "y"},
                      headers={"X-Forwarded-For": "198.51.100.9"},
                      follow_redirects=False)

    client.cookies.set("survey_admin_session", "1")
    body = (await client.get("/admin/api/security/logins")).json()

    assert body["summary"]["failures"] == 4
    assert body["summary"]["addresses"] == 2
    worst = body["summary"]["offenders"][0]
    assert worst["ip"] == "203.0.113.44" and worst["failures"] == 3
    assert worst["locked"] is False        # three is under the limit
    assert body["policy"]["limit"] == db.LOGIN_FAIL_LIMIT
    # No proxy header on this request, so it falls back to the socket address.
    assert body["you"]["ip"] == "127.0.0.1"


@pytest.mark.asyncio
async def test_x_real_ip_is_used_when_there_is_no_forwarded_chain(client):
    await client.post(ADMIN + "/login", data={"username": "survey", "password": "1"},
                      headers={"X-Real-IP": "192.0.2.10"}, follow_redirects=False)
    assert (await db.list_login_events())[0]["ip"] == "192.0.2.10"
