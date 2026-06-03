import re
import mysql.connector
import time

from config import (
    DB_HOST,
    DB_PORT,
    DB_USER,
    DB_PASSWORD,
    DB_NAME
)


# ---------------------------------------------------
# CACHING
# ---------------------------------------------------

_SCHEMA_CACHE = None
_SCHEMA_CACHE_TIME = 0
_COLUMNS_CACHE = None
_COLUMNS_CACHE_TIME = 0
_CACHE_TTL = 3600  # 1 hour

_BUSINESS_CONTEXT_CACHE = None
_BUSINESS_CONTEXT_CACHE_TIME = 0

_COMPANIES_LIST_CACHE = None
_COMPANIES_LIST_CACHE_TIME = 0

# ---------------------------------------------------
# DATABASE CONNECTION
# ---------------------------------------------------

def get_connection():
    """Get database connection - simpler approach without pooling"""
    return mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        connection_timeout=10,
        autocommit=True
    )


# ---------------------------------------------------
# GET DATABASE SCHEMA (WITH CACHE)
# ---------------------------------------------------

def get_table_schema():
    global _SCHEMA_CACHE, _SCHEMA_CACHE_TIME

    current_time = time.time()

    if _SCHEMA_CACHE is not None and (current_time - _SCHEMA_CACHE_TIME) < _CACHE_TTL:
        return _SCHEMA_CACHE

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SHOW TABLES")
    tables = [row[0] for row in cursor.fetchall()]

    schema_text = ""

    for table in tables:
        cursor.execute(f"DESCRIBE {table}")
        columns = cursor.fetchall()
        schema_text += f"\nTABLE: {table}\n"
        for col in columns:
            schema_text += f"- {col[0]} ({col[1]})\n"

    cursor.close()
    conn.close()

    _SCHEMA_CACHE = schema_text
    _SCHEMA_CACHE_TIME = current_time

    return schema_text


def get_table_columns_map():
    """Return {table_name: [column_names]} from live schema."""
    global _COLUMNS_CACHE, _COLUMNS_CACHE_TIME

    current_time = time.time()

    if _COLUMNS_CACHE is not None and (current_time - _COLUMNS_CACHE_TIME) < _CACHE_TTL:
        return _COLUMNS_CACHE

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SHOW TABLES")
    tables = [row[0] for row in cursor.fetchall()]

    columns_map = {}

    for table in tables:
        cursor.execute(f"DESCRIBE {table}")
        columns_map[table] = [col[0] for col in cursor.fetchall()]

    cursor.close()
    conn.close()

    _COLUMNS_CACHE = columns_map
    _COLUMNS_CACHE_TIME = current_time

    return columns_map


def table_has_column(table: str, column: str) -> bool:
    columns_map = get_table_columns_map()
    return column in columns_map.get(table, [])


# ---------------------------------------------------
# COMPANIES
# ---------------------------------------------------

def get_companies():
    """Return active companies for the login selector."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, name
        FROM companies
        WHERE status = 'active'
          AND deleted_at IS NULL
        ORDER BY name
    """)

    companies = [{"id": row[0], "name": row[1]} for row in cursor.fetchall()]

    cursor.close()
    conn.close()

    return companies


def get_company_name(company_id: int) -> str:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM companies WHERE id = %s AND deleted_at IS NULL",
        (company_id,)
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row[0] if row else "Unknown"


def _get_companies_list_cached():
    global _COMPANIES_LIST_CACHE, _COMPANIES_LIST_CACHE_TIME
    current_time = time.time()
    if (
        _COMPANIES_LIST_CACHE is not None
        and (current_time - _COMPANIES_LIST_CACHE_TIME) < _CACHE_TTL
    ):
        return _COMPANIES_LIST_CACHE
    _COMPANIES_LIST_CACHE = get_companies()
    _COMPANIES_LIST_CACHE_TIME = current_time
    return _COMPANIES_LIST_CACHE


def find_company_in_query(user_query: str) -> dict | None:
    """Match a company name or id mentioned in the user's query."""
    q = user_query.lower()

    id_match = re.search(
        r"\bcompany(?:\s+id)?\s*[=:#]?\s*(\d+)\b", q, re.IGNORECASE
    )
    if id_match:
        cid = int(id_match.group(1))
        name = get_company_name(cid)
        if name != "Unknown":
            return {"id": cid, "name": name}

    companies = _get_companies_list_cached()
    for company in sorted(companies, key=lambda c: len(c["name"]), reverse=True):
        name_lower = company["name"].lower().strip()
        if len(name_lower) < 3:
            continue
        if name_lower in q:
            return company

    for company in companies:
        name_lower = company["name"].lower().strip()
        words = [w for w in re.split(r"\W+", name_lower) if len(w) >= 4]
        if len(words) >= 2 and all(w in q for w in words[:2]):
            return company

    return None


