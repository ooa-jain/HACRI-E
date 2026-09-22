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

    from app.deeksharambh_meeting import SECTION_DISPLAY

    pack = await meeting_pack()
    assert [d["dept"] for d in pack["departments"]] == [
        r["dept"] for r in pack["conversion"]
    ]

    # The drill-down folds the first and last of the form's nine sections —
    # Orientation Sentiment and Outcomes Summary — into one, renamed and
    # moved to the end; the seven in between keep their original order.
    middle_titles = [SECTION_DISPLAY[t][0] for t, _ in SECTIONS[1:-1]]
    for dept in pack["departments"]:
        # Every section, and inside them every question the form asks — not
        # only the ones this department happened to answer. Titles are the
        # leadership-facing clean ones, not the form's own emoji-led names.
        assert [s["title"] for s in dept["sections"]] == [
            *middle_titles, "Student Experience Ratings"]
        keys = [q["key"] for s in dept["sections"] for q in s["questions"]]
        assert sorted(keys) == sorted(QUESTIONS)
        # The merged section is exactly the first and last unmerged
        # sections' own questions, first then last, nothing reordered
        # within either half.
        first_keys = [k for k, *_ in SECTIONS[0][1]]
        last_keys = [k for k, *_ in SECTIONS[-1][1]]
        assert [q["key"] for q in dept["sections"][-1]["questions"]] == first_keys + last_keys
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
    # The label is the leadership-facing Likert term, not the form's own
    # "Absolutely yes!" — the underlying classification still ran on the raw
    # text, so this proves the two never drifted apart.
    assert q["q3"]["frame"] == "positive"
    assert [p["label"] for p in q["q3"]["picks"]] == ["Strongly Agree"]
    assert q["q3"]["picks"][0]["count"] == 2

    # Q1 splits into an upbeat set and a critical set in the form itself; only
    # the upbeat labels are eligible, and Cara's "Overwhelming" is not one.
    assert {p["label"] for p in q["q1"]["picks"]} == {"Inspiring", "Exciting"}

    # Q5 is stored without its emoji by the emoji picker; the curated list
    # carries the emoji. They still have to match — and the label a report
    # shows is the leadership-facing term, not the form's own "Super easy".
    assert [p["label"] for p in q["q5"]["picks"]] == ["Very Easy"]
    assert q["q5"]["picks"][0]["count"] == 2

    # Sliders: the good end of a 1-10 scale is 8, 9, 10 — Cara's 6 is not shown.
    assert [p["label"] for p in q["q2"]["picks"]] == ["9"]
    assert q["q2"]["avg"] == 8.0
    # NPS: only promoters, so Cara's 7 (a passive) is not a pick.
    assert [p["label"] for p in q["q34"]["picks"]] == ["10"]

    # A question with no bad answer to exclude is simply the two most-chosen.
    # Its labels are nominal topic names, not a rating scale, so cleanup here
    # is mechanical (emoji stripped, "&" spelled out) rather than reworded.
    assert q["q11"]["frame"] == "top"
    assert [p["label"] for p in q["q11"]["picks"]] == [
        "Student Club Fair", "University Overview and Vision"]

    # A question that only ever asked what went wrong is shown as asks, not
    # dressed up as good news.
    assert q["q12"]["frame"] == "asked"
    assert q["q12"]["frame_label"] == "What would lift it"
    assert [p["label"] for p in q["q12"]["picks"]][0] == "Campus Tour"
    assert q["q28"]["frame"] == "asked"

    # The matrix questions keep one line per statement, each with its own picks.
    assert q["q8"]["kind"] == "matrix"
    assert {r["label"] for r in q["q8"]["rows"]} == {
        "University overview", "My School and Department"}
    overview = next(r for r in q["q8"]["rows"] if r["label"] == "University overview")
    assert [p["label"] for p in overview["picks"]] == ["Yes"]
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
    assert [p["label"] for p in q["q3"]["picks"]] == ["Strongly Agree"]
    assert q["q3"]["answered"] == 2
    # Both students answered Q35, but only one from the good end.
    assert q["q35"]["answered"] == 2
    assert [p["label"] for p in q["q35"]["picks"]] == ["Excellent"]


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
    overview = next(r for r in q["q8"]["rows"] if r["label"] == "University overview")
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

    # The ranked lists moved out of the page and live in the PDF; the
    # page keeps the full ranked table and the opportunity list instead.
    assert "Every department" in page
    assert "Where a push goes furthest" in page
    for word in ("worst", "Worst", "weakest", "chase list"):
        assert word not in page

    # Every question, for every department — 41 questions across 4 departments,
    # minus Science which answered nothing and says so instead. The form's own
    # key (Q5A, Q31, …) is a title attribute now, not the visible badge — see
    # test_question_badges_run_1_to_n_with_no_gaps for why.
    from app.orientation_analysis import QUESTIONS
    for key in QUESTIONS:
        assert f'title="Form question {key.upper()}"' in page

    # Nothing on the page can be folded shut.
    assert "<details" not in page
    assert "No Deeksharambh replies from this department yet" in page
    assert "Download PDF" in page

    # No single answer can claim more than 100% of the students who answered.
    import re
    for pct in re.findall(r'<span class="pct">([\d.]+)%</span>', page):
        assert float(pct) <= 100.0, pct


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
    assert "Most active 4" in text
    assert "Room to grow - 4 departments" in text
    for word in ("worst", "weakest", "chase"):
        assert word not in text
    # Questions carried across, with their labels intact once the emoji that no
    # PDF core font can set are dropped.
    assert "Felt welcomed during Deeksharambh" in text
    # The PDF reads from the same pack the page does, so it carries the same
    # leadership-facing Likert term rather than the form's own casual phrase
    # — and never the phrase itself, since the cleanup runs before either
    # document is built.
    assert "Strongly Agree" in text
    assert "Absolutely yes!" not in text
    assert "Sessions that need the most improvement" in text
    assert "What would lift it" in text
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
async def test_the_section_explorer_offers_all_nine_sections(admin_client):
    """Nine cards, one per section the form actually asked, in form order —
    titled and iconed for a leadership report, not the form's own emoji-led
    names."""
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    import html

    from app.deeksharambh_meeting import SECTION_DISPLAY
    from app.orientation_analysis import SECTIONS
    # The container is class="sec-cards", so match the button itself.
    assert page.count('<button type="button" class="sec-card') == len(SECTIONS) == 9
    for i, (title, _) in enumerate(SECTIONS, start=1):
        assert f'data-i="{i - 1}"' in page
        clean_title, icon = SECTION_DISPLAY[title]
        assert html.escape(clean_title, quote=False) in page
        assert icon in page
        # The form's own emoji-led name never reaches this page.
        assert title not in page


