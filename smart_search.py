import json
import re

import requests

from config import OLLAMA_MODEL, OLLAMA_URL, OLLAMA_TIMEOUT_SEC
from database import get_table_columns_map, get_table_schema, table_has_column


SEARCH_HINTS = (
    "who",
    "named",
    "from",
    "living in",
    "city",
    "recently",
    "recent",
    "hasn't paid",
    "has not paid",
    "didn't pay",
    "unpaid",
    "complaint",
    "complaints",
    "subscription",
    "subscriptions",
    "expires",
    "expire",
    "paid above",
    "above",
    "pending invoice",
    "pending invoices",
)

TABLE_DISPLAY_COLUMNS = {
    "customers": [
        "id",
        "first_name",
        "last_name",
        "name",
        "customer_name",
        "city",
        "status",
        "email",
        "phone",
    ],
    "payments": [
        "id",
        "customer_id",
        "amount",
        "status",
        "payment_status",
        "payment_date",
        "created_at",
    ],
    "orders": [
        "id",
        "customer_id",
        "order_total",
        "payment_status",
        "status",
        "due_date",
        "invoice_date",
        "created_at",
    ],
    "customer_subscriptions": [
        "id",
        "customer_id",
        "status",
        "payment_status",
        "plan_name",
        "plan",
        "start_date",
        "expiry_date",
        "created_at",
    ],
    "complaints": [
        "id",
        "customer_id",
        "status",
        "title",
        "subject",
        "description",
        "created_at",
    ],
}

TABLE_DATE_COLUMNS = {
    "customers": ["created_at", "updated_at"],
    "payments": ["payment_date", "created_at", "updated_at"],
    "orders": ["invoice_date", "due_date", "created_at", "updated_at"],
    "customer_subscriptions": ["expiry_date", "start_date", "created_at", "updated_at"],
    "complaints": ["created_at", "updated_at"],
}


def is_search_query(query: str) -> bool:
    q = query.lower().strip()
    if not q:
        return False
    return any(hint in q for hint in SEARCH_HINTS)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def _extract_json_payload(text: str) -> dict | None:
    candidate = text.strip()
    code_match = re.search(r"```(?:json)?\s*(.*?)```", candidate, re.DOTALL | re.IGNORECASE)
    if code_match:
        candidate = code_match.group(1).strip()

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = candidate[start : end + 1]

    try:
        return json.loads(candidate)
    except Exception:
        candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
        candidate = candidate.replace("'", '"')
        try:
            return json.loads(candidate)
        except Exception:
            return None


def _heuristic_entities(query: str) -> dict:
    q = query.strip()
    q_lower = q.lower()
    name = None
    city = None

    name_match = re.search(r"\b(?:named|name is|customer is|for)\s+([A-Za-z][A-Za-z'\-]*)", q, re.IGNORECASE)
    if name_match:
        name = name_match.group(1)
    else:
        words = re.findall(r"\b[A-Z][a-zA-Z'\-]+\b", q)
        if words:
            name = words[0]

    city_match = re.search(r"\bfrom\s+([A-Za-z][A-Za-z'\-]*)", q, re.IGNORECASE)
    if city_match:
        city = city_match.group(1)
    else:
        city_match = re.search(r"\b(?:in|living in|located in)\s+([A-Za-z][A-Za-z'\-]*)", q, re.IGNORECASE)
        if city_match:
            city = city_match.group(1)

    status = None
    if any(phrase in q_lower for phrase in ("hasn't paid", "has not paid", "didn't pay", "unpaid", "not paid")):
        status = "unpaid"
    elif "paid" in q_lower:
        status = "paid"
    elif "active" in q_lower:
        status = "active"
    elif "inactive" in q_lower:
        status = "inactive"
    elif "pending" in q_lower:
        status = "pending"
    elif "expired" in q_lower:
        status = "expired"
    elif "terminated" in q_lower:
        status = "terminated"

    intent = "customer_search"
    if any(word in q_lower for word in ("complaint", "issue")):
        intent = "complaint_search"
    elif any(word in q_lower for word in ("subscription", "plan", "expire", "renew")):
        intent = "subscription_search"
    elif any(word in q_lower for word in ("payment", "invoice", "order", "bill")):
        intent = "billing_search"

    return {
        "name": name,
        "city": city,
        "status": status,
        "intent": intent,
    }


