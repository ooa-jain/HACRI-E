"""
Tests for app/scoring.py and app/csv_export.py.

These should produce identical results to the CLI for the same fields dict.
"""

from __future__ import annotations

import csv
import io

import pytest

from app.csv_export import scorecard_csv_bytes
from app.hacri_e2_compat import SCHEMA
from app.scoring import delta, is_complete_post, is_complete_pre, score_for_user


def _all_items(value: int) -> dict:
    """Build a fields dict with every Likert item set to `value` (1-5)."""
    return {k: value for k in SCHEMA}


def test_score_for_user_all_3():
    fields = _all_items(3)
    s = score_for_user(fields)
    assert s["lit"] == pytest.approx(3.0)
    assert s["read"] == pytest.approx(3.0)
    # 3,3 → Q4 (sceptic) — lit>=3 read<3 is Q4? actually lit>=3 read>=3 is Q1.
    # Per the plotter: lit>=3 and read>=3 → Q1 Champion.
    assert s["quadrant"] == "Q1: AI Champion"


def test_score_for_user_all_5():
    fields = _all_items(5)
    s = score_for_user(fields)
    # Lit uses no reversed items, so lit = 5.0
    assert s["lit"] == pytest.approx(5.0)
    # Read includes D2 (reversed) so 4 items contribute 1 instead of 5.
    from app.hacri_e2_compat import READ_ITEMS, REVERSED
    n_read = len(READ_ITEMS)
    n_rev = sum(1 for k in READ_ITEMS if k in REVERSED)
    expected_read = (5 * (n_read - n_rev) + 1 * n_rev) / n_read
    assert s["read"] == pytest.approx(expected_read, rel=1e-3)


def test_score_for_user_d2_reversed():
    # D2 items are reverse-scored: raw 1 → effective 5, raw 5 → effective 1
    fields = {k: 3 for k in SCHEMA}
    # Set all D2 items to 1 (worst anxiety). After reversal they contribute 5.
    for k in ("D2a", "D2b", "D2c", "D2d"):
        fields[k] = 1
    s = score_for_user(fields)
    # The 4 D2 items now contribute 5 instead of 3.
    # Their weight in READ_ITEMS is 4 out of len(READ_ITEMS).
    from app.hacri_e2_compat import READ_ITEMS
    n = len(READ_ITEMS)
    expected_read = (3 * (n - 4) + 5 * 4) / n
    assert s["read"] == pytest.approx(expected_read, rel=1e-3)


def test_score_for_user_missing_items_excluded():
    # Provide only the B items (literacy stratum). Lit is computable on them,
    # read has no items → read is None.
    b_items = [k for k in SCHEMA if k.startswith("B")]
    fields = {k: 5 for k in b_items}
    s = score_for_user(fields)
    assert s["lit"] == pytest.approx(5.0)
    assert s["read"] is None


def test_score_for_user_all_missing_returns_none():
    s = score_for_user({})
    assert s["lit"] is None
    assert s["read"] is None


def test_delta_pre_post_growth():
    pre = _all_items(3)
    post = _all_items(4)
    d = delta(pre, post)
    assert d["delta_lit"] == pytest.approx(1.0)
    # Read includes reversed D2: pre (3→5) and post (4→4). Delta is reversed too.
    from app.hacri_e2_compat import READ_ITEMS, REVERSED
    n_read = len(READ_ITEMS)
    n_rev = sum(1 for k in READ_ITEMS if k in REVERSED)
    pre_rev = (3 * (n_read - n_rev) + 5 * n_rev) / n_read
    post_rev = (4 * (n_read - n_rev) + 4 * n_rev) / n_read
    expected_delta = post_rev - pre_rev
    assert d["delta_read"] == pytest.approx(round(expected_delta, 3), rel=1e-2)
    # Movement label depends on sign — should be growth, not decline
    assert "growth" in d["movement"].lower() or "gain" in d["movement"].lower()


def test_is_complete_pre_and_post():
    fields = _all_items(3)
    assert is_complete_pre(fields) is True
    assert is_complete_post(fields) is True

    partial = {k: 3 for k in list(SCHEMA.keys())[:10]}
    assert is_complete_pre(partial) is False


def test_scorecard_csv_has_headers_and_row():
    pre = _all_items(3)
    post = _all_items(4)
    csv_bytes = scorecard_csv_bytes("Alice", "alice@example.com", pre, post)
    text = csv_bytes.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    assert len(rows) == 1
    row = rows[0]
    assert row["Name"] == "Alice"
    assert row["Email"] == "alice@example.com"
    # Lit is the simple average — B/D/E/F/G all 3 / 4 → 3.0 / 4.0
    assert float(row["PRE Literacy"]) == pytest.approx(3.0)
    assert float(row["POST Literacy"]) == pytest.approx(4.0)
    # Spot-check per-item columns
    assert row["PRE B1"] == "3"
    assert row["POST B1"] == "4"
    assert row["Δ B1"] == "1"