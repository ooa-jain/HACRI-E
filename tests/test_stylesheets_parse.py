"""
Every stylesheet must parse.

A single unclosed brace does not fail loudly — the browser silently discards
every rule after it. Half a design system stops applying and the page still
renders, just wrong, which is a slow and confusing thing to debug by eye.
This catches it in a second instead.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

CSS = sorted((Path(__file__).resolve().parents[1] / "app" / "static").rglob("*.css"))


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


@pytest.mark.parametrize("sheet", CSS, ids=lambda p: p.name)
def test_braces_balance(sheet):
    body = _strip_comments(sheet.read_text(encoding="utf-8"))
    opened, closed = body.count("{"), body.count("}")
    assert opened == closed, (
        f"{sheet.name}: {opened} '{{' against {closed} '}}'. Everything after the "
        f"unbalanced one is dropped by the browser without an error."
    )


@pytest.mark.parametrize("sheet", CSS, ids=lambda p: p.name)
def test_the_sheet_parses_without_error(sheet):
    """Brace counting catches the common break; a real parser catches the rest
    — a bad at-rule, a stray token, a rule with no declarations."""
    tinycss2 = pytest.importorskip("tinycss2")

    rules = tinycss2.parse_stylesheet(
        sheet.read_text(encoding="utf-8"),
        skip_comments=True, skip_whitespace=True)
    errors = [r for r in rules if r.type == "error"]
    assert not errors, (
        f"{sheet.name}: " + "; ".join(f"line {e.source_line}: {e.message}"
                                      for e in errors[:5])
    )

    # A qualified rule with an empty body is the shape a half-finished edit
    # leaves behind.
    empty = [r for r in rules
             if r.type == "qualified-rule"
             and not tinycss2.parse_blocks_contents(r.content)]
    assert not empty, (
        f"{sheet.name}: rule(s) with no declarations at line(s) "
        + ", ".join(str(r.source_line) for r in empty[:5])
    )


def test_the_admin_sheet_still_defines_what_the_pages_need():
    """A truncated sheet parses fine up to the break, so also check the rules
    that live near the end of the file are actually present."""
    body = (Path(__file__).resolve().parents[1]
            / "app" / "static" / "css" / "admin_shell.css").read_text(encoding="utf-8")
    for selector in ("body.admin-shell .field",
                     "body.admin-shell .search-wrap .field",
                     "body.admin-shell .btn",
                     "body.admin-shell #toast",
                     "#nav .nav-btn"):
        assert selector in body, f"{selector} is missing from admin_shell.css"
