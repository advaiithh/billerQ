import re
import json
import requests
from memory import memory
from config import OLLAMA_URL, OLLAMA_MODEL
from database import get_table_schema
from database import (
    get_table_schema,
    get_business_context
)


# ---------------------------------------------------
# CALL QWEN MODEL
# ---------------------------------------------------

def _call_qwen(prompt: str, timeout: int = 120) -> str:

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0,
            "top_p": 0.9,
            "num_predict": 512
        }
    }

    response = requests.post(
        OLLAMA_URL,
        json=payload,
        timeout=timeout
    )

    # FIX 5 — better timeout/error handling
    try:
        response.raise_for_status()
    except Exception as e:
        raise Exception(f"Ollama/Qwen request failed: {str(e)}")

    return response.json()["response"].strip()


# ---------------------------------------------------
# EXTRACT SQL FROM MODEL RESPONSE
# ---------------------------------------------------

def _extract_sql(text: str) -> str:

    # Extract markdown SQL block
    match = re.search(
        r"```(?:sql)?\s*(SELECT[\s\S]+?)```",
        text,
        re.IGNORECASE
    )

    if match:
        return match.group(1).strip()

    # Extract plain SELECT query
    match = re.search(
        r"(SELECT[\s\S]+?;)",
        text,
        re.IGNORECASE
    )

    if match:
        return match.group(1).strip()

    return text.strip()


# ---------------------------------------------------
# NATURAL LANGUAGE TO SQL
# ---------------------------------------------------

def natural_language_to_sql(user_query: str) -> dict:

    schema = get_table_schema()

    
    business_context = get_business_context()
    
    chat_history = memory.load_memory_variables({})

    history_text = str(
        chat_history.get("history", "")
    )
    print("\n===== MEMORY =====")
    print(history_text)
    print("==================\n")
    prompt = f"""You are an expert MySQL query generator for BillerQ.

DATABASE SCHEMA:
{schema}
ACTUAL DATABASE VALUES:
{business_context}
IMPORTANT DATE COLUMNS:
- payments table uses created_at
- orders table uses invoice_date
- customers table uses created_at

BUSINESS DEFINITIONS:

- Top customers = customers with highest total payment amount
- Revenue = SUM(payments.amount)
- Latest payments = ORDER BY payments.created_at DESC
- Active customers = customers where status='active'
- Premium customers = customers where customer_type='premium'
- Top orders = orders sorted by amount descending
- Pending invoices = invoices with payment_status='pending'
IMPORTANT COLUMN MEANINGS:

- payment amount column = amount
- order amount column = amount
- customer name columns = first_name, last_name
- customer identifier = id


STRICT RULES:
1. ONLY generate valid MySQL SELECT queries
2. NEVER generate INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE
3. Add LIMIT only when user asks for top/latest/few/sample data
4. Use JOINs if needed
5. Use only existing tables and columns
6. Use COUNT(*) for counting questions
7. Use ORDER BY for latest or recent queries
8. Use LIKE for partial matching
9. Use LOWER() for text comparisons
10. Return ONLY the SQL query, no explanations, no markdown except SQL block
11. If user asks "all", never use LIMIT
12. Use actual database values from context
13. Never invent status values
14. Never invent customer types
15. If unsure, use LIKE queries

EXAMPLES:

User: show all customers
SQL:
```sql
SELECT * FROM customers ;
```

User: show premium customers
SQL:
```sql
SELECT * FROM customers WHERE customer_type = 'premium' ;
```
User: top 5 customers by payments

SQL:
SELECT customers.first_name,
       SUM(payments.amount) AS total_amount
FROM customers
JOIN payments
ON customers.id = payments.customer_id
GROUP BY customers.id
ORDER BY total_amount DESC
LIMIT 5;
User: customers with pending payments

SQL:
SELECT customers.first_name,
       payments.amount,
       payments.payment_status
FROM customers
JOIN payments
ON customers.id = payments.customer_id
WHERE LOWER(payment_status) LIKE '%pending%'
User: latest invoices

SQL:
SELECT *
FROM orders
ORDER BY invoice_date DESC

User: latest invoices

SQL:
SELECT *
FROM orders
ORDER BY invoice_date DESC

User: top 5 orders by amount

SQL:
SELECT *
FROM orders
ORDER BY amount DESC
LIMIT 5;

User: show latest payments
SQL:
```sql
SELECT * FROM payments ORDER BY created_at DESC ;
```

User: customers from kochi
SQL:
```sql
SELECT * FROM customers WHERE LOWER(city) = 'kochi' ;
```

User: how many customers
SQL:
```sql
SELECT COUNT(*) AS total_customers FROM customers;
```
CONVERSATION HISTORY:
{history_text}

USER REQUEST: {user_query}

SQL:
"""

    raw = _call_qwen(prompt)

    sql = _extract_sql(raw)

    sql_clean = sql.strip()

    # FIX 1 — blocked keyword validation
    # safer SQL handling
    # ---------------------------------------------------