def resolve_query_company_scope(user_query: str, user: dict) -> tuple[int | None, str]:
    """
    Determine company filter for a query.
    Regular users: always their company.
    Admin: all companies unless a specific company is named in the query.
    """
    is_admin = user.get("role") == "admin"
    if not is_admin:
        return user["company_id"], user["company_name"]

    q = user_query.lower().strip()
    all_companies_phrases = (
        "all companies", "every company", "each company",
        "show companies", "list companies", "all lcos",
    )
    if any(p in q for p in all_companies_phrases):
        return None, "all companies"

    detected = find_company_in_query(user_query)
    if detected:
        return detected["id"], detected["name"]

    return None, "all companies"


# ---------------------------------------------------
# COMPANY FILTER INJECTION
# ---------------------------------------------------

def append_sql_condition(sql: str, condition: str) -> str:
    """Append a WHERE/AND condition before ORDER BY, GROUP BY, LIMIT, etc."""
    sql = sql.strip().rstrip(";")
    upper = sql.upper()

    insert_keywords = [" ORDER BY ", " GROUP BY ", " LIMIT ", " HAVING "]
    insert_pos = len(sql)

    for kw in insert_keywords:
        idx = upper.find(kw)
        if idx != -1 and idx < insert_pos:
            insert_pos = idx

    base = sql[:insert_pos].rstrip()
    tail = sql[insert_pos:]

    if re.search(r"\bWHERE\b", base, re.IGNORECASE):
        return f"{base} AND {condition}{tail}"

    return f"{base} WHERE {condition}{tail}"


def inject_company_filter(sql: str, company_id: int, table: str) -> str:
    """Scope query results to a single company."""
    if not company_id:
        return sql

    sql = sql.strip().rstrip(";") + ";"

    if table == "companies":
        condition = f"id = {int(company_id)}"
    elif table_has_column(table, "company_id"):
        condition = f"company_id = {int(company_id)}"
    else:
        return sql

    filtered = append_sql_condition(sql.rstrip(";"), condition)

    if (
        table_has_column(table, "deleted_at")
        and "deleted_at is null" not in filtered.lower()
    ):
        filtered = append_sql_condition(filtered, "deleted_at IS NULL")

    return filtered + ";"


# ---------------------------------------------------
# SQL VALIDATION
# ---------------------------------------------------

def validate_sql(sql: str):

    blocked = [
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "ALTER",
        "TRUNCATE",
        "CREATE",
        "REPLACE",
        "GRANT",
        "REVOKE"
    ]

    sql_upper = sql.upper()

    for word in blocked:
        pattern = r'\b' + word + r'\b'
        if re.search(pattern, sql_upper):
            raise ValueError(
                f"Blocked SQL keyword detected: {word}"
            )

    if not sql_upper.strip().startswith("SELECT"):
        raise ValueError(
            "Only SELECT queries are allowed."
        )


# ---------------------------------------------------
# EXECUTE QUERY
# ---------------------------------------------------

def run_query(sql: str) -> dict:

    sql_clean = sql.strip().rstrip(";")

    validate_sql(sql_clean)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(sql_clean)

    columns = [
        desc[0]
        for desc in cursor.description
    ]

    rows = [
        list(row)
        for row in cursor.fetchall()
    ]

    for row in rows:
        for i, val in enumerate(row):
            if val is None:
                row[i] = "NULL"
            elif not isinstance(val, (str, int, float, bool)):
                row[i] = str(val)

    cursor.close()
    conn.close()

    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows)
    }


# ---------------------------------------------------
# BUSINESS CONTEXT FOR AI (WITH CACHE)
# ---------------------------------------------------

def get_business_context():
    global _BUSINESS_CONTEXT_CACHE, _BUSINESS_CONTEXT_CACHE_TIME

    current_time = time.time()

    if _BUSINESS_CONTEXT_CACHE is not None and (current_time - _BUSINESS_CONTEXT_CACHE_TIME) < _CACHE_TTL:
        return _BUSINESS_CONTEXT_CACHE

    conn = get_connection()
    cursor = conn.cursor()

    context = []

    important_columns = {
        "customers": ["customer_type", "status", "city"],
        "payments": ["payment_status", "payment_method"],
        "orders": ["status", "payment_status"],
        "customer_subscriptions": ["status", "payment_status"],
    }

    for table, cols in important_columns.items():
        for col in cols:
            try:
                query = f"""
                SELECT DISTINCT {col}
                FROM {table}
                WHERE {col} IS NOT NULL
                LIMIT 20
                """
                cursor.execute(query)
                values = [
                    str(r[0])
                    for r in cursor.fetchall()
                    if r[0]
                ]
                if values:
                    context.append(f"{table}.{col} values = {values}")
            except Exception:
                pass

    cursor.close()
    conn.close()

    context.append(
        "orders amount column = order_total (NOT amount). "
        "payments amount column = amount."
    )

    result = "\n".join(context)

    _BUSINESS_CONTEXT_CACHE = result
    _BUSINESS_CONTEXT_CACHE_TIME = current_time

    return result
