"""
The admin pages must render without reaching the public internet.

They used to load their entire layout from cdn.tailwindcss.com and every chart
from cdn.jsdelivr.net. When those were unreachable — a campus network that
blocks them, a CDN having a bad day, a laptop on a hotel connection — the admin
page did not degrade, it collapsed: no grid, no cards, nav icons at their
intrinsic size, and no charts at all.

cdn.tailwindcss.com is also a development bundle that compiles classes in the
browser on every page load. Tailwind's own documentation says not to ship it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = sorted((ROOT / "app" / "templates").glob("*.html"))
VENDOR = ROOT / "app" / "static" / "vendor"

# Fonts are allowed to come from Google: every template that asks for one also
# names a real fallback stack, so a blocked font changes the typeface and
# nothing else. Layout and charts get no such grace.
LAYOUT_CDNS = ("cdn.tailwindcss.com", "cdn.jsdelivr.net", "unpkg.com",
               "cdnjs.cloudflare.com")


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.name)
def test_no_template_loads_its_layout_or_charts_from_a_cdn(template):
    text = template.read_text(encoding="utf-8")
    for host in LAYOUT_CDNS:
        assert host not in text, (
            f"{template.name} loads from {host}; vendor it into "
            f"app/static/vendor instead so the page renders offline"
        )


def test_the_vendored_assets_are_present_and_look_right():
    css = VENDOR / "tailwind.css"
    js = VENDOR / "chart.umd.js"
    assert css.exists(), "run tools/build-tailwind.sh"
    assert js.exists(), "chart.umd.js is missing from app/static/vendor"

    body = css.read_text(encoding="utf-8")
    assert len(body) > 5_000, "the Tailwind build looks empty"
    # A handful of classes the admin pages cannot lay out without.
    for cls in (r"\.flex", r"\.grid", r"\.hidden", r"\.w-full", r"\.items-center"):
        assert re.search(cls + r"[,{ ]", body), f"{cls} missing from the build"

    assert "Chart" in js.read_text(encoding="utf-8")[:4000]


@pytest.mark.parametrize("template", [t for t in TEMPLATES
                                      if "cdn" not in t.read_text(encoding="utf-8")])
def test_every_page_that_charts_loads_the_local_chart_bundle(template):
    text = template.read_text(encoding="utf-8")
    if "new Chart(" not in text and "Chart(" not in text:
        pytest.skip("no charts on this page")
    assert "/static/vendor/chart.umd.js" in text, (
        f"{template.name} draws charts but never loads Chart.js locally"
    )
