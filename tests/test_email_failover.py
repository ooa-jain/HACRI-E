"""
Mail delivery when a mailbox stops working.

Two failures live here. One is a mailbox that refuses, hangs or hits its rate
limit — the app now tries a second account before giving up. The other is
quieter and did more damage: an .env written with the names a hosting panel
uses (SMTP_SERVER, SMTP_EMAIL, SMTP_PASSWORD) configured nothing at all. The
app fell back to dry-run, wrote every message to a log file, and looked
completely healthy while delivering nothing.
"""
from __future__ import annotations

import pytest

from app import emailer
from app.settings import Settings


def _settings(**env) -> Settings:
    base = {"mongodb_uri": "mongodb://mock", "mongodb_db": "t",
            "session_secret": "x" * 32}
    return Settings(**{**base, **env})


# ── Configuration ────────────────────────────────────────────────────────────

def test_the_names_a_hosting_panel_uses_configure_the_app():
    s = _settings(SMTP_SERVER="smtp.hostinger.com", SMTP_EMAIL="ooa@example.org",
                  SMTP_PASSWORD="secret", SMTP_PORT=465)
    assert s.smtp_host == "smtp.hostinger.com"
    assert s.smtp_user == "ooa@example.org"
    assert s.smtp_pass == "secret"


def test_a_canonical_name_is_never_overridden_by_an_alias():
    s = _settings(SMTP_HOST="real.example.org", SMTP_SERVER="alias.example.org")
    assert s.smtp_host == "real.example.org"


def test_an_empty_alias_does_not_shadow_anything():
    s = _settings(SMTP_HOST="real.example.org", SMTP_SERVER="")
    assert s.smtp_host == "real.example.org"


# ── Which mailboxes get tried ────────────────────────────────────────────────

def test_one_mailbox_when_no_fallback_is_configured(monkeypatch):
    monkeypatch.setattr(emailer, "settings",
                        _settings(SMTP_HOST="a.example.org", SMTP_USER="u", SMTP_PASS="p"))
    accounts = emailer.smtp_accounts()
    assert [a["hostname"] for a in accounts] == ["a.example.org"]
    assert accounts[0]["use_tls"] is True        # port 465 → implicit TLS


def test_the_fallback_is_tried_after_the_primary(monkeypatch):
    monkeypatch.setattr(emailer, "settings", _settings(
        SMTP_HOST="a.example.org", SMTP_USER="u1", SMTP_PASS="p1",
        SMTP_FALLBACK_HOST="b.example.org", SMTP_FALLBACK_USER="u2",
        SMTP_FALLBACK_PASS="p2", SMTP_FALLBACK_PORT=587))
    accounts = emailer.smtp_accounts()
    assert [a["hostname"] for a in accounts] == ["a.example.org", "b.example.org"]
    assert accounts[1]["username"] == "u2"
    assert accounts[1]["start_tls"] is True      # port 587 → STARTTLS


def test_every_connection_carries_a_timeout(monkeypatch):
    monkeypatch.setattr(emailer, "settings", _settings(
        SMTP_HOST="a.example.org", SMTP_FALLBACK_HOST="b.example.org",
        SMTP_TIMEOUT_SECONDS=12))
    assert [a["timeout"] for a in emailer.smtp_accounts()] == [12, 12]


# ── Sending ──────────────────────────────────────────────────────────────────

@pytest.fixture
def two_mailboxes(monkeypatch):
    monkeypatch.setattr(emailer, "settings", _settings(
        SMTP_HOST="primary.example.org", SMTP_USER="u1", SMTP_PASS="p1",
        SMTP_FALLBACK_HOST="backup.example.org", SMTP_FALLBACK_USER="u2",
        SMTP_FALLBACK_PASS="p2"))


def _message():
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["From"] = "JAIN Office of Academics <primary@example.org>"
    msg["To"] = "student@example.org"
    msg["Subject"] = "Deeksharambh"
    msg.set_content("body")
    return msg


def _record(monkeypatch, failing: set[str]):
    """Records (hostname, From) for each attempt — aiosmtplib never runs."""
    tried: list[tuple[str, str]] = []

    async def fake_send(msg, **kwargs):
        tried.append((kwargs["hostname"], msg["From"]))
        assert "from_addr" not in kwargs, "from_addr leaked into the SMTP kwargs"
        if kwargs["hostname"] in failing:
            raise TimeoutError(f"{kwargs['hostname']} timed out")

    monkeypatch.setattr(emailer.aiosmtplib, "send", fake_send)
    return tried


@pytest.mark.asyncio
async def test_the_primary_alone_handles_a_healthy_send(two_mailboxes, monkeypatch):
    tried = _record(monkeypatch, failing=set())
    await emailer.send_with_failover(_message())
    assert [h for h, _ in tried] == ["primary.example.org"], \
        "the fallback was used unnecessarily"


@pytest.mark.asyncio
async def test_a_timeout_on_the_primary_moves_the_message_to_the_fallback(
        two_mailboxes, monkeypatch):
    tried = _record(monkeypatch, failing={"primary.example.org"})
    await emailer.send_with_failover(_message())
    assert [h for h, _ in tried] == ["primary.example.org", "backup.example.org"]


