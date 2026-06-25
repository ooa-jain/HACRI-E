"""
HACRI-E2 compatibility shim.

The single point in this codebase that imports from the existing CLI tool
`hacri_e2_plotter.py`. Everything else in `app/` should import from here so
the SCHEMA and scoring helpers stay in one place and never drift.

The CLI's `main()` is guarded by `if __name__ == "__main__":`, so importing
the module does NOT execute argparse or the plotting pipeline.
"""

from __future__ import annotations

from hacri_e2_plotter import (  # noqa: F401  (re-exported intentionally)
    SCHEMA,
    REVERSED,
    LIT_ITEMS,
    READ_ITEMS,
    score_likert,
    quadrant,
    band,
    H1_OPTIONS,
    H2_LABELS,
    H3_OPTIONS,
    NAVY,
    GOLD,
    TEAL,
    LGRAY,
    DGRAY,
    QUAD_COLS,
    QUAD_TEXT,
    QUAD_LABELS,
)

__all__ = [
    "SCHEMA",
    "REVERSED",
    "LIT_ITEMS",
    "READ_ITEMS",
    "score_likert",
    "quadrant",
    "band",
    "H1_OPTIONS",
    "H2_LABELS",
    "H3_OPTIONS",
    "NAVY",
    "GOLD",
    "TEAL",
    "LGRAY",
    "DGRAY",
    "QUAD_COLS",
    "QUAD_TEXT",
    "QUAD_LABELS",
]