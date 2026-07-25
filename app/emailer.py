"""
Build and send the results email after Post submission.

Two modes:
- Production: TLS SMTP via aiosmtplib, configured by env vars.
- Dry-run (default in dev): append the rendered email to
  `generated/emails.log` so you can inspect what would have been sent.

Sending is wrapped in `try/except` — email failures must not fail the
submission. The user still sees the results on-screen.
"""

from __future__ import annotations

import asyncio
import logging
from email.message import EmailMessage
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.settings import settings

log = logging.getLogger(__name__)

# Template env scoped to the email body only
_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)

_STATIC_LOGO_PATH = Path(__file__).parent / "static" / "logo.png"


# ── Shared SMTP helpers ────────────────────────────────────────────────────────
def _is_dry_run() -> bool:
    """Dry-run when explicitly enabled or when no SMTP host is configured."""
    return bool(settings.email_dry_run or not settings.smtp_host)


def _smtp_connect_kwargs() -> dict:
    """Connection kwargs shared by one-shot sends and the batch sender.

    Port 465 → implicit TLS (use_tls). Any other port → STARTTLS.
    """
    kwargs: dict[str, Any] = dict(
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user,
        password=settings.smtp_pass,
    )
    if settings.smtp_port == 465:
        kwargs["use_tls"] = True
    else:
        kwargs["start_tls"] = True
    return kwargs


def _build_html_message(
    to_email: str,
    to_name: str,
    subject: str,
    body_text: str,
    body_html: str,
) -> MIMEMultipart:
    """Build a multipart/related HTML email with the inline JAIN logo (cid:logo)."""
    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"] = settings.email_from
    msg["To"] = f"{to_name} <{to_email}>"

    alt = MIMEMultipart("alternative")
    msg.attach(alt)
    alt.attach(MIMEText(body_text, "plain", "utf-8"))
    alt.attach(MIMEText(body_html, "html", "utf-8"))

    if _STATIC_LOGO_PATH.exists():
        with open(_STATIC_LOGO_PATH, "rb") as f:
            logo = MIMEImage(f.read())
        logo.add_header("Content-ID", "<logo>")
        logo.add_header("Content-Disposition", "inline", filename="logo.png")
        msg.attach(logo)

    return msg


def _dry_run_log_message(msg) -> None:
    """Append a compact representation of a message to generated/emails.log."""
    log_dir = settings.generated_root
    log_dir.mkdir(parents=True, exist_ok=True)
    out = log_dir / "emails.log"
    with out.open("a", encoding="utf-8") as f:
        f.write("\n" + "=" * 72 + "\n")
        f.write(f"To: {msg['To']}\n")
        f.write(f"From: {msg['From']}\n")
        f.write(f"Subject: {msg['Subject']}\n")


class SmtpBatchSender:
    """Send many messages over a SINGLE authenticated SMTP connection.

    Opening a fresh connection per email (the old behaviour) is slow and trips
    provider "too many connections" rate limits (Hostinger 451). Reusing one
    connection lets us send hundreds of reminders quickly and reliably.

    Usage:
        async with SmtpBatchSender() as sender:
            for msg in messages:
                await sender.send(msg)

    In dry-run mode no connection is opened; messages are logged instead.
    """

    def __init__(self) -> None:
        self.dry_run = _is_dry_run()
        self._client: aiosmtplib.SMTP | None = None

    async def __aenter__(self) -> "SmtpBatchSender":
        if not self.dry_run:
            await self._connect()
        return self

    async def __aexit__(self, *exc) -> None:
        await self._close()

    async def _connect(self) -> None:
        kwargs = _smtp_connect_kwargs()
        client = aiosmtplib.SMTP(
            hostname=kwargs["hostname"],
            port=kwargs["port"],
            use_tls=kwargs.get("use_tls", False),
            start_tls=kwargs.get("start_tls", False),
            timeout=60,
        )
        await client.connect()
        if settings.smtp_user and settings.smtp_pass:
            await client.login(settings.smtp_user, settings.smtp_pass)
        self._client = client

    async def _close(self) -> None:
        if self._client is not None:
            try:
                await self._client.quit()
            except Exception:  # pragma: no cover - best-effort teardown
                pass
            self._client = None

    async def send(self, msg) -> None:
        """Send one message. Reconnects once if the connection dropped."""
        if self.dry_run:
            _dry_run_log_message(msg)
            return
        try:
            await self._client.send_message(msg)  # type: ignore[union-attr]
        except aiosmtplib.SMTPServerDisconnected:
            # Connection dropped mid-batch — reconnect once and retry.
            log.warning("SMTP connection dropped; reconnecting for next message.")
            await self._close()
            await self._connect()
            await self._client.send_message(msg)  # type: ignore[union-attr]


