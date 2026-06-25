"""
Section metadata for the survey pages. The Likert sections (B, D, E, F, G) are
rendered by iterating SCHEMA in `app/hacri_e2_compat.py`. This file only
describes the *non*-Likert sections: Pre background, Pre prior usage, Pre
future expectations, and Post reflection.
"""

from __future__ import annotations

from app.hacri_e2_compat import H1_OPTIONS, H2_LABELS, H3_OPTIONS

# ── Pre Section A — Your Background ──────────────────────────────────────────
PRE_BACKGROUND: list[tuple[str, str, str, list[str]]] = [
    ("A1", "What is your age?", "select", [
        "Under 18", "18-20", "21-24", "25+", "Prefer not to say",
    ]),
    ("A2", "What is your gender?", "select", [
        "Female", "Male", "Non-binary", "Prefer not to say", "Other",
    ]),
    ("A3", "What program name are you enrolled in?", "select", [
        "Engineering / Technology",
        "Business / Management",
        "Arts / Humanities",
        "Social Sciences",
        "Natural Sciences",
        "Medicine / Health",
        "Law",
        "Education",
        "Other",
    ]),
    ("A4", "What type of school did you attend before university?", "select", [
        "Public school",
        "Private / independent school",
        "International school",
        "Religious school",
        "Other / mixed",
    ]),
    ("A5", "Did your school offer any formal subject or module on AI or Data Science?",
     "select", ["Yes", "No", "Don't know"]),
    ("A6", "How would you describe your access to technology (devices, internet) during school?",
     "select", ["Excellent", "Adequate", "Limited", "Very limited"]),
]

# ── Pre Section C — Prior AI Usage ───────────────────────────────────────────
PRE_USAGE: list[tuple[str, str, str, list[str]]] = [
    ("C1", "Which AI tools have you used? (select all that apply)",
     "checkbox", [
        "ChatGPT or similar chatbots",
        "Google Gemini / Microsoft Copilot",
        "AI image generators (Midjourney, DALL-E)",
        "Grammar / writing assistants (e.g. Grammarly)",
        "AI-powered search (e.g. Perplexity)",
        "Recommendation systems (Netflix, YouTube, Spotify)",
        "Voice assistants (Siri, Alexa, Google Assistant)",
        "AI tools in video games",
        "None of the above",
     ]),
    ("C2", "How frequently did you use AI tools during your school years?",
     "select", ["Daily", "Weekly", "Monthly", "Rarely", "Never"]),
    ("C3", "For what purposes did you use AI tools in school? (select all that apply)",
     "checkbox", [
        "Writing or editing assignments",
        "Researching topics",
        "Solving math or science problems",
        "Generating images or creative content",
        "Language learning or translation",
        "Entertainment / personal use",
        "I did not use AI tools in school",
     ]),
    ("C4", "Did your school teachers encourage the use of AI tools for learning?",
     "select", ["Always", "Often", "Sometimes", "Rarely", "Never", "N/A"]),
    ("C5", "Have you ever been uncertain whether using AI on a school assignment was allowed?",
     "select", ["Always", "Often", "Sometimes", "Rarely", "Never"]),
]

# ── Pre Section H — Future Expectations & Institutional Needs ───────────────
PRE_FUTURE: list[tuple] = [
    ("H1", "How important is it that your university prepares you to work with AI?",
     "scale_1_5", None),
    ("H2", "Which of the following would you find most useful? (up to 3)",
     "checkbox_multi", H2_LABELS),
    ("H3", "How confident are you that your school prepared you for AI at university?",
     "scale_1_5", None),
    ("H4", "Should AI literacy be a compulsory part of every university degree?",
     "select", ["Yes", "No", "Unsure"]),
    ("H5", "What is the one thing you most want to understand about AI before finishing your first year? (max 150 words)",
     "textarea", None),
    ("H6", "What human skills would you think is the most important to retain in the age of AI",
     "textarea", None),
]

# ── Pre Section E — scenario sub-question ────────────────────────────────────
PRE_E11_OPTIONS = [
    "Yes, fully acceptable",
    "Acceptable only with disclosure",
    "Not acceptable",
    "Unsure",
]

# ── Post Section H — Post-Induction Reflection ───────────────────────────────
POST_REFLECTION: list[tuple] = [
    ("H1", "After today's induction session, how has your understanding of AI changed?",
     "select", H1_OPTIONS),
    ("H2", "After today's session, how do you feel about working with AI in your studies?",
     "scale_1_5", None),
    ("H3", "Which part of the induction was most valuable to you?",
     "select", H3_OPTIONS),
    ("H4", "In two or three sentences, describe how you see yourself collaborating with AI during your university studies. (max 100 words)",
     "textarea", None),
]


# ── Friendly section titles (used by templates) ──────────────────────────────
SECTION_TITLES: dict[str, str] = {
    "A": "Your Background",
    "B": "AI Awareness & Literacy",
    "C": "Prior AI Usage",
    "D": "Attitudes & Perceptions Toward AI",
    "E": "AI Ethics & Academic Integrity",
    "F": "Human–AI Collaboration Readiness (HACRI Core)",
    "G": "AI Application as an entrepreneur",
    "H": "Future Expectations & Institutional Needs",
    "H_POST": "Post-Induction Reflection",
}