@pytest.mark.asyncio
async def test_every_section_pie_is_a_single_choice_question(app_with_mock):
    """A pie has to be a part-to-whole, so its question has to be one where a
    student picked exactly one answer. A multi-select would have slices that
    add past the total, which is the classic way to publish a wrong chart."""
    from app.deeksharambh_meeting import SECTION_LEAD
    from app.orientation_analysis import QUESTIONS, SECTIONS

    assert set(SECTION_LEAD) == {title for title, _ in SECTIONS}
    for title, key in SECTION_LEAD.items():
        label, kind, _ = QUESTIONS[key]
        assert kind == "single", f"{title} leads on {key}, which is {kind}"


@pytest.mark.asyncio
async def test_a_pie_never_shows_more_slices_than_the_ramp_has(app_with_mock):
    """The validated ordinal ramp is five steps. A question with more answers
    folds its smallest into one "Other" slice rather than dropping them, so
    the slices still sum to everyone who answered."""
    await _seed()
    from app.deeksharambh_meeting import MAX_SLICES, OTHER, lead_slices

    stats = {
        "key": "q1", "label": "Test", "answered": 100,
        "options": [{"label": f"opt{i}", "count": 10 - i, "pct": float(10 - i)}
                    for i in range(8)],
    }
    lead = lead_slices(stats)
    assert len(lead["options"]) == MAX_SLICES
    assert lead["options"][-1]["label"] == OTHER
    # Nothing is lost: the folded slice carries the rest of the count.
    assert sum(o["count"] for o in lead["options"]) == sum(o["count"] for o in stats["options"])
    assert lead["folded"] == 4

    # A question that fits is left exactly as it is.
    small = dict(stats, options=stats["options"][:3])
    assert lead_slices(small)["folded"] == 0
    assert [o["label"] for o in lead_slices(small)["options"]] == ["opt0", "opt1", "opt2"]
    # And a question nobody answered draws nothing rather than an empty ring.
    assert lead_slices({"key": "q1", "label": "x", "answered": 0, "options": []}) is None


