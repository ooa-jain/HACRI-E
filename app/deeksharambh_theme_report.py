"""
deeksharambh_theme_report.py — Deeksharambh 2026: the programme, its theme, how
each school carried the theme, and what students said, in two pages.

Written for an academic audience in prose only, with no statistics, tables or
charts. The sections are:

  1 Introduction · 2 Theme of Deeksharambh 2026 · 3 How the Schools Brought the
  Theme to Life · 4 Overall Student Feedback (4.1 Strengths, 4.2 Gaps)

Sections 1-3 are the programme's own account: the theme, taglines, focus areas
and messages are as the Deeksharambh 2026 posters print them. Section 4 is
written from the live answers, but every share is turned into a phrase ("a
clear majority", "a minority") rather than printed as a figure, and a point is
made only when the answers support it.

The same content goes to Word and to PDF through the report writers in
`deeksharambh_report_docx`, so the two downloads match.
"""
from __future__ import annotations

import io

from app.deeksharambh_report_docx import _Doc, _Pdf, _plain
from app.deeksharambh_summary_pdf import (
    DEPARTMENT_SESSIONS, DEPARTMENTS, NEGATIVE_WORDS, THEME, _Answers, _join, _lower, _text,
)

# How a department-led session reads in a sentence.
SESSION_PHRASE = {
    "Faculty Interaction": "faculty interactions",
    "School and Dept Introduction": "school and department introductions",
    "Academic Roadmap Session": "academic roadmap sessions",
    "Lab / Discipline Demo Session": "laboratory and discipline demonstrations",
    "Mentor Meet": "mentor meetings",
}

HEADER = "Deeksharambh 2026 · Theme and Student Voice"
TITLE = "Deeksharambh 2026"
SUBTITLE = f"{THEME} — Programme Overview and Student Feedback"

# How each school carried the theme, as its Deeksharambh 2026 poster states it.
SCHOOLS = [
    ("School of Commerce", "Finance Meets Intelligence",
     "introduced FinTech, AI in accounting, business analytics and entrepreneurship with AI: "
     "&ldquo;Analyse smarter. Decide better. Lead tomorrow.&rdquo;"),
    ("School of Management", "Leading in the Age of AI",
     "framed leadership as leading both people and intelligent systems through data-driven, "
     "human-centric decisions."),
    ("School of Computer Science &amp; IT", "Code. Compute. Create the Future.",
     "introduced generative AI, cybersecurity, data science and AI ethics: &ldquo;The future is "
     "intelligent. Build it together.&rdquo;"),
    ("School of Engineering &amp; Technology", "Engineering the Intelligent Future",
     "highlighted AI, robotics, IoT and autonomous systems: &ldquo;By humans. Enhanced by "
     "AI.&rdquo;"),
    ("School of Design", "Imagine. Create. Transform.",
     "explored generative, sustainable and UX/UI design: &ldquo;AI can generate possibilities, "
     "but only humans give them meaning.&rdquo;"),
    ("School of Allied Healthcare &amp; Sciences", "Care. Compassion. Intelligence.",
     "connected AI-assisted diagnostics and patient care with compassion: &ldquo;Intelligence "
     "can analyse; compassion can heal.&rdquo;"),
    ("School of Sciences", "Decoding Nature. Discovering Intelligence.",
     "explored the life, physical and computational sciences: &ldquo;Science explains the world; "
     "intelligence improves it.&rdquo;"),
    ("School of Humanities &amp; Social Sciences",
     "Understanding Humanity. Shaping a Better World.",
     "held that &ldquo;the more intelligent machines become, the more humanity "
     "matters.&rdquo;"),
    ("Department of Languages", "Words Connect. Intelligence Transforms.",
     "linked translation, cultural studies and natural language processing to global "
     "citizenship: &ldquo;Every language is a bridge.&rdquo;"),
    ("School of Law", "Justice. Ethics. Intelligence.",
     "addressed AI regulation, data protection and constitutional rights: &ldquo;AI can process "
     "information; humans deliver justice.&rdquo;"),
    ("School of Sports Education &amp; Research", "Perform. Learn. Transform.",
     "combined sports science, performance analytics and coaching with fair play: "
     "&ldquo;Intelligence trains. Character wins.&rdquo;"),
]

