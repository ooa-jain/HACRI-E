"""
Pure scoring helpers over a flat fields dict.

All HACRI-E2 rules live in `app/hacri_e2_compat.py`; this module just
combines them with movement / delta calculations and completeness checks.
"""

from __future__ import annotations

from typing import Any

from app.hacri_e2_compat import band, quadrant, score_likert


def score_for_user(fields: dict[str, Any]) -> dict[str, Any]:
    """
    Return {lit, read, quadrant, band} for a fields dict.
    Either score may be None if all relevant items were skipped.
    """
    lit = score_likert(fields, "L")
    read = score_likert(fields, "R")
    return {
        "lit": lit,
        "read": read,
        "quadrant": quadrant(lit, read),
        "band": band(lit, read),
    }


def delta(pre_fields: dict, post_fields: dict) -> dict[str, Any]:
    """Pre vs Post summary with movement label."""
    pre = score_for_user(pre_fields)
    post = score_for_user(post_fields)

    d_lit = (
        round(post["lit"] - pre["lit"], 3)
        if (pre["lit"] is not None and post["lit"] is not None)
        else None
    )
    d_read = (
        round(post["read"] - pre["read"], 3)
        if (pre["read"] is not None and post["read"] is not None)
        else None
    )

    if d_lit is not None and d_read is not None:
        if d_lit > 0 and d_read > 0:
            movement = "Champion gain (both up)"
        elif d_lit < 0 and d_read < 0:
            movement = "Decline (both down)"
        elif d_lit >= 0 and d_read >= 0:
            movement = "Mixed growth"
        elif d_lit <= 0 and d_read <= 0:
            movement = "Mixed decline"
        else:
            movement = "Mixed change"
    else:
        movement = "Insufficient data"

    return {
        "pre": pre,
        "post": post,
        "delta_lit": d_lit,
        "delta_read": d_read,
        "movement": movement,
    }


def is_complete_pre(fields: dict[str, Any]) -> bool:
    """All Likert items that contribute to a score are present (B, D, E, F, G)."""
    from app.hacri_e2_compat import SCHEMA
    return all(fields.get(k) is not None for k in SCHEMA)


def is_complete_post(fields: dict[str, Any]) -> bool:
    from app.hacri_e2_compat import SCHEMA
    return all(fields.get(k) is not None for k in SCHEMA)