"""
Suja's Kitchen — Daily Dispatch Automation
Streamlit web app: no install, no command line — Shapan just opens the
link, uploads the day's PDFs, handles any flagged items/adjustments, and
downloads the finished branch dispatch sheets + chef requisition images.
"""
import os
import sys
import re
import io
import zipfile
import tempfile
from datetime import datetime

import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from pdf_parser import parse_order_pdf, BRANCH_KEYWORDS  # noqa: E402
import item_master as im  # noqa: E402
import dispatch_sheet as ds  # noqa: E402
import chef_report as cr  # noqa: E402
import adjustments as adj  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
MASTER_PATH = os.path.join(DATA_DIR, "item_master.csv")

st.set_page_config(page_title="Suja's Kitchen — Dispatch Automation", layout="wide")

# ---------------------------------------------------------------- session --
def init_state():
    defaults = {
        "orders": None,
        "master": None,
        "unmapped_codes": [],
        "adjustments": [],
        "adjustments_log": [],
        "generated": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_state()
if st.session_state.master is None:
    st.session_state.master = im.load(MASTER_PATH)

st.title("🍱 Suja's Kitchen — Daily Dispatch Automation")
st.caption("Upload today's order PDFs → tag anything new → apply WhatsApp adjustments → download everything.")

# --------------------------------------------------------- 1. upload PDFs --
st.header("1. Upload today's order PDFs")
uploaded = st.file_uploader("Drop the branch order PDFs here (any number)", type="pdf", accept_multiple_files=True)

col1, col2 = st.columns([1, 3])
with col1:
    parse_clicked = st.button("Parse orders", type="primary", disabled=not uploaded)

if parse_clicked and uploaded:
    tmp_dir = tempfile.mkdtemp()
    orders, failures = [], []
    for f in uploaded:
        p = os.path.join(tmp_dir, f.name)
        with open(p, "wb") as out:
            out.write(f.getbuffer())
        # Each file is parsed independently — one bad/unexpected PDF in the
        # batch shouldn't block the other good ones from going through.
        try:
            orders.append(parse_order_pdf(p))
        except Exception as e:
            failures.append((f.name, str(e)))

    st.session_state.orders = orders or None
    if orders:
        st.session_state.unmapped_codes = im.sync_with_orders(st.session_state.master, orders)
        st.session_state.generated = None
        st.success(f"Parsed {len(orders)} of {len(uploaded)} uploaded file(s) successfully.")
    for name, err in failures:
        st.error(f"Could not read **{name}** — {err}")

if st.session_state.orders:
    st.subheader("Parsed orders")
    rows = [{"Branch": o["branch"], "Order No.": o["order_no"], "Delivery Date": o["delivery_date"],
             "Items": len(o["items"])} for o in st.session_state.orders]
    st.dataframe(rows, width='stretch', hide_index=True)

    seen_branches = {}
    for o in st.session_state.orders:
        if o["branch"].startswith("UNRECOGNIZED BRANCH"):
            st.warning(f"⚠️ Could not recognize the branch for one PDF (Ship To: '{o['branch_raw']}'). "
                       f"Its items will still be included, but check the branch name before sending out.")
        seen_branches[o["branch"]] = seen_branches.get(o["branch"], 0) + 1
    dupes = [b for b, n in seen_branches.items() if n > 1]
    if dupes:
        st.warning(f"⚠️ More than one uploaded PDF matched the same branch: {', '.join(dupes)}. "
                    f"If that's a duplicate upload rather than two genuine orders, remove one and re-parse — "
                    f"otherwise both will be added into that branch's dispatch sheet.")

# ---------------------------------------------------- 2. tag new items --
if st.session_state.orders and st.session_state.unmapped_codes:
    st.header("2. Tag new items")
    st.info(f"{len(st.session_state.unmapped_codes)} item(s) haven't been seen before — "
            f"tag each one once and it's remembered forever after.")
    sheet_options = im.DISPATCH_SHEETS
    with st.form("tag_form"):
        tag_choices = {}
        for code in st.session_state.unmapped_codes:
            row = st.session_state.master[code]
            st.markdown(f"**{row['item_name']}**  ·  _{row['erp_category']}_  ·  code `{code}`")
            c1, c2, c3 = st.columns(3)
            sheet = c1.selectbox("Dispatch sheet", sheet_options, key=f"sheet_{code}")
            group_opts = im.SHEET_GROUP_ORDER[sheet] + ["+ New group..."]
            group = c2.selectbox("Group / bucket", group_opts, key=f"group_{code}")
            if group == "+ New group...":
                group = c2.text_input("New group name", key=f"newgroup_{code}")
            storage_opts = im.STORAGE_CATEGORIES + ["+ New storage..."]
            storage = c3.selectbox("Storage category", storage_opts, key=f"storage_{code}")
            if storage == "+ New storage...":
                storage = c3.text_input("New storage category", key=f"newstorage_{code}")
            tag_choices[code] = (sheet, group, storage)
            st.divider()
        submitted = st.form_submit_button("Save all tags", type="primary")
    if submitted:
        for code, (sheet, group, storage) in tag_choices.items():
            im.apply_tag(st.session_state.master, code, sheet, group, storage)
        im.save(MASTER_PATH, st.session_state.master)
        st.session_state.unmapped_codes = im.sync_with_orders(st.session_state.master, st.session_state.orders)
        st.success("Tags saved to the Item Master.")
        st.rerun()

# ---------------------------------------------------- 3. adjustments --
if st.session_state.orders and not st.session_state.unmapped_codes:
    st.header("3. WhatsApp add/remove adjustments (optional)")
    branches = [o["branch"] for o in st.session_state.orders]
    all_item_names = sorted({r["item_name"] for r in st.session_state.master.values()})

    with st.form("adj_form", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns([1.2, 2, 1, 1])
        branch_choice = c1.selectbox("Branch", branches)
        item_choice = c2.selectbox("Item", ["+ Type a new item name..."] + all_item_names)
        if item_choice == "+ Type a new item name...":
            item_choice = c2.text_input("New item name")
        action_choice = c3.selectbox("Action", ["Add", "Remove", "Set Qty"])
        qty_choice = c4.number_input("Qty", min_value=0.0, step=1.0)
        add_clicked = st.form_submit_button("Add adjustment")

    if add_clicked and item_choice:
        name_to_code = {r["item_name"]: r["item_code"] for r in st.session_state.master.values()}
        code = name_to_code.get(item_choice)
        if not code:
            code = "MANUAL-" + re.sub(r"[^A-Za-z0-9]+", "-", item_choice.strip().lower())
            if code not in st.session_state.master:
                st.session_state.master[code] = {
                    "item_code": code, "item_name": item_choice, "erp_category": "",
                    "uom": "1Piece", "dispatch_sheet": "", "group": "", "storage_category": "",
                    "chef_bucket": "", "status": "NEEDS TAGGING",
                }
        st.session_state.adjustments.append({
            "branch": branch_choice, "item_code": code, "item_name": item_choice,
            "action": action_choice, "qty": qty_choice,
        })

    if st.session_state.adjustments:
        st.write("Pending adjustments:")
        st.dataframe(
            [{"Branch": a["branch"], "Item": a["item_name"], "Action": a["action"], "Qty": a["qty"]}
             for a in st.session_state.adjustments],
            width='stretch', hide_index=True,
        )
        if st.button("Clear all adjustments"):
            st.session_state.adjustments = []
            st.rerun()

# ---------------------------------------------------- 4. generate --
if st.session_state.orders and not st.session_state.unmapped_codes:
    st.header("4. Generate today's files")
    if st.button("🚀 Generate branch sheets + chef reports", type="primary"):
        orders_copy = [dict(o, items=[dict(it) for it in o["items"]]) for o in st.session_state.orders]

        if st.session_state.adjustments:
            new_codes = im.sync_with_orders(st.session_state.master, orders_copy)
            unresolved = [c for c in new_codes if st.session_state.master[c]["status"] == "NEEDS TAGGING"
                          and st.session_state.master[c].get("dispatch_sheet") == ""]
            log = adj.apply_adjustments(orders_copy, st.session_state.adjustments, st.session_state.master)
            st.session_state.adjustments_log = log

        delivery_date = orders_copy[0]["delivery_date"] if orders_copy else datetime.now().strftime("%d/%b/%y")

        buf = io.BytesIO()
        branch_items_for_chef = {}
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for order in orders_copy:
                joined = []
                for it in order["items"]:
                    m = st.session_state.master.get(it["item_code"], {})
                    joined.append({**it, "dispatch_sheet": m.get("dispatch_sheet", ""),
                                   "group": m.get("group", ""), "storage_category": m.get("storage_category", ""),
                                   "chef_bucket": m.get("chef_bucket", "")})
                branch_items_for_chef[order["branch"]] = joined

                wb = ds.build_branch_workbook(order["branch"], order["delivery_date"], joined)
                fname = ds.safe_filename(order["branch"], order["delivery_date"])
                tmp_xlsx = io.BytesIO()
                wb.save(tmp_xlsx)
                zf.writestr(fname, tmp_xlsx.getvalue())

            for bucket in ("Meals", "Snacks"):
                item_names, brs, grid, totals = cr.build_matrix(branch_items_for_chef, bucket)
                if not item_names:
                    continue
                title = f"Food Store {bucket} Requisition Form"
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                    cr.render_matrix_image(item_names, brs, grid, totals, title, delivery_date, tf.name)
                    zf.write(tf.name, f"{bucket}_Requisition_{delivery_date.replace('/', '_')}.png")
                wb2 = cr.build_matrix_workbook(item_names, brs, grid, totals, title, delivery_date)
                tmp_xlsx2 = io.BytesIO()
                wb2.save(tmp_xlsx2)
                zf.writestr(f"{bucket}_Requisition_{delivery_date.replace('/', '_')}.xlsx", tmp_xlsx2.getvalue())

        st.session_state.generated = buf.getvalue()
        st.success("All files generated.")
        if st.session_state.adjustments_log:
            with st.expander("Adjustments applied"):
                for line in st.session_state.adjustments_log:
                    st.write("• " + line)

    if st.session_state.generated:
        st.download_button("⬇️ Download all files (ZIP)", data=st.session_state.generated,
                            file_name="Sujas_Kitchen_Dispatch.zip", mime="application/zip", type="primary")

# ---------------------------------------------------- sidebar: item master backup --
with st.sidebar:
    st.subheader("Item Master")
    st.caption(f"{len(st.session_state.master)} known items")
    if os.path.exists(MASTER_PATH):
        with open(MASTER_PATH, "rb") as f:
            st.download_button("⬇️ Download backup (CSV)", f.read(), file_name="item_master_backup.csv")
    restore = st.file_uploader("Restore from backup", type="csv", key="restore_master")
    if restore is not None and st.button("Restore this backup"):
        content = restore.getvalue().decode("utf-8")
        with open(MASTER_PATH, "w") as f:
            f.write(content)
        st.session_state.master = im.load(MASTER_PATH)
        st.success("Item Master restored.")
        st.rerun()
    st.divider()
    if st.button("Start a new day (reset)"):
        for k in ("orders", "unmapped_codes", "adjustments", "adjustments_log", "generated"):
            st.session_state[k] = [] if isinstance(st.session_state[k], list) else None
        st.rerun()