# SAFE SQL VALIDATION
# ---------------------------------------------------

    blocked = [
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "ALTER",
        "TRUNCATE",
        "CREATE",
        "REPLACE"
    ]

    sql_upper = sql_clean.upper()

    dangerous = False

    for word in blocked:

        pattern = r"\\b" + word + r"\\b"

        if re.search(pattern, sql_upper):

            dangerous = True
            break

    # AUTO FIX invalid SQL
    if (
        not sql_clean.lower().startswith("select")
        or dangerous
    ):

        print("\n⚠ BAD SQL GENERATED:")
        print(sql_clean)

        fixed_sql = fix_sql_query(
            user_query=user_query,
            failed_sql=sql_clean,
            db_error="Invalid or dangerous SQL",
            schema=schema
        )

        sql_clean = fixed_sql.strip()

    # FINAL FALLBACK
    if not sql_clean.lower().startswith("select"):

        user_lower = user_query.lower()

        if "customer" in user_lower:

            sql_clean = """
            SELECT *
            FROM customers;
            """

        elif "payment" in user_lower:

            sql_clean = """
            SELECT *
            FROM payments;
            """

        elif "invoice" in user_lower:

            sql_clean = """
            SELECT *
            FROM orders;
            """

        elif "subscription" in user_lower:

            sql_clean = """
            SELECT *
            FROM customer_subscriptions;
            """

        else:

            sql_clean = """
            SELECT * FROM customers;
            """

    # Ensure semicolon
    if not sql_clean.endswith(";"):
        sql_clean += ";"

    # FIX 2 — auto add LIMIT if model forgot it
    # Add LIMIT only for top/latest/few queries

    limit_keywords = [
        "top",
        "latest",
        "recent",
        "few",
        "sample"
    ]

    user_lower = user_query.lower()

    needs_limit = any(
        word in user_lower
        for word in limit_keywords
    )

    if needs_limit and "LIMIT" not in sql_upper:

        sql_clean = sql_clean.rstrip(";")

        sql_clean += " LIMIT 20;"
    memory.save_context(
    {"input": user_query},
    {"output": sql_clean}
    )
    return {
        "sql": sql_clean,
        "explanation": f"Generated SQL for: {user_query}"
    }


# ---------------------------------------------------
# AUTO FIX FAILED SQL
# ---------------------------------------------------

def fix_sql_query(
    user_query: str,
    failed_sql: str,
    db_error: str,
    schema: str
) -> str:

    prompt = f"""
You are an expert MySQL SQL fixer.

USER REQUEST:
{user_query}

FAILED SQL:
{failed_sql}

MYSQL ERROR:
{db_error}

DATABASE SCHEMA:
{schema}

TASK:
Fix the SQL query.

IMPORTANT RULES:
1. Use ONLY existing tables
2. Use ONLY existing columns
3. NEVER invent columns
4. NEVER invent aliases
5. If column does not exist, replace it with nearest matching column
6. Customers table may contain:
   - first_name
   - last_name
   - billing_name
   - name
7. Payments table amount column is usually:
   - amount
8. Date columns are usually:
   - created_at
   - invoice_date
9. Return ONLY valid SELECT SQL
10. Never return CREATE, UPDATE, DELETE, DROP
11. If query asks recent/latest use ORDER BY created_at DESC

OUTPUT ONLY SQL.
"""

    raw = _call_qwen(prompt)

    fixed_sql = _extract_sql(raw)

    return fixed_sql.strip()


# ---------------------------------------------------
# GENERATE BUSINESS SUMMARY + INSIGHTS
# ---------------------------------------------------

def generate_full_response(
    user_query: str,
    columns: list,
    rows: list
) -> dict:

    if not rows:
        return {
            "summary": "No records found.",
            "insights": []
        }

    sample = rows[:10]

    table_text = " | ".join(columns) + "\n"
    table_text += "\n".join(
        " | ".join(str(v) for v in row)
        for row in sample
    )

    if len(rows) > 10:
        table_text += f"\n... and {len(rows) - 10} more rows"

    prompt = f"""You are a business analyst for BillerQ.

USER QUESTION: {user_query}

DATABASE RESULTS:
{table_text}

Respond ONLY in valid JSON with this exact structure:
{{
    "summary": "short plain English business summary",
    "insights": [
        "insight 1",
        "insight 2",
        "insight 3"
    ]
}}

RULES:
- Summary should be simple and clear
- Insights should be business-oriented observations
- Mention totals or counts if visible in data
- Mention overdue or pending items if visible
- Return ONLY the JSON, nothing else
"""

    try:

        raw = _call_qwen(prompt)

        match = re.search(r"\{[\s\S]+\}", raw)

        if match:

            # FIX 4 — clean JSON before parsing
            json_text = match.group().strip()
            json_text = json_text.replace("\n", " ")

            parsed = json.loads(json_text)

            return {
                "summary": parsed.get("summary", ""),
                "insights": parsed.get("insights", [])
            }

    except Exception as e:
        print("Error parsing AI response:", e)

    # Fallback
    return {
        "summary": f"Found {len(rows)} matching records.",
        "insights": []
    }