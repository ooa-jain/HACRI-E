"""
Thin wrappers around `hacri_e2_plotter`'s path-based plotting functions.

We don't modify the CLI. Each wrapper builds the shape of dict the plotter
expects, writes the PNG to a deterministic path under `generated/`, and
returns the path. The same path is what `StaticFiles` will serve.

All matplotlib work is CPU-bound; routes should call these via
`run_in_threadpool`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from app.hacri_e2_compat import (  # noqa: E402
    NAVY,
    GOLD,
    LGRAY,
    QUAD_COLS,
    QUAD_LABELS,
    QUAD_TEXT,
)
from app.settings import settings


def _ensure_dir(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


# ── Per-user 2×2 quadrant chart ──────────────────────────────────────────────
def plot_user_png(
    label: str,
    pre_fields: dict[str, Any] | None,
    post_fields: dict[str, Any] | None,
    out_dir: Path | None = None,
) -> Path:
    """Reuse the CLI's plot_student. `label` is the title (email or name)."""
    from hacri_e2_plotter import plot_student
    from app.scoring import score_for_user

    out_dir = out_dir or (settings.generated_root / "users")
    out_path = out_dir / f"{label}.png"
    _ensure_dir(out_path)

    # The CLI's plot_student wants dicts shaped like
    #   {path, fields, lit, read}
    pre_score = score_for_user(pre_fields) if pre_fields else None
    post_score = score_for_user(post_fields) if post_fields else None

    pre = (
        {"fields": pre_fields, "lit": pre_score["lit"], "read": pre_score["read"]}
        if pre_fields and pre_score
        else None
    )
    post = (
        {"fields": post_fields, "lit": post_score["lit"], "read": post_score["read"]}
        if post_fields and post_score
        else None
    )
    try:
        plot_student(label, pre or {}, post or {}, str(out_path))
    except Exception as e:  # pragma: no cover
        # Don't crash the request — write a tiny placeholder PNG with the error.
        _write_placeholder(out_path, f"Chart failed: {e}")
    return out_path


# ── Cohort overlay ───────────────────────────────────────────────────────────
def plot_cohort_png(
    matched: dict[str, dict[str, Any]],
    out_dir: Path | None = None,
    out_path: Path | None = None,
) -> Path:
    from hacri_e2_plotter import plot_cohort
    from app.scoring import score_for_user

    if out_path is None:
        out_dir = out_dir or settings.generated_root
        out_path = out_dir / "cohort.png"
    _ensure_dir(out_path)
    # The CLI expects matched[email] = {"pre": {...}, "post": {...}}
    # Build the right shape.
    norm: dict[str, dict[str, Any]] = {}
    for code, data in matched.items():
        pre_fields = data.get("pre")
        post_fields = data.get("post")
        pre_score = score_for_user(pre_fields) if pre_fields else None
        post_score = score_for_user(post_fields) if post_fields else None
        norm[code] = {
            "pre": (
                {"fields": pre_fields, "lit": pre_score["lit"], "read": pre_score["read"]}
                if pre_fields and pre_score
                else None
            ),
            "post": (
                {"fields": post_fields, "lit": post_score["lit"], "read": post_score["read"]}
                if post_fields and post_score
                else None
            ),
        }
    try:
        plot_cohort(norm, str(out_path))
    except Exception as e:  # pragma: no cover
        _write_placeholder(out_path, f"Cohort chart failed: {e}")
    return out_path


# ── Section H histograms (POST only) ─────────────────────────────────────────
def plot_h_histograms_png(
    post_data: dict[str, dict[str, Any]],
    out_dir: Path | None = None,
) -> dict[str, Path]:
    """
    The CLI's `plot_histograms` writes three PNGs into a directory and
    returns nothing. We wrap it to know the final paths.
    """
    from hacri_e2_plotter import plot_histograms

    out_dir = out_dir or (settings.generated_root / "histograms")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Adapt: the CLI iterates `post_data[email]["fields"]`
    adapted: dict[str, dict[str, Any]] = {}
    for email, data in post_data.items():
        adapted[email] = {"fields": data.get("fields") or data}

    try:
        plot_histograms(adapted, str(out_dir))
    except Exception as e:  # pragma: no cover
        # Write placeholders for each
        for name in ("histogram_H1_understanding_change.png",
                     "histogram_H2_most_useful.png",
                     "histogram_H3_most_valuable.png"):
            _write_placeholder(out_dir / name, f"Histogram failed: {e}")

    return {
        "H1": out_dir / "histogram_H1_understanding_change.png",
        "H2": out_dir / "histogram_H2_most_useful.png",
        "H3": out_dir / "histogram_H3_most_valuable.png",
    }


def _write_placeholder(path: Path, msg: str) -> None:
    """Last-resort PNG so the page still loads with an error message."""
    _ensure_dir(path)
    fig, ax = plt.subplots(figsize=(6, 4))
    fig.patch.set_facecolor(LGRAY)
    ax.set_facecolor("white")
    ax.text(
        0.5, 0.5,
        msg,
        ha="center", va="center",
        fontsize=11, color=NAVY, wrap=True,
        transform=ax.transAxes,
    )
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_color("#CCCCCC")
    fig.tight_layout()
    fig.savefig(str(path), dpi=120, bbox_inches="tight", facecolor=LGRAY)
    plt.close(fig)


