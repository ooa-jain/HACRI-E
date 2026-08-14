"""
cohort_charts.py — figures for the outcome and impact report.

Restrained on purpose: this report goes in front of academic committees, so it
is navy, gold and teal, no emoji, no decoration that isn't carrying a number.
Every function writes a PNG and returns its path.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

NAVY = "#0d2147"
GOLD = "#c9a84c"
TEAL = "#0d9488"
SLATE = "#64748b"
INK = "#1a1a2e"
LINE = "#e2e8f0"
PAPER = "#ffffff"
ROSE = "#be123c"

PRE_COLOUR = "#1e3a8a"
POST_COLOUR = TEAL


def _ensure(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _save(fig, path: Path) -> Path:
    fig.savefig(str(_ensure(path)), dpi=150, facecolor=PAPER)
    plt.close(fig)
    return path


def _empty(path: Path, message: str, size=(10, 4.5)) -> Path:
    fig, ax = plt.subplots(figsize=size)
    ax.axis("off")
    ax.text(0.5, 0.5, message, ha="center", va="center",
            fontsize=14, color=SLATE, fontweight="bold")
    return _save(fig, path)


def _style(ax) -> None:
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(LINE)
    ax.tick_params(colors=SLATE, labelsize=10, length=0)
    ax.grid(axis="y", linestyle=":", alpha=.35, zorder=0)


def clean(label: str, limit: int = 32) -> str:
    """Drop emoji and trim — the report's charts are plain text only."""
    text = "".join(ch for ch in str(label)
                   if ch.isalnum() or ch.isspace() or ch in "&/-–—',.()+%:·")
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# ── The journey ──────────────────────────────────────────────────────────────
def plot_journey(journey: dict, out_path: Path, title: str = "") -> Path:
    """The wire flow: registered, baseline, Deeksharambh, post — and the drop."""
    stages = journey.get("stages") or []
    if not stages:
        return _empty(out_path, "Nobody has registered in this scope yet")

    fig, ax = plt.subplots(figsize=(12.6, 3.5))
    ax.set_xlim(0, len(stages) * 3)
    ax.set_ylim(0.5, 2.72)
    ax.axis("off")

    tones = [NAVY, PRE_COLOUR, GOLD, TEAL]
    for i, stage in enumerate(stages):
        left = i * 3 + 0.34
        tone = tones[i % len(tones)]
        ax.add_patch(FancyBboxPatch((left, 1.05), 2.0, 1.5,
                                    boxstyle="round,pad=0.02,rounding_size=0.12",
                                    facecolor=tone, edgecolor="none"))
        middle = left + 1.0
        ax.text(middle, 2.16, stage["label"].upper(), ha="center", va="center",
                fontsize=10.5, fontweight="bold", color="#ffffff")
        ax.text(middle, 1.66, f"{stage['count']}", ha="center", va="center",
                fontsize=27, fontweight="bold", color="#ffffff")
        ax.text(middle, 1.24, f"{stage['of_registered']:.0f}% of registered",
                ha="center", va="center", fontsize=9, color="#e2e8f0")
        ax.text(middle, 0.78, clean(stage["blurb"], 34), ha="center", va="center",
                fontsize=8.6, color=SLATE)

        if i:
            gap = (left - 0.5, left - 0.08)   # the run between two boxes
            ax.add_patch(FancyArrowPatch((gap[0] - 0.5, 1.8), (gap[1], 1.8),
                                         arrowstyle="-|>", mutation_scale=18,
                                         color=NAVY, linewidth=2))
            centre = (gap[0] - 0.5 + gap[1]) / 2
            ax.text(centre, 2.12, f"{stage['of_previous']:.0f}%", ha="center",
                    fontsize=9.5, fontweight="bold", color=INK)
            if stage["dropped"]:
                ax.text(centre, 1.42, f"-{stage['dropped']}", ha="center",
                        fontsize=9.5, fontweight="bold", color=ROSE)

    if title:
        ax.set_title(title, fontsize=16, fontweight="bold", color=NAVY, loc="left", pad=14)
    fig.tight_layout()
    return _save(fig, out_path)


