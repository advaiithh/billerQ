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
_CACHE_TTL = 3600  # 1 hour

_BUSINESS_CONTEXT_CACHE = None
_BUSINESS_CONTEXT_CACHE_TIME = 0

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
    
    # Return cached schema if still valid
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

            column_name = col[0]
            column_type = col[1]

            schema_text += f"- {column_name} ({column_type})\n"

    cursor.close()
    conn.close()

    # Cache the schema
    _SCHEMA_CACHE = schema_text
    _SCHEMA_CACHE_TIME = current_time

    return schema_text


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

    # Block dangerous keywords - use word boundaries
    import re
    for word in blocked:
        # Match word as whole word only, not as substring
        pattern = r'\b' + word + r'\b'
        if re.search(pattern, sql_upper):
            raise ValueError(
                f"Blocked SQL keyword detected: {word}"
            )

    # Only SELECT allowed
    if not sql_upper.strip().startswith("SELECT"):

        raise ValueError(
            "Only SELECT queries are allowed."
        )


# ---------------------------------------------------
# EXECUTE QUERY
# ---------------------------------------------------

def run_query(sql: str) -> dict:

    sql_clean = sql.strip().rstrip(";")

    # Validate query
    validate_sql(sql_clean)

    

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute(sql_clean)

    # Column names
    columns = [
        desc[0]
        for desc in cursor.description
    ]

    # Rows
    rows = [
        list(row)
        for row in cursor.fetchall()
    ]

    # Convert non-serializable values
    for row in rows:

        for i, val in enumerate(row):

            if val is None:

                row[i] = "NULL"

            elif not isinstance(
                val,
                (str, int, float, bool)
            ):

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
    
    # Return cached context if still valid
    if _BUSINESS_CONTEXT_CACHE is not None and (current_time - _BUSINESS_CONTEXT_CACHE_TIME) < _CACHE_TTL:
        return _BUSINESS_CONTEXT_CACHE

    conn = get_connection()

    cursor = conn.cursor()

    context = []

    important_columns = {

        "customers": [
            "customer_type",
            "status",
            "city"
        ],

        "payments": [
            "payment_status",
            "payment_method"
        ],

        "orders": [
            "status"
        ],

        "customer_subscriptions": [
            "status"
        ]
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

                    context.append(
                        f"{table}.{col} values = {values}"
                    )

            except Exception:

                pass

    cursor.close()

    conn.close()

    result = "\n".join(context)
    
    # Cache the context
    _BUSINESS_CONTEXT_CACHE = result
    _BUSINESS_CONTEXT_CACHE_TIME = current_time

    return result