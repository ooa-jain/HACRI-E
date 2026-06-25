#!/usr/bin/env python3
"""
HACRI-E Student Plotter
========================
Reads submitted Pre and Post PDF survey files, computes normalised
AI Literacy and AI Readiness scores, and generates:
  1. Per-student 2×2 quadrant chart (Pre ● → Post ◆)
  2. Cohort summary chart (all students overlaid)
  3. Histograms for POST Section H (H1, H2, H3 responses)
  4. Scorecard CSV

Usage:
    python hacri_e2_plotter.py \\
        --pre  ./submitted_pre/   \\
        --post ./submitted_post/  \\
        --out  ./results/

Requirements:
    pip install pypdf matplotlib numpy

Scoring:
    Both scores are normalised averages on a 1–5 scale.
    Pre and Post are directly comparable.
    Skipped items are excluded from the average (not penalised).
    D2a–D2d are reverse-scored (6 − raw value).
"""

import os, sys, glob, argparse, csv
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

try:
    from pypdf import PdfReader
except ImportError:
    print("ERROR: pypdf not installed.  Run: pip install pypdf")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════════════════════
# SCORING SCHEMA
# Every Likert field that appears in BOTH Pre and Post surveys.
# dim : "L" = AI Literacy | "R" = AI Readiness
# rev : True  = reverse-scored (score = 6 − raw)   [D2 anxiety items only]
# ═══════════════════════════════════════════════════════════════════════════════
SCHEMA = {
    # ── Section B — AI Awareness & Literacy (all Literacy) ────────────────────
    "B1":  ("L", False), "B2":  ("L", False), "B3":  ("L", False),
    "B4":  ("L", False), "B5":  ("L", False), "B6":  ("L", False),
    "B7":  ("L", False), "B8":  ("L", False), "B9":  ("L", False),
    "B10": ("L", False),

    # ── Section D — Attitudes ──────────────────────────────────────────────────
    "D1a": ("R", False), "D1b": ("R", False),   # Enthusiasm → Readiness
    "D1c": ("R", False), "D1d": ("R", False),
    "D2a": ("R", True),  "D2b": ("R", True),    # Anxiety → Readiness (reversed)
    "D2c": ("R", True),  "D2d": ("R", True),
    "D3a": ("L", False), "D3b": ("L", False),   # Trust → Literacy (critical eval)
    "D3c": ("L", False), "D3d": ("L", False),
    "D4a": ("R", False), "D4b": ("R", False),   # Human Identity → Readiness
    "D4c": ("R", False), "D4d": ("R", False),

    # ── Section E — Ethics & Academic Integrity ────────────────────────────────
    "E1":  ("R", False), "E2":  ("R", False),   # responsible disposition
    "E3":  ("L", False),                         # knows policy → Literacy
    "E4":  ("R", False), "E5":  ("L", False),   # E5: knows AI bias → Literacy
    "E6":  ("R", False), "E7":  ("L", False),   # E7: knows privacy risk → Literacy
    "E8":  ("R", False), "E9":  ("R", False),
    "E10": ("R", False),

    # ── Section F — HACRI Core ─────────────────────────────────────────────────
    "F1a": ("L", False), "F1b": ("L", False),   # Cognitive → Literacy
    "F1c": ("L", False), "F1d": ("L", False),
    "F2a": ("R", False), "F2b": ("R", False),   # Behavioral → Readiness
    "F2c": ("R", False), "F2d": ("R", False),
    "F3a": ("R", False), "F3b": ("R", False),   # Social → Readiness
    "F3c": ("R", False), "F3d": ("R", False),
    "F4a": ("R", False), "F4b": ("L", False),   # F4b/c: metacognitive monitoring → Literacy
    "F4c": ("L", False), "F4d": ("R", False),

    # ── Section G — Entrepreneurial AI Application (all Readiness) ────────────
    "G1a": ("R", False), "G1b": ("R", False), "G1c": ("R", False),
    "G2a": ("R", False), "G2b": ("R", False), "G2c": ("L", False), # G2c → Literacy
    "G3a": ("R", False), "G3b": ("R", False), "G3c": ("R", False),
    "G4a": ("R", False), "G4b": ("R", False), "G4c": ("R", False), "G4d": ("R", False),
}

