"""
The admin portal answers somewhere other than /admin.

Every install of everything has an /admin/login, which is why the sign-in log
fills up with addresses that have never done anything but knock on it. The
pages a person opens moved to ADMIN_PATH; the well-known addresses now answer
404, exactly like a site with no admin at all.
"""

from __future__ import annotations

from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app import db
from app.settings import Settings, settings

ADMIN = settings.admin_path


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


def test_the_path_is_not_the_default_one():
    assert ADMIN != "/admin", "the whole point is that it moved"
    assert ADMIN.startswith("/")


def test_a_path_typed_into_an_env_is_tidied_up():
    """Written with or without the slashes, it means the same thing."""
    base = {"mongodb_uri": "mongodb://mock", "session_secret": "x" * 32}
    for written in ("ooajain/adminooa@", "/ooajain/adminooa@", "/ooajain/adminooa@/"):
        assert Settings(**base, ADMIN_PATH=written).admin_path == "/ooajain/adminooa@"


# ── The door that is gone ────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    "/admin", "/admin/", "/admin/login",
    "/admin/survey", "/admin/orientation",
    "/admin/survey/login", "/admin/orientation/login",
])
async def test_the_well_known_addresses_are_not_found(client: AsyncClient, path):
    resp = await client.get(path, follow_redirects=False)
    assert resp.status_code == 404, f"{path} still answers"
    # Nothing in the reply hints that an admin portal exists elsewhere.
    assert "Admin" not in resp.text
    assert ADMIN not in resp.text


@pytest.mark.asyncio
async def test_the_old_login_cannot_be_posted_to_either(client: AsyncClient):
    """A 404 that still accepts a password would be no protection at all."""
    resp = await client.post("/admin/login",
                             data={"username": settings.survey_admin_username,
                                   "password": settings.survey_admin_password},
                             follow_redirects=False)
    assert resp.status_code == 404
    assert await db.get_db()["admin_otps"].find_one({}) is None
    assert await db.list_login_events() == []      # not even worth logging


@pytest.mark.asyncio
async def test_the_old_otp_request_is_gone_too(client: AsyncClient):
    resp = await client.post("/admin/survey/request-otp",
                             data={"username": settings.survey_admin_username})
    assert resp.status_code == 404


# ── The door that works ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_portal_opens_behind_the_configured_path(client: AsyncClient):
    resp = await client.get(ADMIN + "/login")
    assert resp.status_code == 200
    assert "Admin Username" in resp.text

    # Its own forms post back to the same door, never to /admin.
    assert f'action="{ADMIN}/login"' in resp.text
    assert 'action="/admin/login"' not in resp.text


@pytest.mark.asyncio
async def test_the_portal_root_sends_you_to_its_own_login(client: AsyncClient):
    resp = await client.get(ADMIN, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == ADMIN + "/login"


@pytest.mark.asyncio
async def test_the_dashboard_opens_behind_it_for_a_signed_in_admin(client: AsyncClient):
    client.cookies.set("survey_admin_session", "1")
    resp = await client.get(ADMIN + "/survey")
    assert resp.status_code == 200
    assert "Sign-in activity" in resp.text


@pytest.mark.asyncio
async def test_signing_out_returns_to_the_moved_login(client: AsyncClient):
    client.cookies.set("survey_admin_session", "1")
    resp = await client.get(ADMIN + "/survey/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == ADMIN + "/login"


# ── What stays where it is ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_api_behind_the_door_is_unmoved_and_still_locked(client: AsyncClient):
    """The dashboard's own scripts ask for /admin/api/..., and the session
    cookie is what guards it — there is no password to guess there."""
    assert (await client.get("/admin/api/survey/users")).status_code == 403

    client.cookies.set("survey_admin_session", "1")
    assert (await client.get("/admin/api/survey/users")).status_code == 200
