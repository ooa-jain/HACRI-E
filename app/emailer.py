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

        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_pass,
            start_tls=True,
        )
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

    if settings.email_dry_run:
        import logging
        logging.getLogger(__name__).info(
            "DRY RUN email to %s <%s>: %s", to_name, to_email, subject
        )
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