REVERSED = {k for k, (_, rev) in SCHEMA.items() if rev}

# ── Dimension item counts for reference ───────────────────────────────────────
LIT_ITEMS  = [k for k, (d, _) in SCHEMA.items() if d == "L"]
READ_ITEMS = [k for k, (d, _) in SCHEMA.items() if d == "R"]

# ── Palette ────────────────────────────────────────────────────────────────────
NAVY  = "#1B2A4A"
GOLD  = "#C9A84C"
TEAL  = "#00C9A7"
LGRAY = "#F5F6FA"
DGRAY = "#D0D3DE"

QUAD_COLS = {
    "Q1": "#EBF5EC",  # top-right  green  — Champion
    "Q2": "#FFF9E6",  # top-left   gold   — Enthusiast
    "Q3": "#FBEAEA",  # bot-left   red    — Novice
    "Q4": "#E8EEF7",  # bot-right  blue   — Sceptic
}
QUAD_TEXT = {
    "Q1": "#1A6B3A", "Q2": "#6B3900",
    "Q3": "#7B1818", "Q4": "#1B2A4A",
}
QUAD_LABELS = {
    "Q1": "Q1  AI Champion\n(High Lit · High Read)",
    "Q2": "Q2  AI Enthusiast\n(Low Lit · High Read)",
    "Q3": "Q3  AI Novice\n(Low Lit · Low Read)",
    "Q4": "Q4  AI Sceptic\n(High Lit · Low Read)",
}


# ═══════════════════════════════════════════════════════════════════════════════
# PDF FIELD READER
# ═══════════════════════════════════════════════════════════════════════════════

def read_pdf_fields(path):
    """Return dict of field_name → value string from a filled PDF."""
    try:
        reader = PdfReader(path)
        raw = reader.get_fields() or {}
    except Exception as e:
        print(f"  WARNING: cannot read {path}: {e}")
        return {}

    result = {}
    for name, field in raw.items():
        # pypdf can return value as NameObject ("/Yes", "/3") or plain string
        val = field.get("/V")
        if val is None:
            val = getattr(field, "value", None)
        if val is None:
            continue
        val_str = str(val).strip()
        if val_str.startswith("/"):
            val_str = val_str[1:]
        if val_str in ("", "Off", "No", "False"):
            continue
        result[name] = val_str
    return result


def get_student_code(fields):
    """Extract the STUDENT_CODE field value."""
    for key in ("STUDENT_CODE", "student_code", "StudentCode"):
        if key in fields and fields[key].strip():
            return fields[key].strip().upper()
    return None


def score_likert(fields, dimension):
    """
    Compute normalised 1–5 average for all scored Likert items of the
    given dimension ("L" or "R") found in the fields dict.

    For radio groups: field name = "B1", value = "3"
    Skipped (absent or non-numeric) items are excluded from the average.
    Reversed items: effective = 6 − raw.
    """
    vals = []
    for fname, (dim, rev) in SCHEMA.items():
        if dim != dimension:
            continue
        raw = fields.get(fname)
        if raw is None:
            continue
        try:
            v = float(raw)
        except ValueError:
            continue
        if not (1.0 <= v <= 5.0):
            continue
        vals.append(6.0 - v if rev else v)

    if not vals:
        return None
    return round(sum(vals) / len(vals), 3)


def quadrant(lit, read):
    if lit is None or read is None:
        return "No data"
    if lit >= 3 and read >= 3:   return "Q1: AI Champion"
    if lit < 3  and read >= 3:   return "Q2: AI Enthusiast"
    if lit < 3  and read < 3:    return "Q3: AI Novice"
    return "Q4: AI Sceptic"


