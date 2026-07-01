"""
Pydantic models used by the routes for validation. We validate the
flat `fields` dict at the end, but the route helpers below also accept
the raw form data and coerce it into the canonical field shape.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, field_validator


# ── Identity ─────────────────────────────────────────────────────────────────
class UserIdentity(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    email: EmailStr
    ug_or_pg: Annotated[str, Field(min_length=1, max_length=20)] = "ug"
    education_type: Annotated[str | None, Field(max_length=100)] = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        return v.strip()

    @field_validator("email")
    @classmethod
    def _norm_email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("ug_or_pg")
    @classmethod
    def _check_level(cls, v: str) -> str:
        if v not in ("ug", "pg"):
            raise ValueError("Must be 'ug' or 'pg'")
        return v


# ── Helpers used by routes to build the canonical fields dict ───────────────
def coerce_int(value) -> int | None:
    """Coerce a form value to int. None / '' / non-numeric → None."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def coerce_str(value) -> str | None:
    """Coerce a form value to trimmed str. None / '' → None."""
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def coerce_text(value, max_len: int = 2000) -> str:
    """Free-text: trim, cap at max_len chars."""
    if value is None:
        return ""
    s = str(value).strip()
    if len(s) > max_len:
        s = s[:max_len]
    return s


def coerce_checkbox_list(values) -> list[str]:
    """Multi-value form field (checkboxes) → list of strings."""
    if not values:
        return []
    if isinstance(values, str):
        return [values]
    return [str(v) for v in values if v]