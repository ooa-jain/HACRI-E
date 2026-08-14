"""
Excel export helper using openpyxl.

The shared department workbook is a roster, not a scoresheet: who is
registered and still owes the survey, and who has filled it. Scores live in
the report itself and in the admin's own custom export, so this file stays
readable by the people who chase students.
"""
from __future__ import annotations
import io
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

# The only columns the roster sheets carry.
ROSTER_HEADERS = ["Name", "Email", "Department", "Level", "Education Type"]
_COLUMN_WIDTHS = [26, 32, 38, 10, 22]

NAVY = "1B2A4A"
GOLD = "C9A84C"
MIST = "F5F6FA"


def _styles():
    return {
        "navy": PatternFill(start_color=NAVY, end_color=NAVY, fill_type="solid"),
        "gold": PatternFill(start_color=GOLD, end_color=GOLD, fill_type="solid"),
        "gray": PatternFill(start_color=MIST, end_color=MIST, fill_type="solid"),
        "white_font": Font(name="Segoe UI", size=11, bold=True, color="FFFFFF"),
        "title_font": Font(name="Segoe UI", size=16, bold=True, color="1B2A4A"),
        "bold_font": Font(name="Segoe UI", size=11, bold=True),
        "normal_font": Font(name="Segoe UI", size=11),
        "border": Border(
            left=Side(style="thin", color="DDDDDD"),
            right=Side(style="thin", color="DDDDDD"),
            top=Side(style="thin", color="DDDDDD"),
            bottom=Side(style="thin", color="DDDDDD"),
        ),
    }


def _has_pre(user: dict) -> bool:
    return user.get("status") in ("pre_done", "post_done")


def _has_post(user: dict) -> bool:
    return user.get("status") == "post_done"