def band(lit, read):
    if lit is None or read is None:
        return "—"
    avg = (lit + read) / 2
    if avg >= 4.5: return "AI-Fluent Student"
    if avg >= 3.5: return "AI-Curious Student"
    if avg >= 2.5: return "AI-Aware Student"
    return "AI-Anxious Student"


# ═══════════════════════════════════════════════════════════════════════════════
# LOAD A FOLDER OF PDFs
# ═══════════════════════════════════════════════════════════════════════════════

def load_folder(folder, label=""):
    """Returns dict: student_code → {fields, path, lit, read}"""
    results = {}
    pdfs = sorted(glob.glob(os.path.join(folder, "*.pdf")))
    if not pdfs:
        print(f"  WARNING: No PDFs found in {folder}")
        return results

    for pdf_path in pdfs:
        fields = read_pdf_fields(pdf_path)
        code   = get_student_code(fields)
        if not code:
            print(f"  SKIP {os.path.basename(pdf_path)}: no STUDENT_CODE")
            continue
        lit  = score_likert(fields, "L")
        read = score_likert(fields, "R")
        results[code] = {"path": pdf_path, "fields": fields,
                         "lit": lit, "read": read}
        print(f"  [{label}] {os.path.basename(pdf_path):35s} "
              f"code={code}  Lit={lit}  Read={read}")
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# PER-STUDENT 2×2 QUADRANT CHART
# ═══════════════════════════════════════════════════════════════════════════════

