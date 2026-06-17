import re
import time
from typing import Any

from database import get_connection, get_table_columns_map, run_query, table_has_column
from report_store import safe_result


_CACHE_TTL_SEC = 90
_DASHBOARD_CACHE: dict[tuple[int | None, str], tuple[float, dict[str, Any]]] = {}
_TABLE_COLUMNS_CACHE: dict[str, tuple[float, list[str]]] = {}


def money(value: Any) -> str:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        amount = 0.0
    if amount >= 100000:
        return f"₹{amount / 100000:.2f} lakh"
    return f"₹{amount:,.2f}"


def _table_exists(table: str) -> bool:
    return table in get_table_columns_map()


def _columns_for_table(table: str) -> list[str]:
    cached = _TABLE_COLUMNS_CACHE.get(table)
    if cached and time.time() - cached[0] < 3600:
        return cached[1]
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"DESCRIBE {table}")
        columns = [row[0] for row in cursor.fetchall()]
        _TABLE_COLUMNS_CACHE[table] = (time.time(), columns)
        return columns
    except Exception:
        return []
    finally:
        cursor.close()
        conn.close()


def _first_existing(table: str, candidates: list[str]) -> str | None:
    for column in candidates:
        if table_has_column(table, column):
            return column
    return None


def _deleted_condition(table: str, alias: str | None = None) -> str:
    if not table_has_column(table, "deleted_at"):
        return ""
    prefix = f"{alias}." if alias else ""
    return f"{prefix}deleted_at IS NULL"


def _company_condition(table: str, company_id: int | None, alias: str | None = None) -> str:
    if not company_id:
        return ""
    prefix = f"{alias}." if alias else ""
    if table == "companies":
        return f"{prefix}id = {int(company_id)}"
    if table_has_column(table, "company_id"):
        return f"{prefix}company_id = {int(company_id)}"
    return ""


def _where(parts: list[str]) -> str:
    cleaned = [part for part in parts if part]
    return " WHERE " + " AND ".join(cleaned) if cleaned else ""


def _payment_date_column() -> str:
    return _first_existing("payments", ["payment_date", "paid_at", "created_at", "updated_at"]) or "created_at"


def _customer_name_expr(alias: str = "c") -> str:
    cols = _columns_for_table("customers")
    if "first_name" in cols and "last_name" in cols:
        return f"TRIM(CONCAT(COALESCE({alias}.first_name, ''), ' ', COALESCE({alias}.last_name, '')))"
    for candidate in ("name", "customer_name", "full_name"):
        if candidate in cols:
            return f"{alias}.{candidate}"
    if "phone" in cols:
        return f"{alias}.phone"
    return f"CAST({alias}.id AS CHAR)"


def _run_first_row(sql: str) -> dict[str, Any]:
    result = run_query(sql)
    if not result["rows"]:
        return {}
    return {col: result["rows"][0][idx] for idx, col in enumerate(result["columns"])}


def _sql_value(value: Any) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _customer_name_columns() -> list[str]:
    cols = _columns_for_table("customers")
    return [
        col for col in ("first_name", "last_name", "name", "customer_name", "full_name")
        if col in cols
    ]


def _customer_contact_columns() -> list[str]:
    cols = _columns_for_table("customers")
    return [
        col for col in (
            "phone",
            "mobile",
            "mobile_number",
            "phone_number",
            "contact_number",
            "email",
            "email_id",
        )
        if col in cols
    ]


def _customer_select_columns() -> list[str]:
    cols = _columns_for_table("customers")
    priority = [
        "id",
        "customer_id",
        "first_name",
        "last_name",
        "name",
        "customer_name",
        "full_name",
        "phone",
        "mobile",
        "mobile_number",
        "email",
        "email_id",
        "city",
        "area",
        "address",
        "status",
        "customer_type",
        "created_at",
        "updated_at",
    ]
    selected = [col for col in priority if col in cols]
    safe_cols, _ = safe_result(selected, [])
    return safe_cols or ["id"]


def _mask_phone(value: Any) -> str:
    text = re.sub(r"\D+", "", str(value or ""))
    if len(text) <= 4:
        return text or "not available"
    return "*" * max(len(text) - 4, 0) + text[-4:]