INTRODUCTION = (
    "Deeksharambh is the induction programme of JAIN (Deemed-to-be University), marking the "
    "formal beginning of every student's academic journey. Conceived as a structured transition "
    "from school to university, it introduces new entrants to the University's vision, academic "
    "framework, campus culture and support systems, and to the faculty and peers with whom they "
    "will learn. The 2026 edition was delivered across " + str(DEPARTMENTS) + " departments and "
    "comprised the Footsteps pre-arrival module; an orientation week of university, school and "
    "department sessions, faculty and peer engagement, industry and alumni interactions, the club "
    "fair and cultural programmes; and a Bridge Course addressing academic readiness, the National "
    "Education Policy (NEP) 2020, the Academic Bank of Credits and APAAR, and digital onboarding. "
    "Students recorded their reflections on the programme in a feedback survey at its close.")

THEME_TEXT = (
    f"The 2026 edition was organised around the theme <b>{THEME.replace('&', '&amp;')}</b>. "
    "The theme positions artificial intelligence not as a substitute for human capability but "
    "as a collaborator that extends it, on the premise that the defining competence of the coming "
    "decade will be the ability to combine distinctly human qualities with the intelligence that "
    "AI makes available. The programme expressed this through five actions &mdash; "
    "<i>Ideate, Collaborate, Learn, Analyse and Innovate</i> &mdash; and five shared commitments: "
    "<b>Human</b> (empathy, creativity, purpose), <b>Collaborate</b> (synergy, trust, growth), "
    "<b>AI</b> (intelligence, innovation, impact), <b>Together</b> (limitless possibilities, one "
    "future) and <b>Transform</b> (learn, lead, make a difference). Its guiding message, "
    "&ldquo;Together, we create limitless possibilities,&rdquo; presented Deeksharambh as the "
    "beginning of each student's transformative journey, under the shared identity "
    "<i>#CollaborativeIntelligence</i>: One University. Many Disciplines. Infinite Possibilities.")

SCHOOLS_INTRO = (
    "Each school interpreted the common theme through the lens of its own discipline, "
    "translating it into a distinct message, a set of focus areas and a statement of values for "
    "incoming students. Together, these interpretations demonstrated that collaborative "
    "intelligence is relevant to every field of study.")

FEEDBACK_INTRO = (
    "The feedback gathered at the close of the programme presents a largely positive picture of "
    "the student experience, together with a set of clearly articulated areas for refinement. "
    "The observations below summarise the principal strengths and gaps across all participating "
    "departments; they are presented qualitatively, without statistical detail.")


def _how_many(pct: float) -> str:
    """A share of students, said in words."""
    if pct >= 80:
        return "the large majority of"
    if pct >= 60:
        return "a clear majority of"
    if pct >= 50:
        return "the majority of"
    if pct >= 40:
        return "a substantial proportion of"
    if pct >= 25:
        return "a significant minority of"
    if pct >= 10:
        return "a minority of"
    return "a small number of"


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _names(options, n) -> str:
    return _join([_text(_lower(o["label"])) for o in options[:n]])