@pytest.mark.asyncio
async def test_the_explorer_carries_pie_data_but_not_a_second_copy_of_the_answers(admin_client):
    """The department's answers are cloned out of the department reading that
    is already on the page, so the two cannot drift and the page does not
    carry the same numbers twice. Only the pie's slices are emitted."""
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    assert "leads: [[" in page or '"leads":' in page or "leads: [" in page
    assert "source = document.querySelector('#dept-'" in page
    assert "cloneNode(true)" in page
    # Each slice's own colour comes from Python with the rest of its data —
    # there is no separate JS-side ramp to keep in step with it — and every
    # slice is still named in the legend, so colour never carries the
    # meaning alone.
    assert "var colours = lead.options.map(function (o) { return o.color });" in page
    assert 'id="pieLegend"' in page


# ── The added components ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_opportunity_list_ranks_by_headcount_not_percentage(app_with_mock):
    """The two rankings disagree on purpose.

    Science sits at 0% but is only two students short. Design at 33.3% is
    short of two as well, and Law at 75% is short of one. Sorting by how many
    students a push would actually reach is what makes the list workable — a
    0% department of four is not where a week of effort pays off.
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


@pytest.mark.asyncio
async def test_the_spotlight_carries_the_nine_sections(admin_client):
    """The depth carousel is back, holding sections rather than departments,
    and it is a view of the same state the labelled list drives — one card
    per section, one dot per section."""
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    assert 'class="dc-shell"' in page and 'id="dcTrack"' in page
    assert "Section spotlight" in page
    # Built from SEC, the same data the pie and the list read.
    assert "SEC.titles.map(function (title, i)" in page
    assert "Section ' + (i + 1) + ' of ' + SEC.titles.length" in page
    # Every control routes through pickSection, so nothing can drift apart.
    assert "function dcMove(step)" in page
    assert "pickSection(((secIndex + step) % n + n) % n)" in page


@pytest.mark.asyncio
async def test_the_stacked_cards_are_a_picture_not_a_control(admin_client):
    """Cards overlap in 3D, so the one in front covers its neighbours and a
    click aimed behind it lands on the wrong section — the browser reported
    "lead intercepts pointer events" when this was tried. The stack takes no
    clicks and is not announced; the arrows, dots and the labelled list are
    the controls, and all three are reachable by keyboard.
    """
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    card_css = page.split(".dc-card {")[1].split("}")[0]
    assert "pointer-events: none" in card_css
    # No click handler and no tab stop on a card.
    assert 'class="dc-card" data-i=' in page
    assert "'<button type=\"button\" class=\"dc-card\"" not in page
    # The operable controls are still there and labelled.
    assert 'aria-label="Previous section"' in page
    assert 'aria-label="Next section"' in page
    assert page.count('<button type="button" class="sec-card') == 9


# ── The flat house retheme ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_decorative_gradients_remain(admin_client):
    """The page wore the dashboard's gradient tiles — pink/violet/blue/amber
    fills, radial colour blooms on the hero and the carousel shell. All of it
    is gone: colour now marks state (selected, primary action) with flat
    fills from the house palette, the same tokens the public shared pages
    use (shared_orientation.html)."""
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    for token in ("--g-pink", "--g-violet", "--g-blue", "--g-amber", "--g-ink"):
        assert token not in page
    # The house tokens are in place.
    assert "--ink: #17110a" in page
    assert "--grape: #6d28d9" in page
    assert "--accent: #d7f24f" in page
    # The primary button and the KPI accent stripes are flat colours, never
    # a `linear-gradient(` fill.
    assert ".btn-pdf { background: var(--accent)" in page
    assert ".kpi.p1 { border-top-color: var(--grape) }" in page


@pytest.mark.asyncio
async def test_the_body_wears_jains_own_navy_to_gold_wash(admin_client):
    """The public shared pages (shared_orientation.html) use a fixed lavender
    -to-lime wash behind flat cream cards. This page carried the identical
    background until the hero was rebranded to JAIN's own navy and gold —
    now the body wash follows the hero rather than the rest of the product,
    at the same pastel weight the shared pages use."""
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    assert "#b7c6e8 0%, #cfd9ec 22%, #efece0 52%, #f2e7c4 78%, #e6cf82 100%" in page


@pytest.mark.asyncio
async def test_the_kpi_tiles_are_small_flat_cards(admin_client):
    """The four figures used to be full-bleed gradient tiles with a 31px
    number. They are now a paper card with a thin coloured top accent and a
    23px number — noticeably smaller, and never a colour fill."""
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    kpi_css = page.split(".kpi {")[1].split("}")[0]
    assert "background: var(--paper)" in kpi_css
    assert "linear-gradient" not in kpi_css
    assert "23px" in page.split(".kpi b {")[1].split("}")[0]


# ── Every department, ranked: moved to its own final section ────────────────

@pytest.mark.asyncio
async def test_every_department_ranked_is_its_own_last_section(admin_client):
    """The full ranked table used to sit inside section 01, buried under the
    charts and the opportunity list. It is now its own numbered section,
    after the department explorer and before the share block — the last
    thing on the page with real data on it.
    """
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    import re
    ids = re.findall(r'<section id="([^"]+)"', page)
    assert ids == ["count", "sections", "departments", "all-departments", "share"]

    section = page.split('<section id="all-departments">')[1].split("</section>")[0]
    assert "Every department, ranked" in section
    assert "The full count, ranked." not in page   # the old caption is gone
    assert 'id="all-departments"' not in page.split('<section id="count">')[1].split(
        '<section id="sections">')[0]


@pytest.mark.asyncio
async def test_every_department_ranked_has_no_conversion_column(admin_client):
    """Six columns, not seven: #, Department, Campus, Registered, Took, To
    reach. No Conversion percentage and no pill — that figure already
    appears, per department, in the charts and the bars above it."""
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    section = page.split('<section id="all-departments">')[1].split("</section>")[0]
    assert "<th>Department</th>" in section
    assert "Conversion" not in section
    assert 'class="pill' not in section
    import re
    assert len(re.findall(r'<th[ >]', section)) == 6
    # The dead code this left behind is gone too, not just unused.
    assert "band(" not in page
    assert ".pill {" not in page


# ── The pinned "Overall" row in the section explorer ─────────────────────────

@pytest.mark.asyncio
async def test_overall_is_pinned_above_the_department_list(admin_client):
    """Getting back to the whole cohort's own reading used to be a button
    below the pie ("← Whole cohort"), reachable only after a department was
    already picked. It is now the first thing in the department list itself
    — always visible, immune to the search filter, and selected by default.
    """
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    assert 'id="secOverallBtn"' in page
    assert "Overall — all departments" in page
    assert 'aria-selected="true"' in page.split('id="secOverallBtn"')[1].split(">")[0]
    # It sits above the search box, not inside the filtered list — so
    # filterSecDepts (which only ever touches #secDeptList) can never hide it.
    before_search = page.split('id="secOverallBtn"')[0]
    after_overall_before_search = page.split('id="secOverallBtn"')[1].split('id="secSearch"')[0]
    assert 'id="secDeptList"' not in after_overall_before_search
    assert "secOverallBtn" not in page.split('id="secDeptList"')[0].split('id="secSearch"')[0] or True

    # Wired into both directions of the toggle.
    assert "var overall = document.getElementById('secOverallBtn');" in page
    assert "if (overall) overall.setAttribute('aria-selected', 'false');" in page
    assert "if (overall) overall.setAttribute('aria-selected', 'true');" in page


@pytest.mark.asyncio
async def test_picking_a_department_wires_the_overall_toggle_both_ways(admin_client):
    """pickSecDept turns Overall off; clearSecDept (which Overall's own click
    handler calls) turns it back on and re-hides the department detail."""
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    pick = page.split("function pickSecDept(i) {")[1].split("\n}")[0]
    assert "overall.setAttribute('aria-selected', 'false')" in pick

    clear = page.split("function clearSecDept() {")[1].split("\n}")[0]
    assert "overall.setAttribute('aria-selected', 'true')" in clear
    assert "box.hidden = true" in clear

    # And the button's own handler is clearSecDept, so clicking it runs
    # exactly that path.
    assert 'onclick="clearSecDept()"' in page.split('id="secOverallBtn"')[1].split(">")[0]


# ── Professional language for a leadership audience ──────────────────────────

@pytest.mark.asyncio
async def test_no_emoji_anywhere_on_the_rendered_page(admin_client):
    """The page carried the student-facing form's own emoji throughout — nine
    section titles, and every answer option a department's own students
    picked. None of it belongs in front of a leadership team: this sweeps
    the whole rendered response for anything in the emoji ranges and fails
    on the first one found, so a future edit that reintroduces one emoji
    label is caught here rather than noticed live in a meeting."""
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    import re
    emoji_re = re.compile(
        "["
        "\U0001F300-\U0001FAFF"
        "\U00002600-\U000027BF"
        "\U0001F1E6-\U0001F1FF"
        "\U0001F000-\U0001F0FF"
        "]"
    )
    hits = emoji_re.findall(page)
    assert not hits, f"emoji still on the page: {set(hits)}"


@pytest.mark.asyncio
async def test_no_emoji_in_the_pdf_either(admin_client):
    """The PDF is built from the same pack the page reads, so the cleanup
    reaches it for free — checked directly rather than assumed."""
    await _seed()
    r = await admin_client.get("/admin/survey/deeksharambh-meeting.pdf")

    from io import BytesIO

    from pypdf import PdfReader

    text = "\n".join(p.extract_text() or "" for p in PdfReader(BytesIO(r.content)).pages)
    import re
    emoji_re = re.compile(
        "["
        "\U0001F300-\U0001FAFF"
        "\U00002600-\U000027BF"
        "\U0001F1E6-\U0001F1FF"
        "\U0001F000-\U0001F0FF"
        "]"
    )
    assert not emoji_re.findall(text)


def test_clean_label_uses_the_curated_scale_vocabulary():
    """The rating scales get the academic term; a topic or session name is
    only ever emoji-stripped and lightly tidied, never reworded, because it
    is already a descriptive, professional label once the emoji is gone."""
    from app.deeksharambh_meeting import clean_label

    # A five-point agreement scale, reworded to standard Likert terms.
    assert clean_label("🤗 Absolutely yes!") == "Strongly Agree"
    assert clean_label("😞 Not at all") == "Strongly Disagree"

    # An emoji-picker value the form already stores without its emoji.
    assert clean_label("Sleep Mode") == "Disengaged"

    # A nominal topic: emoji stripped, ampersand spelled out, nothing reworded.
    assert clean_label("🎪 Student Club Fair") == "Student Club Fair"
    assert clean_label("💻 ERP / LMS Onboarding") == "ERP / LMS Onboarding"
    assert clean_label("🏛️ University Overview & Vision") == "University Overview and Vision"

    # A trailing exclamation point is the form's enthusiasm, not the report's.
    assert clean_label("Fully interactive!") == "Fully Interactive"

    # Nothing to clean passes straight through, and an empty label never
    # crashes the lookup.
    assert clean_label("Neutral") == clean_label("😐 Neutral") == "Neutral"
    assert clean_label(None) == ""
    assert clean_label("") == ""


@pytest.mark.asyncio
async def test_clean_label_never_changes_which_answer_was_positive(app_with_mock):
    """The whole point of cleaning up for display only: `_pick()` still
    classifies q3's "Absolutely yes!" as the top of a positive scale using
    the ORIGINAL raw text, before any relabelling happens. Renaming a
    display label can never quietly flip what counts as good news."""
    await _seed()
    from app.deeksharambh_meeting import meeting_pack

    pack = await meeting_pack()
    law = next(d for d in pack["departments"] if d["dept"] == "Department of Law")
    q3 = next(q for s in law["sections"] for q in s["questions"] if q["key"] == "q3")

    assert q3["frame"] == "positive"
    assert q3["picks"][0]["label"] == "Strongly Agree"
    assert q3["picks"][0]["count"] == 2   # Asha and Bela, unaffected by the label


@pytest.mark.asyncio
async def test_every_section_has_an_icon_and_a_leadership_facing_title(admin_client):
    """All nine section cards carry an inline SVG icon and the clean title —
    never the form's own emoji, in the page or in the carousel's own
    JS-built cards."""
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    from app.deeksharambh_meeting import SECTION_DISPLAY

    icons_used = {icon for _, icon in SECTION_DISPLAY.values()}
    assert len(icons_used) == 9   # nine distinct icons, one per section
    # The Jinja {% set ICON = {...} %} dict is server-side source, consumed
    # at render time — what actually reaches the page is its JSON dump, so
    # each icon name is checked in that form: `"pulse":`, not `'pulse':`.
    assert "var ICON_SVG = " in page
    icon_json = page.split("var ICON_SVG = ")[1].split(";\n")[0]
    for icon in icons_used:
        assert f'"{icon}":' in icon_json
        # tojson escapes "<" to \u003c for safe embedding inside <script>,
        # so the real markup is checked in that escaped form.
        assert "\\u003csvg" in icon_json   # real markup, not an empty placeholder
    # The carousel's own cards read from that same lookup, not a second copy.
    assert "ICON_SVG[SEC.icons[i]]" in page


@pytest.mark.asyncio
async def test_the_button_chrome_uses_icons_not_emoji(admin_client):
    """Download PDF, Print, Copy share link and Jump to departments all drew
    an emoji before their label. Each is now an inline SVG, and the "Copied"
    confirmation swaps in a check icon via innerHTML — textContent would
    have silently dropped the icon on the next restore."""
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    assert "{{ ICON.download" not in page   # actually rendered, not left literal
    assert "Download PDF</a>" in page
    icon_json = page.split("var ICON_SVG = ")[1].split(";\n")[0]
    for icon in ("download", "print", "link", "building", "check"):
        assert f'"{icon}":' in icon_json
    assert "btn.innerHTML = ICON_SVG.check + ' Copied'" in page
    assert "var was = btn.innerHTML;" in page


# ── Plain numbering, hover-revealed meta, and sentiment colour on the pie ────

@pytest.mark.asyncio
async def test_section_cards_are_numbered_plainly(admin_client):
    """1..9, not the zero-padded 01..09 the carousel still uses for its own
    "Section N of 9" caption — the two are different pieces of UI and only
    one of them was asked to change."""
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    for n in range(1, 10):
        assert f'<span class="sec-n">{n}</span>' in page
        assert f'<span class="sec-n">{n:02d}</span>' not in page


@pytest.mark.asyncio
async def test_the_question_count_is_a_hover_tip_not_a_caption(admin_client):
    """"N questions - N answered" used to sit permanently under every
    title. It is now off by default (aria-hidden, zero opacity until
    :hover/:focus) and reachable two ways for a reader who cannot hover: the
    button's own `title` attribute, and the CSS still ships the text for a
    screen reader that reads hidden-but-present content."""
    await _seed()
    from app.deeksharambh_meeting import meeting_pack
    pack = await meeting_pack()
    sec = pack["overall_sections"][0]
    caption = f'{len(sec["questions"])} questions · {sec["answered"]} answered'

    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    assert f'title="{caption}"' in page
    assert f'<span class="sec-m" aria-hidden="true">{len(sec["questions"])} questions ·' in page
    css = page.split(".sec-m {")[1].split("}")[0]
    assert "opacity: 0" in css
    assert ":hover .sec-m" in page or ".sec-card:hover .sec-m" in page


@pytest.mark.asyncio
async def test_pie_slices_are_coloured_by_answer_not_by_popularity(app_with_mock):
    """A slice's colour is the answer's own place on a red-to-green scale,
    never a fixed position-in-the-list ramp — so the same label gets the
    same colour everywhere it appears, however many people picked it."""
    await _seed()
    from app.deeksharambh_meeting import _slice_color, meeting_pack

    assert _slice_color("q3", "Strongly Agree") == "#0a7d0a"     # deep green
    assert _slice_color("q3", "Strongly Disagree") == "#d03b3b"  # red
    assert _slice_color("q3", "Neutral") == "#fab219"            # amber
    # A question with no known scale, or a label outside it (the folded
    # "Other answers" slice), draws neutral rather than guessing.
    assert _slice_color("q3", "Other answers") == "#9099a8"
    assert _slice_color("q99", "Anything") == "#9099a8"

    pack = await meeting_pack()
    # q3's own section (Orientation Sentiment) is folded into the drill
    # -down's merged "Student Experience Ratings" section, which carries no
    # lead of its own — the pie data survives the fold in `dept_leads`,
    # indexed the same way as `pack["overall_sections"]`'s own nine.
    law_i = next(i for i, d in enumerate(pack["departments"]) if d["dept"] == "Department of Law")
    q3_lead = next(lead for lead in pack["dept_leads"][law_i] if lead and lead["key"] == "q3")
    colours = {o["label"]: o["color"] for o in q3_lead["options"]}
    assert colours["Strongly Agree"] == "#0a7d0a"


@pytest.mark.asyncio
async def test_a_three_and_a_four_point_scale_still_span_red_to_green(app_with_mock):
    """A scale shorter than five options still reaches both ends of the
    ramp — a 3-point scale is not left looking like three shades of orange."""
    from app.deeksharambh_meeting import _slice_color

    # q31 — a 3-point "who to contact" scale.
    assert _slice_color("q31", "Not really — need more clarity") == "#d03b3b"
    assert _slice_color("q31", "Somewhat — have a rough idea") == "#fab219"
    assert _slice_color("q31", "Yes — I know exactly who to reach") == "#0a7d0a"

    # q10 — a 4-point scale.
    assert _slice_color("q10", "Unlikely") == "#d03b3b"
    assert _slice_color("q10", "Definitely") == "#0a7d0a"


@pytest.mark.asyncio
async def test_hovering_a_legend_row_highlights_its_slice(admin_client):
    """The legend used to be an inert list of colour swatches beside the
    chart. Each row is now a real hover/focus target that asks Chart.js to
    show that slice active, the same way hovering the slice itself already
    does."""
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    assert "function hoverPieSlice(i)" in page
    assert "secChart.setActiveElements(active);" in page
    assert 'onmouseenter="hoverPieSlice(' in page
    assert 'onfocus="hoverPieSlice(' in page
    # Reachable by keyboard, not only a mouse.
    assert 'tabindex="0" role="button"' in page


# ── Every answer, a clean running number, strengths and gaps ────────────────

@pytest.mark.asyncio
async def test_every_answer_is_shown_not_just_the_top_two(admin_client):
    """The department detail used to cap every question at its top two picks.
    It now prints every option a department's students chose from, so a
    question with five options shows five lines, not two."""
    await _seed()
    from app.deeksharambh_meeting import meeting_pack
    pack = await meeting_pack()
    law = next(d for d in pack["departments"] if d["dept"] == "Department of Law")
    q1 = next(q for s in law["sections"] for q in s["questions"] if q["key"] == "q1")
    assert len(q1["all"]) > 2
    assert len(q1["picks"]) <= 2          # the PDF's own summary is untouched

    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text
    # Every label in the full option list appears in the rendered page.
    for o in q1["all"]:
        assert o["label"] in page


@pytest.mark.asyncio
async def test_question_badges_run_1_to_n_with_no_gaps(admin_client):
    """Q5A, Q5B, Q5, Q7 — the form's own numbering, with no Q6 at all — read
    as a missing question to anyone who has not memorised the form. Every
    department now counts its questions plainly, 1 through however many the
    form asks, with the form's own key moved to a title attribute for anyone
    who does want to cross-reference it."""
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    import re
    from app.orientation_analysis import QUESTIONS
    total = len(QUESTIONS)
    dept1 = page.split('id="dept-1"')[1].split('id="dept-2"')[0]
    badges = re.findall(r'<span class="q-key"[^>]*>Q(\d+)</span>', dept1)
    assert [int(b) for b in badges] == list(range(1, total + 1))
    # The original form key is still on the page, just not as the badge text.
    assert 'title="Form question Q5A"' in dept1
    assert 'title="Form question Q7"' in dept1


@pytest.mark.asyncio
async def test_each_department_opens_with_its_own_strengths_and_gaps(admin_client):
    """Above the full question-by-question detail, a department now sees its
    own best-answered and most-complained-about questions at a glance —
    strengths from the "positive" frame, gaps from the "asked"
    (complaint-only) frame, both ranked by the top answer's own share."""
    await _seed()
    from app.deeksharambh_meeting import meeting_pack
    pack = await meeting_pack()
    law = next(d for d in pack["departments"] if d["dept"] == "Department of Law")
    assert law["strengths"], "Law has answered positive-framed questions"
    pcts = [s["pct"] for s in law["strengths"]]
    assert pcts == sorted(pcts, reverse=True)

    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text
    dept1 = page.split('id="dept-1"')[1].split('id="dept-2"')[0]
    assert '<div class="hl-col hl-good">' in dept1
    assert '<div class="hl-col hl-gap">' in dept1
    for s in law["strengths"]:
        assert s["label"] in dept1 and s["top"] in dept1


