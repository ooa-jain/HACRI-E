"""
schools.py — which school each department belongs to.

A department is what a student picks at registration and what every survey
link is keyed on. A school is the unit a dean asks about, and until this
existed there was no way to answer "how is the School of Sciences doing?"
without adding up seven departments by hand.

The mapping below is the Office of Academics' own list. Anything it does not
name — a department added later, a school that spells its departments
differently, a blank on a student record — lands in OTHER_SCHOOL rather than
disappearing, so every registered student is counted under exactly one school.
"""
from __future__ import annotations

import re

OTHER_SCHOOL = "Other"

# school → its departments, exactly as the departments are spelled on student
# records. Order is the order the schools are listed in.
SCHOOLS: dict[str, list[str]] = {
    "School of Computer Science and Engineering": [
        "Department of Computer Science and Engineering",
        "Department of Information Science and Engineering",
    ],
    "School of Aerospace Engineering": [
        "Department of Aerospace Engineering",
    ],
    "School of Engineering & Technology": [
        "Department of Civil Engineering",
        "Department of Mechanical Engineering",
        "Department of Electrical and Electronics Engineering",
        "Department of Electronics and Communication Engineering",
        "Department of Food Technology",
    ],
    "School of Humanities and Social Sciences": [
        "Department of Humanities & Social Sciences",
        "Department of Economics",
        "Department of Performing Arts and Cultural Studies",
        "Department of Languages",
        "Department of Journalism and Mass Communication",
    ],
    "School of Law": [
        "Department of Law",
    ],
    "School of Sciences": [
        "Department of Chemistry and Biochemistry",
        "Department of Biotechnology and Genetics",
        "Department of Microbiology and Botany",
        "Department of Data Analytics and Mathematical Science",
        "Department of Forensic Science",
        "Department of Physics and Electronics",
        "Department of Psychology and Allied Sciences",
    ],
    "School of Allied Healthcare and Sciences": [
        "Department of Allied Healthcare and Sciences",
    ],
    # The registration list spells this one as an "Area", which is the same
    # unit under its older name.
    "School of Sports Science & Research": [
        "Area - School of Sports Education and Research",
    ],
    "School of Computer Science & Information Technology": [
        "Department of Computer Science and IT",
        "Department of Animation and Virtual Reality",
    ],
    "School of Commerce": [
        "Department of Commerce",
    ],
    # The school list has one management department; registration splits it
    # into UG and PG, and both are CMS.
    "CMS Business School": [
        "Department of Management Studies - UG",
        "Department of Management Studies - PG",
    ],
    # No department registers under this one yet; it is listed so the page
    # shows the whole university rather than only the parts that replied.
    "School of Aviation and Aerospace Management": [],
    "School of Design, Media and Creative Arts": [
        "Department of Design",
        "Department of Art and Design",
        "Department of Art and Design (Interior Design)",
    ],
}

SCHOOL_NAMES: list[str] = list(SCHOOLS)


def _key(name: str) -> str:
    """Compare department names without tripping over &/and, case or spacing."""
    text = (name or "").strip().lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


_BY_DEPARTMENT: dict[str, str] = {
    _key(dept): school
    for school, departments in SCHOOLS.items()
    for dept in departments
}


def school_of(dept: str | None) -> str:
    """The school a department belongs to — OTHER_SCHOOL when none claims it.

    A department nobody listed is still somebody's student, so it is grouped
    rather than dropped. Seeing a real department sitting in "Other" is the
    signal to add it to SCHOOLS above.
    """
    return _BY_DEPARTMENT.get(_key(dept), OTHER_SCHOOL)


def school_slug(school: str | None) -> str:
    """URL-safe slug for a school name."""
    slug = re.sub(r"[^a-z0-9]+", "-", (school or "").strip().lower()).strip("-")
    return slug or "other"


def resolve_school(slug: str) -> str:
    """Name the school a slug refers to, or OTHER_SCHOOL."""
    slug = (slug or "").strip().lower()
    for school in SCHOOLS:
        if school_slug(school) == slug:
            return school
    return OTHER_SCHOOL


def departments_of(school: str) -> list[str]:
    return list(SCHOOLS.get(school, []))
