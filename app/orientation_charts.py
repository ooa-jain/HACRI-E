"""
orientation_charts.py — the picture half of the Deeksharambh report.

Drawn to sit inside the Deeksharambh deck (`orientation_ppt.py`) and to look
like it: a serif face, navy headings, one teal accent, and the four muted
series colours the department-wise charts have always used. Colour carries the
series, not a verdict — the words do the judging.

Every function writes a PNG and returns its path, so both the dashboard and the
PowerPoint deck draw from exactly the same picture.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

# Georgia is the deck's face; DejaVu Serif ships with matplotlib and stands in
# on machines that do not have it, so a chart is never drawn in the wrong voice.
plt.rcParams["font.family"] = "serif"
plt.rcParams["font.serif"] = ["Georgia", "Bookman Old Style", "DejaVu Serif"]

NAVY = "#2e3a64"
TEAL = "#21a88a"
TEAL_DEEP = "#17806a"
MINT = "#d9f1ec"
GOLD = "#c8a45a"
INK = "#2f3640"
MUTED = "#5b6570"
PAPER = "#ffffff"
LINE = "#dfe4e8"

# One bar per series, in the order a legend reads them.
SERIES = ["#4a7ebb", "#c0504d", "#9bbb59", "#8064a2"]

# Single-hue ramp for a 1-10 distribution: pale mint at the low end, deep teal
# at the high one.
VIBE_CMAP = LinearSegmentedColormap.from_list(
    "vibe", ["#cfe9e2", "#8fd0be", "#4fb99b", "#21a88a", "#12735e"]
)

# What an average vibe actually means, in words a reader can use.
MOODS: list[tuple[float, str, str]] = [
    (9.0, "Buzzing", "#12735e"),
    (8.0, "Loving it", "#21a88a"),
    (7.0, "Good vibes", "#4fb99b"),
    (6.0, "Warming up", "#c8a45a"),
    (5.0, "Mixed feelings", "#c98a4d"),
    (0.0, "Needs a lift", "#c0504d"),
]


def mood_for(avg: float | None) -> tuple[str, str]:
    """(word, colour) for an average out of ten."""
    if avg is None:
        return ("No answers yet", MUTED)
    for floor, word, colour in MOODS:
        if avg >= floor:
            return (word, colour)
    return ("Needs a lift", "#c0504d")


def clean(label: str, limit: int = 34) -> str:
    """Drop emoji and trim — matplotlib's fonts draw them as empty boxes."""
    text = "".join(
        ch for ch in str(label)
        if ch.isalnum() or ch.isspace() or ch in "&/-–—',.()+%:"
    ).strip()
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _ensure(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _empty(path: Path, message: str, size=(10, 5)) -> Path:
    fig, ax = plt.subplots(figsize=size)
    ax.axis("off")
    ax.text(0.5, 0.5, message, ha="center", va="center",
            fontsize=15, color=MUTED, fontweight="bold")
    fig.savefig(str(_ensure(path)), dpi=150, facecolor=PAPER)
    plt.close(fig)
    return path


def _style(ax) -> None:
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(LINE)
    ax.tick_params(colors=MUTED, labelsize=11, length=0)


# ── The headline: how the week felt ───────────────────────────────────────────
def plot_vibe_hero(stats: dict, out_path: Path, title: str = "Overall vibe of the students") -> Path:
    """Score-by-score distribution, coloured from "wanted to leave" to "never ended"."""
    options = [o for o in stats.get("options", []) if o.get("count")]
    if not options:
        return _empty(out_path, "No vibe ratings yet")

    scores = [int(o["label"]) for o in options]
    counts = [o["count"] for o in options]
    avg = stats.get("avg")
    word, colour = mood_for(avg)

    fig, ax = plt.subplots(figsize=(11, 5.2))
    fig.patch.set_facecolor(PAPER)
    bars = ax.bar(scores, counts,
                  color=[VIBE_CMAP((s - 1) / 9) for s in scores],
                  width=0.72, zorder=3)
    for bar, count in zip(bars, counts):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                f"{count}", ha="center", va="bottom",
                fontsize=11, fontweight="bold", color=INK)

    if avg is not None:
        ax.axvline(avg, color=NAVY, linestyle="--", linewidth=2, zorder=4)
        ax.text(avg, max(counts) * 1.16, f"  average {avg:.1f}",
                color=NAVY, fontsize=12, fontweight="bold", va="center")

    ax.set_title(title, fontsize=17, fontweight="bold", color=NAVY, pad=18, loc="left")
    ax.set_xlabel("1 = I wanted to leave        →        10 = I wish it never ended",
                  fontsize=11, color=MUTED, labelpad=10)
    ax.set_ylabel("Students", fontsize=11, color=MUTED)
    ax.set_xticks(range(1, 11))
    ax.set_ylim(0, max(counts) * 1.32)
    ax.grid(axis="y", linestyle=":", alpha=0.35, zorder=0)
    _style(ax)

    if avg is not None:
        ax.text(0.995, 1.14, word.upper(), transform=ax.transAxes,
                ha="right", va="top", fontsize=15, fontweight="bold", color=colour)

    fig.tight_layout()
    fig.savefig(str(_ensure(out_path)), dpi=150, facecolor=PAPER)
    plt.close(fig)
    return out_path


