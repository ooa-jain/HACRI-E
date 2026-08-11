"""
orientation_charts.py — the picture half of the Deeksharambh report.

These are deliberately louder than the HACRI-E score charts: the orientation
survey is a mood reading of a first week, so the charts lead with the number
students would recognise (a vibe out of ten, an NPS ring) rather than with a
grid of axes.

Every function writes a PNG and returns its path, so both the dashboard and the
PowerPoint deck draw from exactly the same picture.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

NAVY = "#0d2147"
GOLD = "#e6b324"
INK = "#1a1a2e"
MUTED = "#64748b"
PAPER = "#ffffff"

# Cool-to-warm ramp used everywhere a 1-10 feeling is drawn.
VIBE_CMAP = LinearSegmentedColormap.from_list(
    "vibe", ["#e11d48", "#f97316", "#facc15", "#84cc16", "#059669"]
)

# What an average vibe actually means, in words a reader can use.
MOODS: list[tuple[float, str, str]] = [
    (9.0, "Buzzing", "#059669"),
    (8.0, "Loving it", "#16a34a"),
    (7.0, "Good vibes", "#84cc16"),
    (6.0, "Warming up", "#facc15"),
    (5.0, "Mixed feelings", "#f97316"),
    (0.0, "Needs a lift", "#e11d48"),
]


def mood_for(avg: float | None) -> tuple[str, str]:
    """(word, colour) for an average out of ten."""
    if avg is None:
        return ("No answers yet", MUTED)
    for floor, word, colour in MOODS:
        if avg >= floor:
            return (word, colour)
    return ("Needs a lift", "#e11d48")


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
    ax.spines["bottom"].set_color("#e2e8f0")
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
    colours = ["#059669", "#facc15", "#e11d48"]

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


def plot_feeling_meters(items: list[tuple[str, float | None, int]], out_path: Path,
                        title: str = "How the cohort feels") -> Path:
    """Rounded meters — one per headline average, filled to its share of the max."""
    items = [(label, value, maximum) for label, value, maximum in items if value is not None]
    if not items:
        return _empty(out_path, "No ratings yet", size=(10, 4))

    fig, ax = plt.subplots(figsize=(10.5, 0.95 * len(items) + 1.6))
    fig.patch.set_facecolor(PAPER)
    ax.set_xlim(0, 1.14)
    ax.set_ylim(-0.6, len(items) - 0.4)
    ax.axis("off")

    for i, (label, value, maximum) in enumerate(reversed(items)):
        share = max(0.0, min(1.0, value / maximum))
        colour = VIBE_CMAP(share)
        ax.add_patch(FancyBboxPatch((0, i - 0.17), 1.0, 0.34,
                                    boxstyle="round,pad=0,rounding_size=0.17",
                                    facecolor="#eef2f7", edgecolor="none"))
        if share > 0:
            ax.add_patch(FancyBboxPatch((0, i - 0.17), max(share, 0.02), 0.34,
                                        boxstyle="round,pad=0,rounding_size=0.17",
                                        facecolor=colour, edgecolor="none"))
        ax.text(0, i + 0.32, label, fontsize=12, fontweight="bold", color=INK)
        ax.text(1.03, i, f"{value:.1f}/{maximum}", fontsize=13,
                fontweight="bold", color=NAVY, va="center")

    ax.set_title(title, fontsize=17, fontweight="bold", color=NAVY, loc="left", pad=16)
    fig.tight_layout()
    fig.savefig(str(_ensure(out_path)), dpi=150, facecolor=PAPER)
    plt.close(fig)
    return out_path


def plot_dept_vibe(rows: list[dict], out_path: Path,
                   value_key: str = "vibe", maximum: int = 10,
                   title: str = "Vibe by department") -> Path:
    """One bar per department, coloured by how the department actually feels."""
    rows = [r for r in rows if r.get(value_key) is not None]
    if not rows:
        return _empty(out_path, "No department averages yet")

    rows = sorted(rows, key=lambda r: r[value_key])
    labels = [clean(r["dept"], 30) for r in rows]
    values = [r[value_key] for r in rows]
    counts = [r.get("filled", 0) for r in rows]

    fig, ax = plt.subplots(figsize=(11, max(3.2, 0.62 * len(rows) + 1.8)))
    fig.patch.set_facecolor(PAPER)
    bars = ax.barh(labels, values,
                   color=[VIBE_CMAP(v / maximum) for v in values],
                   height=0.62, zorder=3)
    for bar, value, count in zip(bars, values, counts):
        ax.text(bar.get_width() + maximum * 0.015, bar.get_y() + bar.get_height() / 2,
                f"{value:.1f}   ({count})", va="center",
                fontsize=11, fontweight="bold", color=INK)

    ax.set_xlim(0, maximum * 1.18)
    ax.set_title(title, fontsize=17, fontweight="bold", color=NAVY, loc="left", pad=16)
    ax.set_xlabel(f"Average out of {maximum}  ·  (n) = responses", fontsize=11, color=MUTED)
    ax.grid(axis="x", linestyle=":", alpha=0.35, zorder=0)
    _style(ax)
    ax.tick_params(axis="y", labelsize=11.5)
    fig.tight_layout()
    fig.savefig(str(_ensure(out_path)), dpi=150, facecolor=PAPER)
    plt.close(fig)
    return out_path


def plot_top_options(options: list[dict], out_path: Path, title: str,
                     colour: str = "#2563eb", limit: int = 7) -> Path:
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
    ax.barh(labels, filled, color="#0d9488", height=0.62, label="Filled", zorder=3)
    ax.barh(labels, pending, left=filled, color="#e2e8f0", height=0.62,
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
    fig.savefig(str(_ensure(out_path)), dpi=150, facecolor=PAPER)
    plt.close(fig)
    return out_path