# ── Score distributions ──────────────────────────────────────────────────────
def plot_distribution(block: dict, out_path: Path, title: str = "", colour: str = PRE_COLOUR) -> Path:
    """How one survey's literacy and readiness scores fell."""
    if not block.get("scored"):
        return _empty(out_path, "No scored responses in this scope yet")

    labels = [row["label"] for row in block["literacy"]]
    fig, axes = plt.subplots(1, 2, figsize=(12.4, 4.4), sharey=True)
    for ax, key, name, avg in (
        (axes[0], "literacy", "AI Literacy", block["avg_lit"]),
        (axes[1], "readiness", "AI Readiness", block["avg_read"]),
    ):
        counts = [row["count"] for row in block[key]]
        ax.bar(labels, counts, color=colour, width=.68, zorder=3)
        for x, count in enumerate(counts):
            if count:
                ax.text(x, count, str(count), ha="center", va="bottom",
                        fontsize=9.5, fontweight="bold", color=INK)
        ax.set_title(f"{name}   ·   average {avg if avg is not None else '—'} / 5",
                     fontsize=12, fontweight="bold", color=NAVY, loc="left")
        ax.set_xlabel("Score band", fontsize=9.5, color=SLATE)
        ax.tick_params(axis="x", labelrotation=45)
        _style(ax)
    axes[0].set_ylabel("Students", fontsize=10, color=SLATE)

    if title:
        fig.suptitle(title, fontsize=15, fontweight="bold", color=NAVY, x=.012, ha="left")
    fig.tight_layout()
    return _save(fig, out_path)


def plot_pre_post(outcome: dict, impact: dict, out_path: Path,
                  title: str = "Baseline against post workshop") -> Path:
    """The two curves side by side — the shape of the shift."""
    if not outcome.get("scored") and not impact.get("scored"):
        return _empty(out_path, "No scored responses in this scope yet")

    labels = [row["label"] for row in outcome["literacy"]]
    x = range(len(labels))
    fig, axes = plt.subplots(1, 2, figsize=(12.4, 4.4), sharey=True)
    for ax, key, name in ((axes[0], "literacy", "AI Literacy"),
                          (axes[1], "readiness", "AI Readiness")):
        pre = [row["pct"] for row in outcome[key]]
        post = [row["pct"] for row in impact[key]]
        ax.bar([i - .19 for i in x], pre, width=.36, color=PRE_COLOUR, label="Baseline", zorder=3)
        ax.bar([i + .19 for i in x], post, width=.36, color=POST_COLOUR, label="Post workshop", zorder=3)
        ax.set_xticks(list(x))
        ax.set_xticklabels(labels, rotation=45)
        ax.set_title(name, fontsize=12, fontweight="bold", color=NAVY, loc="left")
        _style(ax)
    axes[0].set_ylabel("Share of students (%)", fontsize=10, color=SLATE)
    axes[1].legend(frameon=False, fontsize=10, loc="upper left")

    fig.suptitle(title, fontsize=15, fontweight="bold", color=NAVY, x=.012, ha="left")
    fig.tight_layout()
    return _save(fig, out_path)


def plot_trajectory(report: dict, out_path: Path,
                    title: str = "From baseline to post workshop") -> Path:
    """Where each department started and where it reached, on one 1-5 scale."""
    rows = []
    outcome, impact = report.get("outcome", {}), report.get("impact", {})
    if outcome.get("avg_overall") is not None:
        rows.append({"dept": "Overall", "pre": outcome["avg_overall"],
                     "post": impact.get("avg_overall")})
    for d in report.get("departments", []):
        if d.get("pre_avg") is not None:
            rows.append({"dept": d["dept"], "pre": d["pre_avg"], "post": d.get("post_avg")})

    if not rows:
        return _empty(out_path, "No scored responses in this scope yet")

    rows = rows[:13][::-1]           # widest first at the bottom, Overall on top
    labels = [clean(r["dept"], 30) for r in rows]

    fig, ax = plt.subplots(figsize=(11.6, max(3.4, .52 * len(rows) + 1.9)))
    for i, row in enumerate(rows):
        pre, post = row["pre"], row["post"]
        if post is not None:
            rising = post >= pre
            ax.annotate("", xy=(post, i), xytext=(pre, i),
                        arrowprops=dict(arrowstyle="-|>", mutation_scale=14,
                                        color=TEAL if rising else ROSE, linewidth=3,
                                        shrinkA=0, shrinkB=0))
            ax.scatter([post], [i], s=110, color=POST_COLOUR, zorder=4,
                       edgecolors="white", linewidths=1.5)
            ax.text(post, i + .3, f"{post:.2f}", ha="center", fontsize=9.5,
                    fontweight="bold", color=INK)
        ax.scatter([pre], [i], s=110, color=PRE_COLOUR, zorder=4,
                   edgecolors="white", linewidths=1.5)
        ax.text(pre, i - .42, f"{pre:.2f}", ha="center", fontsize=9.5,
                fontweight="bold", color=SLATE)

    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(labels, fontsize=10.5)
    ax.set_xlim(1, 5)
    ax.set_ylim(-.7, len(rows) - .3)
    ax.set_xticks([1, 2, 3, 4, 5])
    ax.set_xlabel("Average score out of 5", fontsize=10, color=SLATE)
    ax.set_title(title, fontsize=15, fontweight="bold", color=NAVY, loc="left", pad=26)
    ax.scatter([], [], s=90, color=PRE_COLOUR, label="Baseline")
    ax.scatter([], [], s=90, color=POST_COLOUR, label="Post workshop")
    ax.legend(frameon=False, fontsize=10, ncol=2, loc="lower right",
              bbox_to_anchor=(1.0, 1.0))
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(LINE)
    ax.tick_params(colors=SLATE, length=0)
    ax.grid(axis="x", linestyle=":", alpha=.4, zorder=0)
    fig.tight_layout()
    return _save(fig, out_path)