def extract_entities(query: str) -> dict:
    prompt = f"""
Extract entities from this billing database search query.

Return JSON only with these keys:
{{
  "name": "",
  "city": "",
  "status": "",
  "intent": "",
  "recent": false,
  "amount": null,
  "table_hint": ""
}}

Rules:
- Normalize unpaid / hasn't paid / not paid to "unpaid".
- Normalize paid to "paid".
- Normalize recent / recently to recent=true.
- Keep empty strings or null when the query does not mention a field.
- intent should be a short label like customer_search, payment_search, subscription_search, or complaint_search.

Query:
{query}
"""

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0, "num_predict": 128},
            },
            timeout=OLLAMA_TIMEOUT_SEC,
        )
        response.raise_for_status()
        payload = _extract_json_payload(response.json().get("response", ""))
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass

    return _heuristic_entities(query)


def _singularize(table_name: str) -> str:
    if table_name.endswith("ies"):
        return table_name[:-3] + "y"
    if table_name.endswith("ses"):
        return table_name[:-2]
    if table_name.endswith("s"):
        return table_name[:-1]
    return table_name


def _table_alias(table_name: str) -> str:
    if table_name == "customer_subscriptions":
        return "subs"
    if table_name == "complaints":
        return "comp"
    if table_name == "customers":
        return "c"
    if table_name == "payments":
        return "p"
    if table_name == "orders":
        return "o"
    return table_name[:1]


def _choose_base_table(query: str, entities: dict, columns_map: dict[str, list[str]]) -> str:
    q = query.lower()
    if any(word in q for word in ("complaint", "issue")) and "complaints" in columns_map:
        return "complaints"
    if any(word in q for word in ("subscription", "plan", "expire", "renew")) and "customer_subscriptions" in columns_map:
        return "customer_subscriptions"
    if any(word in q for word in ("order", "invoice", "bill")) and "orders" in columns_map:
        return "orders"
    if any(word in q for word in ("payment", "paid", "unpaid", "receipt")) and "payments" in columns_map:
        return "payments"
    if entities.get("name") or entities.get("city") or any(word in q for word in ("customer", "subscriber", "user")):
        return "customers" if "customers" in columns_map else next(iter(columns_map), "customers")
    return "customers" if "customers" in columns_map else next(iter(columns_map), "customers")


def _resolve_related_tables(base_table: str, query: str, entities: dict, columns_map: dict[str, list[str]]) -> list[str]:
    q = query.lower()
    related = []

    if base_table != "customers" and "customers" in columns_map:
        related.append("customers")

    if any(word in q for word in ("payment", "paid", "unpaid", "recent", "recently")) and "payments" in columns_map:
        if base_table != "payments":
            related.append("payments")

    if any(word in q for word in ("subscription", "plan", "expire", "renew")) and "customer_subscriptions" in columns_map:
        if base_table != "customer_subscriptions":
            related.append("customer_subscriptions")

    if any(word in q for word in ("complaint", "issue")) and "complaints" in columns_map:
        if base_table != "complaints":
            related.append("complaints")

    if any(word in q for word in ("order", "invoice", "bill", "amount")) and "orders" in columns_map:
        if base_table != "orders":
            related.append("orders")

    if entities.get("name") or entities.get("city"):
        if "customers" in columns_map and "customers" not in related and base_table != "customers":
            related.insert(0, "customers")

    return list(dict.fromkeys(related))


