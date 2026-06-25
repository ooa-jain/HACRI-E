"""
FastAPI dependencies: DB handle, current-user (from signed cookie),
CSRF token helpers.

CSRF is validated inline in routes (where the form data is already parsed)
because FastAPI doesn't expose the parsed form to plain dependencies.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from itsdangerous import BadSignature, URLSafeSerializer

from app.db import get_db
from app.settings import settings


# ── Signed-cookie session ────────────────────────────────────────────────────
_SESSION_COOKIE = "hacri_session"
_CSRF_COOKIE = "hacri_csrf"

_serializer = URLSafeSerializer(settings.session_secret, salt="hacri-session")


def _sign(payload: dict) -> str:
    return _serializer.dumps(payload)


def _unsign(token: str) -> dict | None:
    try:
        return _serializer.loads(token)
    except BadSignature:
        return None


def issue_session(response, email: str, name: str) -> None:
    """Set the signed session cookie."""
    token = _sign({"email": email, "name": name})
    response.set_cookie(
        key=_SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=60 * 60 * 24 * 30,  # 30 days
    )


def clear_session(response) -> None:
    response.delete_cookie(_SESSION_COOKIE)


def issue_csrf(response, token: str) -> None:
    response.set_cookie(
        key=_CSRF_COOKIE,
        value=token,
        httponly=False,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=60 * 60 * 24 * 30,
    )


def make_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def verify_csrf(submitted: str | None, hacri_csrf: str | None) -> None:
    """Compare submitted form `csrf` value against the cookie. Raises 403."""
    if not hacri_csrf or not submitted:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token missing.",
        )
    if not secrets.compare_digest(str(submitted), str(hacri_csrf)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token invalid.",
        )


# ── FastAPI dependencies ─────────────────────────────────────────────────────
def get_current_session(
    hacri_session: Annotated[str | None, Cookie()] = None,
) -> dict:
    """Return {email, name} from the signed session cookie, or raise 401."""
    if not hacri_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No session. Please enter your name and email to start.",
        )
    payload = _unsign(hacri_session)
    if not payload or "email" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session. Please re-enter your name and email.",
        )
    return payload


async def get_current_user(
    session: Annotated[dict, Depends(get_current_session)],
):
    """Return the user doc from Mongo, scoped to the session email."""
    db = get_db()
    user = await db["users"].find_one({"email": session["email"]})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session is no longer valid. Please re-enter your details.",
        )
    return user


def get_csrf_token(
    hacri_csrf: Annotated[str | None, Cookie()] = None,
) -> str | None:
    return hacri_csrf