def strengths_and_gaps(pack: dict) -> tuple[list[str], list[str]]:
    """The strengths and gaps, as sentences in words only — no figures."""
    d = pack.get("overall_dept") or {}
    a = _Answers(d)
    h = d.get("headline") or {}
    strengths, gaps = [], []

    welcomed = a.share("q3", "Strongly Agree", "Agree")
    if welcomed is not None and welcomed >= 50:
        belong = h.get("belonging")
        strengths.append(
            f"<b>A welcoming environment.</b> {_cap(_how_many(welcomed))} students agreed that they "
            "felt welcomed during Deeksharambh"
            + (f", and their sense of belonging to JAIN was rated "
               f"{'highly' if belong >= 7 else 'positively'}" if belong is not None and belong >= 6
               else "")
            + ", indicating that the programme achieved its central aim of integration.")

    words = [o for o in a.top("q1", 4) if not any(_lower(o["label"]) == _lower(w)
                                                     for w in NEGATIVE_WORDS)][:3]
    now = a.top("q23b", 2)
    if words:
        worst = max((a.share("q1", w) or 0 for w in NEGATIVE_WORDS), default=0)
        better = a.share("q23b", "Better than I expected")
        strengths.append(
            f"<b>A positive overall experience.</b> Students most frequently described the "
            f"programme as {_join([_text(_lower(o['label'])) for o in words])}"
            + ("; negative descriptors were reported only rarely." if worst < 10 else ".")
            + (f" They now regard university as {_names(now, 2)}"
               + (", and many found it better than they had expected." if better is not None
                  and better >= 20 else ".") if now else ""))

    smooth = a.share("q5", "Manageable", "Very Easy", "Easy")
    if smooth is not None and smooth >= 50:
        first = a.top("q7", 1)
        none_first = bool(first) and _lower(first[0]["label"]).startswith("no challenges")
        strengths.append(
            f"<b>A smooth transition.</b> {_cap(_how_many(smooth))} students found the move into "
            "university manageable or easy"
            + (", and the most common response on onboarding was that no challenges had been "
               "encountered." if none_first else "."))

    rows = [a.share("q8", "Yes", row=r) for r in ("University overview", "School", "Programme")]
    rows = [v for v in rows if v is not None]
    if rows and min(rows) >= 50:
        useful = a.top("q9", 2)
        strengths.append(
            f"<b>Effective pre-arrival preparation.</b> The Footsteps module helped "
            f"{_how_many(min(rows))} students understand the University, their school and "
            "department, and their programme structure before arrival"
            + (f", with the {_names(useful, 2)} valued most." if useful else "."))

    smile, surprise = a.top("q27", 1), a.top("q26", 1)
    if smile or surprise:
        text = "<b>Strong peer connection.</b> "
        if smile:
            text += f"Students were most delighted by {_text(_lower(smile[0]['label']))}"
            text += (f", and what surprised them most was {_text(_lower(surprise[0]['label']))}."
                     if surprise else ".")
        else:
            text += f"What surprised students most was {_text(_lower(surprise[0]['label']))}."
        strengths.append(text)

    # Faculty connect: the sessions, what to keep, the surprises and the reasons to
    # recommend JAIN, each said only where faculty is among the leading answers.
    def leads(key, name, n=3):
        return any(_lower(o["label"]).startswith(_lower(name)) for o in a.top(key, n))

    impactful = leads("q11", "Faculty Interaction")
    keep = leads("q37", "Faculty interaction")
    quality = leads("q26", "Quality of faculty")
    impression = leads("q36", "Strong Faculty Impression")
    if impactful or keep or quality or impression:
        first = []
        if impactful:
            first.append("faculty interaction ranked among the most impactful sessions of the "
                         "programme")
        if keep:
            first.append("students named it among the elements that should continue in the next "
                         "edition" if impactful else "students named faculty interaction among the "
                         "elements that should continue in the next edition")
        second = []
        if quality:
            second.append("the quality of faculty was among students' greatest surprises")
        if impression:
            second.append("a strong faculty impression was among the leading reasons for "
                          "recommending JAIN")
        text = "<b>Faculty connect.</b> "
        if first:
            text += _cap(", and ".join(first)) + "."
        if second:
            text += " " + _cap(", and ".join(second)) + "."
        strengths.append(text.strip())

    prepared = a.share("q18", "Well Prepared", "Very Well Prepared")
    if prepared is not None and prepared >= 50:
        areas = a.top("q17", 3)
        strengths.append(
            f"<b>Academic readiness.</b> {_cap(_how_many(prepared))} students reported feeling well "
            "prepared for regular classes after the Bridge Course"
            + (f", which particularly strengthened {_names(areas, 3)}." if areas else "."))

    understood = a.share("q21", "Mostly Understood", "Fully Understood")
    unaware = a.share("q20", "Not Aware", "Minimally Aware")
    if understood is not None and understood >= 50:
        strengths.append(
            "<b>Understanding of academic regulations.</b> "
            + ("Awareness of NEP 2020 was limited among many students before the programme; "
               "after it, " if unaware is not None and unaware >= 40 else "After the programme, ")
            + f"{_how_many(understood)} students understood the Academic Bank of Credits, APAAR "
            "and the credit framework.")

    # ── Gaps ──────────────────────────────────────────────────────────────
    stop = a.top("q38", 1)
    stress = a.top("q28", 1)
    overload = (a.share("q38", "Too much information in one day")
                or a.share("q28", "Information overload in one day")
                or a.share("q7", "Information was too much at once"))
    if stop:
        same = stress and set(_lower(stop[0]["label"]).split()) & {"long", "sessions"} \
            and set(_lower(stress[0]["label"]).split()) & {"long", "sessions"}
        gaps.append(
            f"<b>Session length and pacing.</b> The concern raised most often was "
            f"{_text(_lower(stop[0]['label']))}"
            + (", which was also the leading source of stress" if same else
               f", while students found {_text(_lower(stress[0]['label']))} most stressful"
               if stress else "")
            + (". Students also reported receiving more information than they could absorb in a "
               "single day" if overload is not None and overload >= 20 else "")
            + ". A more varied schedule, with shorter sessions, regular breaks and content "
            "distributed across the week, is indicated.")

    inter = a.share("q14", "Highly Interactive", "Fully Interactive")
    asks = a.top("q39", 3)
    if inter is not None and inter < 50:
        gaps.append(
            "<b>Limited interactivity.</b> Fewer than half of the students described the sessions "
            "as highly interactive"
            + (f"; the additions requested most for the next edition were {_names(asks, 3)}."
               if asks else "."))
    elif asks:
        gaps.append(f"<b>Breadth of engagement.</b> The additions students requested most for the "
                    f"next edition were {_names(asks, 3)}.")

    unsure = a.share("q31", "Somewhat", "Not really")
    lost = a.share("q7", "Didn't know who to ask for help")
    if (unsure is not None and unsure >= 30) or (lost is not None and lost >= 15):
        gaps.append(
            f"<b>Clarity on support channels.</b> {_cap(_how_many(max(unsure or 0, lost or 0)))} "
            "students were not fully certain whom to approach for help; a clearly communicated "
            "first point of contact for every student would address this.")

    fix = a.top("q12", 1)
    rated = sorted([(n, a.share("q11", n)) for n in DEPARTMENT_SESSIONS
                    if a.share("q11", n) is not None], key=lambda x: x[1])
    low = [n for n, _s in rated[:2]]
    if fix or low:
        text = "<b>Sessions requiring redesign.</b> "
        if fix:
            text += (f"The {_text(fix[0]['label'])} was the session most often identified for "
                     "improvement" + (", while " if low else "."))
        if low:
            lead = "" if fix else "Department-led "
            text += (("department-led " if fix else lead)
                     + _join([SESSION_PHRASE.get(n, n.lower()) for n in low])
                     + " were rated as having comparatively limited impact.")
        gaps.append(text)

    barrier = a.share("q7", "Language barrier")
    lonely = a.share("q30", "No close friends yet")
    if (barrier is not None and barrier >= 10) or (lonely is not None and lonely >= 10):
        gaps.append("<b>Support for students who settle more slowly.</b> A minority of students "
                    "reported language barriers or had not yet formed close friendships, "
                    "suggesting a need for targeted mentoring and peer-buddy support.")

    return strengths, gaps


