"""
PDF order parser for Suja's Kitchen daily incoming-order PDFs.

The ERP ("Incoming Order") PDF layout is 100% consistent across branches:
    Item Name <spaces> ERP Category <spaces> UOM <spaces> Quantity
    <item code, on its own line>
repeated for every item, with a page-footer ("Order #...", "Page X of Y",
"This is a system-generated order...") interrupting the item list at every
page break. Header/footer noise must be stripped WITHOUT breaking parsing,
since items continue on the next page without repeating the column header.

Branch names in the "Ship To" field are NOT consistent (e.g. "Al Qouz" vs
"Al Quoz", "Oud Metha - ... - Business Bay"), so branch identification is
done by keyword match against a canonical branch list rather than exact
string match or filename.
"""
import re
import pdfplumber

# Known ERP category strings (longest-first so a shorter category can't
# accidentally swallow part of a longer one during regex matching).
ERP_CATEGORIES = [
    "Beverage - Soft Drinks", "Food - Cookies/Cakes/Pastries", "Food - Cooking Oil",
    "Food - Herbs & Spices", "Food - Milk & Cream", "Food - Poultry",
    "Food - Rice & Flour", "Food - Stockable Portion Recipe", "Food - Vegetables",
    "Food - Fruits", "Food - Frozen Food", "Food - Meat", "Food - Seafood",
    "Food - Sauces & Dressings", "Food - Groceries/Dry Goods", "Packaging - Packaging",
    "Stationery - Stationery", "Cleaning Supplies - Other Cleaning Supplies",
    "Consumables - Consumables",
]

# Canonical branch list -> keyword(s) used to recognize it in "Ship To" text.
# Add new (keyword_list, canonical_name) pairs here if a new branch/spelling shows up.
BRANCH_KEYWORDS = [
    ("Abu Dhabi", ["abu dhabi"]),
    ("Al Quoz", ["qouz", "quoz"]),
    ("Al Qusais", ["qusais"]),
    ("Arjan", ["arjan"]),
    ("DSO", ["dso"]),
    ("Oud Metha", ["oud metha", "business bay"]),
    ("Sharjah", ["sharjah"]),
]

_CAT_PATTERN = "(" + "|".join(re.escape(c) for c in sorted(ERP_CATEGORIES, key=len, reverse=True)) + ")"
_ITEM_LINE_RE = re.compile(r"^(.*?)\s+" + _CAT_PATTERN + r"\s+(.+?)\s+([\d,]+\.\d+)$")
_PAGE_FOOTER_RE = re.compile(r"^Page \d+ of \d+$")


def normalize_branch(ship_to_text: str) -> str:
    """Map a raw 'Ship To' string to a canonical branch name. Returns the
    raw text (flagged) if no keyword matches, so a genuinely new branch
    doesn't silently get dropped."""
    text = ship_to_text.lower()
    for canonical, keywords in BRANCH_KEYWORDS:
        if any(kw in text for kw in keywords):
            return canonical
    return f"UNRECOGNIZED BRANCH: {ship_to_text.strip()}"


def _extract_header_fields(all_text: str) -> dict:
    ship_to_match = re.search(r"Ship To\n(.*?)\n", "\n".join(all_text.split("\n")))
    # Ship To value is the line(s) right after "Ship To" in the 3-column header block.
    lines = all_text.split("\n")
    order_no, delivery_date, ship_to_line = None, None, None
    for i, l in enumerate(lines):
        if l.strip().startswith("INCOMING ORDER"):
            pass
        if re.match(r"^\d{6}-[A-Za-z0-9]+$", l.strip()) and order_no is None:
            order_no = l.strip()
        if l.strip() == "Supplier Details Ship To Created On" and i + 1 < len(lines):
            ship_to_line = lines[i + 1]
        if "Delivery Date" in l:
            # value is on the next line, 2nd column
            pass
    m = re.search(r"Delivery Date\n.*?(\d{2}/[A-Za-z]{3}/\d{2})", all_text)
    if m:
        delivery_date = m.group(1)
    return {
        "order_no": order_no,
        "delivery_date": delivery_date,
        "ship_to_raw": ship_to_line or "",
    }


def parse_order_pdf(file_path: str) -> dict:
    """Parse one Incoming Order PDF into a dict:
    {order_no, delivery_date, branch, branch_raw, items: [ {item_code, item_name,
    erp_category, uom, qty}, ... ] }
    Raises ValueError if zero items were parsed (signals a template change
    or a non-order PDF, rather than silently returning an empty order).
    """
    with pdfplumber.open(file_path) as pdf:
        raw_lines = []
        full_text_parts = []
        for page in pdf.pages:
            t = page.extract_text() or ""
            full_text_parts.append(t)
            raw_lines.extend(t.split("\n"))
    full_text = "\n".join(full_text_parts)
    header = _extract_header_fields(full_text)
    branch = normalize_branch(header["ship_to_raw"]) if header["ship_to_raw"] else "UNKNOWN"

    # Strip header/footer noise while keeping items flowing across page breaks.
    clean = []
    started = False
    for l in raw_lines:
        s = l.strip()
        if s == "Item Name Category UOM Quantity":
            started = True
            continue
        if not started:
            continue
        if s == "Notes/Comments":
            break
        if s.startswith("Order #") or _PAGE_FOOTER_RE.match(s) or "system-generated" in s:
            continue
        clean.append(l)

    items = []
    idx, n = 0, len(clean)
    while idx < n:
        line = clean[idx].strip()
        m = _ITEM_LINE_RE.match(line)
        if m:
            item_name, category, uom, qty = m.groups()
            code_line = clean[idx + 1].strip() if idx + 1 < n else ""
            items.append({
                "item_code": code_line,
                "item_name": item_name.strip(),
                "erp_category": category,
                "uom": uom.strip(),
                "qty": float(qty.replace(",", "")),
            })
            idx += 2
        else:
            idx += 1

    if not items:
        raise ValueError(
            f"No items parsed from {file_path} — the PDF template may have "
            f"changed, or this isn't an Incoming Order PDF. Check manually."
        )

    return {
        "order_no": header["order_no"],
        "delivery_date": header["delivery_date"],
        "branch": branch,
        "branch_raw": header["ship_to_raw"].strip(),
        "items": items,
    }


def parse_order_pdfs(file_paths: list) -> list:
    """Parse multiple PDFs, returning one dict per file (see parse_order_pdf).
    A file that fails to parse raises with its filename in the message so
    the caller can surface exactly which upload is the problem."""
    results = []
    for fp in file_paths:
        try:
            results.append(parse_order_pdf(fp))
        except Exception as e:
            raise ValueError(f"Failed to parse '{fp}': {e}") from e
    return results