def _mask_email(value: Any) -> str:
    text = str(value or "").strip()
    if "@" not in text:
        return text or "not available"
    name, domain = text.split("@", 1)
    if len(name) <= 2:
        masked = name[:1] + "*"
    else:
        masked = name[:2] + "*" * (len(name) - 2)
    return f"{masked}@{domain}"


def _row_dict(columns: list[str], row: list[Any]) -> dict[str, Any]:
    return {columns[idx]: row[idx] for idx in range(len(columns))}


def _customer_display_name(customer: dict[str, Any]) -> str:
    for column in ("name", "customer_name", "full_name"):
        if customer.get(column) not in (None, "", "NULL"):
            return str(customer[column]).strip()
    first = str(customer.get("first_name") or "").strip()
    last = str(customer.get("last_name") or "").strip()
    full = f"{first} {last}".strip()
    if full:
        return full
    return f"Customer #{customer.get('id', 'unknown')}"


def _customer_quick_lines(customer: dict[str, Any]) -> list[str]:
    lines = []
    for label, keys in (
        ("Status", ("status",)),
        ("Phone", ("phone", "mobile", "mobile_number", "phone_number", "contact_number")),
        ("Email", ("email", "email_id")),
        ("City", ("city",)),
        ("Area", ("area",)),
        ("Type", ("customer_type",)),
    ):
        for key in keys:
            value = customer.get(key)
            if value not in (None, "", "NULL"):
                lines.append(f"{label}: {value}")
                break
    return lines


