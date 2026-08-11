"""
orientation_analysis.py — turn raw Deeksharambh orientation answers into a
campus-wise report.

The orientation form (app/templates/orientation.html) stores one loose dict per
student: sliders as numbers, single-choice questions as the chosen label,
multi-selects as a list of labels, and the two matrix questions as
{row: column} maps. Nothing here assumes a question was answered — students can
skip anything, and older submissions predate some questions.

`summarize_orientation()` is the single place that decides what the admin report
shows, so the on-screen analysis and any future export can never drift apart.
"""
from __future__ import annotations

from collections import Counter

# Campuses the registration form and the orientation form both offer.
CAMPUSES = ("Bangalore", "Kochi")


def normalize_campus(value) -> str:
    """Map any campus spelling to "Bangalore" / "Kochi", or "" when unknown.

    The orientation form stores the chip label ("📍 Bangalore") while the user
    record stores the plain name, so both have to land on the same key.
    """
    text = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in str(value or ""))
    text = text.strip().lower()
    for campus in CAMPUSES:
        if campus.lower() in text:
            return campus
    return ""


# ── Question map ──────────────────────────────────────────────────────────────
# (key, label, kind, max) grouped by the section the student saw it in.
#   scale  — slider, averaged and shown as a 1..max distribution
#   nps    — 0-10 recommendation score, reported the NPS way
#   single — one label chosen
#   multi  — any number of labels chosen
#   matrix — {statement: answer} map
SECTIONS: list[tuple[str, list[tuple]]] = [
    ("🔥 The Vibe Check", [
        ("q1",  "Words describing the Deeksharambh experience", "multi",  None),
        ("q2",  "Overall vibe of Deeksharambh 2026",            "scale",  10),
        ("q3",  "Felt welcomed during Deeksharambh",            "single", None),
        ("q4",  "How students felt during Deeksharambh",        "multi",  None),
        ("q5a", "Sessions that sparked the most interest",      "multi",  None),
        ("q5b", "Sessions that felt least connecting",          "multi",  None),
    ]),
    ("🧭 Settling In", [
        ("q5",  "Ease of transition into university life",      "single", None),
        ("q7",  "Challenges faced during onboarding",           "multi",  None),
    ]),
    ("👣 Footsteps (pre-arrival)", [
        ("q8",  "Footsteps helped me understand…",              "matrix", None),
        ("q9",  "Most useful Footsteps content",                "multi",  None),
        ("q10", "Would binge-watch a Footsteps season 2",       "single", None),
    ]),
    ("🎯 Orientation Experience", [
        ("q11", "Sessions with the biggest impact",             "multi",  None),
        ("q12", "Sessions that need the most improvement",      "multi",  None),
        ("q13", "The Orientation Programme helped me…",         "matrix", None),
        ("q14", "How hands-on / interactive the sessions were", "single", None),
        ("q15", "How engaging the sessions were",               "single", None),
    ]),
    ("🌉 Bridge Course", [
        ("q16", "Academic confidence after the Bridge Course",  "scale",  5),
        ("q17", "Bridge Course areas that helped most",         "multi",  None),
        ("q18", "Feels prepared for regular classes",           "single", None),
        ("q19", "Most helpful aspects of the programme",        "multi",  None),
    ]),
    ("📜 NEP 2020 & Digital Readiness", [
        ("q20", "Knew what NEP 2020 means — before",            "single", None),
        ("q21", "Understands ABC ID / APAAR / credits — after", "single", None),
        ("q22", "Digital and tech confidence",                  "single", None),
    ]),
    ("💬 The Gen Z Lens", [
        ("q23a", "Expected university to be",                   "multi",  None),
        ("q23b", "Now thinks university will be",               "multi",  None),
        ("q24",  "Deeksharambh as a movie genre",               "single", None),
        ("q25",  "The first week felt like",                    "single", None),
        ("q26",  "Biggest surprises",                           "multi",  None),
        ("q27",  "What made them smile",                        "multi",  None),
        ("q28",  "What stressed them out",                      "multi",  None),
    ]),
    ("❤️ Belonging & Expectations", [
        ("q29", "I feel I belong at JAIN",                      "scale",  10),
        ("q30", "Friends made so far",                          "single", None),
        ("q31", "Knows whom to contact for help",               "single", None),
        ("q32", "I can see myself succeeding at JAIN",          "scale",  10),
        ("q33", "Top academic expectations",                    "multi",  None),
    ]),
    ("📊 Score & Mic Drop", [
        ("q34", "Likelihood to recommend JAIN (NPS)",           "nps",    10),
        ("q35", "Overall learning experience",                  "single", None),
        ("q36", "Reasons behind the NPS rating",                "multi",  None),
        ("q37", "Should definitely continue next year",         "multi",  None),
        ("q38", "Should stop doing next year",                  "multi",  None),
        ("q39", "Should introduce next year",                   "multi",  None),
        ("q40", "Deeksharambh left them feeling",               "multi",  None),
        ("q41", "Their JAIN avatar",                            "single", None),
    ]),
]

# Flat lookup: key → (label, kind, max)
QUESTIONS: dict[str, tuple[str, str, int | None]] = {
    key: (label, kind, maximum)
    for _, items in SECTIONS
    for key, label, kind, maximum in items
}