def plot_nps_ring(stats: dict, out_path: Path) -> Path:
    """Promoters / passives / detractors as a ring with the NPS in the middle."""
    parts = [stats.get("promoters", 0), stats.get("passives", 0), stats.get("detractors", 0)]
    if not sum(parts):
        return _empty(out_path, "No recommendation scores yet", size=(7, 5))

    labels = ["Promoters 9–10", "Passives 7–8", "Detractors 0–6"]
    colours = [TEAL, "#e8c468", "#c0504d"]

    fig, ax = plt.subplots(figsize=(7.4, 5.4))
    fig.patch.set_facecolor(PAPER)
    wedges, _ = ax.pie(parts, colors=colours, startangle=90,
                       wedgeprops=dict(width=0.36, edgecolor=PAPER, linewidth=3))
    nps = stats.get("nps")
    ax.text(0, 0.12, "—" if nps is None else f"{nps:+.0f}",
            ha="center", va="center", fontsize=42, fontweight="bold", color=NAVY)
    ax.text(0, -0.24, "N P S", ha="center", va="center",
            fontsize=13, fontweight="bold", color=MUTED)

    total = sum(parts)
    ax.legend(wedges,
              [f"{lbl} — {n} ({100 * n / total:.0f}%)" for lbl, n in zip(labels, parts)],
              loc="lower center", bbox_to_anchor=(0.5, -0.12),
              frameon=False, fontsize=11, ncol=1)
    ax.set_title("Would they recommend JAIN?", fontsize=16, fontweight="bold",
                 color=NAVY, pad=14)
    fig.tight_layout()
    fig.savefig(str(_ensure(out_path)), dpi=150, facecolor=PAPER)
    plt.close(fig)
    return out_path


def plot_top_options(options: list[dict], out_path: Path, title: str,
                     colour: str = TEAL, limit: int = 7) -> Path:
    """The loudest answers to one multi-select question."""
    options = [o for o in options if o.get("count")][:limit]
    if not options:
        return _empty(out_path, "Nobody answered this yet", size=(9, 4))

    options = list(reversed(options))
    labels = [clean(o["label"], 40) for o in options]
    counts = [o["count"] for o in options]
    shares = [o.get("pct", 0) for o in options]
    top = max(counts)

    fig, ax = plt.subplots(figsize=(10, max(2.8, 0.62 * len(options) + 1.5)))
    fig.patch.set_facecolor(PAPER)
    bars = ax.barh(labels, counts,
                   color=[(colour if i == len(counts) - 1 else colour) for i in range(len(counts))],
                   alpha=0.92, height=0.62, zorder=3)
    for bar, count, share in zip(bars, counts, shares):
        ax.text(bar.get_width() + top * 0.02, bar.get_y() + bar.get_height() / 2,
                f"{count}  ·  {share:.0f}%", va="center",
                fontsize=11, fontweight="bold", color=INK)

    ax.set_xlim(0, top * 1.28)
    ax.set_title(title, fontsize=16, fontweight="bold", color=NAVY, loc="left", pad=14)
    ax.grid(axis="x", linestyle=":", alpha=0.3, zorder=0)
    _style(ax)
    ax.tick_params(axis="y", labelsize=11.5)
    fig.tight_layout()
    fig.savefig(str(_ensure(out_path)), dpi=150, facecolor=PAPER)
    plt.close(fig)
    return out_path