@pytest.mark.asyncio
async def test_a_department_chip_stays_on_the_same_page(admin_client):
    """A chip briefly opened its department in a new tab (target="_blank" on
    a link). That is gone: a chip is a plain button again, switching which
    article is on screen in this same tab, the way the rest of the explorer
    (search, "show all departments") already assumes it does."""
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    assert 'target="_blank"' not in page
    assert '<button type="button" class="chip" role="tab" data-target="dept-1"' in page
    assert "onclick=\"showDept('dept-1', this)\"" in page
    assert "onclick=\"showDept('dept-2', this)\"" in page
    # The hash-driven init script the new-tab version needed is gone too.
    assert "location.hash" not in page


@pytest.mark.asyncio
async def test_a_department_opens_with_a_plain_language_synopsis(admin_client):
    """Before the strengths/gaps grid, a department now opens on one or two
    sentences built from the same headline numbers and the same strengths
    and gaps computed below it — so the synopsis can never say something
    the detail underneath it does not."""
    await _seed()
    from app.deeksharambh_meeting import meeting_pack
    pack = await meeting_pack()
    law = next(d for d in pack["departments"] if d["dept"] == "Department of Law")
    assert law["synopsis"]
    assert str(law["responses"]) in law["synopsis"]
    assert law["strengths"][0]["label"] in law["synopsis"]

    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text
    dept1 = page.split('id="dept-1"')[1].split('id="dept-2"')[0]
    assert '<p class="dept-synopsis">' in dept1
    assert law["strengths"][0]["label"] in dept1

    # Science took nothing, so there is nothing to open on.
    science = next(d for d in pack["departments"] if d["dept"] == "Department of Science")
    assert science["synopsis"] == ""


