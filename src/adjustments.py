"""
Applies manual add/remove/set-quantity adjustments (the WhatsApp-sourced
requests) on top of the freshly parsed orders, before dispatch sheets and
chef reports get generated.
"""


def apply_adjustments(orders: list, adjustments: list, master: dict):
    """orders: list of parsed order dicts (mutated in place).
    adjustments: list of {branch, item_code, action, qty} where action is
    one of 'Add', 'Remove', 'Set Qty'.
    master: Item Master lookup, used to fill in erp_category/uom when an
    adjustment introduces an item that wasn't in that branch's original
    order at all.
    Returns a list of human-readable log lines describing what was applied,
    so the UI can show a confirmation before generating final files.
    """
    log = []
    by_branch = {o["branch"]: o for o in orders}

    for adj in adjustments:
        branch = adj["branch"]
        code = adj["item_code"]
        action = adj["action"]
        qty = float(adj["qty"])

        order = by_branch.get(branch)
        if order is None:
            log.append(f"SKIPPED — branch '{branch}' not found in today's uploaded orders.")
            continue

        existing = next((it for it in order["items"] if it["item_code"] == code), None)
        item_name = master.get(code, {}).get("item_name", existing["item_name"] if existing else code)

        if action == "Add":
            if existing:
                existing["qty"] += qty
                log.append(f"{branch}: {item_name} increased by {qty} (now {existing['qty']}).")
            else:
                m = master.get(code, {})
                order["items"].append({
                    "item_code": code,
                    "item_name": item_name,
                    "erp_category": m.get("erp_category", ""),
                    "uom": m.get("uom", ""),
                    "qty": qty,
                })
                log.append(f"{branch}: added new line {item_name} x {qty}.")
        elif action == "Remove":
            if existing:
                existing["qty"] -= qty
                if existing["qty"] <= 0:
                    order["items"].remove(existing)
                    log.append(f"{branch}: {item_name} removed entirely (requested removal met/exceeded ordered qty).")
                else:
                    log.append(f"{branch}: {item_name} reduced by {qty} (now {existing['qty']}).")
            else:
                log.append(f"SKIPPED — {branch}: cannot remove '{item_name}', it wasn't in today's order.")
        elif action == "Set Qty":
            if existing:
                existing["qty"] = qty
            else:
                m = master.get(code, {})
                order["items"].append({
                    "item_code": code, "item_name": item_name,
                    "erp_category": m.get("erp_category", ""), "uom": m.get("uom", ""), "qty": qty,
                })
            log.append(f"{branch}: {item_name} quantity set to {qty}.")
        else:
            log.append(f"SKIPPED — unknown action '{action}'.")

    return log