# Re-exports for templates / results page
QUADRANT_COLORS = QUAD_COLS
QUADRANT_LABELS = QUAD_LABELS
QUADRANT_TEXT = QUAD_TEXT
PALETTE = {"NAVY": NAVY, "GOLD": GOLD}


def safe_delete(path: Path) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def plot_histograms_png(
    matched: dict[str, dict[str, Any]],
    out_dir: Path | None = None,
    out_path: Path | None = None,
) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from app.scoring import score_for_user

    if out_path is None:
        out_dir = out_dir or settings.generated_root
        out_path = out_dir / "histograms.png"
    _ensure_dir(out_path)

    pre_lits = []
    pre_reads = []
    post_lits = []
    post_reads = []

    for email, data in matched.items():
        pre_fields = data.get("pre")
        post_fields = data.get("post")
        if pre_fields:
            pre_score = score_for_user(pre_fields)
            if pre_score and pre_score.get("lit") is not None:
                pre_lits.append(pre_score["lit"])
                pre_reads.append(pre_score["read"])
        if post_fields:
            post_score = score_for_user(post_fields)
            if post_score and post_score.get("lit") is not None:
                post_lits.append(post_score["lit"])
                post_reads.append(post_score["read"])

    # Create subplots
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4))

    # Color palette matching theme
    navy_col = "#1a3a7a"
    teal_col = "#0d9488"

    # 1. Literacy Distribution
    bins = np.linspace(0, 10, 11)
    if pre_lits:
        ax1.hist(pre_lits, bins=bins, alpha=0.5, label="Pre-Survey", color=navy_col, edgecolor="black")
    if post_lits:
        ax1.hist(post_lits, bins=bins, alpha=0.5, label="Post-Survey", color=teal_col, edgecolor="black")
    ax1.set_title("AI Literacy Score Distribution", fontsize=12, fontweight="bold", color="#0d2147")
    ax1.set_xlabel("Score (0-10)", fontsize=10)
    ax1.set_ylabel("Frequency", fontsize=10)
    ax1.legend(loc="upper left")
    ax1.set_xticks(range(11))
    ax1.grid(True, linestyle="--", alpha=0.4)

    # 2. Readiness Distribution
    if pre_reads:
        ax2.hist(pre_reads, bins=bins, alpha=0.5, label="Pre-Survey", color=navy_col, edgecolor="black")
    if post_reads:
        ax2.hist(post_reads, bins=bins, alpha=0.5, label="Post-Survey", color=teal_col, edgecolor="black")
    ax2.set_title("AI Readiness Score Distribution", fontsize=12, fontweight="bold", color="#0d2147")
    ax2.set_xlabel("Score (0-10)", fontsize=10)
    ax2.set_ylabel("Frequency", fontsize=10)
    ax2.legend(loc="upper left")
    ax2.set_xticks(range(11))
    ax2.grid(True, linestyle="--", alpha=0.4)

    fig.tight_layout()
    try:
        fig.savefig(str(out_path), dpi=150)
    except Exception as e:
        _write_placeholder(out_path, f"Histograms chart failed: {e}")
    finally:
        plt.close(fig)

    return out_path


def plot_h1_histogram_custom(
    matched: dict[str, dict[str, Any]],
    out_path: Path,
) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from collections import defaultdict
    from hacri_e2_plotter import H1_OPTIONS

    h1_counts = defaultdict(int)
    n_students = len(matched)

    for email, data in matched.items():
        post_fields = data.get("post") or {}
        h1_val = post_fields.get("H1", "")
        if h1_val:
            for lbl in H1_OPTIONS:
                if h1_val.strip().lower() in lbl.lower() or \
                   lbl.lower().startswith(h1_val.strip().lower()):
                    h1_counts[lbl] += 1
                    break
            else:
                h1_counts[h1_val] += 1

    fig, ax = plt.subplots(figsize=(8, 4))
    fig.patch.set_facecolor("#F5F6FA")
    ax.set_facecolor("white")
    labels = H1_OPTIONS
    counts = [h1_counts.get(l, 0) for l in labels]
    
    bar_color = "#1a3a7a"
    bars = ax.barh(labels, counts, color=bar_color, edgecolor="white", linewidth=0.5)
    
    for bar, cnt in zip(bars, counts):
        if cnt > 0:
            ax.text(bar.get_width() + 0.1, bar.get_y() + bar.get_height()/2,
                    f"{cnt}  ({cnt/n_students*100:.0f}%)" if n_students else f"{cnt}",
                    va="center", fontsize=9, color="#1a3a7a", fontweight="bold")
                    
    ax.set_xlabel("Number of Students", fontsize=10, color="#1a3a7a", fontweight="bold")
    ax.set_title("H1 · How has your understanding of AI changed after the induction?",
                 fontsize=11, fontweight="bold", color="#1a3a7a", pad=10)
    ax.set_xlim(0, max(counts or [1]) + 2)
    ax.tick_params(labelsize=9)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    
    fig.tight_layout()
    try:
        fig.savefig(str(out_path), dpi=150, bbox_inches="tight", facecolor="#F5F6FA")
    except Exception as e:
        _write_placeholder(out_path, f"H1 Chart failed: {e}")
    finally:
        plt.close(fig)

    return out_path