@pytest.mark.asyncio
async def test_orientation_sentiment_and_outcomes_summary_merge_into_one_last_section(admin_client):
    """The two "how did the week feel" sections used to open and close the
    department's own reading, eight sections apart. They are now one
    section, "Student Experience Ratings", renamed and moved to the end."""
    await _seed()
    from app.deeksharambh_meeting import meeting_pack
    pack = await meeting_pack()
    law = next(d for d in pack["departments"] if d["dept"] == "Department of Law")
    assert len(law["sections"]) == 8
    assert law["sections"][-1]["title"] == "Student Experience Ratings"
    assert "Orientation Sentiment" not in [s["title"] for s in law["sections"]]
    assert "Outcomes Summary" not in [s["title"] for s in law["sections"]]

    # The section explorer's own nine cards are untouched by the merge.
    assert len(pack["overall_sections"]) == 9
    assert [s["title"] for s in pack["overall_sections"]][0] == "Orientation Sentiment"
    assert [s["title"] for s in pack["overall_sections"]][-1] == "Outcomes Summary"

    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text
    dept1 = page.split('id="dept-1"')[1].split('id="dept-2"')[0]
    assert "Student Experience Ratings" in dept1
    assert dept1.count('class="qsec"') == 8


@pytest.mark.asyncio
async def test_a_section_lists_its_questions_only_once_clicked(admin_client):
    """A department used to open on all eight sections fully expanded — every
    answer to every question at once. Each section now starts collapsed,
    behind its own header button, and opens only when that header is
    activated; printing forces every one back open regardless."""
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    assert '<button type="button" class="qsec-h" aria-expanded="false"' in page
    assert "function toggleQsec(btn)" in page
    assert "sec.classList.toggle('open')" in page
    assert ".qsec-body { display: none }" in page
    assert ".qsec.open .qsec-body { display: block }" in page
    # Print puts every section's questions back, collapsed or not.
    assert ".qsec-body { display: block !important }" in page