def _roster_sheet(wb, title: str, subtitle: str, users: list[dict], st, fill) -> None:
    """One tab: the five columns, nothing else."""
    ws = wb.create_sheet(title[:31])
    ws.views.sheetView[0].showGridLines = True

    ws["A1"] = title
    ws["A1"].font = st["title_font"]
    ws["A2"] = subtitle
    ws["A2"].font = st["bold_font"]

    header_row = 4
    for col_idx, text in enumerate(ROSTER_HEADERS, start=1):
        cell = ws.cell(row=header_row, column=col_idx, value=text)
        cell.font = st["white_font"]
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = st["border"]
    ws.row_dimensions[header_row].height = 24

    for row_idx, user in enumerate(users, start=header_row + 1):
        values = [
            user.get("name", ""),
            user.get("email", ""),
            user.get("program", "") or "—",
            (user.get("ug_or_pg", "ug") or "ug").upper(),
            user.get("education_type", "") or "—",
        ]
        for col_idx, value in enumerate(values, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.font = st["normal_font"]
            cell.border = st["border"]
            cell.alignment = Alignment(horizontal="center" if col_idx == 4 else "left")

    if not users:
        cell = ws.cell(row=header_row + 1, column=1, value="Nobody in this list")
        cell.font = st["normal_font"]

    for col_idx, width in enumerate(_COLUMN_WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)


def generate_cohort_excel(
    dept_name: str,
    users_list: list[dict],
    survey_type: str = "pre",
    dept_rows: list[dict] | None = None,
) -> bytes:
    """Roster workbook for one department — or for all of them.

    `users_list` is every registered student in scope, filled or not: the
    counts here are meant to match the report page, and they cannot if the
    caller has already dropped the students who never answered.

    Three sheets — a summary, who still owes the survey, and who has filled
    it. `dept_rows` adds the per-department breakdown used by the
    all-departments export.
    """
    label = "Post" if survey_type == "post" else "Pre"
    done = _has_post if survey_type == "post" else _has_pre

    filled = [u for u in users_list if done(u)]
    not_filled = [u for u in users_list if not done(u)]

    st = _styles()
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.views.sheetView[0].showGridLines = True

    ws["A1"] = "HACRI-E2 Department Cohort"
    ws["A1"].font = st["title_font"]
    ws["A2"] = f"Department: {dept_name or 'All Departments'}"
    ws["A2"].font = st["bold_font"]

    stats = [
        ("Total Registered Students", len(users_list)),
        ("Baseline (Pre) Survey Completed", sum(1 for u in users_list if _has_pre(u))),
        ("Baseline (Pre) Survey Pending", sum(1 for u in users_list if not _has_pre(u))),
        ("Post-Workshop Survey Completed", sum(1 for u in users_list if _has_post(u))),
        ("Post-Workshop Survey Pending", sum(1 for u in users_list if not _has_post(u))),
        (f"In this workbook — {label} filled", len(filled)),
        (f"In this workbook — {label} not filled", len(not_filled)),
    ]

    for col_idx, text in enumerate(["Metric", "Count"], start=1):
        cell = ws.cell(row=4, column=col_idx, value=text)
        cell.font = st["white_font"]
        cell.fill = st["navy"]
        cell.alignment = Alignment(horizontal="center")
        cell.border = st["border"]

    for row_idx, (metric, value) in enumerate(stats, start=5):
        name_cell = ws.cell(row=row_idx, column=1, value=metric)
        name_cell.font = st["normal_font"]
        name_cell.fill = st["gray"]
        name_cell.border = st["border"]

        value_cell = ws.cell(row=row_idx, column=2, value=value)
        value_cell.font = st["bold_font"]
        value_cell.border = st["border"]
        value_cell.alignment = Alignment(horizontal="center")

    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 14

    _roster_sheet(
        wb, f"Registered - {label} Not Filled",
        f"{len(not_filled)} student(s) registered who have not filled the "
        f"{label.lower()} survey — {dept_name or 'All Departments'}",
        not_filled, st, st["gold"],
    )
    _roster_sheet(
        wb, f"Filled - {label} Survey",
        f"{len(filled)} student(s) who have filled the {label.lower()} survey — "
        f"{dept_name or 'All Departments'}",
        filled, st, st["navy"],
    )

    if dept_rows:
        _write_dept_breakdown(wb, dept_rows, st["navy"], st["gold"], st["gray"],
                              st["white_font"], st["title_font"], st["bold_font"],
                              st["normal_font"], st["border"])

    out_buf = io.BytesIO()
    wb.save(out_buf)
    return out_buf.getvalue()


def _write_dept_breakdown(wb, dept_rows, navy_fill, gold_fill, gray_fill,
                          white_font, title_font, bold_font, normal_font,
                          thin_border) -> None:
    """Second sheet: one line per department, plus a totals line.

    Mirrors the shared department directory, so the numbers on the page and
    the numbers in the workbook always agree.
    """
    ws = wb.create_sheet("Department Breakdown", 0)
    ws.views.sheetView[0].showGridLines = True

    ws["A1"] = "HACRI-E2 Department Breakdown"
    ws["A1"].font = title_font
    ws["A2"] = "Every department, side by side"
    ws["A2"].font = bold_font

    headers = [
        "Department", "Registered", "Baseline Filled", "Post Filled",
        "Baseline Pending", "Post Pending", "Reminders Sent", "Clicked Mail",
        "Filled After Mail", "Avg PRE Literacy", "Avg PRE Readiness",
        "Avg POST Literacy", "Avg POST Readiness",
    ]
    header_row = 4
    for col_idx, text in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=col_idx, value=text)
        cell.font = white_font
        cell.fill = gold_fill if text.startswith(("Post", "Avg POST")) else navy_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border
    ws.row_dimensions[header_row].height = 30

    totals = {k: 0 for k in ("registered", "pre_done", "post_done", "pre_pending",
                             "post_pending", "reminders_sent", "clicked", "completed_after")}
    row_idx = header_row
    for row_idx, d in enumerate(dept_rows, start=header_row + 1):
        for key in totals:
            totals[key] += d.get(key, 0) or 0
        values = [
            d.get("dept", ""),
            d.get("registered", 0), d.get("pre_done", 0), d.get("post_done", 0),
            d.get("pre_pending", 0), d.get("post_pending", 0),
            d.get("reminders_sent", 0), d.get("clicked", 0), d.get("completed_after", 0),
            d.get("avg_lit_pre"), d.get("avg_read_pre"),
            d.get("avg_lit_post"), d.get("avg_read_post"),
        ]
        for col_idx, val in enumerate(values, start=1):
            cell = ws.cell(row=row_idx, column=col_idx,
                           value="—" if val is None else val)
            cell.font = normal_font
            cell.border = thin_border
            cell.alignment = Alignment(horizontal="left" if col_idx == 1 else "center")

    total_row = row_idx + 1
    total_values = [
        "ALL DEPARTMENTS",
        totals["registered"], totals["pre_done"], totals["post_done"],
        totals["pre_pending"], totals["post_pending"],
        totals["reminders_sent"], totals["clicked"], totals["completed_after"],
        "", "", "", "",
    ]
    for col_idx, val in enumerate(total_values, start=1):
        cell = ws.cell(row=total_row, column=col_idx, value=val)
        cell.font = bold_font
        cell.fill = gray_fill
        cell.border = thin_border
        cell.alignment = Alignment(horizontal="left" if col_idx == 1 else "center")

    ws.column_dimensions["A"].width = 44
    for col_idx in range(2, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 15
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