def _extract_customer_name(query: str) -> str | None:
    cleaned = query.strip().replace("’", "'")
    patterns = [
        r"\b(?:give|show|get|find|search)\s+(?:me\s+)?(?:the\s+)?(?:details?\s+(?:of|for)\s+)([A-Za-z][A-Za-z .'\-]{1,60})",
        r"\b(?:give|show|get|find|search)\s+(?:me\s+)?([A-Za-z][A-Za-z .'\-]{1,60}?)(?:'s)?\s+(?:details?|profile|information|info)\b",
        r"\bdetails?\s+(?:of|for)\s+([A-Za-z][A-Za-z .'\-]{1,60})",
        r"\b([A-Za-z][A-Za-z .'\-]{1,60}?)(?:'s)?\s+(?:details?|profile|information|info)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned, re.IGNORECASE)
        if match:
            name = re.sub(r"\b(customer|subscriber|please|details|detail)\b", "", match.group(1), flags=re.IGNORECASE)
            name = re.sub(r"\s+", " ", name).strip(" .'")
            return name or None
    return None


def _identifier_conditions(identifier: str) -> list[str]:
    value = identifier.strip()
    if not value:
        return []
    cols = _customer_contact_columns()
    conditions = []
    if "@" in value:
        for column in cols:
            if "email" in column:
                conditions.append(f"{column} = {_sql_value(value)}")
    else:
        digits = re.sub(r"\D+", "", value)
        if digits:
            for column in cols:
                if any(word in column for word in ("phone", "mobile", "contact")):
                    conditions.append(f"REPLACE(REPLACE(REPLACE(REPLACE({column}, ' ', ''), '-', ''), '+', ''), '.', '') LIKE '%{digits}%'")
    return conditions


def _customer_name_conditions(name: str) -> list[str]:
    value = name.strip()
    if not value:
        return []
    exact = _sql_value(value)
    starts_with = "'" + value.replace("'", "''") + "%'"
    conditions = []
    name_cols = _customer_name_columns()
    for column in name_cols:
        conditions.append(f"{column} = {exact}")
        conditions.append(f"{column} LIKE {starts_with}")
    if "first_name" in name_cols and "last_name" in name_cols:
        conditions.append(f"CONCAT(COALESCE(first_name, ''), ' ', COALESCE(last_name, '')) = {exact}")
        conditions.append(f"CONCAT(COALESCE(first_name, ''), ' ', COALESCE(last_name, '')) LIKE {starts_with}")
    return conditions


def _customer_company_condition(company_id: int | None) -> str:
    cols = _columns_for_table("customers")
    if company_id and "company_id" in cols:
        return f"company_id = {int(company_id)}"
    return ""


def _customer_deleted_condition() -> str:
    return "deleted_at IS NULL" if "deleted_at" in _columns_for_table("customers") else ""


def _fetch_customers(
    company_id: int | None,
    *,
    name: str | None = None,
    identifier: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    select_cols = _customer_select_columns()
    where_parts = [_customer_company_condition(company_id), _customer_deleted_condition()]

    name_conditions = _customer_name_conditions(name or "")
    identifier_conditions = _identifier_conditions(identifier or "")
    if name_conditions:
        where_parts.append("(" + " OR ".join(name_conditions) + ")")
    if identifier_conditions:
        where_parts.append("(" + " OR ".join(identifier_conditions) + ")")

    sql = (
        f"SELECT /*+ MAX_EXECUTION_TIME(4000) */ {', '.join(select_cols)} FROM customers"
        f"{_where(where_parts)} LIMIT {int(limit)}"
    )
    try:
        return run_query(sql)
    except Exception:
        return {"columns": select_cols, "rows": [], "row_count": 0}


def get_customer_details(company_id: int | None, scope_label: str, query: str) -> dict[str, Any] | None:
    if not _columns_for_table("customers"):
        return None
    name = _extract_customer_name(query)
    identifier_match = re.search(r"[\w.\-+]+@[\w.\-]+\.\w+|\+?\d[\d\s.\-]{5,}\d", query)
    identifier = identifier_match.group(0).strip() if identifier_match else None

    if not name and not identifier:
        return None

    result = _fetch_customers(company_id, name=name, identifier=identifier, limit=10)
    safe_columns, safe_rows = safe_result(result["columns"], result["rows"])
    customers = [_row_dict(safe_columns, row) for row in safe_rows]

    if not customers:
        target = name or identifier
        return {
            "summary": f"I couldn't find a customer matching {target} in {scope_label}.",
            "narrative": f"I checked the customer records for **{target}**, but nothing matched in this company scope.",
            "insights": ["Try the full phone number or email if the name spelling is different."],
            "columns": safe_columns,
            "rows": safe_rows,
            "row_count": 0,
            "service_used": "Customer Service",
            "route": "business_service",
            "intent": "Customer Details",
            "detail_mode": "collapsed",
        }

    if len(customers) > 1 and not identifier:
        choices = []
        for idx, customer in enumerate(customers, start=1):
            phone = next((customer.get(k) for k in ("phone", "mobile", "mobile_number", "phone_number", "contact_number") if customer.get(k)), "")
            email = next((customer.get(k) for k in ("email", "email_id") if customer.get(k)), "")
            city = customer.get("city") or customer.get("area") or "location not set"
            choices.append(
                f"{idx}. {_customer_display_name(customer)} - phone {_mask_phone(phone)}, email {_mask_email(email)}, {city}"
            )
        return {
            "summary": f"I found {len(customers)} customers matching {name}.",
            "narrative": (
                f"I found **{len(customers)} customers** named **{name}**. "
                "Which one do you mean? Reply with that customer's phone number or email.\n\n"
                + "\n".join(choices)
            ),
            "insights": ["I will use your next reply to identify the exact customer."],
            "columns": safe_columns,
            "rows": safe_rows,
            "row_count": len(customers),
            "service_used": "Customer Service",
            "route": "business_service",
            "intent": "Customer Details",
            "detail_mode": "collapsed",
            "needs_disambiguation": True,
            "disambiguation": {"type": "customer", "name": name},
        }

    customer = customers[0]
    display_name = _customer_display_name(customer)
    quick_lines = _customer_quick_lines(customer)
    narrative = f"Got it - here's the safe customer snapshot for **{display_name}**."
    if quick_lines:
        narrative += "\n\n" + "\n".join(f"- {line}" for line in quick_lines[:8])

    return {
        "summary": f"Customer details found for {display_name}.",
        "narrative": narrative,
        "insights": ["Sensitive fields are hidden. Open the report for the full safe profile."],
        "columns": safe_columns,
        "rows": [safe_rows[0]],
        "row_count": 1,
        "service_used": "Customer Service",
        "route": "business_service",
        "intent": "Customer Details",
        "detail_mode": "collapsed",
        "report_title": f"Customer Details - {display_name}",
    }


def resolve_customer_details(
    company_id: int | None,
    scope_label: str,
    pending: dict[str, Any],
    identifier: str,
) -> dict[str, Any] | None:
    if pending.get("type") != "customer":
        return None
    name = pending.get("name")
    result = _fetch_customers(company_id, name=name, identifier=identifier, limit=2)
    safe_columns, safe_rows = safe_result(result["columns"], result["rows"])
    if result["row_count"] != 1:
        return {
            "summary": "I still could not identify exactly one customer.",
            "narrative": "Please send the full phone number or email for the customer you mean.",
            "insights": [],
            "columns": safe_columns,
            "rows": safe_rows,
            "row_count": result["row_count"],
            "service_used": "Customer Service",
            "route": "business_service",
            "intent": "Customer Details",
            "detail_mode": "collapsed",
            "needs_disambiguation": True,
            "disambiguation": pending,
        }
    customer = _row_dict(safe_columns, safe_rows[0])
    display_name = _customer_display_name(customer)
    quick_lines = _customer_quick_lines(customer)
    narrative = f"Perfect, I found **{display_name}**."
    if quick_lines:
        narrative += "\n\n" + "\n".join(f"- {line}" for line in quick_lines[:8])
    return {
        "summary": f"Customer details found for {display_name}.",
        "narrative": narrative,
        "insights": ["Sensitive fields are hidden. Open the report for the full safe profile."],
        "columns": safe_columns,
        "rows": safe_rows,
        "row_count": 1,
        "service_used": "Customer Service",
        "route": "business_service",
        "intent": "Customer Details",
        "detail_mode": "collapsed",
        "report_title": f"Customer Details - {display_name}",
    }


def _status_count(table: str, company_id: int | None, status: str, alias: str | None = None) -> int:
    if not _table_exists(table) or not table_has_column(table, "status"):
        return 0
    prefix = f"{alias}." if alias else ""
    status_condition = f"{prefix}status = '{status}'"
    sql = (
        f"SELECT COUNT(*) AS total FROM {table}"
        f"{_where([_company_condition(table, company_id, alias), _deleted_condition(table, alias), status_condition])}"
    )
    row = _run_first_row(sql)
    return int(row.get("total") or 0)


def get_today_collection(company_id: int | None, scope_label: str) -> dict[str, Any] | None:
    if not _table_exists("payments") or not table_has_column("payments", "amount"):
        return None

    date_col = _payment_date_column()
    status_col = _first_existing("payments", ["payment_status", "status"])
    status_filter = f"{status_col} = 'paid'" if status_col else ""
    sql = (
        "SELECT COUNT(*) AS payment_count, COALESCE(SUM(amount), 0) AS total_collection "
        "FROM payments"
        f"{_where([_company_condition('payments', company_id), _deleted_condition('payments'), status_filter, f'DATE({date_col}) = CURDATE()'])}"
    )
    row = _run_first_row(sql)
    total = row.get("total_collection", 0)
    count = int(row.get("payment_count") or 0)

    return {
        "summary": f"Today's collection for {scope_label} is {money(total)} from {count} payment(s).",
        "narrative": f"{count} payment(s) were collected today, totaling **{money(total)}**.",
        "insights": ["Answered through Payment Service without AI SQL generation."],
        "columns": ["payment_count", "total_collection"],
        "rows": [[count, total]],
        "row_count": 1,
        "service_used": "Payment Service",
        "route": "business_service",
        "intent": "Collection Query",
        "detail_mode": "collapsed",
    }


def get_payments_by_amount_today(
    company_id: int | None,
    scope_label: str,
    amount: float,
) -> dict[str, Any] | None:
    if not _table_exists("payments") or not table_has_column("payments", "amount"):
        return None

    date_col = _payment_date_column()
    status_col = _first_existing("payments", ["payment_status", "status"])
    status_filter = f"p.{status_col} = 'paid'" if status_col else ""
    joins = ""
    name_expr = "CAST(p.customer_id AS CHAR)" if table_has_column("payments", "customer_id") else "'Unknown'"
    if _table_exists("customers") and table_has_column("payments", "customer_id"):
        joins = " LEFT JOIN customers c ON c.id = p.customer_id"
        if table_has_column("customers", "company_id"):
            joins += " AND c.company_id = p.company_id" if table_has_column("payments", "company_id") else ""
        customer_deleted = _deleted_condition("customers", "c")
        if customer_deleted:
            joins += f" AND {customer_deleted}"
        name_expr = _customer_name_expr("c")

    sql = (
        f"SELECT {name_expr} AS customer_name, p.amount, p.{date_col} AS payment_date "
        "FROM payments p"
        f"{joins}"
        f"{_where([_company_condition('payments', company_id, 'p'), _deleted_condition('payments', 'p'), status_filter, f'DATE(p.{date_col}) = CURDATE()', f'p.amount = {float(amount):.2f}'])} "
        f"ORDER BY p.{date_col} DESC LIMIT 50"
    )
    result = run_query(sql)
    names = [str(row[0]).strip() or "Unknown" for row in result["rows"]]
    count = result["row_count"]
    display_amount = money(amount)
    narrative = f"{count} customer(s) made payments of **{display_amount}** today."
    if names:
        narrative += "\n\nCustomer Names:\n" + "\n".join(f"- {name}" for name in names[:10])

    return {
        "summary": f"{count} customer(s) paid {display_amount} today.",
        "narrative": narrative,
        "insights": ["Detailed rows are available in the report view."],
        "columns": result["columns"],
        "rows": result["rows"],
        "row_count": count,
        "service_used": "Payment Service",
        "route": "business_service",
        "intent": "Payment Query",
        "detail_mode": "collapsed",
    }


def get_pending_payments(company_id: int | None, scope_label: str) -> dict[str, Any] | None:
    table = "orders" if _table_exists("orders") and table_has_column("orders", "payment_status") else "payments"
    if not _table_exists(table):
        return None

    if table == "orders":
        amount_col = _first_existing("orders", ["order_total", "amount", "total"]) or "id"
        status_condition = "payment_status IN ('pending', 'partially paid', 'unpaid')"
    else:
        amount_col = _first_existing("payments", ["amount", "total"]) or "id"
        status_col = _first_existing("payments", ["payment_status", "status"])
        if not status_col:
            return None
        status_condition = f"{status_col} IN ('pending', 'partially paid', 'unpaid', 'failed')"

    sql = (
        f"SELECT COUNT(*) AS pending_count, COALESCE(SUM({amount_col}), 0) AS outstanding_amount "
        f"FROM {table}"
        f"{_where([_company_condition(table, company_id), _deleted_condition(table), status_condition])}"
    )
    row = _run_first_row(sql)
    count = int(row.get("pending_count") or 0)
    total = row.get("outstanding_amount", 0)
    return {
        "summary": f"There are {count} pending payment(s) for {scope_label}, totaling {money(total)}.",
        "narrative": f"**{count} pending payment(s)** need attention, with an outstanding value of **{money(total)}**.",
        "insights": [f"Source: {table} payment status fields."],
        "columns": ["pending_count", "outstanding_amount"],
        "rows": [[count, total]],
        "row_count": 1,
        "service_used": "Payment Service",
        "route": "business_service",
        "intent": "Payment Query",
        "detail_mode": "collapsed",
    }


def get_dashboard_metrics(company_id: int | None, scope_label: str) -> dict[str, Any] | None:
    cache_key = (company_id, "dashboard_metrics")
    cached = _DASHBOARD_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < _CACHE_TTL_SEC:
        payload = dict(cached[1])
        payload["insights"] = payload.get("insights", []) + ["Served from Dashboard Cache."]
        return payload

    metrics: dict[str, Any] = {}
    if _table_exists("customers"):
        metrics["active_customers"] = _status_count("customers", company_id, "active")
    if _table_exists("customer_subscriptions"):
        metrics["active_subscribers"] = _status_count("customer_subscriptions", company_id, "active")
    if _table_exists("complaints"):
        status_col = _first_existing("complaints", ["status"])
        complaint_filter = f"{status_col} NOT IN ('closed', 'resolved')" if status_col else ""
        row = _run_first_row(
            "SELECT COUNT(*) AS open_complaints FROM complaints"
            f"{_where([_company_condition('complaints', company_id), _deleted_condition('complaints'), complaint_filter])}"
        )
        metrics["open_complaints"] = int(row.get("open_complaints") or 0)

    today_collection = get_today_collection(company_id, scope_label)
    if today_collection and today_collection.get("rows"):
        metrics["today_collection"] = today_collection["rows"][0][1]

    pending = get_pending_payments(company_id, scope_label)
    if pending and pending.get("rows"):
        metrics["pending_payments"] = pending["rows"][0][0]
        metrics["outstanding_amount"] = pending["rows"][0][1]

    if not metrics:
        return None

    columns = list(metrics.keys())
    rows = [[metrics[col] for col in columns]]
    narrative_parts = []
    if "today_collection" in metrics:
        narrative_parts.append(f"today's collection is **{money(metrics['today_collection'])}**")
    if "active_customers" in metrics:
        narrative_parts.append(f"**{metrics['active_customers']} active customers**")
    if "pending_payments" in metrics:
        narrative_parts.append(f"**{metrics['pending_payments']} pending payments** worth **{money(metrics.get('outstanding_amount', 0))}**")
    if "open_complaints" in metrics:
        narrative_parts.append(f"**{metrics['open_complaints']} open complaints**")

    payload = {
        "summary": f"Dashboard snapshot for {scope_label}.",
        "narrative": "For this dashboard view, " + ", ".join(narrative_parts) + ".",
        "insights": ["Answered through Dashboard Service before attempting SQL generation."],
        "columns": columns,
        "rows": rows,
        "row_count": 1,
        "service_used": "Dashboard Service",
        "route": "dashboard_cache",
        "intent": "Dashboard Query",
        "detail_mode": "collapsed",
    }
    _DASHBOARD_CACHE[cache_key] = (time.time(), payload)
    return payload


def get_customer_count(company_id: int | None, scope_label: str, status: str | None = None) -> dict[str, Any] | None:
    if not _table_exists("customers"):
        return None
    status_filter = f"status = '{status}'" if status and table_has_column("customers", "status") else ""
    sql = (
        "SELECT COUNT(*) AS customer_count FROM customers"
        f"{_where([_company_condition('customers', company_id), _deleted_condition('customers'), status_filter])}"
    )
    row = _run_first_row(sql)
    count = int(row.get("customer_count") or 0)
    status_label = f"{status} " if status else ""
    return {
        "summary": f"There are {count} {status_label}customer(s) for {scope_label}.",
        "narrative": f"Found **{count} {status_label}customer(s)** in this company scope.",
        "insights": ["Answered through Customer Service."],
        "columns": ["customer_count"],
        "rows": [[count]],
        "row_count": 1,
        "service_used": "Customer Service",
        "route": "business_service",
        "intent": "Customer Search",
        "detail_mode": "collapsed",
    }


def get_complaint_summary(company_id: int | None, scope_label: str) -> dict[str, Any] | None:
    if not _table_exists("complaints"):
        return None
    status_col = _first_existing("complaints", ["status"])
    select = "COUNT(*) AS total_complaints"
    if status_col:
        select += f", SUM(CASE WHEN {status_col} IN ('open', 'pending') THEN 1 ELSE 0 END) AS open_complaints"
    sql = f"SELECT {select} FROM complaints{_where([_company_condition('complaints', company_id), _deleted_condition('complaints')])}"
    row = _run_first_row(sql)
    total = int(row.get("total_complaints") or 0)
    open_count = int(row.get("open_complaints") or 0)
    return {
        "summary": f"{scope_label} has {total} complaint(s), including {open_count} open/pending.",
        "narrative": f"There are **{total} complaint(s)** in this scope. **{open_count}** are still open or pending.",
        "insights": ["Answered through Complaint Service."],
        "columns": ["total_complaints", "open_complaints"],
        "rows": [[total, open_count]],
        "row_count": 1,
        "service_used": "Complaint Service",
        "route": "business_service",
        "intent": "Complaint Query",
        "detail_mode": "collapsed",
    }
