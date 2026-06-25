"""
Per-user scorecard CSV.

Columns mirror the CLI's scorecard (Pre/Post Lit/Read/Quadrant/Band plus
deltas) and additionally include every Likert item in the SCHEMA so the
student can see exactly which items moved.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from app.hacri_e2_compat import SCHEMA
from app.scoring import score_for_user

CSV_COLUMNS = [
    "Name",
    "Email",
    "PRE Literacy",
    "PRE Readiness",
    "PRE Quadrant",
    "PRE Band",
    "POST Literacy",
    "POST Readiness",
    "POST Quadrant",
    "POST Band",
    "Δ Literacy",
    "Δ Readiness",
    "Movement",
]


def _scorecard_row(name: str, email: str, pre: dict, post: dict) -> dict[str, Any]:
    pre_s = score_for_user(pre)
    post_s = score_for_user(post)
    d_lit = (
        round(post_s["lit"] - pre_s["lit"], 3)
        if (pre_s["lit"] is not None and post_s["lit"] is not None)
        else ""
    )
    d_read = (
        round(post_s["read"] - pre_s["read"], 3)
        if (pre_s["read"] is not None and post_s["read"] is not None)
        else ""
    )
    if isinstance(d_lit, float) and isinstance(d_read, float):
        if d_lit > 0 and d_read > 0:
            movement = "Champion gain (both up)"
        elif d_lit < 0 and d_read < 0:
            movement = "Decline (both down)"
        else:
            movement = "Mixed change"
    else:
        movement = "Insufficient data"

    return {
        "Name": name,
        "Email": email,
        "PRE Literacy": pre_s["lit"],
        "PRE Readiness": pre_s["read"],
        "PRE Quadrant": pre_s["quadrant"],
        "PRE Band": pre_s["band"],
        "POST Literacy": post_s["lit"],
        "POST Readiness": post_s["read"],
        "POST Quadrant": post_s["quadrant"],
        "POST Band": post_s["band"],
        "Δ Literacy": d_lit,
        "Δ Readiness": d_read,
        "Movement": movement,
    }


def _per_item_columns() -> list[str]:
    cols: list[str] = []
    for key in SCHEMA:
        cols += [f"PRE {key}", f"POST {key}", f"Δ {key}"]
    return cols


def scorecard_csv_bytes(name: str, email: str, pre: dict, post: dict) -> bytes:
    """UTF-8 CSV for one user."""
    row = _scorecard_row(name, email, pre, post)
    all_cols = CSV_COLUMNS + _per_item_columns()

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=all_cols, extrasaction="ignore")
    writer.writeheader()

    # Add per-item values
    for key in SCHEMA:
        pv = pre.get(key)
        ov = post.get(key)
        try:
            pv_n = int(pv) if pv not in (None, "") else ""
            ov_n = int(ov) if ov not in (None, "") else ""
            d = (ov_n - pv_n) if isinstance(pv_n, int) and isinstance(ov_n, int) else ""
        except (TypeError, ValueError):
            pv_n, ov_n, d = "", "", ""
        row[f"PRE {key}"] = pv_n
        row[f"POST {key}"] = ov_n
        row[f"Δ {key}"] = d

    writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def cohort_csv_bytes(users_list: list[dict], pre_docs: list[dict], post_docs: list[dict]) -> bytes:
    """UTF-8 CSV for the entire cohort."""
    pre_map = {doc["email"]: doc.get("fields", {}) for doc in pre_docs}
    post_map = {doc["email"]: doc.get("fields", {}) for doc in post_docs}

    all_cols = CSV_COLUMNS + _per_item_columns()
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=all_cols, extrasaction="ignore")
    writer.writeheader()

    for u in users_list:
        email = u["email"]
        name = u.get("name", "")
        pre = pre_map.get(email, {})
        post = post_map.get(email, {})

        row = _scorecard_row(name, email, pre, post)

        # Add per-item values
        for key in SCHEMA:
            pv = pre.get(key)
            ov = post.get(key)
            try:
                pv_n = int(pv) if pv not in (None, "") else ""
                ov_n = int(ov) if ov not in (None, "") else ""
                d = (ov_n - pv_n) if isinstance(pv_n, int) and isinstance(ov_n, int) else ""
            except (TypeError, ValueError):
                pv_n, ov_n, d = "", "", ""
            row[f"PRE {key}"] = pv_n
            row[f"POST {key}"] = ov_n
            row[f"Δ {key}"] = d

        writer.writerow(row)

    return buf.getvalue().encode("utf-8")