def plot_student(code, pre, post, out_path):
    fig, ax = plt.subplots(figsize=(7, 6.5))
    fig.patch.set_facecolor(LGRAY)
    ax.set_facecolor("white")

    mid = 3.0

    # Quadrant backgrounds
    ax.fill_between([1, mid], [mid, mid], [5, 5],   color=QUAD_COLS["Q2"], zorder=0)
    ax.fill_between([mid, 5], [mid, mid], [5, 5],   color=QUAD_COLS["Q1"], zorder=0)
    ax.fill_between([1, mid], [1, 1],     [mid, mid], color=QUAD_COLS["Q3"], zorder=0)
    ax.fill_between([mid, 5], [1, 1],     [mid, mid], color=QUAD_COLS["Q4"], zorder=0)

    # Quadrant labels
    for (qx, qy, qk, va) in [
        (1.06, 4.92, "Q2", "top"), (mid+0.06, 4.92, "Q1", "top"),
        (1.06, 1.08, "Q3", "bottom"), (mid+0.06, 1.08, "Q4", "bottom"),
    ]:
        ax.text(qx, qy, QUAD_LABELS[qk], va=va, ha="left",
                fontsize=6.8, color=QUAD_TEXT[qk],
                fontstyle="italic", alpha=0.9, linespacing=1.4)

    # Midpoint lines
    ax.axvline(mid, color="#AAAAAA", lw=1.0, ls="--", zorder=1)
    ax.axhline(mid, color="#AAAAAA", lw=1.0, ls="--", zorder=1)

    has_pre  = pre  and pre.get("lit")  is not None and pre.get("read")  is not None
    has_post = post and post.get("lit") is not None and post.get("read") is not None

    # Pre point
    if has_pre:
        px, py = pre["lit"], pre["read"]
        ax.scatter(px, py, s=200, color=NAVY, marker="o", zorder=5,
                   edgecolors="white", linewidths=1.5,
                   label=f"PRE  (Lit={px:.2f}, Read={py:.2f})")
        ax.annotate(f"PRE\n{px:.2f}, {py:.2f}", (px, py),
                    textcoords="offset points", xytext=(-42, 8),
                    fontsize=7.5, color=NAVY, fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.25", fc="white",
                              ec=NAVY, alpha=0.9))

    # Post point
    if has_post:
        qx2, qy2 = post["lit"], post["read"]
        ax.scatter(qx2, qy2, s=200, color=GOLD, marker="D", zorder=5,
                   edgecolors="white", linewidths=1.5,
                   label=f"POST (Lit={qx2:.2f}, Read={qy2:.2f})")
        ax.annotate(f"POST\n{qx2:.2f}, {qy2:.2f}", (qx2, qy2),
                    textcoords="offset points", xytext=(8, -28),
                    fontsize=7.5, color="#8B6914", fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.25", fc="white",
                              ec=GOLD, alpha=0.9))

    # Arrow Pre → Post
    if has_pre and has_post:
        dx = post["lit"]  - pre["lit"]
        dy = post["read"] - pre["read"]
        dist = np.sqrt(dx**2 + dy**2)
        if dist > 0.05:
            arrow_col = ("#2ECC71" if (dx >= 0 and dy >= 0)
                         else "#E74C3C" if (dx < 0 and dy < 0)
                         else "#F39C12")
            ax.annotate("",
                xy=(post["lit"], post["read"]),
                xytext=(pre["lit"],  pre["read"]),
                arrowprops=dict(arrowstyle="-|>", color=arrow_col,
                                lw=2.0, mutation_scale=16,
                                connectionstyle="arc3,rad=0.08"),
                zorder=4)
            # Delta text box removed as per request
            pass

    # Axes
    ax.set_xlim(1, 5); ax.set_ylim(1, 5)
    ax.set_xticks([1, 2, 3, 4, 5]); ax.set_yticks([1, 2, 3, 4, 5])
    ax.tick_params(labelsize=8, color="#AAAAAA")
    for spine in ax.spines.values():
        spine.set_color("#CCCCCC")

    ax.set_xlabel("AI LITERACY  →  'Do I understand AI?'",
                  fontsize=9, fontweight="bold", color=NAVY, labelpad=8)
    ax.set_ylabel("AI READINESS  →  'Am I prepared & willing to use AI?'",
                  fontsize=9, fontweight="bold", color="#8B6914", labelpad=8)
    ax.set_title(f"Code: {code}", fontsize=13, fontweight="bold",
                 color=NAVY, pad=10)
    fig.suptitle("HACRI-E  ·  AI Literacy × AI Readiness  ·  Pre → Post",
                 fontsize=10, color=GOLD, y=0.98, fontweight="bold")

    # Summary band box
    pre_q  = quadrant(pre.get("lit"),  pre.get("read"))  if has_pre  else "—"
    post_q = quadrant(post.get("lit"), post.get("read")) if has_post else "—"
    pre_b  = band(pre.get("lit"),  pre.get("read"))  if has_pre  else "—"
    post_b = band(post.get("lit"), post.get("read")) if has_post else "—"
    ax.text(0.5, -0.14,
            f"PRE:   {pre_q}  ·  {pre_b}\nPOST: {post_q}  ·  {post_b}",
            transform=ax.transAxes, ha="center", va="top",
            fontsize=8, color=NAVY,
            bbox=dict(boxstyle="round,pad=0.4", fc=LGRAY,
                      ec="#CCCCCC", alpha=1.0))

    if has_pre or has_post:
        ax.legend(loc="lower right", fontsize=7.5,
                  framealpha=0.9, edgecolor="#CCCCCC", fancybox=True)

    plt.tight_layout(rect=[0, 0.1, 1, 0.96])
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor=LGRAY)
    plt.close(fig)


# ═══════════════════════════════════════════════════════════════════════════════
# COHORT SUMMARY CHART
# ═══════════════════════════════════════════════════════════════════════════════

