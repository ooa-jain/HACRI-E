#!/usr/bin/env python3
"""
SMTP diagnostic — run this ON THE SERVER to find out why mail isn't sending.

Usage:
    python scripts/test_smtp.py you@example.com

It prints the SMTP settings the app actually resolved (password masked),
warns if the app is in dry-run mode, then tries a real connect + login +
send and reports the exact error if anything fails.
"""
from __future__ import annotations
import asyncio
import os
import sys

# Allow running as `python scripts/test_smtp.py` from the project root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _mask(secret: str | None) -> str:
    if not secret:
        return "(empty)"
    if len(secret) <= 4:
        return "*" * len(secret)
    return secret[:2] + "*" * (len(secret) - 4) + secret[-2:]


async def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_smtp.py recipient@example.com")
        return 2
    recipient = sys.argv[1].strip()

    from app.settings import settings

    print("=" * 60)
    print("RESOLVED SMTP CONFIG (what the running code actually sees)")
    print("=" * 60)
    print(f"  SMTP host      : {settings.smtp_host or '(EMPTY!)'}")
    print(f"  SMTP port      : {settings.smtp_port}")
    print(f"  SMTP user      : {settings.smtp_user or '(EMPTY!)'}")
    print(f"  SMTP pass      : {_mask(settings.smtp_pass)} (len {len(settings.smtp_pass or '')})")
    print(f"  From address   : {settings.email_from}")
    print(f"  EMAIL_DRY_RUN  : {settings.email_dry_run}")
    print("=" * 60)

    if not settings.smtp_host:
        print("\n❌ smtp_host is EMPTY. The app cannot send.")
        print("   → Either the new code isn't deployed (git pull + restart),")
        print("     or set the canonical names: SMTP_HOST, SMTP_USER, SMTP_PASS.")
        return 1

    if settings.email_dry_run:
        print("\n❌ EMAIL_DRY_RUN is TRUE — mail is only written to")
        print("   generated/emails.log, never actually sent.")
        print("   → Set EMAIL_DRY_RUN=false in the environment and restart.")
        return 1

    # Attempt a real send using the app's own sender path.
    from app import emailer
    print(f"\nAttempting a real test send to {recipient} ...")
    try:
        await emailer.send_simple_email(
            recipient,
            "SMTP Test",
            "HACRI-E SMTP test",
            "This is a test message from the HACRI-E SMTP diagnostic. "
            "If you received it, outbound mail is working.",
        )
        print("✅ SUCCESS — the server accepted the message.")
        print("   Check the recipient inbox (and Spam).")
        return 0
    except Exception as exc:  # noqa: BLE001
        print("❌ SEND FAILED. Exact error below:")
        print(f"   {type(exc).__name__}: {exc}")
        s = str(exc).lower()
        if "username and password not accepted" in s or "535" in s:
            print("   → Gmail rejected the login. Use a Google *App Password* "
                  "(not your normal password), and make sure it belongs to the "
                  "same account as SMTP_EMAIL.")
        elif "5.7.0" in s or "authentication" in s:
            print("   → Authentication problem: check SMTP_EMAIL / SMTP_PASSWORD.")
        elif "ratelimit" in s or "451" in s or "4.7.1" in s:
            print("   → Provider rate limit. Wait for the quota to reset.")
        elif "timed out" in s or "connection" in s:
            print("   → Network/port issue. Confirm port 587 (Gmail) is allowed "
                  "outbound from the host.")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
