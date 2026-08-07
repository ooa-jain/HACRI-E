"""
departments.py — the canonical list of programmes / departments.

Kept in one place so the registration form, the department-wise survey links
and the admin portal all spell a department exactly the same way. Spelling
matters: a department name is stored verbatim on every user record and is what
the department links are matched against.
"""
from __future__ import annotations

DEPARTMENTS: list[str] = [
    "Department of Humanities & Social Sciences",
    "Department of Economics",
    "Department of Journalism and Mass Communication",
    "Department of Languages",
    "Department of Law",
    "Department of Performing Arts and Cultural Studies",
    "Department of Computer Science and IT",
    "Department of Allied Healthcare and Sciences",
    "Department of Biotechnology and Genetics",
    "Department of Chemistry and Biochemistry",
    "Department of Data Analytics and Mathematical Science",
    "Department of Forensic Science",
    "Department of Microbiology and Botany",
    "Department of Physics and Electronics",
    "Department of Psychology and Allied Sciences",
    "Department of Animation and Virtual Reality",
    "Department of Commerce",
    "Department of Art and Design",
    "Department of Design",
    "Department of Aerospace Engineering",
    "Department of Computer Science and Engineering",
    "Department of Electrical and Electronics Engineering",
    "Department of Electronics and Communication Engineering",
    "Department of Food Technology",
    "Department of Information Science and Engineering",
    "Department of Civil Engineering",
    "Department of Mechanical Engineering",
    "Department of Management Studies - UG",
    "Area - School of Sports Education and Research",
    "CeRSSE",
    "Department of Management Studies - PG",
    "Department of Art and Design (Interior Design)",
]
