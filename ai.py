import re
import json
import requests
from memory import memory
from config import OLLAMA_MODEL, OLLAMA_URL
from database import (
    get_table_schema,
    get_business_context,
    get_table_columns_map,
    table_has_column,
    inject_company_filter,
    get_company_name,
)


TABLE_MAPPINGS = {
    "company": "companies",
    "companies": "companies",
    "org": "companies",
    "organization": "companies",
    "business": "companies",
    "client": "companies",
    "clients": "companies",
    "lco": "companies",
    "lcos": "companies",
    "customer": "customers",
    "customers": "customers",
    "subscriber": "customers",
    "subscribers": "customers",
    "user": "customers",
    "users": "customers",
    "payment": "payments",
    "payments": "payments",
    "transaction": "payments",
    "transactions": "payments",
    "invoice": "orders",
    "invoices": "orders",
    "order": "orders",
    "orders": "orders",
    "sale": "orders",
    "sales": "orders",
    "bill": "orders",
    "bills": "orders",
    "subscription": "customer_subscriptions",
    "subscriptions": "customer_subscriptions",
    "product": "packages",
    "products": "packages",
    "package": "packages",
    "packages": "packages",
    "complaint": "complaints",
    "complaints": "complaints",
    "issue": "complaints",
    "issues": "complaints",
    "lead": "enquiries",
    "leads": "enquiries",
    "enquiry": "enquiries",
    "enquiries": "enquiries",
    "prospect": "enquiries",
    "prospects": "enquiries",
    "vendor": "vendors",
    "vendors": "vendors",
    "supplier": "vendors",
    "suppliers": "vendors",
    "addon": "customer_add_ons",
    "addons": "customer_add_ons",
    "add_on": "customer_add_ons",
    "add_ons": "customer_add_ons",
    "stb": "stbs",
    "stbs": "stbs",
    "device": "stbs",
    "devices": "stbs",
    "area": "areas",
    "areas": "areas",
    "region": "areas",
    "regions": "areas",
    "expense": "expenses",
    "expenses": "expenses",
    "income": "incomes",
    "incomes": "incomes",
}

AMOUNT_COLUMNS = {
    "orders": "order_total",
    "payments": "amount",
    "expenses": "amount",
    "incomes": "amount",
}

DATE_COLUMNS = {
    "orders": "invoice_date",
    "payments": "created_at",
    "customers": "created_at",
    "customer_subscriptions": "created_at",
}


def _has_word(text: str, word: str) -> bool:
    return re.search(r"\b" + re.escape(word) + r"\b", text) is not None


def _extract_limit(user_query: str, default: int = 10) -> int:
    match = re.search(r"\btop\s+(\d+)\b", user_query.lower())
    if match:
        return int(match.group(1))
    match = re.search(r"\b(\d+)\s+(?:top|best|highest)\b", user_query.lower())
    if match:
        return int(match.group(1))
    if _has_word(user_query.lower(), "top") or _has_word(user_query.lower(), "best"):
        return default
    return default


def _find_best_table(user_query: str) -> str:
    user_lower = user_query.lower()

    # Prefer longer keyword matches (e.g. "subscriptions" before "subscription")
    matches = []
    for keyword, table in TABLE_MAPPINGS.items():
        if _has_word(user_lower, keyword) or keyword in user_lower:
            matches.append((len(keyword), table))

    if matches:
        matches.sort(reverse=True)
        return matches[0][1]

    return "customers"


def _resolve_amount_column(table: str) -> str:
    if table in AMOUNT_COLUMNS and table_has_column(table, AMOUNT_COLUMNS[table]):
        return AMOUNT_COLUMNS[table]
    columns_map = get_table_columns_map()
    cols = columns_map.get(table, [])
    for candidate in ["order_total", "amount", "total", "balance", "sub_total"]:
        if candidate in cols:
            return candidate
    return "id"


def _resolve_date_column(table: str) -> str:
    if table in DATE_COLUMNS and table_has_column(table, DATE_COLUMNS[table]):
        return DATE_COLUMNS[table]
    for candidate in ["created_at", "invoice_date", "updated_at"]:
        if table_has_column(table, candidate):
            return candidate
    return "id"


