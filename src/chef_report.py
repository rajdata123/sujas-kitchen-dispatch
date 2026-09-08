"""
Builds the two Main-Branch-Chef requisition reports (Meals, Snacks): an
item x branch quantity matrix with a Total column, rendered both as an
.xlsx (for records/editing) and a .png image (for sending directly, same
as the images Shapan currently builds by hand).
"""
import os
import re
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from PIL import Image, ImageDraw, ImageFont

from pdf_parser import BRANCH_KEYWORDS

CANONICAL_BRANCHES = [name for name, _ in BRANCH_KEYWORDS]  # fixed display order

YELLOW = "FFFF00"
GREEN = "00B050"
LIGHT_BLUE = "DCE6F1"
FONT_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts")


def chef_display_name(item_name: str) -> str:
    """Strip the trailing weight/UOM/'POR ...' suffix ERP item names carry,
    e.g. 'Beef Curry (400g) POR 1Piece' -> 'Beef Curry',
    'Frozen Unnakkaya 500g' -> 'Frozen Unnakkaya' — matching the shortened
    names used on the existing chef requisition forms."""
    name = re.split(r"\s*\(|\s+\d", item_name, maxsplit=1)[0]
    return name.strip()


def build_matrix(branch_items: dict, bucket: str):
    """branch_items: {branch: [ {item_name, qty, chef_bucket}, ... ]}
    Returns (item_names_sorted, per_item_branch_qty, totals) for the given
    chef_bucket ('Meals' or 'Snacks')."""
    data = {}  # display_name -> {branch: qty}
    for branch, items in branch_items.items():
        for it in items:
            if it.get("chef_bucket") != bucket:
                continue
            disp = chef_display_name(it["item_name"])
            data.setdefault(disp, {})
            data[disp][branch] = data[disp].get(branch, 0) + it["qty"]

    item_names = sorted(data.keys())
    present = {b for name in item_names for b in data[name]}
    # Known branches print first in their usual order; a branch that isn't
    # in the canonical list yet (a new store, or an unrecognized "Ship To"
    # that got flagged) is appended at the end instead of being dropped
    # from the report entirely.
    known = [b for b in CANONICAL_BRANCHES if b in present]
    extra = sorted(b for b in present if b not in CANONICAL_BRANCHES)
    branches = known + extra or CANONICAL_BRANCHES
    grid = {name: [data[name].get(b, 0) for b in branches] for name in item_names}
    totals = {name: sum(grid[name]) for name in item_names}
    return item_names, branches, grid, totals


def build_matrix_workbook(item_names, branches, grid, totals, title: str, delivery_date: str) -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]

    ncols = 3 + len(branches) + 1  # Sl No, Item, Unit, branches..., Total
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols - 1)
    ws.cell(row=1, column=1, value=title).font = Font(name="Arial", size=16, bold=True)
    ws.cell(row=1, column=1).alignment = Alignment(horizontal="center", vertical="center")
    ws.cell(row=1, column=1).fill = PatternFill("solid", fgColor=YELLOW)
    ws.cell(row=1, column=ncols, value=f"Date: {delivery_date}").font = Font(name="Arial", size=10, bold=True)

    green_fill = PatternFill("solid", fgColor=GREEN)
    ws.merge_cells(start_row=2, start_column=4, end_row=2, end_column=3 + len(branches))
    ws.cell(row=2, column=4, value="Branch").font = Font(bold=True, color="FFFFFF")
    ws.cell(row=2, column=4).fill = green_fill
    ws.cell(row=2, column=4).alignment = Alignment(horizontal="center")

    headers = ["Sl No", "Item Description", "Unit"] + branches + ["Total"]
    for c, h in enumerate(headers, start=1):
        cell = ws.cell(row=3, column=c, value=h)
        cell.font = Font(bold=True)
        cell.fill = green_fill if c > 3 else PatternFill("solid", fgColor="D9D9D9")
        cell.alignment = Alignment(horizontal="center", wrap_text=True)

    thin = Side(style="thin")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    blue_fill = PatternFill("solid", fgColor=LIGHT_BLUE)
    for r, name in enumerate(item_names, start=4):
        ws.cell(row=r, column=1, value=r - 3)
        ws.cell(row=r, column=2, value=name)
        ws.cell(row=r, column=3, value="Nos")
        first_branch_col = 4
        last_branch_col = 3 + len(branches)
        for c, branch in enumerate(branches, start=first_branch_col):
            ws.cell(row=r, column=c, value=grid[name][c - first_branch_col])
        total_col = last_branch_col + 1
        col_letter_start = get_column_letter(first_branch_col)
        col_letter_end = get_column_letter(last_branch_col)
        ws.cell(row=r, column=total_col,
                value=f"=SUM({col_letter_start}{r}:{col_letter_end}{r})")
        for c in range(1, total_col + 1):
            cell = ws.cell(row=r, column=c)
            cell.border = border
            cell.alignment = Alignment(horizontal="center")
            if c == total_col:
                cell.fill = blue_fill
                cell.font = Font(bold=True)

    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 30
    ws.column_dimensions["C"].width = 8
    for c in range(4, ncols + 1):
        ws.column_dimensions[get_column_letter(c)].width = 10
    return wb