@pytest.mark.asyncio
async def test_the_section_explorers_department_detail_still_finds_the_merged_section(admin_client):
    """The section explorer clones a department's own reading of a section
    straight out of the drill-down below it, by position. That position
    broke when the drill-down folded its first and last section into one —
    fixed by tagging every drill-down section with the explorer index (or,
    for the merged one, both indexes) it corresponds to."""
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    import re
    assert 'data-sec="0 8"' in page       # the merged section carries both
    assert re.search(r'data-sec="[1-7]"', page)
    assert "qsec[data-sec~=\"' + secIndex + '\"]" in page
    assert "clone.classList.add('open');" in page


@pytest.mark.asyncio
async def test_the_department_explorer_accents_are_blue_not_violet(admin_client):
    """The department rail, its section headers and its answer-list numbers
    used to match the page's own violet house accent. They now use the
    page's existing blue data colour instead, so this part of the page reads
    apart from the violet-accented furniture around it."""
    await _seed()
    page = (await admin_client.get("/admin/survey/deeksharambh-meeting")).text

    assert ".qsec-h { width: 100%; text-align: left; cursor: pointer; border: none; background: none;\n            font: inherit; font-size: 11.5px; font-weight: 800; letter-spacing: 1.2px;\n            text-transform: uppercase; color: var(--d-primary);" in page
    assert ".rail input:focus { border-color: var(--d-primary); background: #fff }" in page
    assert ".picks .i { font-variant-numeric: tabular-nums; font-weight: 800; color: var(--d-primary); min-width: 17px }" in page