def _resolve_status_column(table: str) -> str:
    if table == "payments" and table_has_column(table, "payment_status"):
        return "payment_status"
    return "status"


def _soft_delete_clause(table: str) -> str:
    if table_has_column(table, "deleted_at"):
        return "deleted_at IS NULL"
    return ""


def _build_sql_from_query(user_query: str, table: str) -> str:
    user_lower = user_query.lower()
    soft_delete = _soft_delete_clause(table)
    status_col = _resolve_status_column(table)
    date_col = _resolve_date_column(table)
    amount_col = _resolve_amount_column(table)

    def with_base(where_parts=None, order_by=None, limit=None):
        parts = list(where_parts or [])
        if soft_delete:
            parts.append(soft_delete)

        sql = f"SELECT * FROM {table}"
        if parts:
            sql += " WHERE " + " AND ".join(parts)
        if order_by:
            sql += f" ORDER BY {order_by}"
        if limit:
            sql += f" LIMIT {limit}"
        return sql + ";"

    # COUNT queries
    if _has_word(user_lower, "count") or "how many" in user_lower:
        where = [soft_delete] if soft_delete else []
        if where:
            return f"SELECT COUNT(*) AS total FROM {table} WHERE {' AND '.join(where)};"
        return f"SELECT COUNT(*) AS total FROM {table};"

    # INACTIVE — must be checked BEFORE active (inactive contains "active")
    if _has_word(user_lower, "inactive") or _has_word(user_lower, "disabled"):
        if table == "customers":
            return with_base([f"{status_col} = 'inactive'"])
        if table == "customer_subscriptions":
            return with_base([f"{status_col} IN ('inactive', 'terminated', 'expired')"])
        if table == "companies":
            return with_base([f"{status_col} = 'inactive'"])
        return with_base([f"{status_col} = 'inactive'"])

    # OVERDUE invoices
    if _has_word(user_lower, "overdue") and table == "orders":
        return with_base([
            "due_date < NOW()",
            "payment_status != 'paid'",
        ])

    # TOP / BEST / HIGHEST
    if _has_word(user_lower, "top") or _has_word(user_lower, "best") or _has_word(user_lower, "highest"):
        limit = _extract_limit(user_query, default=5)
        if any(w in user_lower for w in ["amount", "revenue", "sales", "total", "value"]):
            return with_base(order_by=f"{amount_col} DESC", limit=limit)
        return with_base(order_by=f"{date_col} DESC", limit=limit)

    # LATEST / RECENT / NEW
    if any(w in user_lower for w in ["latest", "recent", "newest", "new"]):
        return with_base(order_by=f"{date_col} DESC")

    # STATUS: active, pending, unpaid, paid, terminated, expired, suspended
    if _has_word(user_lower, "active"):
        return with_base([f"{status_col} = 'active'"])

    if _has_word(user_lower, "terminated"):
        return with_base([f"{status_col} = 'terminated'"])

    if _has_word(user_lower, "expired"):
        return with_base([f"{status_col} = 'expired'"])

    if _has_word(user_lower, "suspended"):
        return with_base([f"{status_col} = 'suspended'"])

    if _has_word(user_lower, "pending"):
        return with_base([f"{status_col} = 'pending'"])

    if _has_word(user_lower, "unpaid"):
        if table == "orders" and table_has_column(table, "payment_status"):
            return with_base(["payment_status IN ('pending', 'partially paid')"])
        if table == "payments":
            return with_base(["payment_status = 'pending'"])
        return with_base([f"{status_col} = 'pending'"])

    if _has_word(user_lower, "paid"):
        if table in ("orders", "payments") and table_has_column(table, "payment_status"):
            return with_base(["payment_status = 'paid'"])
        return with_base([f"{status_col} = 'paid'"])

    return with_base()


def _extract_sql_from_llm_response(text: str) -> str:
    text = text.strip()
    code_match = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if code_match:
        text = code_match.group(1).strip()
    select_match = re.search(r"(SELECT\b.+?;?)\s*$", text, re.DOTALL | re.IGNORECASE)
    if select_match:
        text = select_match.group(1).strip()
    if not text.endswith(";"):
        text += ";"
    return text