def plot_cohort(matched, out_path):
    fig, ax = plt.subplots(figsize=(9, 8))
    fig.patch.set_facecolor(LGRAY)
    ax.set_facecolor("white")

    mid = 3.0
    ax.fill_between([1, mid], [mid, mid], [5, 5],   color=QUAD_COLS["Q2"], zorder=0, alpha=0.5)
    ax.fill_between([mid, 5], [mid, mid], [5, 5],   color=QUAD_COLS["Q1"], zorder=0, alpha=0.5)
    ax.fill_between([1, mid], [1, 1],     [mid, mid], color=QUAD_COLS["Q3"], zorder=0, alpha=0.5)
    ax.fill_between([mid, 5], [1, 1],     [mid, mid], color=QUAD_COLS["Q4"], zorder=0, alpha=0.5)

    for (qx, qy, qk, va) in [
        (1.06, 4.92, "Q2", "top"), (mid+0.06, 4.92, "Q1", "top"),
        (1.06, 1.08, "Q3", "bottom"), (mid+0.06, 1.08, "Q4", "bottom"),
    ]:
        ax.text(qx, qy, QUAD_LABELS[qk], va=va, ha="left",
                fontsize=7.5, color=QUAD_TEXT[qk],
                fontstyle="italic", alpha=0.9, linespacing=1.4)

    ax.axvline(mid, color="#AAAAAA", lw=1.0, ls="--", zorder=1)
    ax.axhline(mid, color="#AAAAAA", lw=1.0, ls="--", zorder=1)

    cmap = plt.cm.tab20
    n    = max(len(matched), 1)

    for i, (code, data) in enumerate(sorted(matched.items())):
        col  = cmap(i / n)
        pre  = data.get("pre",  {})
        post = data.get("post", {})
        hp   = pre  and pre.get("lit")  is not None and pre.get("read")  is not None
        hpo  = post and post.get("lit") is not None and post.get("read") is not None

        if hp:
            ax.scatter(pre["lit"], pre["read"], s=80, color=col, marker="o",
                       zorder=5, edgecolors="white", linewidths=0.8, alpha=0.9)
            ax.text(pre["lit"]+0.04, pre["read"]+0.04,
                    code[:5], fontsize=5.5, color=col, alpha=0.8)
        if hpo:
            ax.scatter(post["lit"], post["read"], s=80, color=col, marker="D",
                       zorder=5, edgecolors="white", linewidths=0.8, alpha=0.9)
        if hp and hpo:
            dx = post["lit"]  - pre["lit"]
            dy = post["read"] - pre["read"]
            if np.sqrt(dx**2 + dy**2) > 0.05:
                ax.annotate("",
                    xy=(post["lit"], post["read"]),
                    xytext=(pre["lit"],  pre["read"]),
                    arrowprops=dict(arrowstyle="-|>", color=col, lw=1.2,
                                    mutation_scale=10, alpha=0.7,
                                    connectionstyle="arc3,rad=0.06"),
                    zorder=4)

    ax.set_xlim(1, 5); ax.set_ylim(1, 5)
    ax.set_xticks([1, 2, 3, 4, 5]); ax.set_yticks([1, 2, 3, 4, 5])
    ax.tick_params(labelsize=8, color="#AAAAAA")
    for spine in ax.spines.values():
        spine.set_color("#CCCCCC")
    ax.set_xlabel("AI LITERACY  →  'Do I understand AI?'",
                  fontsize=10, fontweight="bold", color=NAVY, labelpad=8)
    ax.set_ylabel("AI READINESS  →  'Am I prepared & willing to use AI?'",
                  fontsize=10, fontweight="bold", color="#8B6914", labelpad=8)
    ax.set_title(f"HACRI-E Cohort Overview  ·  {len(matched)} Students"
                 f"  ·  ● Pre   ◆ Post",
                 fontsize=11, fontweight="bold", color=NAVY, pad=10)
    fig.suptitle("HACRI-E  ·  AI Literacy × AI Readiness  ·  Workshop Impact",
                 fontsize=10, color=GOLD, y=0.99, fontweight="bold")

    plt.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor=LGRAY)
    plt.close(fig)
    print(f"  Cohort chart: {out_path}")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION H HISTOGRAMS  (POST only)
# H1 — how has understanding changed?  (4 radio options)
# H2 — what was most useful?           (7 checkboxes, up to 3 selected)
# H3 — confidence scale 1–5
# ═══════════════════════════════════════════════════════════════════════════════

H1_OPTIONS = [
    "Significantly increased",
    "Somewhat increased",
    "No change",
    "Somewhat decreased",
]