def _join_condition(left_table: str, right_table: str, columns_map: dict[str, list[str]]) -> str | None:
    right_columns = columns_map.get(right_table, [])
    left_columns = columns_map.get(left_table, [])
    left_tokens = [left_table, _singularize(left_table)]

    fk_candidates = []
    for token in left_tokens:
        fk_candidates.extend(
            [
                f"{token}_id",
                f"{token[:-1]}_id" if token.endswith("s") else None,
            ]
        )
    fk_candidates = [candidate for candidate in fk_candidates if candidate]

    for candidate in fk_candidates:
        if candidate in right_columns:
            return f"{_table_alias(left_table)}.id = {_table_alias(right_table)}.{candidate}"

    right_tokens = [right_table, _singularize(right_table)]
    reverse_candidates = []
    for token in right_tokens:
        reverse_candidates.extend(
            [
                f"{token}_id",
                f"{token[:-1]}_id" if token.endswith("s") else None,
            ]
        )
    reverse_candidates = [candidate for candidate in reverse_candidates if candidate]

    for candidate in reverse_candidates:
        if candidate in left_columns:
            return f"{_table_alias(left_table)}.{candidate} = {_table_alias(right_table)}.id"

    if "company_id" in left_columns and "company_id" in right_columns:
        return f"{_table_alias(left_table)}.company_id = {_table_alias(right_table)}.company_id"

    return None


def _select_columns(table: str, alias: str, columns_map: dict[str, list[str]]) -> list[str]:
    columns = columns_map.get(table, [])
    selected = []
    for candidate in TABLE_DISPLAY_COLUMNS.get(table, []):
        if candidate in columns:
            selected.append(f"{alias}.{candidate} AS {table}_{candidate}")

    if not selected:
        selected.append(f"{alias}.*")
    return selected


def _summary_columns(table: str, alias: str, columns_map: dict[str, list[str]]) -> list[str]:
    columns = columns_map.get(table, [])
    selected = []

    if table == "payments":
        for candidate, output in (("payment_date", "last_payment_date"), ("amount", "last_payment_amount"), ("payment_status", "payment_status"), ("status", "status"), ("created_at", "last_payment_created_at")):
            if candidate in columns:
                selected.append(f"MAX({alias}.{candidate}) AS {output}")
        return selected

    if table == "orders":
        for candidate, output in (("invoice_date", "last_invoice_date"), ("due_date", "last_due_date"), ("order_total", "last_order_total"), ("payment_status", "payment_status"), ("status", "status"), ("created_at", "last_order_created_at")):
            if candidate in columns:
                selected.append(f"MAX({alias}.{candidate}) AS {output}")
        return selected

    if table == "customer_subscriptions":
        for candidate, output in (("expiry_date", "subscription_expiry_date"), ("start_date", "subscription_start_date"), ("status", "subscription_status"), ("payment_status", "payment_status"), ("plan_name", "plan_name"), ("plan", "plan"), ("created_at", "last_subscription_created_at")):
            if candidate in columns:
                selected.append(f"MAX({alias}.{candidate}) AS {output}")
        return selected

    if table == "complaints":
        for candidate, output in (("status", "complaint_status"), ("title", "complaint_title"), ("subject", "complaint_subject"), ("created_at", "last_complaint_created_at")):
            if candidate in columns:
                selected.append(f"MAX({alias}.{candidate}) AS {output}")
        return selected

    if table == "customers":
        for candidate, output in (("city", "customer_city"), ("status", "customer_status"), ("created_at", "last_customer_created_at")):
            if candidate in columns:
                selected.append(f"MAX({alias}.{candidate}) AS {output}")
        return selected

    return [f"MAX({alias}.id) AS {table}_id"] if "id" in columns else []


def _search_window_days(query: str) -> int:
    q = query.lower()
    if "this week" in q or "last week" in q:
        return 7
    if "this month" in q or "last month" in q:
        return 30
    return 30