def _try_ollama_sql(user_query: str, company_id: int, table: str) -> str | None:
    try:
        schema = get_table_schema()
        context = get_business_context()
        company_name = get_company_name(company_id) if company_id else "All Companies"

        if company_id:
            company_scope = f"""COMPANY SCOPE (MANDATORY):
- User is logged in as company_id = {company_id} ({company_name})
- ALWAYS filter by company_id = {company_id} on tables that have company_id column
- For companies table, use WHERE id = {company_id}
- Exclude soft-deleted rows: deleted_at IS NULL where deleted_at column exists
- NEVER return data from other companies"""
        else:
            company_scope = """COMPANY SCOPE (ADMIN — FULL ACCESS):
- User is an ADMIN with access to ALL companies
- Do NOT filter by company_id unless the user explicitly asks for a specific company by name
- If the user names a specific company, filter by that company_id only
- Exclude soft-deleted rows: deleted_at IS NULL where deleted_at column exists
- Include company_id in results when showing data across all companies"""

        prompt = f"""You are a MySQL expert for a billing system called BillerQ.
Generate ONLY a single SELECT query. No explanation, no markdown unless using a sql code block.

DATABASE SCHEMA:
{schema}

BUSINESS RULES:
{context}

IMPORTANT COLUMN MAPPINGS:
- orders/invoice amount = order_total (NOT amount)
- payments amount = amount
- customers status values: active, inactive, suspended, archive
- customer_subscriptions status values: inactive, pending, active, terminated, expired
- orders payment_status values: pending, partially paid, paid
- overdue invoices: due_date < NOW() AND payment_status != 'paid'

{company_scope}

USER QUESTION:
{user_query}

Likely primary table: {table}

Return ONLY the SQL query:"""

        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 512},
            },
            timeout=3,
        )
        response.raise_for_status()
        result = response.json().get("response", "").strip()
        if not result:
            return None

        sql = _extract_sql_from_llm_response(result)
        if not sql.upper().startswith("SELECT"):
            return None
        return sql

    except Exception:
        return None


def _use_rules_only(user_query: str) -> bool:
    """Fast path for chip prompts and common short queries."""
    q = user_query.lower().strip()
    chip_phrases = {
        "show all customers", "inactive customers", "recent payments",
        "latest invoices", "active subscriptions", "inactive subscriptions",
        "overdue invoices", "top 5 orders by amount",
    }
    if q in chip_phrases:
        return True
    if len(q.split()) <= 8 and any(
        w in q for w in [
            "inactive", "active", "overdue", "recent", "latest", "top",
            "pending", "unpaid", "paid", "show all", "count", "how many",
        ]
    ):
        return True
    return False


def natural_language_to_sql(user_query: str, company_id: int = None) -> dict:
    table = _find_best_table(user_query)

    if _use_rules_only(user_query):
        sql = _build_sql_from_query(user_query, table)
        method = "rules"
    else:
        sql = _try_ollama_sql(user_query, company_id, table)
        method = "ai"
        if not sql:
            sql = _build_sql_from_query(user_query, table)
            method = "rules"

    if company_id:
        sql = inject_company_filter(sql, company_id, table)

    try:
        memory.save_context({"input": user_query}, {"output": sql})
    except Exception:
        pass

    return {
        "sql": sql.strip(),
        "explanation": f"Generated SQL ({method}) for: {user_query}",
        "table": table,
        "method": method,
    }


def generate_full_response(user_query: str, columns: list, rows: list) -> dict:
    if not rows:
        return {"summary": "No records found.", "insights": []}

    summary = f"Found {len(rows)} record(s)."
    insights = []

    q = user_query.lower()
    if "customer" in q:
        insights.append(f"{len(rows)} customers")
    elif "payment" in q:
        insights.append(f"{len(rows)} payments")
    elif "order" in q or "invoice" in q:
        insights.append(f"{len(rows)} orders/invoices")

    return {"summary": summary, "insights": insights}