def _num(value) -> float | None:
    """Best-effort number, ignoring the label text sliders sometimes carry."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        digits = "".join(ch for ch in text if ch.isdigit() or ch == ".")
        try:
            return float(digits)
        except ValueError:
            return None


def _labels(value) -> list[str]:
    """Every chosen label, whether the question stored one or many."""
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value).strip()]


def _pct(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def _answer_for(record: dict, key: str):
    """The stored answer, falling back to the "<key>_label" emoji variant."""
    value = record.get(key)
    if value in (None, "", [], {}):
        value = record.get(f"{key}_label")
    return value


def _scale_stats(records: list[dict], key: str, maximum: int) -> dict:
    values = [v for v in (_num(_answer_for(r, key)) for r in records) if v is not None]
    counts = Counter(int(round(v)) for v in values)
    return {
        "answered": len(values),
        "avg": round(sum(values) / len(values), 2) if values else None,
        "max": maximum,
        "options": [
            {"label": str(score), "count": counts.get(score, 0),
             "pct": _pct(counts.get(score, 0), len(values))}
            for score in range(1, maximum + 1)
        ],
    }


def _nps_stats(records: list[dict], key: str) -> dict:
    values = [v for v in (_num(_answer_for(r, key)) for r in records) if v is not None]
    promoters  = sum(1 for v in values if v >= 9)
    passives   = sum(1 for v in values if 7 <= v < 9)
    detractors = sum(1 for v in values if v < 7)
    total = len(values)
    counts = Counter(int(round(v)) for v in values)
    return {
        "answered": total,
        "avg": round(sum(values) / total, 2) if total else None,
        "max": 10,
        "promoters": promoters,
        "passives": passives,
        "detractors": detractors,
        "promoters_pct": _pct(promoters, total),
        "passives_pct": _pct(passives, total),
        "detractors_pct": _pct(detractors, total),
        "nps": round(_pct(promoters, total) - _pct(detractors, total), 1) if total else None,
        "options": [
            {"label": str(score), "count": counts.get(score, 0),
             "pct": _pct(counts.get(score, 0), total)}
            for score in range(0, 11)
        ],
    }


def _choice_stats(records: list[dict], key: str, multi: bool) -> dict:
    counts: Counter[str] = Counter()
    answered = 0
    picks = 0
    for record in records:
        chosen = _labels(_answer_for(record, key))
        if not chosen:
            continue
        answered += 1
        picks += len(chosen)
        counts.update(chosen)
    options = [
        {"label": label, "count": count, "pct": _pct(count, answered)}
        for label, count in counts.most_common()
    ]
    return {"answered": answered, "picks": picks if multi else answered, "options": options}


def _matrix_stats(records: list[dict], key: str) -> dict:
    rows: dict[str, Counter] = {}
    answered = 0
    for record in records:
        value = _answer_for(record, key)
        if not isinstance(value, dict) or not value:
            continue
        answered += 1
        for statement, reply in value.items():
            if reply in (None, ""):
                continue
            rows.setdefault(str(statement), Counter())[str(reply)] += 1
    return {
        "answered": answered,
        "rows": [
            {
                "label": statement,
                "answered": sum(counter.values()),
                "options": [
                    {"label": reply, "count": count, "pct": _pct(count, sum(counter.values()))}
                    for reply, count in counter.most_common()
                ],
            }
            for statement, counter in rows.items()
        ],
    }


def _question_stats(records: list[dict], key: str, label: str, kind: str, maximum) -> dict:
    if kind == "scale":
        stats = _scale_stats(records, key, maximum or 10)
    elif kind == "nps":
        stats = _nps_stats(records, key)
    elif kind == "matrix":
        stats = _matrix_stats(records, key)
    else:
        stats = _choice_stats(records, key, multi=(kind == "multi"))
    return {"key": key, "label": label, "kind": kind, **stats}


def summarize_orientation(records: list[dict]) -> dict:
    """Aggregate a list of orientation `data` dicts into the admin report.

    Sections with nothing answered are dropped, so a half-filled cohort shows a
    short honest report instead of pages of zeroes.
    """
    total = len(records)

    sections = []
    for title, items in SECTIONS:
        questions = [
            _question_stats(records, key, label, kind, maximum)
            for key, label, kind, maximum in items
        ]
        questions = [q for q in questions if q.get("answered")]
        if questions:
            sections.append({"title": title, "questions": questions})

    vibe      = _scale_stats(records, "q2", 10)
    bridge    = _scale_stats(records, "q16", 5)
    belonging = _scale_stats(records, "q29", 10)
    success   = _scale_stats(records, "q32", 10)
    nps       = _nps_stats(records, "q34")

    def top(key: str, limit: int = 5) -> list[dict]:
        return _choice_stats(records, key, multi=True)["options"][:limit]

    return {
        "count": total,
        "headline": {
            "vibe": vibe["avg"], "vibe_max": 10,
            "bridge": bridge["avg"], "bridge_max": 5,
            "belonging": belonging["avg"], "belonging_max": 10,
            "success": success["avg"], "success_max": 10,
            "nps": nps["nps"],
            "nps_avg": nps["avg"],
            "promoters": nps["promoters"],
            "passives": nps["passives"],
            "detractors": nps["detractors"],
            "nps_answered": nps["answered"],
        },
        "highlights": {
            "impactful": top("q11"),
            "needs_work": top("q12"),
            "keep": top("q37"),
            "stop": top("q38"),
            "introduce": top("q39"),
            "stressors": top("q28"),
        },
        "sections": sections,
    }
