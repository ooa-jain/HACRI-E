"""
Excel export helper using openpyxl.
Generates a styled Excel sheet containing cohort data and survey scores.
"""
from __future__ import annotations
import io
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from app.hacri_e2_compat import SCHEMA
from app.scoring import score_for_user

def generate_cohort_excel(
    dept_name: str,
    users_list: list[dict],
    pre_docs: list[dict],
    post_docs: list[dict],
    dept_rows: list[dict] | None = None,
) -> bytes:
    """Cohort workbook for one department — or for all of them.

    `dept_rows` adds a "Department Breakdown" sheet: one line per department
    with its counts, reminder-mail figures and average scores. Pass it for the
    all-departments export, where a flat student list alone says nothing about
    how each department is doing.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Department Analysis"
    
    # Enable grid lines explicitly
    ws.views.sheetView[0].showGridLines = True

    # Color Palette (Navy / Gold Theme)
    navy_fill = PatternFill(start_color="1B2A4A", end_color="1B2A4A", fill_type="solid")
    gold_fill = PatternFill(start_color="C9A84C", end_color="C9A84C", fill_type="solid")
    gray_fill = PatternFill(start_color="F5F6FA", end_color="F5F6FA", fill_type="solid")
    white_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    title_font = Font(name="Segoe UI", size=16, bold=True, color="1B2A4A")
    bold_font = Font(name="Segoe UI", size=11, bold=True)
    normal_font = Font(name="Segoe UI", size=11)
    
    thin_border = Border(
        left=Side(style='thin', color='DDDDDD'),
        right=Side(style='thin', color='DDDDDD'),
        top=Side(style='thin', color='DDDDDD'),
        bottom=Side(style='thin', color='DDDDDD')
    )

    # 1. Title
    ws["A1"] = f"HACRI-E2 Department Cohort Analysis"
    ws["A1"].font = title_font
    ws["A2"] = f"Department: {dept_name or 'All Departments'}"
    ws["A2"].font = bold_font
    
    # 2. Key Stats Summary Table
    total = len(users_list)
    pre_done = sum(1 for u in users_list if u.get("status") in ("pre_done", "post_done"))
    post_done = sum(1 for u in users_list if u.get("status") == "post_done")
    pending = pre_done - post_done

    stats_headers = ["Metric", "Count"]
    stats_data = [
        ("Total Registered Students", total),
        ("Baseline (Pre) Survey Completed", pre_done),
        ("Post-Workshop Survey Completed", post_done),
        ("Pending Post-Workshop Survey", pending)
    ]
    
    # Write summary table
    for col_idx, text in enumerate(stats_headers, start=1):
        cell = ws.cell(row=4, column=col_idx, value=text)
        cell.font = white_font
        cell.fill = navy_fill
        cell.alignment = Alignment(horizontal="center")
        cell.border = thin_border
        
    for row_idx, (metric, val) in enumerate(stats_data, start=5):
        cell_m = ws.cell(row=row_idx, column=1, value=metric)
        cell_m.font = normal_font
        cell_m.border = thin_border
        cell_m.fill = gray_fill
        
        cell_v = ws.cell(row=row_idx, column=2, value=val)
        cell_v.font = bold_font
        cell_v.border = thin_border
        cell_v.alignment = Alignment(horizontal="center")
        
    # 3. Main Data Table
    start_row = 10
    
    # Build column headers
    base_headers = [
        "Name", "Email", "Department", "Level", "Education Type",
        "PRE Literacy", "PRE Readiness", "PRE Quadrant", "PRE Band",
        "POST Literacy", "POST Readiness", "POST Quadrant", "POST Band",
        "Δ Literacy", "Δ Readiness", "Movement"
    ]
    
    item_headers = []
    for key in SCHEMA:
        item_headers += [f"PRE {key}", f"POST {key}", f"Δ {key}"]
        
    headers = base_headers + item_headers
    
    for col_idx, h_text in enumerate(headers, start=1):
        cell = ws.cell(row=start_row, column=col_idx, value=h_text)
        cell.font = white_font
        # Use gold fill for post survey columns to distinguish
        if "POST" in h_text or "Δ" in h_text or "Movement" in h_text:
            cell.fill = gold_fill
        else:
            cell.fill = navy_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border
        
    ws.row_dimensions[start_row].height = 28
    
    pre_map = {doc["email"]: doc.get("fields", {}) for doc in pre_docs}
    post_map = {doc["email"]: doc.get("fields", {}) for doc in post_docs}
    
    # Fill Data
    current_row = start_row + 1
    for u in users_list:
        email = u["email"]
        name = u.get("name", "")
        level = u.get("ug_or_pg", "ug").upper()
        edu = u.get("education_type", "")
        
        pre = pre_map.get(email, {})
        post = post_map.get(email, {})
        
        pre_s = score_for_user(pre)
        post_s = score_for_user(post)
        
        d_lit = (
            round(post_s["lit"] - pre_s["lit"], 3)
            if (pre_s["lit"] is not None and post_s["lit"] is not None)
            else ""
        )
        d_read = (
            round(post_s["read"] - pre_s["read"], 3)
            if (pre_s["read"] is not None and post_s["read"] is not None)
            else ""
        )
        
        if isinstance(d_lit, float) and isinstance(d_read, float):
            if d_lit > 0 and d_read > 0:
                movement = "Champion gain"
            elif d_lit < 0 and d_read < 0:
                movement = "Decline"
            else:
                movement = "Mixed change"
        else:
            movement = "Insufficient data"
            
        row_vals = [
            name, email, u.get("program", "") or "—", level, edu,
            pre_s["lit"], pre_s["read"], pre_s["quadrant"], pre_s["band"],
            post_s["lit"], post_s["read"], post_s["quadrant"], post_s["band"],
            d_lit, d_read, movement
        ]
        
        # Add per-item values
        for key in SCHEMA:
            pv = pre.get(key)
            ov = post.get(key)
            try:
                pv_n = int(pv) if pv not in (None, "") else ""
                ov_n = int(ov) if ov not in (None, "") else ""
                d = (ov_n - pv_n) if isinstance(pv_n, int) and isinstance(ov_n, int) else ""
            except (TypeError, ValueError):
                pv_n, ov_n, d = "", "", ""
            row_vals += [pv_n, ov_n, d]
            
        left = {"Name", "Email", "Department", "Education Type"}
        centre = {"Level", "PRE Quadrant", "PRE Band", "POST Quadrant",
                  "POST Band", "Movement"}
        for col_idx, val in enumerate(row_vals, start=1):
            cell = ws.cell(row=current_row, column=col_idx, value=val)
            cell.font = normal_font
            cell.border = thin_border

            header = headers[col_idx - 1] if col_idx <= len(headers) else ""
            if header in left:
                cell.alignment = Alignment(horizontal="left")
            elif header in centre:
                cell.alignment = Alignment(horizontal="center")
            else:
                cell.alignment = Alignment(horizontal="right")

        current_row += 1

    # Auto-adjust column widths
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        
        # Calculate max length based on rows from start_row onwards
        for cell in col[start_row-1:]:
            if cell.value:
                max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[col_letter].width = max(max_len + 3, 10)
        
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 28
    ws.column_dimensions["C"].width = 34

    if dept_rows:
        _write_dept_breakdown(wb, dept_rows, navy_fill, gold_fill, gray_fill,
                              white_font, title_font, bold_font, normal_font,
                              thin_border)

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
