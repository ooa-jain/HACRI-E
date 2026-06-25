"""
Drift guard: the SCHEMA and option lists exposed by app/hacri_e2_compat.py
must match the ones in hacri_e2_plotter.py. If you ever add a new Likert
item to the CLI, this test forces you to consider the web form.
"""

from __future__ import annotations

from app.hacri_e2_compat import (
    H1_OPTIONS,
    H2_LABELS,
    H3_OPTIONS,
    REVERSED,
    SCHEMA,
)
from hacri_e2_plotter import (
    H1_OPTIONS as CLI_H1,
    H2_LABELS as CLI_H2,
    H3_OPTIONS as CLI_H3,
    REVERSED as CLI_REVERSED,
    SCHEMA as CLI_SCHEMA,
)


def test_schema_matches_cli():
    assert set(SCHEMA.keys()) == set(CLI_SCHEMA.keys())
    assert dict(SCHEMA) == dict(CLI_SCHEMA)


def test_reversed_matches_cli():
    assert REVERSED == CLI_REVERSED


def test_h_option_lists_match_cli():
    assert H1_OPTIONS == CLI_H1
    assert H2_LABELS == CLI_H2
    assert H3_OPTIONS == CLI_H3


def test_schema_includes_expected_likert_items():
    # Sanity: all four sections that contribute to Lit/Read are present
    expected_sections = ("B", "D", "E", "F", "G")
    for sec in expected_sections:
        assert any(k.startswith(sec) for k in SCHEMA), f"Section {sec} missing"


def test_d2_reversed():
    for k in ("D2a", "D2b", "D2c", "D2d"):
        assert k in REVERSED, f"{k} should be reverse-scored"