import re
import json
import requests
from memory import memory
from config import OLLAMA_MODEL


# Table name mappings for intelligent query generation
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

# Common column names for different tables
COLUMN_MAPPINGS = {
    "companies": {
        "id": "id",
        "name": "name",
        "status": "status",
        "created": "created_at",
        "created_at": "created_at",
    },
    "customers": {
        "id": "id",
        "name": "first_name",  # Default to first_name
        "status": "status",
        "type": "customer_type",
        "created": "created_at",
        "created_at": "created_at",
    },
    "payments": {
        "id": "id",
        "amount": "amount",
        "status": "payment_status",
        "method": "payment_method",
        "created": "created_at",
        "created_at": "created_at",
    },
    "orders": {
        "id": "id",
        "amount": "amount",
        "status": "status",
        "date": "invoice_date",
        "invoice_date": "invoice_date",
        "created": "invoice_date",
    }
}


def _find_best_table(user_query: str) -> str:
    """Find the most likely table based on user query keywords"""
    user_lower = user_query.lower()
    
    # Check for exact table name matches first
    for keyword, table in TABLE_MAPPINGS.items():
        if keyword in user_lower:
            return table
    
    # Fallback to customers
    return "customers"


def _build_sql_from_query(user_query: str, table: str) -> str:
    """Build SQL based on query patterns"""
    user_lower = user_query.lower()
    
    # Determine what kind of query this is
    if "count" in user_lower or "how many" in user_lower or "total" in user_lower:
        # COUNT query
        return f"SELECT COUNT(*) AS total FROM {table};"
        
    elif "top" in user_lower or "best" in user_lower or "highest" in user_lower:
        # TOP N query
        if "amount" in user_lower or "revenue" in user_lower or "sales" in user_lower:
            return f"SELECT * FROM {table} ORDER BY amount DESC;"
        elif "payment" in table or "order" in table:
            return f"SELECT * FROM {table} ORDER BY amount DESC;"
        else:
            return f"SELECT * FROM {table} ORDER BY created_at DESC;"
            
    elif "latest" in user_lower or "recent" in user_lower or "new" in user_lower:
        # Latest/recent query
        date_col = "invoice_date" if table == "orders" else "created_at"
        return f"SELECT * FROM {table} ORDER BY {date_col} DESC;"
        
    elif any(k in user_lower for k in ("inactive", "pending", "unpaid", "active")):
        # Status-based query — check for specific words using word boundaries
        if re.search(r"\binactive\b", user_lower):
            status_col = "status" if table in ["orders", "companies"] else ("payment_status" if table == "payments" else "status")
            return f"SELECT * FROM {table} WHERE {status_col} = 'inactive';"
        if re.search(r"\bactive\b", user_lower):
            status_col = "status" if table in ["orders", "companies"] else ("payment_status" if table == "payments" else "status")
            return f"SELECT * FROM {table} WHERE {status_col} = 'active';"
        if re.search(r"\bpending\b", user_lower):
            status_col = "payment_status" if table == "payments" else "status"
            return f"SELECT * FROM {table} WHERE {status_col} = 'pending';"
        if re.search(r"\bunpaid\b", user_lower):
            return f"SELECT * FROM {table} WHERE payment_status = 'unpaid';"
    
    # Default: show all
    return f"SELECT * FROM {table};"


# ---------------------------------------------------
# NATURAL LANGUAGE TO SQL
# ---------------------------------------------------

def natural_language_to_sql(user_query: str) -> dict:
    """Convert natural language to SQL using intelligent table detection"""
    
    # Find the best matching table
    table = _find_best_table(user_query)
    
    # Build SQL based on the query pattern
    sql = _build_sql_from_query(user_query, table)
    
    # Save to memory
    try:
        memory.save_context({"input": user_query}, {"output": sql})
    except:
        pass
    
    return {
        "sql": sql.strip(),
        "explanation": f"Generated SQL for: {user_query}"
    }


# ---------------------------------------------------
# GENERATE RESPONSE
# ---------------------------------------------------

def generate_full_response(user_query: str, columns: list, rows: list) -> dict:
    """Generate summary of results"""
    
    if not rows:
        return {
            "summary": "No records found.",
            "insights": []
        }
    
    summary = f"Found {len(rows)} record(s)."
    insights = []
    
    if "customer" in user_query.lower():
        insights.append(f"{len(rows)} customers")
    elif "payment" in user_query.lower():
        insights.append(f"{len(rows)} payments")
    elif "order" in user_query.lower() or "invoice" in user_query.lower():
        insights.append(f"{len(rows)} orders/invoices")
    
    return {
        "summary": summary,
        "insights": insights
    }
