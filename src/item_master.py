"""
Item Master: the single lookup table that decides, for every item, which
dispatch sheet/bucket/storage zone it belongs to, and which chef report
(Meals/Snacks/neither) it feeds. This is the piece that replaces Shapan's
manual daily re-sorting.

Stored as a simple CSV so it's human-readable/editable outside the app too
(e.g. opened in Excel for a bulk review) without needing to touch code.
"""
import csv
import os

FIELDS = [
    "item_code", "item_name", "erp_category", "uom",
    "dispatch_sheet", "group", "storage_category", "chef_bucket", "status",
]

# Fixed display order for buckets within each dispatch sheet — matches the
# order observed in the existing branch workbooks. A bucket not in this list
# (e.g. a brand-new one Shapan creates while tagging) is appended at the end.
SHEET_GROUP_ORDER = {
    "Catergery-1": ["PACKING CHILLER", "PORTION CURRY", "SNACK", "Pudding/Cake", "Pickle"],
    "Catergery-2": ["PACKING AREA", "DRY STORE", "VEGETABLE", "Maida/ cutlets", "Fish/meat", "Diary chiller"],
}

DISPATCH_SHEETS = ["Catergery-1", "Catergery-2"]
STORAGE_CATEGORIES = ["Cold Store", "Dry Store", "Veg Store", "Cold Store (Bakery Room)", "Dispo Store"]
CHEF_BUCKETS = ["Meals", "Snacks", ""]


def load(path: str) -> dict:
    """Load the Item Master CSV into {item_code: {..fields..}}."""
    lookup = {}
    if not os.path.exists(path):
        return lookup
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            lookup[row["item_code"]] = row
    return lookup


def save(path: str, lookup: dict):
    """Write {item_code: {..fields..}} back to CSV, sorted for readability
    (mapped items grouped by sheet/group first, unmapped/needs-tagging last)."""
    rows = list(lookup.values())

    def group_rank(r):
        sheet = r.get("dispatch_sheet", "")
        group = r.get("group", "")
        order = SHEET_GROUP_ORDER.get(sheet, [])
        return order.index(group) if group in order else len(order)

    rows.sort(key=lambda r: (
        r.get("status") != "Mapped",
        DISPATCH_SHEETS.index(r["dispatch_sheet"]) if r.get("dispatch_sheet") in DISPATCH_SHEETS else 99,
        group_rank(r),
        r.get("item_name", ""),
    ))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def derive_chef_bucket(dispatch_sheet: str, group: str) -> str:
    if dispatch_sheet == "Catergery-1":
        if group == "SNACK":
            return "Snacks"
        if group in ("PACKING CHILLER", "PORTION CURRY", "Pudding/Cake", "Pickle"):
            return "Meals"
    return ""


def sync_with_orders(lookup: dict, parsed_orders: list) -> list:
    """Given freshly parsed order dicts (from pdf_parser), make sure every
    item_code seen has an entry in the lookup (creating a 'NEEDS TAGGING'
    placeholder row for anything new), and return the list of item_codes
    that still need tagging (empty list = ready to generate everything)."""
    for order in parsed_orders:
        for item in order["items"]:
            code = item["item_code"]
            if code not in lookup:
                lookup[code] = {
                    "item_code": code,
                    "item_name": item["item_name"],
                    "erp_category": item["erp_category"],
                    "uom": item["uom"],
                    "dispatch_sheet": "",
                    "group": "",
                    "storage_category": "",
                    "chef_bucket": "",
                    "status": "NEEDS TAGGING",
                }
    return [c for c, r in lookup.items() if r.get("status") == "NEEDS TAGGING"]


def apply_tag(lookup: dict, item_code: str, dispatch_sheet: str, group: str, storage_category: str):
    """Called when Shapan/Raj tags a previously-unmapped item via the UI.
    Once saved, this item is never flagged again."""
    row = lookup.setdefault(item_code, {"item_code": item_code})
    row["dispatch_sheet"] = dispatch_sheet
    row["group"] = group
    row["storage_category"] = storage_category
    row["chef_bucket"] = derive_chef_bucket(dispatch_sheet, group)
    row["status"] = "Mapped"