def _write(W, pack: dict) -> None:
    W.title_block(TITLE, SUBTITLE)
    W.h1("Introduction")
    W.para(INTRODUCTION)
    W.h1("Theme of Deeksharambh 2026")
    W.para(THEME_TEXT)
    W.h1("How the Schools Brought the Theme to Life")
    W.para(SCHOOLS_INTRO)
    W.bullets([f"<b>{school} &mdash; <i>{tag}</i>{'' if tag.endswith('.') else '.'}</b> "
               f"The {'school' if school.startswith('School') else 'department'} {text}"
               for school, tag, text in SCHOOLS])
    W.h1("Overall Student Feedback")
    W.para(FEEDBACK_INTRO)
    strengths, gaps = strengths_and_gaps(pack)
    W.h2("Strengths")
    W.bullets(strengths or ["The feedback received so far does not yet support a firm statement "
                            "of strengths."])
    W.h2("Gaps")
    W.bullets(gaps or ["The feedback received so far does not point to a clear gap."])


def build_theme_docx(pack: dict) -> bytes:
    W = _Doc(_plain(pack.get("campus") or "All campuses"), header=HEADER, size=10, h1_size=13.5)
    _write(W, pack)
    return W.save()


def build_theme_pdf(pack: dict) -> bytes:
    W = _Pdf(_plain(pack.get("campus") or "All campuses"), header=HEADER, size=10, h1_size=13.5)
    _write(W, pack)
    return W.save()


async def theme_report_response(*, campus: str = "", kind: str = "pdf"):
    """The two-page report as a PDF or Word attachment."""
    from fastapi.responses import StreamingResponse

    from app.deeksharambh_meeting import meeting_pack
    from app.routes.shared_analysis import _in_thread

    pack = await meeting_pack(campus=campus)
    if kind == "docx":
        data = await _in_thread(build_theme_docx, pack)
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        data = await _in_thread(build_theme_pdf, pack)
        media = "application/pdf"
    name = f"Deeksharambh_2026_Theme_and_Student_Voice_{campus or 'All'}.{kind}"
    name = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in name)
    return StreamingResponse(io.BytesIO(data), media_type=media,
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


