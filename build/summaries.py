"""
Build plain-English summaries under query results (no extra LLM call).
"""
import re
from database import run_query, table_has_column


def _money(val) -> str:
    try:
        n = float(val)
        return f"₹{n:,.2f}" if n >= 1000 else f"₹{n:,.2f}"
    except (TypeError, ValueError):
        return str(val)


def _col_index(columns: list, name: str) -> int | None:
    lower = [c.lower() for c in columns]
    if name.lower() in lower:
        return lower.index(name.lower())
    return None


def _count_by_column(columns: list, rows: list, col: str) -> dict:
    idx = _col_index(columns, col)
    if idx is None:
        return {}
    counts = {}
    for row in rows:
        v = str(row[idx]).lower() if row[idx] is not None else "unknown"
        counts[v] = counts.get(v, 0) + 1
    return counts


def _sum_column(columns: list, rows: list, col: str) -> float:
    idx = _col_index(columns, col)
    if idx is None:
        return 0.0
    total = 0.0
    for row in rows:
        try:
            if row[idx] not in (None, "NULL"):
                total += float(row[idx])
        except (TypeError, ValueError):
            pass
    return total


def _company_where(company_id: int | None, table: str) -> str:
    if not company_id:
        return ""
    if table == "companies":
        return f" AND id = {int(company_id)}"
    if table_has_column(table, "company_id"):
        return f" AND company_id = {int(company_id)}"
    return ""


def _deleted_clause(table: str) -> str:
    return " AND deleted_at IS NULL" if table_has_column(table, "deleted_at") else ""


def fetch_table_stats(company_id: int | None, table: str) -> dict:
    """One fast aggregate query for narrative context."""
    cw = _company_where(company_id, table)
    dc = _deleted_clause(table)
    stats = {}

    try:
        if table == "customers":
            # Get total + breakdown of ALL status values dynamically
            sql_total = f"SELECT COUNT(*) FROM customers WHERE 1=1{dc}{cw}"
            r = run_query(sql_total)
            stats["total"] = r["rows"][0][0] if r["rows"] else 0

            # Get per-status counts for ALL statuses that exist
            sql_status = f"""
                SELECT status, COUNT(*) as cnt
                FROM customers
                WHERE 1=1{dc}{cw}
                GROUP BY status
                ORDER BY cnt DESC
            """
            r2 = run_query(sql_status)
            status_breakdown = {}
            for row in r2["rows"]:
                status_val = str(row[0]).lower() if row[0] else "unknown"
                status_breakdown[status_val] = int(row[1])
            stats["status_breakdown"] = status_breakdown
            # Keep legacy keys for backward compat
            stats["active"] = status_breakdown.get("active", 0)
            stats["inactive"] = status_breakdown.get("inactive", 0)
            stats["suspended"] = status_breakdown.get("suspended", 0)

        elif table == "orders" and table_has_column(table, "payment_status"):
            amt = "order_total" if table_has_column(table, "order_total") else "amount"
            sql = f"""
                SELECT
                    COUNT(*) AS overdue_count,
                    COALESCE(SUM({amt}), 0) AS overdue_total
                FROM orders
                WHERE due_date < NOW()
                  AND payment_status != 'paid'{dc}{cw}
            """
            r = run_query(sql)
            if r["rows"]:
                row = r["rows"][0]
                cols = r["columns"]
                stats = {cols[i]: row[i] for i in range(len(cols))}

            sql2 = f"""
                SELECT COUNT(*) AS total_invoices,
                       COALESCE(SUM({amt}), 0) AS total_value
                FROM orders
                WHERE 1=1{dc}{cw}
            """
            r2 = run_query(sql2)
            if r2["rows"]:
                stats["total_invoices"] = r2["rows"][0][0]
                stats["total_value"] = r2["rows"][0][1]

        elif table == "customer_subscriptions" and table_has_column(table, "status"):
            sql = f"""
                SELECT status, COUNT(*) as cnt
                FROM customer_subscriptions
                WHERE 1=1{dc}{cw}
                GROUP BY status
            """
            r = run_query(sql)
            breakdown = {}
            total = 0
            for row in r["rows"]:
                sv = str(row[0]).lower() if row[0] else "unknown"
                breakdown[sv] = int(row[1])
                total += int(row[1])
            stats["status_breakdown"] = breakdown
            stats["total"] = total
            stats["active"] = breakdown.get("active", 0)
            stats["inactive"] = sum(v for k, v in breakdown.items() if k != "active")

        elif table == "payments":
            amt = "amount" if table_has_column(table, "amount") else "id"
            sql = f"""
                SELECT COUNT(*) AS total,
                       COALESCE(SUM({amt}), 0) AS total_amount
                FROM payments
                WHERE 1=1{dc}{cw}
            """
            r = run_query(sql)
            if r["rows"]:
                stats["total"] = r["rows"][0][0]
                stats["total_amount"] = r["rows"][0][1]
    except Exception:
        pass

    return stats


