"""
The department meeting pack — the count, the two call-out lists, every
department's own question-by-question reading, and the PDF of all three.

Eleven students, by hand, so every number below is known before the code runs:

  Law        Asha, Bela, Cara, Dev registered; Asha, Bela, Cara took it  → 3/4 = 75%
  Commerce   Esha, Farid registered; both took it                       → 2/2 = 100%
  Design     Gita, Hari, Ira registered; Gita took it                    → 1/3 = 33.3%
  Science    Jai, Kiran registered; neither took it                      → 0/2 = 0%

  registered = 11, took = 6, conversion = 54.5%

Kiran never started the baseline either — which is the point of building the
count off the registration portal rather than the orientation dashboard's own
eligible pool: Kiran still counts as registered here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app import db


@pytest_asyncio.fixture
async def app_with_mock():
    db._set_client_for_tests(AsyncMongoMockClient())
    try:
        from app.main import app
        await db.init_indexes(allow_duplicate_email=True)
        yield app
    finally:
        db._reset_clients_for_tests()


@pytest_asyncio.fixture
async def admin_client(app_with_mock) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app_with_mock)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.cookies.set("survey_admin_session", "1")
        yield ac


@pytest_asyncio.fixture
async def client(app_with_mock) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app_with_mock)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# Six replies, written so each question's answer is arithmetic rather than
# atmosphere. Three students are glowing, two are middling, one is unhappy.
GLOWING = {
    "location": "📍 Bangalore",
    "q1": ["🔥 Inspiring", "🚀 Exciting"],
    "q2": 9,
    "q3": "🤗 Absolutely yes!",
    "q5": "Super easy",                 # emoji-picker: stored without the emoji
    "q7": ["✅ Nothing — it was smooth!"],
    "q8": {"🏛️ University overview": "✅ Yes", "🏫 My School & Department": "✅ Yes"},
    "q11": ["🏛️ University Overview & Vision", "🎪 Student Club Fair"],
    "q12": ["🚶 Campus Tour"],
    "q28": ["🤯 Information overload in one day"],
    "q34": 10,
    "q35": "Absolutely loved it",
    "q36": ["🌟 Great overall experience"],
}
MIDDLING = {
    "location": "📍 Bangalore",
    "q1": ["😵 Overwhelming"],
    "q2": 6,
    "q3": "😐 Neutral",
    "q5": "Okay",
    "q7": ["📚 Information was too much at once"],
    "q8": {"🏛️ University overview": "🤔 Somewhat", "🏫 My School & Department": "✅ Yes"},
    "q11": ["🎪 Student Club Fair"],
    "q12": ["🚶 Campus Tour", "🎭 Cultural Programme"],
    "q28": ["🤯 Information overload in one day", "⏳ Too many long sessions"],
    "q34": 7,
    "q35": "It was okay",
    "q36": ["📋 Programme needs more clarity"],
}
UNHAPPY = {
    "location": "📍 Bangalore",
    "q1": ["😴 Boring"],
    "q2": 3,
    "q3": "😞 Not at all",
    "q5": "Very hard",
    "q7": ["💻 Tech systems were confusing"],
    "q11": ["🤝 Mentor Meet"],
    "q12": ["🚶 Campus Tour"],
    "q28": ["⏳ Too many long sessions"],
    "q34": 4,
    "q35": "Not great",
    "q36": ["😐 Sessions were not engaging enough"],
}

PEOPLE = [
    # email, name, department, took Deeksharambh, the answers they gave, baseline
    ("asha@x.com",  "Asha",  "Department of Law",      GLOWING,  True),
    ("bela@x.com",  "Bela",  "Department of Law",      GLOWING,  True),
    ("cara@x.com",  "Cara",  "Department of Law",      MIDDLING, True),
    ("dev@x.com",   "Dev",   "Department of Law",      None,     True),
    ("esha@x.com",  "Esha",  "Department of Commerce", GLOWING,  True),
    ("farid@x.com", "Farid", "Department of Commerce", UNHAPPY,  True),
    ("gita@x.com",  "Gita",  "Department of Design",   MIDDLING, True),
    ("hari@x.com",  "Hari",  "Department of Design",   None,     True),
    ("ira@x.com",   "Ira",   "Department of Design",   None,     True),
    ("jai@x.com",   "Jai",   "Department of Science",  None,     True),
    ("kiran@x.com", "Kiran", "Department of Science",  None,     False),
]


async def _seed() -> None:
    now = datetime.now(timezone.utc)
    for i, (email, name, program, answers, baseline) in enumerate(PEOPLE):
        await db.get_db()["users"].insert_one({
            "email": email, "name": name, "program": program, "ug_or_pg": "ug",
            "location": "Bangalore",
            "status": db.STATUS_PRE_DONE if baseline else None,
            "created_at": now, "pre_submitted_at": now if baseline else None,
        })
        if baseline:
            await db.get_db()["pre_responses"].insert_one(
                {"email": email, "submitted_at": now, "fields": {}})
        if answers:
            await db.get_db()["orientation_responses"].insert_one({
                "email": email, "name": name,
                "submitted_at": now - timedelta(hours=i), "data": answers,
            })


# ── The count ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_count_runs_from_the_portal_not_from_the_baseline(app_with_mock):
    await _seed()
    from app.deeksharambh_meeting import meeting_pack

    pack = await meeting_pack()
    totals = pack["totals"]
    assert totals["registered"] == 11          # Kiran included: never did the baseline
    assert totals["took"] == 6
    assert totals["missing"] == 5
    assert totals["pct"] == 54.5
    assert totals["departments"] == 4
    assert totals["unmatched"] == 0

    rows = {r["dept"]: r for r in pack["conversion"]}
    assert (rows["Department of Commerce"]["took"],
            rows["Department of Commerce"]["registered"],
            rows["Department of Commerce"]["pct"]) == (2, 2, 100.0)
    assert (rows["Department of Law"]["took"],
            rows["Department of Law"]["registered"],
            rows["Department of Law"]["pct"]) == (3, 4, 75.0)
    assert rows["Department of Design"]["pct"] == 33.3
    assert rows["Department of Science"]["pct"] == 0.0
    assert rows["Department of Science"]["missing"] == 2

    # Each department's registered total is its own students and nobody else's.
    assert sum(r["registered"] for r in pack["conversion"]) == totals["registered"]
    assert sum(r["took"] for r in pack["conversion"]) == totals["took"]


@pytest.mark.asyncio
async def test_top_and_least_are_ranked_on_that_conversion(app_with_mock):
    await _seed()
    from app.deeksharambh_meeting import meeting_pack

    callouts = (await meeting_pack())["callouts"]
    assert [r["dept"] for r in callouts["top"]][:4] == [
        "Department of Commerce", "Department of Law",
        "Department of Design", "Department of Science",
    ]
    # Worst first — the order they get chased in.
    assert [r["dept"] for r in callouts["least"]][:4] == [
        "Department of Science", "Department of Design",
        "Department of Law", "Department of Commerce",
    ]
    # Four departments cannot fill a top five and a bottom five, and the pack
    # says which names are being read out twice rather than implying ten.
    assert callouts["ranked"] == 4
    assert callouts["overlap"] == sorted(r["dept"] for r in callouts["top"])


def test_departments_level_on_percentage_are_split_by_their_size():
    from app.deeksharambh_meeting import conversion_rows

    rows = conversion_rows(
        [{"program": "Big", "campus": "Bangalore", "orientation": True}] * 40
        + [{"program": "Small", "campus": "Bangalore", "orientation": True}] * 4
    )
    assert [r["dept"] for r in rows] == ["Big", "Small"]
    assert rows[0]["pct"] == rows[1]["pct"] == 100.0


# ── The department reading ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_every_question_is_printed_for_every_department(app_with_mock):
    await _seed()
    from app.deeksharambh_meeting import meeting_pack
    from app.orientation_analysis import QUESTIONS, SECTIONS

    pack = await meeting_pack()
    assert [d["dept"] for d in pack["departments"]] == [
        r["dept"] for r in pack["conversion"]
    ]

    for dept in pack["departments"]:
        # Every section, and inside them every question the form asks — not
        # only the ones this department happened to answer.
        assert [s["title"] for s in dept["sections"]] == [t for t, _ in SECTIONS]
        keys = [q["key"] for s in dept["sections"] for q in s["questions"]]
        assert keys == list(QUESTIONS)
        for q in (q for s in dept["sections"] for q in s["questions"]):
            assert len(q["picks"]) <= pack["picks"]

    # Science answered nothing, and still gets a section saying exactly that.
    science = next(d for d in pack["departments"] if d["dept"] == "Department of Science")
    assert science["responses"] == 0
    assert science["registered"] == 2
    assert all(q["answered"] == 0
               for s in science["sections"] for q in s["questions"])


@pytest.mark.asyncio
async def test_the_two_answers_come_from_the_good_end(app_with_mock):
    await _seed()
    from app.deeksharambh_meeting import meeting_pack

    pack = await meeting_pack()
    law = next(d for d in pack["departments"] if d["dept"] == "Department of Law")
    q = {q["key"]: q for s in law["sections"] for q in s["questions"]}

    # Law: Asha and Bela glowing, Cara middling. Q3's positive answers are the
    # top two rungs of the agreement scale, so Cara's "Neutral" is not picked.
    assert q["q3"]["frame"] == "positive"
    assert [p["label"] for p in q["q3"]["picks"]] == ["🤗 Absolutely yes!"]
    assert q["q3"]["picks"][0]["count"] == 2

    # Q1 splits into an upbeat set and a critical set in the form itself; only
    # the upbeat labels are eligible, and Cara's "Overwhelming" is not one.
    assert {p["label"] for p in q["q1"]["picks"]} == {"🔥 Inspiring", "🚀 Exciting"}

    # Q5 is stored without its emoji by the emoji picker; the curated list
    # carries the emoji. They still have to match.
    assert [p["label"] for p in q["q5"]["picks"]] == ["Super easy"]
    assert q["q5"]["picks"][0]["count"] == 2

    # Sliders: the good end of a 1-10 scale is 8, 9, 10 — Cara's 6 is not shown.
    assert [p["label"] for p in q["q2"]["picks"]] == ["9"]
    assert q["q2"]["avg"] == 8.0
    # NPS: only promoters, so Cara's 7 (a passive) is not a pick.
    assert [p["label"] for p in q["q34"]["picks"]] == ["10"]

    # A question with no bad answer to exclude is simply the two most-chosen.
    assert q["q11"]["frame"] == "top"
    assert [p["label"] for p in q["q11"]["picks"]] == [
        "🎪 Student Club Fair", "🏛️ University Overview & Vision"]

    # A question that only ever asked what went wrong is shown as asks, not
    # dressed up as good news.
    assert q["q12"]["frame"] == "asked"
    assert q["q12"]["frame_label"].startswith("Top 2 asks")
    assert [p["label"] for p in q["q12"]["picks"]][0] == "🚶 Campus Tour"
    assert q["q28"]["frame"] == "asked"

    # The matrix questions keep one line per statement, each with its own picks.
    assert q["q8"]["kind"] == "matrix"
    assert {r["label"] for r in q["q8"]["rows"]} == {
        "🏛️ University overview", "🏫 My School & Department"}
    overview = next(r for r in q["q8"]["rows"] if r["label"] == "🏛️ University overview")
    assert [p["label"] for p in overview["picks"]] == ["✅ Yes"]
    assert overview["picks"][0]["count"] == 2


@pytest.mark.asyncio
async def test_a_department_with_nothing_good_to_report_says_so(app_with_mock):
    await _seed()
    from app.deeksharambh_meeting import meeting_pack

    pack = await meeting_pack()
    commerce = next(d for d in pack["departments"] if d["dept"] == "Department of Commerce")
    q = {q["key"]: q for s in commerce["sections"] for q in s["questions"]}

    # Esha glowing, Farid unhappy. Q3 has one positive answer between them and
    # the report shows that one rather than padding it with "Not at all".
    assert [p["label"] for p in q["q3"]["picks"]] == ["🤗 Absolutely yes!"]
    assert q["q3"]["answered"] == 2
    # Both students answered Q35, but only one from the good end.
    assert q["q35"]["answered"] == 2
    assert [p["label"] for p in q["q35"]["picks"]] == ["Absolutely loved it"]


@pytest.mark.asyncio
async def test_percentages_are_of_the_students_who_answered_that_question(app_with_mock):
    await _seed()
    from app.deeksharambh_meeting import meeting_pack

    pack = await meeting_pack()
    law = next(d for d in pack["departments"] if d["dept"] == "Department of Law")
    q = {q["key"]: q for s in law["sections"] for q in s["questions"]}

    # Three of Law's four registered students answered; two of those three said
    # "Absolutely yes!" — 66.7% of the answerers, not 50% of the department.
    assert law["responses"] == 3
    assert q["q3"]["answered"] == 3
    assert q["q3"]["picks"][0]["pct"] == 66.7

    # A combined figure is only offered where the options were exclusive and
    # there are two of them to combine. Q3 picked one answer, so there is
    # nothing to add up.
    assert q["q3"]["share"] is None

    # Q1 let a student tick both "Inspiring" and "Exciting", and two of them
    # did — adding those two 66.7%s would claim 133.4% of three students, so
    # a multi-select never carries a combined share.
    assert q["q1"]["kind"] == "multi"
    assert len(q["q1"]["picks"]) == 2
    assert q["q1"]["share"] is None
    assert all(x["share"] is None
               for s in law["sections"] for x in s["questions"]
               if x["kind"] == "multi")

    # The matrix rows do add up: one answer per statement per student.
    overview = next(r for r in q["q8"]["rows"] if r["label"] == "🏛️ University overview")
    assert overview["picks"][0]["pct"] == 66.7


@pytest.mark.asyncio
async def test_a_reply_with_no_registration_is_counted_and_declared(app_with_mock):
    await _seed()
    await db.get_db()["orientation_responses"].insert_one({
        "email": "ghost@x.com", "name": "Ghost",
        "submitted_at": datetime.now(timezone.utc), "data": GLOWING,
    })
    from app.deeksharambh_meeting import meeting_pack

    pack = await meeting_pack()
    # The conversion cannot hold a student the portal never registered, so the
    # totals stay put and the pack says how many replies sit outside them.
    assert pack["totals"]["registered"] == 11
    assert pack["totals"]["took"] == 6
    assert pack["totals"]["unmatched"] == 1

    ghost = next(d for d in pack["departments"] if d["dept"] == "No department")
    assert ghost["responses"] == 1
    assert ghost["registered"] == 0


@pytest.mark.asyncio
async def test_one_campus_narrows_both_halves_of_the_pack(app_with_mock):
    await _seed()
    await db.get_db()["users"].insert_one({
        "email": "lata@x.com", "name": "Lata", "program": "Department of Arts",
        "ug_or_pg": "ug", "location": "Kochi", "status": db.STATUS_PRE_DONE,
        "created_at": datetime.now(timezone.utc),
    })
    from app.deeksharambh_meeting import meeting_pack

    pack = await meeting_pack(campus="Kochi")
    assert pack["campus"] == "Kochi"
    assert pack["totals"]["registered"] == 1
    assert [r["dept"] for r in pack["conversion"]] == ["Department of Arts"]
    assert [d["dept"] for d in pack["departments"]] == ["Department of Arts"]


# ── The link ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_admin_link_prints_every_department_in_full(admin_client):
    await _seed()
    r = await admin_client.get("/admin/survey/deeksharambh-meeting")
    assert r.status_code == 200
    page = r.text

    for dept in ("Department of Law", "Department of Commerce",
                 "Department of Design", "Department of Science"):
        assert page.count(dept) >= 2      # the count table and its own section

    # The count itself.
    assert "Registered in portal" in page
    assert ">11<" in page and ">6<" in page and ">54.5%<" in page

    # Both call-out lists.
    assert "Top 4 by conversion" in page
    assert "Least 4 by conversion" in page

    # Every question, for every department — 41 questions across 4 departments,
    # minus Science which answered nothing and says so instead.
    from app.orientation_analysis import QUESTIONS
    for key in QUESTIONS:
        assert f">{key.upper()}<" in page

    # Nothing on the page can be folded shut.
    assert "<details" not in page
    assert "No Deeksharambh replies from this department yet" in page
    assert "Download PDF" in page

    # The combined figure appears only under exclusive-choice questions, so no
    # line on the page can claim more than 100% of the students who answered.
    import re
    for share in re.findall(r"Between them, ([\d.]+)% of the", page):
        assert float(share) <= 100.0, share


@pytest.mark.asyncio
async def test_the_meeting_link_is_admin_only_until_it_is_shared(client, admin_client):
    await _seed()
    assert (await client.get("/admin/survey/deeksharambh-meeting")).status_code == 403
    assert (await client.get("/admin/survey/deeksharambh-meeting.pdf")).status_code == 403

    # No token, a wrong token, and a token minted for another campus all fail.
    from app.routes.shared_analysis import get_meeting_token

    assert (await client.get("/shared/deeksharambh-meeting")).status_code == 422
    assert (await client.get(
        "/shared/deeksharambh-meeting?token=nope")).status_code == 403
    assert (await client.get(
        "/shared/deeksharambh-meeting"
        f"?campus=Bangalore&token={get_meeting_token('Kochi')}")).status_code == 403

    # An orientation link already handed out does not quietly open this one.
    from app.routes.shared_analysis import get_orientation_token

    assert (await client.get(
        "/shared/deeksharambh-meeting"
        f"?token={get_orientation_token('')}")).status_code == 403

    good = await client.get(f"/shared/deeksharambh-meeting?token={get_meeting_token('')}")
    assert good.status_code == 200
    assert "Department of Law" in good.text


# ── The PDF ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_pdf_carries_the_whole_pack(admin_client):
    await _seed()
    r = await admin_client.get("/admin/survey/deeksharambh-meeting.pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert "Department_Meeting_Pack" in r.headers["content-disposition"]
    assert r.content.startswith(b"%PDF-")

    from io import BytesIO

    from pypdf import PdfReader

    pages = PdfReader(BytesIO(r.content)).pages
    # A cover, the count, the call-outs and one page-break per department: this
    # is a document, not a one-pager.
    assert len(pages) >= 6
    text = "\n".join(page.extract_text() or "" for page in pages)

    assert "Department meeting pack" in text
    for dept in ("Department of Law", "Department of Commerce",
                 "Department of Design", "Department of Science"):
        assert dept in text
    # The count, and both call-out lists.
    assert "REGISTERED IN PORTAL" in text and "54.5%" in text
    assert "Top 4 by conversion" in text
    assert "Least 4 by conversion" in text
    # Questions carried across, with their labels intact once the emoji that no
    # PDF core font can set are dropped.
    assert "Felt welcomed during Deeksharambh" in text
    assert "Absolutely yes!" in text
    assert "Sessions that need the most improvement" in text
    assert "Top 2 asks" in text
    # Page furniture.
    assert "Page 1" in text


@pytest.mark.asyncio
async def test_the_shared_pdf_is_the_same_document(client):
    await _seed()
    from app.routes.shared_analysis import get_meeting_token

    r = await client.get(
        f"/shared/deeksharambh-meeting.pdf?token={get_meeting_token('')}")
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF-")
    assert (await client.get(
        "/shared/deeksharambh-meeting.pdf?token=nope")).status_code == 403


@pytest.mark.asyncio
async def test_the_pdf_survives_an_empty_cohort(admin_client):
    r = await admin_client.get("/admin/survey/deeksharambh-meeting.pdf")
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF-")

    page = await admin_client.get("/admin/survey/deeksharambh-meeting")
    assert page.status_code == 200
    assert "No students registered in this scope yet" in page.text


def test_an_exclusive_question_with_two_picks_does_carry_a_combined_share():
    """The other half of the rule above: where the options really were
    exclusive and two of them were picked, adding them up is the honest
    summary and the pack says so."""
    from app.deeksharambh_meeting import question_picks
    from app.orientation_analysis import summarize_orientation

    # Four students rate the vibe 10, 9, 9 and 4. The good end of the scale is
    # 8-10, so the two picks are "9" (2 of 4) and "10" (1 of 4).
    report = summarize_orientation([{"q2": v} for v in (10, 9, 9, 4)])
    q = {q["key"]: q for s in question_picks(report) for q in s["questions"]}

    assert [p["label"] for p in q["q2"]["picks"]] == ["9", "10"]
    assert [p["pct"] for p in q["q2"]["picks"]] == [50.0, 25.0]
    assert q["q2"]["share"] == 75.0      # three of the four, and no more
    assert q["q2"]["avg"] == 8.0


# ── The page's shape ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_every_department_is_in_the_page_even_though_one_shows_at_a_time(admin_client):
    """The explorer answers "stop making me scroll" without hiding anything.

    Only one department is on screen, but all of them are in the document —
    so Ctrl+F, the rail, screen readers, printing and the PDF all still reach
    every one. A department behind a click is fine; a department missing from
    the page is not.
    """
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    # Four departments rendered, exactly one of them marked visible.
    assert page.count('class="dept ') + page.count('class="dept"') == 4
    assert page.count('class="dept on"') == 1

    # And every one is reachable from the rail, with its conversion on it.
    for dept in ("Department of Commerce", "Department of Law",
                 "Department of Design", "Department of Science"):
        assert f'data-name="{dept.lower()}"' in page

    # Nothing is inside a collapsed element.
    assert "<details" not in page

    # Print puts them all back — this rule is the whole guarantee.
    assert ".dept { display: block !important" in page


@pytest.mark.asyncio
async def test_the_page_charts_from_the_vendored_bundle_not_a_cdn(admin_client):
    """The campus network blocks CDNs; the charts have to survive that."""
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    assert "/static/vendor/chart.umd.js" in page
    for host in ("cdn.jsdelivr.net", "cdnjs.cloudflare.com", "unpkg.com"):
        assert host not in page


@pytest.mark.asyncio
async def test_the_carousel_reads_the_same_rows_the_tables_print(admin_client):
    """The spotlight is a view of the call-out lists, never a second copy.

    Both are rendered from `callouts`, so a department cannot lead the
    carousel while the table under it says something else — and the tables
    survive into print, where the carousel is dropped.
    """
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    # The carousel's data is handed over as JSON from the same structure.
    assert '"dept": "Department of Commerce"' in page or \
           '"dept":"Department of Commerce"' in page
    # Both plain tables are present for the reader and the printer.
    assert "Top 4 by conversion" in page
    assert "Least 4 by conversion" in page
    assert ".dc-shell, .rail, .no-print" in page   # dropped when printing


@pytest.mark.asyncio
async def test_the_hero_photo_is_served_locally_and_dropped_when_printing(admin_client):
    """The campus behind the hero is an asset of this app, not a hotlink, and
    it is chrome: paper gets the words, not a full-bleed photograph."""
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    # Served from our own /static, cache-stamped like every other asset.
    assert "/static/img/campus-hero.jpg?v=" in page
    assert "http://" not in page.split("<style>")[1].split("</style>")[0]

    # And it really is on disk, or the page would render a broken frame.
    from pathlib import Path
    from app.main import BASE_DIR
    photo = Path(BASE_DIR) / "static" / "img" / "campus-hero.jpg"
    assert photo.is_file() and photo.stat().st_size > 20_000

    # Print drops it — the rule also hides the seam gradient now, so this
    # checks the print block rather than one exact declaration.
    print_block = page.split("@media print {")[1]
    assert ".se-media" in print_block.split("@page")[0]
    assert "display: none" in print_block.split(".se-media")[1][:80]


@pytest.mark.asyncio
async def test_the_hero_cannot_clip_its_own_buttons(admin_client):
    """A fixed-height frame cut the Download PDF row off on a short laptop.

    The fix is that the frame's height is a floor, not a size: the scroll
    interpolates `min-height` while `height` stays `auto`, so at any progress
    value on any screen the frame grows to whatever the headline, the pill and
    the button row need. That is also what let the expand come back on mobile,
    where it had been switched off to dodge this very bug.
    """
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    frame = page.split(".se-frame {")[1].split("}")[0]
    assert "height: auto;" in frame
    assert "min-height: calc(var(--h0) + (100vh - var(--h0)) * var(--p, 0));" in frame
    # svh too, so a phone's URL bar hiding does not resize the frame
    # mid-animation — the vh line above it is the fallback.
    assert "min-height: calc(var(--h0) + (100svh - var(--h0)) * var(--p, 0));" in frame
    # No fixed height anywhere in the frame's own rule (min-height is not
    # a fixed height, so the check has to exclude it).
    import re
    assert re.search(r"(?<!min-)height: calc\(", frame) is None


@pytest.mark.asyncio
async def test_the_hero_expands_on_a_phone_too(admin_client):
    """It was switched off below 640px to dodge the clipping bug above. Now
    that the frame cannot clip, the only reader handed the opened state
    outright is one who asked for less motion."""
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    # No width breakpoint stands the animation down any more.
    assert "window.matchMedia('(max-width: 640px)')" not in page
    assert "function isStatic() { return REDUCED; }" in page
    # The phone rule opens from a sensible inset instead of a letterbox.
    assert "width: calc(86% + (100% - 86%) * var(--pw, 0))" in page
    assert "@media (prefers-reduced-motion: reduce)" in page


@pytest.mark.asyncio
async def test_the_hero_backdrop_is_clipped_on_every_screen(admin_client):
    """The campus also fills the plate the frame sits on, and must stay in it.

    The backdrop is an absolutely positioned layer inset past its box, so it
    is only contained by an ancestor that establishes a containing block.
    A phone rule once made that ancestor `static`, the layer escaped
    `overflow: hidden`, and its negative inset pushed the page 44px sideways.
    The plate is sticky at every width now, so it is always a containing
    block — this pins the clip and the positioning that makes it work.
    """
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    sticky = page.split(".se-sticky {")[1].split("}")[0]
    assert "position: sticky" in sticky and "overflow: hidden" in sticky
    # Every on-screen rule for the plate keeps it a containing block. Print
    # is exempt: there the backdrop is display:none, so it has nothing to
    # escape from.
    screen_css = page.split("@media print")[0]
    for block in screen_css.split(".se-sticky {")[1:]:
        assert "position: static" not in block.split("}")[0]
    # Same photo as the frame's own media, served locally.
    assert page.count("/static/img/campus-hero.jpg?v=") == 2


@pytest.mark.asyncio
async def test_the_hero_names_the_survey_and_leaves_the_figures_to_the_tiles(admin_client):
    """The four figures moved out of the hero into the KPI row below it.

    They are not gone — repeating them twice in one screen was what crowded
    the hero into clipping its own buttons — so this checks both halves: the
    hero says what the page is, and the numbers are still on the page.
    """
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    assert "<h1>Deeksharambh</h1>" in page
    assert 'class="se-sub">Department-wise survey<' in page
    assert "se-stage" not in page          # the old tile grid is gone entirely

    # …and every figure it used to show still appears, in the tiles below.
    for label in ("Registered in portal", "Took Deeksharambh",
                  "Yet to take it", "Conversion"):
        assert label in page
    assert ">11<" in page and ">6<" in page and ">54.5%<" in page


@pytest.mark.asyncio
async def test_the_copy_button_hands_out_a_link_that_works_without_a_login(admin_client, client):
    """The share button used to copy whatever URL the reader was on.

    From the admin page that is an admin-only URL, so every person it was sent
    to got a 403 — a share button that silently shared nothing. It now carries
    the token link the server minted, and this walks that exact link through a
    client with no admin cookie.
    """
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    # Pull the link straight out of the rendered page, the way a reader would.
    import html
    import re
    match = re.search(r'id="shareUrl"[^>]*value="([^"]+)"', page)
    assert match, "the page offers no shareable link"
    url = html.unescape(match.group(1))
    assert "token=" in url and "/shared/deeksharambh-meeting" in url

    # The button copies that same link, not location.href.
    assert 'data-share="' in page
    assert "location.href" in page   # only as the fallback, after data-share
    assert "btn.getAttribute('data-share') || location.href" in page

    # A reader with no admin cookie can open it and read the whole pack.
    from urllib.parse import urlparse
    path = urlparse(url)
    shared = await client.get(f"{path.path}?{path.query}")
    assert shared.status_code == 200
    assert "Department of Law" in shared.text
    assert "<h1>Deeksharambh</h1>" in shared.text
    # …and every department is in it, same as the admin copy.
    for dept in ("Department of Commerce", "Department of Design", "Department of Science"):
        assert dept in shared.text

    # The PDF on that same token works too.
    pdf = await client.get(f"{path.path}.pdf?{path.query}")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF-")


@pytest.mark.asyncio
async def test_copying_still_works_where_the_clipboard_api_is_missing(admin_client):
    """This app is served over plain HTTP on some deployments, and
    navigator.clipboard does not exist outside a secure context. Without a
    fallback the share button would do nothing on the one server it matters
    on."""
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    assert "window.isSecureContext" in page
    assert "document.execCommand('copy')" in page
    assert "window.prompt(" in page
    # And the link is on the page as selectable text regardless.
    assert 'id="shareUrl"' in page


# ── The added components ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_bands_account_for_every_department_exactly_once(app_with_mock):
    """The band strip is a partition, not a sample: each department lands in
    one band, the four add up to the whole field, and the boundaries do not
    overlap — 75.0% is "75% and up", not the band below it."""
    await _seed()
    from app.deeksharambh_meeting import meeting_pack

    pack = await meeting_pack()
    bands = pack["bands"]
    assert [b["label"] for b in bands] == ["Under 25%", "25 – 49%", "50 – 74%", "75% and up"]

    named = [r for r in pack["conversion"] if r["dept"] != "No department"]
    assert sum(b["count"] for b in bands) == len(named)

    # Every department appears in exactly one band's membership list.
    listed = [d for b in bands for d in b["departments"]]
    assert sorted(listed) == sorted(r["dept"] for r in named)
    assert len(listed) == len(set(listed))

    # Our four: 0%, 33.3%, 75%, 100%.
    counts = {b["label"]: b["count"] for b in bands}
    assert counts == {"Under 25%": 1, "25 – 49%": 1, "50 – 74%": 0, "75% and up": 2}
    # And the registered totals travel with them.
    under = next(b for b in bands if b["label"] == "Under 25%")
    assert under["registered"] == 2 and under["missing"] == 2   # Science


@pytest.mark.asyncio
async def test_the_chase_list_ranks_by_headcount_not_percentage(app_with_mock):
    """The two rankings disagree on purpose.

    Science is last on conversion (0%) but only two students short. Design
    at 33.3% is short of two as well, and Law at 75% is short of one. Sorting
    by what is actually missing is what makes the list workable — a 0%
    department of four is not where a week of chasing goes.
    """
    await _seed()
    from app.deeksharambh_meeting import meeting_pack

    gaps = (await meeting_pack())["gaps"]
    assert [(r["dept"], r["missing"]) for r in gaps] == [
        ("Department of Science", 2),   # 2 missing, 0% — worse pct breaks the tie
        ("Department of Design", 2),    # 2 missing, 33.3%
        ("Department of Law", 1),
    ]
    # Departments with nobody left to chase are simply not on the list.
    assert all(r["missing"] > 0 for r in gaps)
    assert "Department of Commerce" not in [r["dept"] for r in gaps]


@pytest.mark.asyncio
async def test_the_campus_split_reconciles_with_the_cohort_total(app_with_mock):
    await _seed()
    await db.get_db()["users"].insert_one({
        "email": "lata@x.com", "name": "Lata", "program": "Department of Arts",
        "ug_or_pg": "ug", "location": "Kochi", "status": db.STATUS_PRE_DONE,
        "created_at": datetime.now(timezone.utc),
    })
    from app.deeksharambh_meeting import meeting_pack

    pack = await meeting_pack()
    campuses = {c["campus"]: c for c in pack["campuses"]}
    assert campuses["Bangalore"]["registered"] == 11
    assert campuses["Kochi"]["registered"] == 1
    # The parts are the whole — no student counted twice or dropped.
    assert sum(c["registered"] for c in pack["campuses"]) == pack["totals"]["registered"]
    assert sum(c["took"] for c in pack["campuses"]) == pack["totals"]["took"]


@pytest.mark.asyncio
async def test_the_hero_is_open_before_it_hands_over_to_the_page(admin_client):
    """The hard line between the photo and the page was a frame still opening.

    At the handover the frame was ~94% open: visible side gutters, a residual
    corner radius, and the pale page starting underneath it. Three things fix
    it, and all three are pinned here — the width saturates early, full bleed
    is reached halfway through the hero and held, and once the hero is behind
    you the frame is snapped open regardless of where the easing got to.
    """
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    assert "--pw: min(1, calc(var(--p, 0) / 0.82))" in page
    assert "width: calc(42% + (100% - 42%) * var(--pw, 0))" in page
    assert "border-radius: calc(24px * (1 - var(--pw, 0)))" in page
    assert "var HOLD = 0.5, SMOOTH = 0.16;" in page
    assert "current = 1; wrap.style.setProperty('--p', 1); ticking = false; return;" in page
    # And the frame's floor fades into the page's own colour.
    assert ".se-frame::after" in page
    assert "var(--plane) 100%" in page


@pytest.mark.asyncio
async def test_no_inline_grid_columns_defeat_the_responsive_rules(admin_client):
    """An inline grid-template-columns beat the media query and kept two
    columns on a phone, pushing the campus cards off the side of the page.
    Layout belongs in classes so the breakpoints can win."""
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    assert 'style="grid-template-columns' not in page
    assert ".grid2, .grid2.even, .explorer { grid-template-columns: 1fr }" in page