# ── Public API ───────────────────────────────────────────────────────────────
async def send_results_email(
    *,
    name: str,
    email: str,
    results_url: str,
    png_paths: dict[str, Path],
    csv_path: Path | None,
    deltas: dict[str, Any],
) -> None:
    """Build and dispatch the results email. Never raises to the caller."""
    try:
        msg = build_results_email(
            name=name,
            email=email,
            results_url=results_url,
            png_paths=png_paths,
            csv_path=csv_path,
            deltas=deltas,
        )

        if settings.email_dry_run or not settings.smtp_host:
            _dry_run_save(msg)
            return

        smtp_kwargs = dict(
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_pass,
        )
        if settings.smtp_port == 465:
            smtp_kwargs["use_tls"] = True
        else:
            smtp_kwargs["start_tls"] = True

        await aiosmtplib.send(msg, **smtp_kwargs)
    except Exception as e:  # pragma: no cover
        log.exception("Failed to send results email to %s: %s", email, e)


def build_results_email(
    *,
    name: str,
    email: str,
    results_url: str,
    png_paths: dict[str, Path],
    csv_path: Path | None,
    deltas: dict[str, Any],
) -> EmailMessage:
    """Construct the EmailMessage with HTML body + attachments."""
    tpl = _env.get_template("results_email.html")
    html_body = tpl.render(
        name=name,
        results_url=results_url,
        pre=deltas.get("pre", {}),
        post=deltas.get("post", {}),
        d_lit=deltas.get("delta_lit"),
        d_read=deltas.get("delta_read"),
        movement=deltas.get("movement", ""),
    )

    msg = EmailMessage()
    msg["Subject"] = "Your HACRI-E2 Workshop Results"
    msg["From"] = settings.email_from
    msg["To"] = f"{name} <{email}>"
    msg.set_content(_plain_text_fallback(name, results_url, deltas))
    msg.add_alternative(html_body, subtype="html")

    # Attach PNGs
    for label, path in png_paths.items():
        if path and path.exists():
            with open(path, "rb") as f:
                data = f.read()
            msg.add_attachment(
                data,
                maintype="image",
                subtype="png",
                filename=path.name,
            )

    # Attach CSV
    if csv_path and csv_path.exists():
        with open(csv_path, "rb") as f:
            msg.add_attachment(
                f.read(),
                maintype="text",
                subtype="csv",
                filename=csv_path.name,
            )

    return msg


# ── Internal helpers ─────────────────────────────────────────────────────────
def _plain_text_fallback(name: str, results_url: str, deltas: dict) -> str:
    pre = deltas.get("pre", {})
    post = deltas.get("post", {})
    return (
        f"Hi {name},\n\n"
        f"Thank you for completing the HACRI-E2 Pre and Post surveys.\n\n"
        f"Pre  — Literacy: {pre.get('lit')}, Readiness: {pre.get('read')}, "
        f"Quadrant: {pre.get('quadrant')}, Band: {pre.get('band')}\n"
        f"Post — Literacy: {post.get('lit')}, Readiness: {post.get('read')}, "
        f"Quadrant: {post.get('quadrant')}, Band: {post.get('band')}\n\n"
        f"Δ Literacy: {deltas.get('delta_lit')}\n"
        f"Δ Readiness: {deltas.get('delta_read')}\n"
        f"Movement: {deltas.get('movement')}\n\n"
        f"View your full results online: {results_url}\n"
        f"Charts and the scorecard CSV are attached.\n\n"
        f"— HACRI-E2"
    )


def _dry_run_save(msg: EmailMessage) -> None:
    log_dir = settings.generated_root
    log_dir.mkdir(parents=True, exist_ok=True)
    out = log_dir / "emails.log"
    # Append a compact representation — we don't binarise attachments.
    with out.open("a", encoding="utf-8") as f:
        f.write("\n" + "=" * 72 + "\n")
        f.write(f"To: {msg['To']}\n")
        f.write(f"From: {msg['From']}\n")
        f.write(f"Subject: {msg['Subject']}\n")
        f.write("Attachments: " + ", ".join(
            p.get_filename() or "?" for p in msg.iter_attachments()
        ) + "\n")
        body = _extract_html_body(msg)
        f.write("--- HTML body ---\n")
        f.write(body[:4000] + ("\n[truncated]" if len(body) > 4000 else "") + "\n")
    log.info("Dry-run: appended email to %s", out)