def build_narrative(
    user_msg: str,
    company_id: int | None,
    scope_label: str,
    table: str,
    columns: list,
    rows: list,
    row_count: int,
) -> tuple[str, list[str]]:
    """
    Returns (main narrative paragraph, bullet insights).
    """
    q = user_msg.lower().strip()
    insights = []
    scope = scope_label or "your company"

    if row_count == 0:
        return (
            f"No matching records for **{scope}**. "
            "Try a broader filter or check spelling of status words (active, inactive, paid).",
            [],
        )

    stats = {}
    chip_like = len(q.split()) <= 12 and any(
        w in q
        for w in (
            "customer", "invoice", "payment", "subscription",
            "overdue", "inactive", "active", "top", "recent",
        )
    )
    if chip_like or row_count <= 50:
        stats = fetch_table_stats(company_id, table)

    # --- Customers ---
    if table == "customers":
        shown = row_count
        total = int(stats.get("total") or 0)
        active = int(stats.get("active") or 0)
        status_breakdown = stats.get("status_breakdown", {})

        # Build a human-readable breakdown of ALL status values
        def _breakdown_str(bd: dict) -> str:
            if not bd:
                return ""
            parts = [f"**{v} {k}**" for k, v in sorted(bd.items(), key=lambda x: -x[1])]
            return ", ".join(parts)

        if "inactive" in q:
            narrative = f"**{shown} non-active customer(s)** shown for {scope}. "
            if total and status_breakdown:
                bd_str = _breakdown_str(status_breakdown)
                narrative += f"Out of **{total} total customers**: {bd_str}."
            elif total:
                inactive_count = total - active
                narrative += f"Out of **{total} total customers**, **{active} active** and **{inactive_count} non-active**."

        elif "active" in q and "inactive" not in q:
            narrative = f"**{shown} active customer(s)** in this view for {scope}. "
            if total and status_breakdown:
                bd_str = _breakdown_str(status_breakdown)
                narrative += f"Company-wide breakdown: {bd_str}."
            elif total:
                narrative += f"Company-wide: **{total} total customers**."

        else:
            narrative = f"**{shown} customer record(s)** for {scope}. "
            if total and status_breakdown:
                bd_str = _breakdown_str(status_breakdown)
                narrative += f"Full company breakdown: {bd_str}."
            elif total:
                narrative += f"Total customers on record: **{total}**."

        # Always add insights for any non-standard statuses found
        if status_breakdown:
            for sv, cnt in status_breakdown.items():
                if sv not in ("active", "inactive") and cnt > 0:
                    insights.append(f"{cnt} customer(s) with status '{sv}'")

        return narrative, insights

    # --- Overdue / orders ---
    if table == "orders":
        amt_col = "order_total" if _col_index(columns, "order_total") is not None else "amount"
        dues = _sum_column(columns, rows, amt_col)
        overdue_n = int(stats.get("overdue_count") or row_count)
        overdue_total = float(stats.get("overdue_total") or dues)

        if "overdue" in q:
            narrative = (
                f"**{row_count} overdue invoice(s)** listed for {scope}. "
                f"Outstanding value in this result set: **{_money(dues)}**."
            )
            if stats.get("overdue_total") is not None:
                narrative += (
                    f" Across all overdue bills for this scope, about **{_money(overdue_total)}** "
                    f"remains unpaid ({overdue_n} invoice(s))."
                )
            insights.append(f"Unpaid balance (shown rows): {_money(dues)}")
        elif "top" in q:
            narrative = (
                f"Top **{row_count} order(s) by amount** for {scope}. "
                f"Combined value in table: **{_money(dues)}**."
            )
        else:
            narrative = (
                f"**{row_count} invoice/order record(s)** for {scope}. "
                f"Total in this table: **{_money(dues)}**."
            )
            if stats.get("total_invoices"):
                narrative += (
                    f" Overall **{stats['total_invoices']} invoices** worth "
                    f"**{_money(stats.get('total_value', 0))}**."
                )
        return narrative, insights

    # --- Subscriptions ---
    if table == "customer_subscriptions":
        total = int(stats.get("total") or 0)
        active = int(stats.get("active") or 0)
        inactive = int(stats.get("inactive") or 0)
        if "inactive" in q:
            narrative = (
                f"**{row_count} inactive subscription(s)** shown for {scope}. "
            )
            if total:
                narrative += (
                    f"Of **{total} subscriptions**, **{active} active** and **{inactive} inactive/ended**."
                )
        elif "active" in q:
            narrative = (
                f"**{row_count} active subscription(s)** for {scope}. "
            )
            if total:
                narrative += f"Total subscriptions: **{total}** ({active} active)."
        else:
            narrative = f"**{row_count} subscription record(s)** for {scope}."
        return narrative, insights

    # --- Payments ---
    if table == "payments":
        total_amt = _sum_column(columns, rows, "amount")
        ps = _count_by_column(columns, rows, "payment_status")
        narrative = (
            f"**{row_count} payment record(s)** for {scope}, "
            f"summing to **{_money(total_amt)}** in this view."
        )
        if ps:
            narrative += " Status mix: " + ", ".join(f"{k}: {v}" for k, v in ps.items()) + "."
        return narrative, insights

    # --- Generic fallback ---
    status_counts = _count_by_column(columns, rows, "status")
    if not status_counts:
        status_counts = _count_by_column(columns, rows, "payment_status")

    narrative = f"**{row_count} record(s)** returned for {scope}."
    if status_counts:
        narrative += " " + ", ".join(
            f"**{v}** with status «{k}»" for k, v in list(status_counts.items())[:5]
        ) + "."
    return narrative, insights