def plot_mix(outcome: dict, impact: dict, out_path: Path, key: str = "quadrants",
             title: str = "Quadrant mix, baseline against post") -> Path:
    """Quadrant or band counts, before and after."""
    pre_rows, post_rows = outcome.get(key) or [], impact.get(key) or []
    if not any(r["count"] for r in pre_rows + post_rows):
        return _empty(out_path, "No scored responses in this scope yet")

    labels = [clean(r["label"], 26) for r in pre_rows]
    y = range(len(labels))
    fig, ax = plt.subplots(figsize=(11.4, max(3.4, .78 * len(labels) + 1.6)))
    ax.barh([i + .19 for i in y], [r["count"] for r in pre_rows], height=.36,
            color=PRE_COLOUR, label="Baseline", zorder=3)
    ax.barh([i - .19 for i in y], [r["count"] for r in post_rows], height=.36,
            color=POST_COLOUR, label="Post workshop", zorder=3)
    for i, (pre, post) in enumerate(zip(pre_rows, post_rows)):
        ax.text(pre["count"], i + .19, f"  {pre['count']}", va="center",
                fontsize=9.5, fontweight="bold", color=INK)
        ax.text(post["count"], i - .19, f"  {post['count']}", va="center",
                fontsize=9.5, fontweight="bold", color=INK)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=10.5)
    ax.invert_yaxis()
    ax.legend(frameon=False, fontsize=10, loc="lower right")
    ax.set_title(title, fontsize=15, fontweight="bold", color=NAVY, loc="left", pad=12)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color(LINE)
    ax.spines["bottom"].set_color(LINE)
    ax.tick_params(colors=SLATE, length=0)
    ax.grid(axis="x", linestyle=":", alpha=.35, zorder=0)
    fig.tight_layout()
    return _save(fig, out_path)


def plot_movement(movement: dict, out_path: Path,
                  title: str = "Where the matched students moved") -> Path:
    """Gained, unchanged, declined — and the average shift on each scale."""
    total = movement.get("matched", 0)
    if not total:
        return _empty(out_path, "No student has finished both surveys yet", size=(9, 4))

    fig, axes = plt.subplots(1, 2, figsize=(12.2, 4.2),
                             gridspec_kw={"width_ratios": [1.25, 1]})

    parts = [("Improved", movement["gained"], TEAL),
             ("No change", movement["unchanged"], SLATE),
             ("Declined", movement["declined"], ROSE)]
    ax = axes[0]
    ax.bar([p[0] for p in parts], [p[1] for p in parts],
           color=[p[2] for p in parts], width=.6, zorder=3)
    for x, (_, value, _) in enumerate(parts):
        ax.text(x, value, f"{value}\n{100 * value / total:.0f}%", ha="center", va="bottom",
                fontsize=10, fontweight="bold", color=INK)
    ax.set_ylim(0, max(p[1] for p in parts) * 1.32 or 1)
    ax.set_title(f"{total} students completed both surveys",
                 fontsize=12, fontweight="bold", color=NAVY, loc="left")
    _style(ax)

    ax = axes[1]
    deltas = [("AI Literacy", movement.get("avg_delta_lit") or 0),
              ("AI Readiness", movement.get("avg_delta_read") or 0)]
    colours = [TEAL if value >= 0 else ROSE for _, value in deltas]
    ax.barh([d[0] for d in deltas], [d[1] for d in deltas],
            color=colours, height=.42, zorder=3)
    span = max(.25, max(abs(v) for _, v in deltas) * 1.5)
    ax.set_xlim(-span, span)
    for i, (_, value) in enumerate(deltas):
        ax.text(value + (.02 * span if value >= 0 else -.02 * span), i,
                f"{value:+.2f}", va="center", ha="left" if value >= 0 else "right",
                fontsize=11, fontweight="bold", color=INK)
    ax.axvline(0, color=SLATE, linewidth=1)
    ax.set_title("Average change per student (points out of 5)",
                 fontsize=12, fontweight="bold", color=NAVY, loc="left")
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(LINE)
    ax.tick_params(colors=SLATE, labelsize=10.5, length=0)
    ax.grid(axis="x", linestyle=":", alpha=.35, zorder=0)

    fig.suptitle(title, fontsize=15, fontweight="bold", color=NAVY, x=.012, ha="left")
    fig.tight_layout()
    return _save(fig, out_path)