def _extract_html_body(msg: EmailMessage) -> str:
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            try:
                return part.get_content()
            except Exception:
                return part.get_payload(decode=True).decode("utf-8", "replace")
    return ""

async def send_simple_email(
    to_email: str,
    to_name: str,
    subject: str,
    body_text: str,
) -> None:
    """Send a plain-text email (used for admin alerts)."""
    import aiosmtplib
    from email.mime.text import MIMEText
    from app.settings import settings

    if settings.email_dry_run or not settings.smtp_host:
        import logging
        logging.getLogger(__name__).info(
            "DRY RUN email to %s <%s>: %s", to_name, to_email, subject
        )
        log_dir = settings.generated_root
        log_dir.mkdir(parents=True, exist_ok=True)
        out = log_dir / "emails.log"
        with out.open("a", encoding="utf-8") as f:
            f.write("\n" + "=" * 72 + "\n")
            f.write(f"To: {to_name} <{to_email}>\n")
            f.write(f"From: {settings.email_from}\n")
            f.write(f"Subject: {subject}\n")
            f.write("--- Plain-text body ---\n")
            f.write(body_text + "\n")
        return

    msg = MIMEText(body_text, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = settings.email_from
    msg["To"] = f"{to_name} <{to_email}>"

    smtp_kwargs = dict(
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user,
        password=settings.smtp_pass,
    )
    if settings.smtp_port == 465:
        smtp_kwargs["use_tls"] = True
    else:
        smtp_kwargs["start_tls"] = True

    await aiosmtplib.send(msg, **smtp_kwargs)


async def send_html_email(
    to_email: str,
    to_name: str,
    subject: str,
    body_text: str,
    body_html: str,
) -> None:
    """Send a single HTML email with plain-text fallback (one-shot connection)."""
    msg = _build_html_message(to_email, to_name, subject, body_text, body_html)
    if _is_dry_run():
        log.info("DRY RUN HTML email to %s <%s>: %s", to_name, to_email, subject)
        _dry_run_log_message(msg)
        return
    await aiosmtplib.send(msg, **_smtp_connect_kwargs())


# ── Reminder message builders (used by single sends AND the batch sender) ──────
def build_pre_reminder_message(email: str, name: str, resume_link: str) -> MIMEMultipart:
    tpl = _env.get_template("pre_reminder_email.html")
    html_body = tpl.render(name=name, resume_link=resume_link)
    subject = "Reminder: Please complete the Pre-AI Survey"
    body_text = (
        f"Hi {name},\n\n"
        "We noticed you registered for the Pre-AI Survey but haven't completed it yet.\n\n"
        f"Please click the link below to directly resume and finish your survey:\n{resume_link}\n\n"
        "Thank you,\nOffice of Academics\nJAIN (Deemed-to-be University)"
    )
    return _build_html_message(email, name, subject, body_text, html_body)


def build_post_reminder_message(email: str, name: str, resume_link: str) -> MIMEMultipart:
    tpl = _env.get_template("post_reminder_email.html")
    html_body = tpl.render(name=name, resume_link=resume_link)
    subject = "Reminder: Please complete the Post-Workshop Survey"
    body_text = (
        f"Hi {name},\n\n"
        "Thank you for completing the Pre-AI Survey.\n\n"
        f"You haven't yet submitted the Post-Workshop Survey. Please click the link below to directly resume and complete it:\n{resume_link}\n\n"
        "Thank you,\nOffice of Academics\nJAIN (Deemed-to-be University)"
    )
    return _build_html_message(email, name, subject, body_text, html_body)


async def send_pre_reminder_email(email: str, name: str, resume_link: str) -> None:
    msg = build_pre_reminder_message(email, name, resume_link)
    if _is_dry_run():
        log.info("DRY RUN pre-reminder to %s <%s>", name, email)
        _dry_run_log_message(msg)
        return
    await aiosmtplib.send(msg, **_smtp_connect_kwargs())


async def send_post_reminder_email(email: str, name: str, resume_link: str) -> None:
    msg = build_post_reminder_message(email, name, resume_link)
    if _is_dry_run():
        log.info("DRY RUN post-reminder to %s <%s>", name, email)
        _dry_run_log_message(msg)
        return
    await aiosmtplib.send(msg, **_smtp_connect_kwargs())