H3_OPTIONS = [
    "Understanding what AI is",
    "Seeing AI in my subject area",
    "Hands-on AI activity",
    "Ethics & integrity discussion",
    "University expectations",
]

H2_LABELS = [
    "AI literacy course",
    "AI in existing subjects",
    "Workshops / bootcamps",
    "University guidelines",
    "Peer community / club",
    "AI tools provided",
    "Career guidance",
]


def collect_h_responses(post_data_dict):
    """
    Extracts H1, H2, H3 values from all POST field dicts.
    H1: radio field "H1"  → value = one of the option strings (first ~20 chars)
    H2: checkboxes "H2_0"…"H2_6"  → "Yes"/"On" when checked
    H3: radio field "H3"  → value = one of the option strings
    Returns: h1_counts, h2_counts, h3_counts (dicts)
    """
    h1_counts = defaultdict(int)
    h2_counts = defaultdict(int)    # H2_0..H2_6
    h3_1to5   = []                  # numeric scale

    for code, data in post_data_dict.items():
        fields = data.get("fields", {})

        # H1 — radio: value is truncated option text (first 20 chars)
        h1_val = fields.get("H1", "")
        if h1_val:
            # Match to full label
            for lbl in H1_OPTIONS:
                if h1_val.strip().lower() in lbl.lower() or \
                   lbl.lower().startswith(h1_val.strip().lower()):
                    h1_counts[lbl] += 1
                    break
            else:
                h1_counts[h1_val] += 1   # fallback

        # H2 — individual checkboxes H2_0 … H2_6
        for idx in range(7):
            val = fields.get(f"H2_{idx}", "")
            if val and val.lower() not in ("off", "no", "false", ""):
                label = H2_LABELS[idx] if idx < len(H2_LABELS) else f"Option {idx}"
                h2_counts[label] += 1

        # H3 — radio scale (value = option text prefix)
        h3_val = fields.get("H3", "")
        if h3_val:
            for lbl in H3_OPTIONS:
                if h3_val.strip().lower() in lbl.lower() or \
                   lbl.lower().startswith(h3_val.strip().lower()):
                    h3_counts = getattr(collect_h_responses, "_h3_tmp", defaultdict(int))
                    h3_counts[lbl] += 1
                    collect_h_responses._h3_tmp = h3_counts
                    break

    h3_counts = getattr(collect_h_responses, "_h3_tmp", defaultdict(int))
    return h1_counts, h2_counts, h3_counts