def _filter_conditions(query: str, entities: dict, base_table: str, base_alias: str, related_tables: list[str], columns_map: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    q = query.lower()
    where_parts = []
    having_parts = []

    def choose_alias(table_name: str) -> str:
        return _table_alias(table_name)

    customer_alias = choose_alias("customers") if "customers" in columns_map else base_alias

    if entities.get("name") and (base_table == "customers" or "customers" in related_tables or table_has_column(base_table, "first_name") or table_has_column(base_table, "name")):
        name_value = entities["name"].replace("'", "''")
        customer_columns = [col for col in ("first_name", "last_name", "name", "customer_name") if col in columns_map.get("customers", [])]
        if customer_columns:
            name_conditions = [f"{customer_alias}.{col} LIKE '%{name_value}%'" for col in customer_columns]
            where_parts.append("(" + " OR ".join(name_conditions) + ")")

    if entities.get("city") and (base_table == "customers" or "customers" in related_tables or table_has_column(base_table, "city")):
        city_value = entities["city"].replace("'", "''")
        city_columns = [col for col in ("city", "location", "area") if col in columns_map.get("customers", [])]
        if not city_columns and table_has_column(base_table, "city"):
            city_columns = ["city"]
        if city_columns:
            where_parts.append(
                "(" + " OR ".join(f"{customer_alias}.{col} LIKE '%{city_value}%'" for col in city_columns) + ")"
            )

    status = _normalize_text(str(entities.get("status") or ""))
    if status:
        status_tables = []
        if status in {"paid", "unpaid", "pending", "failed"}:
            status_tables = [table for table in related_tables if table in ("payments", "orders", "customer_subscriptions")]
            if base_table in ("payments", "orders", "customer_subscriptions"):
                status_tables.insert(0, base_table)
        else:
            status_tables = [table for table in ([base_table] + related_tables) if table_has_column(table, "status")]

        for table_name in dict.fromkeys(status_tables):
            alias = choose_alias(table_name)
            status_column = "payment_status" if table_name in ("payments", "orders", "customer_subscriptions") and table_has_column(table_name, "payment_status") else "status"
            if status == "unpaid":
                if table_name == "orders" and table_has_column(table_name, "payment_status"):
                    where_parts.append(f"{alias}.payment_status IN ('pending', 'partially paid', 'unpaid')")
                elif table_name == "payments":
                    where_parts.append(f"{alias}.{status_column} IN ('pending', 'unpaid', 'failed')")
                else:
                    where_parts.append(f"{alias}.{status_column} != 'paid'")
            else:
                status_value = status.replace("'", "''")
                where_parts.append(f"{alias}.{status_column} = '{status_value}'")

    amount_match = re.search(r"\b(?:above|over|greater than|more than|>=?)\s*(\d+(?:\.\d+)?)", q)
    if amount_match:
        amount_value = amount_match.group(1)
        if base_table == "payments" and table_has_column(base_table, "amount"):
            where_parts.append(f"{base_alias}.amount >= {amount_value}")
        elif base_table == "orders" and table_has_column(base_table, "order_total"):
            where_parts.append(f"{base_alias}.order_total >= {amount_value}")
        elif "payments" in related_tables and table_has_column("payments", "amount"):
            where_parts.append(f"{choose_alias('payments')}.amount >= {amount_value}")
        elif "orders" in related_tables and table_has_column("orders", "order_total"):
            where_parts.append(f"{choose_alias('orders')}.order_total >= {amount_value}")

    recent = bool(entities.get("recent")) or any(word in q for word in ("recent", "recently", "latest", "newest", "this week", "last week", "this month", "last month"))
    if recent:
        window_days = _search_window_days(q)
        date_targets = []
        for table_name in [base_table] + related_tables:
            for candidate in TABLE_DATE_COLUMNS.get(table_name, []):
                if table_has_column(table_name, candidate):
                    date_targets.append((table_name, candidate))
                    break
        if date_targets:
            table_name, candidate = date_targets[0]
            alias = choose_alias(table_name)
            if table_name == "customer_subscriptions" and candidate == "expiry_date" and ("expire" in q or "expires" in q):
                having_parts.append(f"MAX({alias}.{candidate}) <= DATE_ADD(NOW(), INTERVAL {window_days} DAY)")
            else:
                having_parts.append(f"MAX({alias}.{candidate}) >= DATE_SUB(NOW(), INTERVAL {window_days} DAY)")

    if "hasn't paid" in q or "has not paid" in q or "didn't pay" in q or "unpaid" in q:
        if "payments" in related_tables or base_table == "payments":
            alias = choose_alias("payments")
            if table_has_column("payments", "payment_date"):
                having_parts.append(
                    f"(MAX({alias}.payment_date) IS NULL OR MAX({alias}.payment_date) < DATE_SUB(NOW(), INTERVAL 30 DAY))"
                )
            if table_has_column("payments", "payment_status"):
                where_parts.append(f"{alias}.payment_status IN ('pending', 'unpaid', 'failed', 'partially paid')")

    return where_parts, having_parts


def smart_search_sql(user_query: str, company_id: int | None = None) -> str | None:
    columns_map = get_table_columns_map()
    if not columns_map:
        return None

    entities = extract_entities(user_query)
    base_table = _choose_base_table(user_query, entities, columns_map)
    related_tables = _resolve_related_tables(base_table, user_query, entities, columns_map)

    base_alias = _table_alias(base_table)
    select_parts = _select_columns(base_table, base_alias, columns_map)
    join_parts = []
    where_parts = []
    having_parts = []
    group_by_parts = []

    for column in columns_map.get(base_table, []):
        if column in TABLE_DISPLAY_COLUMNS.get(base_table, []):
            group_by_parts.append(f"{base_alias}.{column}")

    for table_name in related_tables:
        alias = _table_alias(table_name)
        join_condition = _join_condition(base_table, table_name, columns_map)
        if not join_condition:
            continue
        join_parts.append(f"LEFT JOIN {table_name} {alias} ON {join_condition}")
        select_parts.extend(_summary_columns(table_name, alias, columns_map))

        if table_name in ("payments", "orders", "customer_subscriptions", "complaints"):
            group_by_parts.append(f"{base_alias}.id")

    filter_where_parts, filter_having_parts = _filter_conditions(
        user_query,
        entities,
        base_table,
        base_alias,
        related_tables,
        columns_map,
    )
    where_parts.extend(filter_where_parts)
    having_parts.extend(filter_having_parts)

    if company_id:
        for table_name in [base_table] + related_tables:
            if table_has_column(table_name, "company_id"):
                alias = _table_alias(table_name)
                where_parts.append(f"{alias}.company_id = {int(company_id)}")

    for table_name in [base_table] + related_tables:
        if table_has_column(table_name, "deleted_at"):
            alias = _table_alias(table_name)
            where_parts.append(f"{alias}.deleted_at IS NULL")

    where_parts = list(dict.fromkeys(where_parts))
    having_parts = list(dict.fromkeys(having_parts))
    group_by_parts = list(dict.fromkeys(group_by_parts))

    sql = [
        f"SELECT {', '.join(select_parts)}",
        f"FROM {base_table} {base_alias}",
    ]
    sql.extend(join_parts)

    if where_parts:
        sql.append("WHERE " + " AND ".join(where_parts))

    if group_by_parts and any(part.startswith("MAX(") for part in select_parts):
        sql.append("GROUP BY " + ", ".join(group_by_parts))

    if having_parts:
        sql.append("HAVING " + " AND ".join(having_parts))

    sql.append("ORDER BY " + f"{base_alias}.id DESC")
    sql.append("LIMIT 50")

    return "\n".join(sql).strip() + ";"