def plot_response_rate(rows: list[dict], out_path: Path,
                       title: str = "Who has answered, department by department") -> Path:
    """Filled vs still-pending per department, stacked."""
    rows = [r for r in rows if r.get("eligible")]
    if not rows:
        return _empty(out_path, "Nobody is registered here yet")

    rows = sorted(rows, key=lambda r: r.get("pct", 0))
    labels = [clean(r["dept"], 30) for r in rows]
    filled = [r.get("filled", 0) for r in rows]
    pending = [max(0, r.get("eligible", 0) - r.get("filled", 0)) for r in rows]

    fig, ax = plt.subplots(figsize=(11, max(3.2, 0.62 * len(rows) + 1.8)))
    fig.patch.set_facecolor(PAPER)
    ax.barh(labels, filled, color=TEAL, height=0.62, label="Filled", zorder=3)
    ax.barh(labels, pending, left=filled, color=MINT, height=0.62,
            label="Still pending", zorder=3)
    widest = max(r["eligible"] for r in rows)
    for i, row in enumerate(rows):
        ax.text(row["eligible"] + widest * 0.02, i, f"{row.get('pct', 0):.0f}%",
                va="center", fontsize=11, fontweight="bold", color=INK)

    ax.set_xlim(0, widest * 1.16)
    ax.set_title(title, fontsize=17, fontweight="bold", color=NAVY, loc="left", pad=34)
    # Above the bars: inside the axes it collides with the shortest rows.
    ax.legend(frameon=False, fontsize=11, ncol=2,
              loc="lower right", bbox_to_anchor=(1.0, 1.005))
    ax.grid(axis="x", linestyle=":", alpha=0.3, zorder=0)
    _style(ax)
    ax.tick_params(axis="y", labelsize=11.5)
    fig.tight_layout()
    fig.savefig(str(_ensure(out_path)), dpi=150, facecolor=PAPER,
                bbox_inches="tight", pad_inches=0.16)
    plt.close(fig)
    return out_path


def plot_dept_series(rows: list[dict], series: list[tuple[str, str]], out_path: Path,
                     maximum: float = 10.0, title: str = "",
                     empty: str = "No department averages yet") -> Path:
    """Department-wise grouped bars — one bar per measure, one group per department.

    The shape the Deeksharambh deck has always used for its department slides:
    the departments down the left, a bar per measure across, the value printed
    on each bar, and the legend off to the right where it cannot crowd them.

    `series` is [(key, label), ...] read off each row.
    """
    keys = [key for key, _ in series]
    rows = [r for r in rows if any(r.get(k) is not None for k in keys)]
    if not rows or not series:
        return _empty(out_path, empty)

    rows = sorted(rows, key=lambda r: -(r.get(keys[0]) or 0))
    labels = [clean(r["dept"], 42) for r in rows]
    count = len(series)
    height = 0.8 / count
    positions = range(len(rows))

    fig, ax = plt.subplots(
        figsize=(9.6, min(7.2, max(2.8, 0.34 * count * len(rows) + 1.3))))
    fig.patch.set_facecolor(PAPER)

    for i, (key, label) in enumerate(series):
        values = [(r.get(key) or 0) for r in rows]
        # Top series at the top of each group, so the legend reads downwards.
        offset = (count - 1) / 2 - i
        bars = ax.barh([p + offset * height for p in positions], values,
                       height=height * 0.86, color=SERIES[i % len(SERIES)],
                       label=label, zorder=3)
        for bar, value, row in zip(bars, values, rows):
            # A department that did not answer this measure gets no bar and no
            # label — a "0" printed at the axis reads as a score of zero.
            if not row.get(key):
                continue
            ax.text(bar.get_width() - maximum * 0.012,
                    bar.get_y() + bar.get_height() / 2,
                    f"{value:.1f}".rstrip("0").rstrip("."),
                    va="center", ha="right", fontsize=10, color=INK,
                    bbox=dict(boxstyle="square,pad=0.2", facecolor=PAPER,
                              edgecolor="none"), zorder=4)

    ax.set_yticks(list(positions))
    ax.set_yticklabels(labels, fontsize=10.5, fontweight="bold", color=MUTED)
    ax.set_xlim(0, maximum * 1.04)
    ax.invert_yaxis()
    if title:
        ax.set_title(title, fontsize=16, fontweight="bold", color=NAVY, pad=16)
    ax.legend(frameon=False, fontsize=10.5, loc="upper left",
              bbox_to_anchor=(1.01, 1.0), labelcolor=NAVY)
    ax.grid(axis="x", linestyle=":", alpha=0.3, zorder=0)
    _style(ax)
    ax.tick_params(axis="x", labelsize=10)
    fig.tight_layout()
    fig.savefig(str(_ensure(out_path)), dpi=150, facecolor=PAPER,
                bbox_inches="tight", pad_inches=0.16)
    plt.close(fig)
    return out_path

