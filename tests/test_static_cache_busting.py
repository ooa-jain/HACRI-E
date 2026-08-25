"""
A deploy has to reach the browser.

nginx serves /static with `expires 7d`, so a stylesheet the browser already
has is reused for a week. The fix for that is a URL that changes when the file
does — which `asset()` does by stamping the file's mtime.

The failure this guards against is subtler than forgetting to cache-bust: the
admin page carried hand-written stamps like `admin_shell.css?v=2`. Those only
change when a person remembers to change them, and nobody does. A deploy that
fixed the stylesheet shipped it under a URL every browser already had cached,
so the fix was live on the server and invisible in the page.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = sorted((ROOT / "app" / "templates").glob("*.html"))

# href="/static/..." or src="/static/..." written as a bare literal.
LITERAL = re.compile(r'(?:href|src)\s*=\s*"(/static/[^"]*\.(?:css|js))"')


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.name)
def test_no_stylesheet_or_script_is_linked_without_a_version_stamp(template):
    found = LITERAL.findall(template.read_text(encoding="utf-8"))
    assert not found, (
        f"{template.name} links {found} directly. Wrap it: "
        f"{{{{ asset('/static/...') }}}} — otherwise nginx's 7-day expiry keeps "
        f"the browser on the old copy after a deploy."
    )


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.name)
def test_no_template_hand_writes_a_version_number(template):
    """`?v=2` is a number somebody has to remember to bump. They will not."""
    hand = re.findall(r'(?:href|src)\s*=\s*"[^"]*\?v=\d+"',
                      template.read_text(encoding="utf-8"))
    assert not hand, f"{template.name} hand-writes a version: {hand}"


def test_the_stamp_changes_when_the_file_changes(tmp_path, monkeypatch):
    from app import main

    css = ROOT / "app" / "static" / "css" / "admin_shell.css"
    first = main.asset("/static/css/admin_shell.css")
    assert re.fullmatch(r"/static/css/admin_shell\.css\?v=\d+", first), first

    stamp = int(re.search(r"v=(\d+)", first).group(1))
    original = css.stat().st_mtime
    try:
        import os
        os.utime(css, (original + 60, original + 60))
        assert main.asset("/static/css/admin_shell.css") != first
        assert int(re.search(r"v=(\d+)",
                             main.asset("/static/css/admin_shell.css")).group(1)) > stamp
    finally:
        import os
        os.utime(css, (original, original))


def test_a_missing_file_returns_the_plain_path_rather_than_raising():
    from app import main
    assert main.asset("/static/css/not-here.css") == "/static/css/not-here.css"