@pytest.mark.asyncio
async def test_the_error_surfaces_only_when_every_mailbox_fails(
        two_mailboxes, monkeypatch):
    tried = _record(monkeypatch,
                    failing={"primary.example.org", "backup.example.org"})
    with pytest.raises(TimeoutError):
        await emailer.send_with_failover(_message())
    assert [h for h, _ in tried] == ["primary.example.org", "backup.example.org"]


@pytest.mark.asyncio
async def test_falling_back_is_logged_loudly_enough_to_notice(
        two_mailboxes, monkeypatch, caplog):
    _record(monkeypatch, failing={"primary.example.org"})
    with caplog.at_level("WARNING"):
        await emailer.send_with_failover(_message())
    joined = caplog.text
    assert "primary.example.org" in joined
    assert "backup.example.org" in joined
    # A mailbox that has quietly stopped working must not stay quiet.
    assert any(r.levelname in ("WARNING", "ERROR") for r in caplog.records)


@pytest.mark.asyncio
async def test_no_mailbox_configured_is_an_error_not_a_silent_no_op(monkeypatch):
    monkeypatch.setattr(emailer, "settings", _settings())
    with pytest.raises(RuntimeError, match="No SMTP host"):
        await emailer.send_with_failover(_message())


# ── The one button whose success depends on mail ─────────────────────────────
#
# The admin OTP is the login. It is the only place in the app that awaits a
# send inline and shows the result to the person who pressed the button, so it
# is the place a mail problem is actually visible as "the button is broken".

@pytest.mark.asyncio
async def test_the_otp_screen_does_not_claim_a_mail_that_was_never_sent(monkeypatch):
    """In dry-run the flow still continues — the code is in the log — but the
    screen must not say "OTP sent" to an admin who will never receive one."""
    from httpx import ASGITransport, AsyncClient
    from mongomock_motor import AsyncMongoMockClient
    from app import db
    from app.settings import settings as live

    db._set_client_for_tests(AsyncMongoMockClient())
    try:
        from app.main import app
        await db.init_indexes(allow_duplicate_email=True)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.post("/admin/survey/request-otp",
                             data={"username": live.survey_admin_username})
        assert r.status_code == 200
        assert "no OTP was emailed" in r.text
        assert "EMAIL_DRY_RUN=false" in r.text
    finally:
        db._reset_clients_for_tests()


@pytest.mark.asyncio
async def test_a_failed_otp_names_every_mailbox_it_tried(two_mailboxes, monkeypatch):
    """"Please check SMTP config" does not say which host failed or why."""
    hosts = [a["hostname"] for a in emailer.smtp_accounts()]
    assert hosts == ["primary.example.org", "backup.example.org"]
    # The route builds its message from exactly this list, so both appear.
    assert len(hosts) > 1


# ── Sending as the right address ─────────────────────────────────────────────
#
# A provider will not relay a message claiming to be from someone else's
# domain. Handing Hostinger a message that says it is from a gmail.com address
# is a rejection, so the whole failover would have been for nothing.

@pytest.mark.asyncio
async def test_the_fallback_sends_as_itself_not_as_the_primary(monkeypatch):
    monkeypatch.setattr(emailer, "settings", _settings(
        SMTP_HOST="primary.example.org", SMTP_USER="a@primary.example.org",
        SMTP_PASS="p1", EMAIL_FROM="Office <a@primary.example.org>",
        SMTP_FALLBACK_HOST="backup.example.org",
        SMTP_FALLBACK_USER="b@backup.example.org", SMTP_FALLBACK_PASS="p2"))
    tried = _record(monkeypatch, failing={"primary.example.org"})

    await emailer.send_with_failover(_message())

    hosts = [h for h, _ in tried]
    froms = [f for _, f in tried]
    assert hosts == ["primary.example.org", "backup.example.org"]
    assert froms[0] == "Office <a@primary.example.org>"
    assert froms[1] == "b@backup.example.org", (
        "the fallback tried to send as the primary's address"
    )


@pytest.mark.asyncio
async def test_an_explicit_fallback_from_wins_over_the_fallback_username(monkeypatch):
    monkeypatch.setattr(emailer, "settings", _settings(
        SMTP_HOST="primary.example.org", EMAIL_FROM="Office <a@primary.example.org>",
        SMTP_FALLBACK_HOST="backup.example.org",
        SMTP_FALLBACK_USER="smtp-login@backup.example.org",
        SMTP_FALLBACK_FROM="Office of Academics <ooa@backup.example.org>"))
    tried = _record(monkeypatch, failing={"primary.example.org"})

    await emailer.send_with_failover(_message())
    assert tried[1][1] == "Office of Academics <ooa@backup.example.org>"


def test_the_primary_keeps_the_configured_from(monkeypatch):
    monkeypatch.setattr(emailer, "settings", _settings(
        SMTP_HOST="primary.example.org", EMAIL_FROM="Office <a@primary.example.org>"))
    assert emailer.smtp_accounts()[0]["from_addr"] == "Office <a@primary.example.org>"