def plot_histograms(post_data_dict, out_dir):
    """Generate three histogram/bar charts for H1, H2, H3."""
    h1, h2, h3 = collect_h_responses(post_data_dict)
    n_students  = len(post_data_dict)

    bar_color = NAVY
    accent    = TEAL

    # ── H1 — Understanding change ─────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(8, 4.5))
    fig.patch.set_facecolor(LGRAY)
    ax.set_facecolor("white")
    labels = H1_OPTIONS
    counts = [h1.get(l, 0) for l in labels]
    bars   = ax.barh(labels, counts, color=bar_color, edgecolor="white",
                     linewidth=0.5)
    for bar, cnt in zip(bars, counts):
        if cnt > 0:
            ax.text(bar.get_width() + 0.1, bar.get_y() + bar.get_height()/2,
                    f"{cnt}  ({cnt/n_students*100:.0f}%)" if n_students else f"{cnt}",
                    va="center", fontsize=9, color=NAVY)
    ax.set_xlabel("Number of Students", fontsize=10, color=NAVY)
    ax.set_title("H1 · How has your understanding of AI changed after the induction?",
                 fontsize=10, fontweight="bold", color=NAVY, pad=10)
    ax.set_xlim(0, max(counts or [1]) + 2)
    ax.tick_params(labelsize=9)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    fig.suptitle("HACRI-E  ·  POST-Workshop Section H Responses",
                 fontsize=9, color=GOLD, y=1.01)
    plt.tight_layout()
    p1 = os.path.join(out_dir, "histogram_H1_understanding_change.png")
    fig.savefig(p1, dpi=150, bbox_inches="tight", facecolor=LGRAY)
    plt.close(fig)
    print(f"  H1 histogram: {p1}")

    # ── H2 — Most useful parts ────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(9, 5))
    fig.patch.set_facecolor(LGRAY)
    ax.set_facecolor("white")
    h2_labels = H2_LABELS
    h2_counts  = [h2.get(l, 0) for l in h2_labels]
    bars = ax.barh(h2_labels, h2_counts, color=accent, edgecolor="white",
                   linewidth=0.5)
    for bar, cnt in zip(bars, h2_counts):
        if cnt > 0:
            ax.text(bar.get_width() + 0.1, bar.get_y() + bar.get_height()/2,
                    f"{cnt}  ({cnt/n_students*100:.0f}%)" if n_students else f"{cnt}",
                    va="center", fontsize=9, color=NAVY)
    ax.set_xlabel("Number of Selections (max 3 per student)", fontsize=10, color=NAVY)
    ax.set_title("H2 · Which would you find most useful? (up to 3)",
                 fontsize=10, fontweight="bold", color=NAVY, pad=10)
    ax.set_xlim(0, max(h2_counts or [1]) + 2)
    ax.tick_params(labelsize=9)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    plt.tight_layout()
    p2 = os.path.join(out_dir, "histogram_H2_most_useful.png")
    fig.savefig(p2, dpi=150, bbox_inches="tight", facecolor=LGRAY)
    plt.close(fig)
    print(f"  H2 histogram: {p2}")

    # ── H3 — Most valuable part of induction ─────────────────────────────────
    fig, ax = plt.subplots(figsize=(9, 4.5))
    fig.patch.set_facecolor(LGRAY)
    ax.set_facecolor("white")
    h3_labels = H3_OPTIONS
    h3_vals   = [h3.get(l, 0) for l in h3_labels]
    bars = ax.barh(h3_labels, h3_vals, color=GOLD, edgecolor="white",
                   linewidth=0.5)
    for bar, cnt in zip(bars, h3_vals):
        if cnt > 0:
            ax.text(bar.get_width() + 0.1, bar.get_y() + bar.get_height()/2,
                    f"{cnt}  ({cnt/n_students*100:.0f}%)" if n_students else f"{cnt}",
                    va="center", fontsize=9, color=NAVY)
    ax.set_xlabel("Number of Students", fontsize=10, color=NAVY)
    ax.set_title("H3 · Which part of the induction was most valuable?",
                 fontsize=10, fontweight="bold", color=NAVY, pad=10)
    ax.set_xlim(0, max(h3_vals or [1]) + 2)
    ax.tick_params(labelsize=9)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    plt.tight_layout()
    p3 = os.path.join(out_dir, "histogram_H3_most_valuable.png")
    fig.savefig(p3, dpi=150, bbox_inches="tight", facecolor=LGRAY)
    plt.close(fig)
    print(f"  H3 histogram: {p3}")


# ═══════════════════════════════════════════════════════════════════════════════
# SCORECARD CSV
# ═══════════════════════════════════════════════════════════════════════════════