# ── Departments and campuses ─────────────────────────────────────────────────
def plot_departments(rows: list[dict], out_path: Path, metric: str = "completion_pct",
                     title: str = "Completion by department") -> Path:
    """One bar per department — completion, or the score shift."""
    rows = [r for r in rows if r.get(metric) is not None]
    if not rows:
        return _empty(out_path, "No department data in this scope yet")

    rows = sorted(rows, key=lambda r: r[metric])[-14:]
    labels = [clean(r["dept"], 30) for r in rows]
    values = [r[metric] for r in rows]
    suffix = "%" if metric.endswith("pct") else ""
    colours = [TEAL if v >= 0 else ROSE for v in values]

    fig, ax = plt.subplots(figsize=(11.4, max(3.2, .56 * len(rows) + 1.7)))
    ax.barh(labels, values, color=colours, height=.6, zorder=3)
    span = max(abs(v) for v in values) or 1
    for i, (row, value) in enumerate(zip(rows, values)):
        ax.text(value + span * .015, i, f"{value:.0f}{suffix}" if suffix else f"{value:+.2f}",
                va="center", fontsize=10, fontweight="bold", color=INK)
    ax.set_xlim(min(0, min(values) * 1.25), span * 1.2)
    ax.set_title(title, fontsize=15, fontweight="bold", color=NAVY, loc="left", pad=12)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(LINE)
    ax.tick_params(colors=SLATE, labelsize=10.5, length=0)
    ax.grid(axis="x", linestyle=":", alpha=.35, zorder=0)
    fig.tight_layout()
    return _save(fig, out_path)


def plot_campus_split(rows: list[dict], out_path: Path,
                      title: str = "Each step, campus by campus") -> Path:
    """Registered, baseline, Deeksharambh and post, per campus."""
    rows = [r for r in rows if r.get("registered")]
    if not rows:
        return _empty(out_path, "No campus data in this scope yet")

    steps = [("registered", "Registered", NAVY), ("pre", "Baseline", PRE_COLOUR),
             ("orientation", "Deeksharambh", GOLD), ("post", "Post survey", TEAL)]
    x = range(len(rows))
    width = .2

    fig, ax = plt.subplots(figsize=(11.4, 4.6))
    for i, (key, label, colour) in enumerate(steps):
        offset = (i - 1.5) * width
        values = [r[key] for r in rows]
        ax.bar([p + offset for p in x], values, width=width, color=colour, label=label, zorder=3)
        for p, value in zip(x, values):
            ax.text(p + offset, value, str(value), ha="center", va="bottom",
                    fontsize=8.8, fontweight="bold", color=INK)

    ax.set_xticks(list(x))
    ax.set_xticklabels([clean(r["campus"], 22) for r in rows], fontsize=11, fontweight="bold")
    ax.set_ylabel("Students", fontsize=10, color=SLATE)
    ax.legend(frameon=False, fontsize=10, ncol=4, loc="upper center",
              bbox_to_anchor=(.5, 1.14))
    ax.set_title(title, fontsize=15, fontweight="bold", color=NAVY, loc="left", pad=30)
    _style(ax)
    fig.tight_layout()
    return _save(fig, out_path)