def render_matrix_image(item_names, branches, grid, totals, title: str, delivery_date: str, out_path: str):
    """Renders the same matrix as a PNG, styled like the existing chef
    requisition-form screenshots (yellow title bar, green branch header,
    light-blue Total column)."""
    col_w = 90
    first_col_w = 40
    name_col_w = 260
    unit_col_w = 60
    row_h = 32
    header_h = 36
    ncols_data = len(branches) + 1  # + Total
    width = first_col_w + name_col_w + unit_col_w + col_w * ncols_data + 2
    height = header_h * 2 + row_h * (len(item_names) + 1) + 2  # +1 for column-name row

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    font_bold = ImageFont.truetype(os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf"), 14)
    font_bold_title = ImageFont.truetype(os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf"), 18)
    font_reg = ImageFont.truetype(os.path.join(FONT_DIR, "DejaVuSans.ttf"), 13)

    def cell(x, y, w, h, text, fill=None, font=None, text_color="black"):
        if fill:
            draw.rectangle([x, y, x + w, y + h], fill=fill, outline="black")
        else:
            draw.rectangle([x, y, x + w, y + h], outline="black")
        if text is not None:
            f = font or font_reg
            bbox = draw.textbbox((0, 0), str(text), font=f)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.text((x + (w - tw) / 2, y + (h - th) / 2 - bbox[1]), str(text), fill=text_color, font=f)

    y = 0
    total_w = first_col_w + name_col_w + unit_col_w + col_w * ncols_data
    cell(0, y, total_w, header_h, title, fill="#FFFF00", font=font_bold_title)
    y += header_h

    cell(0, y, first_col_w + name_col_w + unit_col_w, header_h, f"Date: {delivery_date}", font=font_bold)
    x = first_col_w + name_col_w + unit_col_w
    cell(x, y, col_w * ncols_data, header_h, "Branch", fill="#00B050", font=font_bold, text_color="white")
    y += header_h

    x = 0
    cell(x, y, first_col_w, row_h, "Sl No", fill="#D9D9D9", font=font_bold); x += first_col_w
    cell(x, y, name_col_w, row_h, "Item Description", fill="#D9D9D9", font=font_bold); x += name_col_w
    cell(x, y, unit_col_w, row_h, "Unit", fill="#D9D9D9", font=font_bold); x += unit_col_w
    for b in branches:
        cell(x, y, col_w, row_h, b, fill="#00B050", font=font_bold, text_color="white")
        x += col_w
    cell(x, y, col_w, row_h, "Total", fill="#DCE6F1", font=font_bold)
    y += row_h

    for i, name in enumerate(item_names, start=1):
        x = 0
        cell(x, y, first_col_w, row_h, i); x += first_col_w
        cell(x, y, name_col_w, row_h, name); x += name_col_w
        cell(x, y, unit_col_w, row_h, "Nos"); x += unit_col_w
        for v in grid[name]:
            cell(x, y, col_w, row_h, int(v) if v == int(v) else v)
            x += col_w
        cell(x, y, col_w, row_h, int(totals[name]) if totals[name] == int(totals[name]) else totals[name],
             fill="#DCE6F1", font=font_bold)
        y += row_h

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path)
    return out_path