def export_scorecard(matched, out_path):
    rows = []
    for code, data in sorted(matched.items()):
        pre  = data.get("pre",  {})
        post = data.get("post", {})
        pl = pre.get("lit");   pr_ = pre.get("read")
        ol = post.get("lit");  or_ = post.get("read")
        row = {
            "Student Code":   code,
            "PRE Literacy":   pl,
            "PRE Readiness":  pr_,
            "PRE Quadrant":   quadrant(pl, pr_),
            "PRE Band":       band(pl, pr_),
            "POST Literacy":  ol,
            "POST Readiness": or_,
            "POST Quadrant":  quadrant(ol, or_),
            "POST Band":      band(ol, or_),
            "Δ Literacy":     round(ol - pl, 3) if pl is not None and ol is not None else "",
            "Δ Readiness":    round(or_ - pr_, 3) if pr_ is not None and or_ is not None else "",
        }
        rows.append(row)

    if not rows:
        print("  No data for scorecard.")
        return

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"  Scorecard CSV: {out_path}")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="HACRI-E Plotter — reads submitted PDFs, plots 2×2 charts & histograms"
    )
    parser.add_argument("--pre",  required=True,
                        help="Folder containing filled PRE-Workshop PDFs")
    parser.add_argument("--post", required=True,
                        help="Folder containing filled POST-Workshop PDFs")
    parser.add_argument("--out",  default="hacri_e2_results",
                        help="Output folder (default: hacri_e2_results)")
    args = parser.parse_args()

    student_dir = os.path.join(args.out, "students")
    hist_dir    = os.path.join(args.out, "histograms")
    for d in [args.out, student_dir, hist_dir]:
        os.makedirs(d, exist_ok=True)

    print(f"\n{'='*62}")
    print("HACRI-E  ·  Student Plotter")
    print(f"{'='*62}")

    # ── Load ──────────────────────────────────────────────────────────────────
    print(f"\n[1/5] Reading PRE surveys from:  {args.pre}")
    pre_data  = load_folder(args.pre,  "PRE")
    print(f"      → {len(pre_data)} valid students")

    print(f"\n[2/5] Reading POST surveys from: {args.post}")
    post_data = load_folder(args.post, "POST")
    print(f"      → {len(post_data)} valid students")

    # ── Match ─────────────────────────────────────────────────────────────────
    print(f"\n[3/5] Matching Pre & Post by STUDENT_CODE...")
    all_codes = sorted(set(pre_data) | set(post_data))
    matched   = {}
    for code in all_codes:
        hp = code in pre_data
        ho = code in post_data
        status = "✓ matched" if (hp and ho) else ("pre only" if hp else "post only")
        print(f"      {code}: {status}")
        matched[code] = {
            "pre":  pre_data.get(code),
            "post": post_data.get(code),
        }
    n_full = sum(1 for v in matched.values() if v["pre"] and v["post"])
    print(f"\n      {n_full} students with both Pre & Post  |  {len(matched)} unique codes")

    # ── Per-student plots ─────────────────────────────────────────────────────
    print(f"\n[4/5] Generating per-student charts...")
    for code, data in matched.items():
        out_file = os.path.join(student_dir, f"HACRI_E2_{code}.png")
        plot_student(code, data.get("pre") or {}, data.get("post") or {}, out_file)
        print(f"      → {os.path.basename(out_file)}")

    # ── Cohort chart ──────────────────────────────────────────────────────────
    if matched:
        plot_cohort(matched,
                    os.path.join(args.out, "HACRI_E2_Cohort_Summary.png"))

    # ── H-section histograms (POST only) ──────────────────────────────────────
    print(f"\n[5/5] Generating Section H histograms from POST responses...")
    if post_data:
        plot_histograms(post_data, hist_dir)
    else:
        print("      No POST data — skipping histograms.")

    # ── Scorecard CSV ─────────────────────────────────────────────────────────
    export_scorecard(matched, os.path.join(args.out, "HACRI_E2_Scorecard.csv"))

    print(f"\n{'='*62}")
    print(f"Done.  All outputs in:  {os.path.abspath(args.out)}")
    print(f"  ├── students/     Per-student 2×2 charts")
    print(f"  ├── histograms/   H1, H2, H3 frequency charts")
    print(f"  ├── HACRI_E2_Cohort_Summary.png")
    print(f"  └── HACRI_E2_Scorecard.csv")
    print(f"{'='*62}\n")

    # ── Print scoring summary ─────────────────────────────────────────────────
    print("Scoring schema used:")
    print(f"  AI Literacy  [{len(LIT_ITEMS)} items]: "
          f"{', '.join(LIT_ITEMS)}")
    print(f"  AI Readiness [{len(READ_ITEMS)} items]: "
          f"{', '.join(READ_ITEMS)}")
    print(f"  Reversed     [{len(REVERSED)} items]:  {', '.join(sorted(REVERSED))}")


if __name__ == "__main__":
    main()
