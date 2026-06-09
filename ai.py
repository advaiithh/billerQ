import re
import json
import requests
from memory import memory, get_conversation_context
from config import OLLAMA_MODEL, OLLAMA_URL, OLLAMA_TIMEOUT_SEC
from response_cache import get_cached_sql, set_cached_sql
from smart_search import is_search_query, smart_search_sql
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

CHIP_PHRASES = {
    "show all customers",
    "inactive customers",
    "recent payments",
    "latest invoices",
    "active subscriptions",
    "inactive subscriptions",
    "overdue invoices",
    "top 5 orders by amount",
}

BLOCKED_MESSAGES = {
    "INSERT": (
        "This assistant is **read-only** — it cannot add or create records in the database. "
        "Operations like INSERT / CREATE are blocked for safety. "
        "To add a customer (e.g. the name you mentioned), use your main BillerQ admin panel or CRM, "
        "not this chat."
    ),
    "UPDATE": (
        "This assistant is **read-only** — it cannot update or edit existing records. "
        "Operations like UPDATE are blocked. Use your BillerQ admin application to change data."
    ),
    "DELETE": (
        "This assistant is **read-only** — it cannot delete or remove records. "
        "Operations like DELETE are blocked. Use your BillerQ admin application instead."
    ),
    "DDL": (
        "This assistant cannot change database structure (CREATE TABLE, ALTER, DROP, etc.). "
        "Only read queries (SELECT) are allowed."
    ),
    "OTHER": (
        "I can only **look up** billing data (customers, invoices, payments, subscriptions) — "
        "not general chat. Try **\"Show all customers\"**, **\"Overdue invoices\"**, "
        "or tap a quick-action button below."
    ),
}

# Exact phrases that are greetings / chat — never run SQL
_CONVERSATIONAL_EXACT = {
    "hi", "hii", "hiii", "hey", "heya", "hello", "hallo", "howdy", "yo",
    "hi there", "hey there", "hello there",
    "good morning", "good afternoon", "good evening", "good night",
    "thanks", "thank you", "thx", "ty", "ok", "okay", "k", "cool",
    "bye", "goodbye", "see you", "see ya",
    "help", "help me", "?", "what", "why", "how",
    "what can you do", "what do you do", "who are you",
    "how are you", "how r u", "sup", "wassup", "what's up", "whats up",
}

_DATA_SIGNAL_WORDS = (
    "customer", "subscriber", "invoice", "order", "payment", "subscription",
    "company", "lco", "complaint", "package", "vendor", "overdue", "unpaid",
    "paid", "pending", "active", "inactive", "terminated", "expired",
    "show", "list", "get", "find", "display", "fetch", "search", "count",
    "how many", "total", "top", "recent", "latest", "sum", "average",
    "revenue", "dues", "balance", "amount", "report", "between", "last",
    "this month", "today", "yesterday",
)


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
            # Include ALL non-active statuses: inactive, suspended, archive, blocked, etc.
            return with_base([f"{status_col} != 'active'"])
        if table == "customer_subscriptions":
            return with_base([f"{status_col} IN ('inactive', 'terminated', 'expired', 'pending')"])
        if table == "companies":
            return with_base([f"{status_col} != 'active'"])
        return with_base([f"{status_col} != 'active'"])

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
    # NOTE: "active" filter is ONLY applied when user explicitly asks for active,
    # NOT when they say "show all" — that should return everything.
    if _has_word(user_lower, "active") and not any(
        phrase in user_lower for phrase in ("show all", "all customers", "all subscribers")
    ):
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


def _mentions_data(q: str) -> bool:
    """True if the message is plausibly asking about billing data."""
    if any(kw in q for kw in _DATA_SIGNAL_WORDS):
        return True
    if re.search(r"\b(top|last)\s+\d+\b", q):
        return True
    return False


def _is_conversational(user_query: str) -> bool:
    """Greetings, thanks, or vague chat — not a database question."""
    q = user_query.lower().strip()
    q_clean = re.sub(r"[^\w\s']", "", q).strip()

    if q_clean in _CONVERSATIONAL_EXACT:
        return True

    words = q_clean.split()
    if len(words) <= 2:
        if words and words[0] in (
            "hi", "hey", "hello", "thanks", "thank", "bye", "help", "ok", "okay",
        ):
            return True
        if q_clean in ("thank you", "good morning", "good afternoon"):
            return True

    if len(words) <= 4 and not _mentions_data(q):
        if re.match(
            r"^(hi|hey|hello|thanks|thank you|good morning|good afternoon|"
            r"good evening|bye|help|ok|okay)\b",
            q_clean,
        ):
            return True

    if len(words) <= 6 and not _mentions_data(q):
        if re.search(
            r"\b(what can you do|who are you|how are you|what do you do|"
            r"help me|i need help)\b",
            q,
        ):
            return True

    return False


def conversational_reply(user_query: str) -> str:
    q = user_query.lower().strip()
    if re.match(r"^(hi|hey|hello|howdy|good morning|good afternoon|good evening)\b", q):
        return (
            "Hi! I'm the **BillerQ assistant**. I help you **view** your company's "
            "customers, invoices, payments, and subscriptions — I don't handle "
            "general chat or database changes.\n\n"
            "Try asking: **\"Show all customers\"**, **\"Overdue invoices\"**, "
            "or use the **quick buttons** below."
        )
    if re.search(r"\b(thanks|thank you|thx)\b", q):
        return "You're welcome! Ask anytime you need billing data from your company."
    if re.search(r"\b(bye|goodbye)\b", q):
        return "Goodbye! Come back when you need to look up billing data."
    if re.search(r"\b(help|what can you)\b", q):
        return BLOCKED_MESSAGES["OTHER"]
    return BLOCKED_MESSAGES["OTHER"]


def _is_read_query(q: str) -> bool:
    """True when the user is clearly asking to view/list/count data."""
    read_patterns = [
        r"^(show|list|get|find|display|fetch|search|tell me|give me)\b",
        r"^what\b",
        r"^which\b",
        r"^how many\b",
        r"^count\b",
        r"^who\b",
        r"^when\b",
        r"\bshow (all|me|the|my)\b",
        r"\blist (all|the|my)\b",
        r"\bhow many\b",
        r"\bnumber of\b",
        r"\btotal (number|count)\b",
    ]
    return any(re.search(p, q) for p in read_patterns)


def _classify_intent_rules(user_query: str) -> str:
    """
    Classify intent using rules. Returns SELECT, INSERT, UPDATE, DELETE, DDL, or OTHER.
    """
    q = user_query.lower().strip()
    if not q:
        return "OTHER"

    if _is_conversational(user_query):
        return "OTHER"

    if q in CHIP_PHRASES:
        return "SELECT"

    if re.search(
        r"\b(create|alter|drop|truncate)\s+(table|database|index)\b", q
    ) or re.search(r"\b(drop|truncate)\s+(table|database)\b", q):
        return "DDL"

    # Write operations — check before generic SELECT heuristics
    if re.search(
        r"\b(insert|create|register|enroll)\b", q
    ) and not re.search(r"\b(sign\s*up\s+for|registered)\b", q):
        return "INSERT"

    if re.search(
        r"\badd\s+("
        r"a|an|one|the|new|\d+|more\b|another\b|\w+\s+more\b"
        r")",
        q,
    ) or re.search(
        r"\badd\s+\w+\s+"
        r"(customer|subscriber|invoice|payment|order|subscription|user|record)\b",
        q,
    ) or re.search(
        r"\badd\s+(customer|subscriber|invoice|payment|order|subscription)\b", q
    ) or (
        re.search(r"\badd\b", q)
        and re.search(r"\b(named|called)\s+\w+", q)
        and re.search(r"\b(customer|subscriber|user)\b", q)
    ):
        return "INSERT"

    if _is_read_query(q):
        if re.search(r"\bhow to (add|create|insert|update|delete|remove)\b", q):
            return "OTHER"
        return "SELECT"

    if re.search(
        r"\b(update|edit|change|modify|rename|mark|set)\b", q
    ) and not re.search(r"\b(asset|setting)s?\b", q):
        if re.search(r"\b(set|mark)\s+(as|to)\b", q) or re.search(
            r"\b(update|edit|change|modify|rename)\b", q
        ):
            return "UPDATE"

    if re.search(r"\b(delete|remove|erase|cancel)\b", q) and not re.search(
        r"\b(remove|cancel)\s+(filter|sort)\b", q
    ):
        return "DELETE"

    if _mentions_data(q):
        return "SELECT"

    return "OTHER"


def _try_ollama_intent(user_query: str) -> str | None:
    """Ask Qwen to classify intent before generating SQL. Cached in memory."""
    # Intent classification is fast but we still cache it to skip Ollama for repeats
    cached = get_cached_sql("__intent__" + user_query, None)
    if cached:
        return cached
    prompt = f"""You classify user messages for a read-only billing database chatbot.

Reply with ONLY one word — no punctuation, no explanation:
SELECT   = user wants to VIEW, LIST, COUNT, SEARCH, or REPORT existing data
INSERT   = user wants to ADD, CREATE, or REGISTER new data
UPDATE   = user wants to CHANGE or EDIT existing data
DELETE   = user wants to DELETE or REMOVE data
DDL      = user wants to change database structure
OTHER    = general help, unclear, or not a data request

Examples:
- "show inactive customers" -> SELECT
- "add a customer named John" -> INSERT
- "update customer email" -> UPDATE
- "delete invoice 5" -> DELETE
- "hello" -> OTHER

User message:
{user_query}

Intent:"""

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0, "num_predict": 16},
            },
            timeout=OLLAMA_TIMEOUT_SEC,
        )
        response.raise_for_status()
        text = response.json().get("response", "").strip().upper()
        for intent in ("SELECT", "INSERT", "UPDATE", "DELETE", "DDL", "OTHER"):
            if intent in text.split():
                set_cached_sql("__intent__" + user_query, None, intent)
                return intent
        if text.startswith("SELECT"):
            set_cached_sql("__intent__" + user_query, None, "SELECT")
            return "SELECT"
        return None
    except Exception:
        return None


def classify_intent(user_query: str) -> dict:
    """
    Understand what the user wants before building SQL.
    Uses rules first; uses Ollama for longer/ambiguous messages.
    """
    rules_intent = _classify_intent_rules(user_query)
    q = user_query.lower().strip()
    word_count = len(q.split())

    if rules_intent != "SELECT":
        return {
            "intent": rules_intent,
            "source": "rules",
            "reason": f"Detected {rules_intent} request from keywords.",
        }

    # Short/vague messages: ask Qwen before defaulting to a data query
    use_ai = q not in CHIP_PHRASES and (
        not _mentions_data(q)
        or word_count > 5
        or re.search(r"\b(add|create|update|delete|remove|insert)\b", q)
    )

    if use_ai:
        ai_intent = _try_ollama_intent(user_query)
        if ai_intent:
            return {
                "intent": ai_intent,
                "source": "ai",
                "reason": f"Qwen classified this as {ai_intent}.",
            }

    if not _mentions_data(q):
        return {
            "intent": "OTHER",
            "source": "rules",
            "reason": "No billing data keywords — treated as conversation, not a query.",
        }

    return {
        "intent": "SELECT",
        "source": "rules",
        "reason": "Treated as a data lookup (SELECT).",
    }


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


def _try_ollama_sql(user_query: str, company_id: int, table: str, session_id: str | None = None) -> str | None:
    # ── Layer 2: SQL cache — skip Ollama entirely if we've seen this before ──
    cached_sql = get_cached_sql(user_query, company_id)
    if cached_sql:
        return cached_sql

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

        # Build conversation context block
        conv_context = ""
        if session_id:
            history = get_conversation_context(session_id, max_turns=4)
            if history:
                lines = []
                for turn in history:
                    lines.append(f"  User: {turn['user']}")
                    if turn.get("entity"):
                        lines.append(f"  (entity mentioned: {turn['entity']})")
                conv_context = "\nCONVERSATION HISTORY (for context resolution — pronouns like 'her/him/they' refer to the last entity):\n" + "\n".join(lines) + "\n"

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
- To get customer names: use first_name, last_name columns or CONCAT(first_name, ' ', last_name)
- Always SELECT name columns (first_name, last_name, name) when the user asks for names or people
{company_scope}
{conv_context}
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
            timeout=OLLAMA_TIMEOUT_SEC,
        )
        response.raise_for_status()
        result = response.json().get("response", "").strip()
        if not result:
            return None

        sql = _extract_sql_from_llm_response(result)
        if not sql.upper().startswith("SELECT"):
            return None
        # ── Store in SQL cache so the next identical question skips Ollama ──
        set_cached_sql(user_query, company_id, sql)
        return sql

    except Exception:
        return None


def _use_rules_only(user_query: str) -> bool:
    """Fast path only for trusted read-only chip prompts and clear list queries."""
    q = user_query.lower().strip()
    if q in CHIP_PHRASES:
        return True
    if _classify_intent_rules(user_query) != "SELECT":
        return False
    if not _mentions_data(q):
        return False
    if len(q.split()) <= 10 and _is_read_query(q):
        return True
    if len(q.split()) <= 8 and any(
        phrase in q
        for phrase in (
            "inactive",
            "active",
            "overdue",
            "recent",
            "latest",
            "top ",
            "pending",
            "unpaid",
            "paid",
            "show all",
            "count",
            "how many",
        )
    ):
        return True
    return False


def _build_names_sql(user_query: str, table: str) -> str:
    """Build a SELECT targeting name columns only — for 'show names only' queries."""
    cols = get_table_columns_map().get(table, [])
    name_parts = []
    if "first_name" in cols and "last_name" in cols:
        name_parts.append("TRIM(CONCAT(COALESCE(first_name,''), ' ', COALESCE(last_name,''))) AS full_name")
    elif "name" in cols:
        name_parts.append("name")
    elif "customer_name" in cols:
        name_parts.append("customer_name")
    elif "full_name" in cols:
        name_parts.append("full_name")

    if not name_parts:
        # fallback: generic sql
        return _build_sql_from_query(user_query, table)

    if "id" in cols:
        name_parts.insert(0, "id")

    soft_del = _soft_delete_clause(table)
    where = f" WHERE {soft_del}" if soft_del else ""
    status_col = _resolve_status_column(table)
    user_lower = user_query.lower()

    # Apply any status filter from the query
    conditions = [soft_del] if soft_del else []
    if _has_word(user_lower, "inactive") or _has_word(user_lower, "disabled"):
        conditions.append(f"{status_col} != 'active'")
    elif _has_word(user_lower, "active") and "inactive" not in user_lower:
        conditions.append(f"{status_col} = 'active'")

    sql = f"SELECT {', '.join(name_parts)} FROM {table}"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " LIMIT 100;"
    return sql


def natural_language_to_sql(user_query: str, company_id: int = None, session_id: str | None = None) -> dict:
    intent_info = classify_intent(user_query)
    intent = intent_info["intent"]

    if intent != "SELECT":
        if intent == "OTHER":
            message = conversational_reply(user_query)
        else:
            message = BLOCKED_MESSAGES.get(intent, BLOCKED_MESSAGES["OTHER"])
        return {
            "blocked": True,
            "conversational": intent == "OTHER",
            "intent": intent,
            "sql": None,
            "message": message,
            "explanation": intent_info["reason"],
            "table": _find_best_table(user_query),
            "method": intent_info["source"],
        }

    table = _find_best_table(user_query)

    if is_search_query(user_query):
        sql = smart_search_sql(user_query, company_id=company_id)
        if sql:
            try:
                memory.save_context({"input": user_query}, {"output": sql})
            except Exception:
                pass
            return {
                "blocked": False,
                "intent": "SELECT",
                "sql": sql.strip(),
                "explanation": "Understood as a structured business search with entity extraction and joins.",
                "table": table,
                "method": "smart-search",
            }

    if _use_rules_only(user_query):
        sql = _build_sql_from_query(user_query, table)
        method = "rules"
    else:
        # "names only" queries — use rules + ensure name columns are selected
        q_low = user_query.lower()
        is_names_query = any(phrase in q_low for phrase in (
            "names only", "names alone", "just names", "only names",
            "show names", "list names", "give names",
        ))
        if is_names_query:
            sql = _build_names_sql(user_query, table)
            method = "rules-names"
        else:
            sql = _try_ollama_sql(user_query, company_id, table, session_id=session_id)
            method = "ai"
        if not sql:
            if _classify_intent_rules(user_query) != "SELECT":
                message = BLOCKED_MESSAGES.get(
                    _classify_intent_rules(user_query), BLOCKED_MESSAGES["OTHER"]
                )
                return {
                    "blocked": True,
                    "intent": _classify_intent_rules(user_query),
                    "sql": None,
                    "message": message,
                    "explanation": "Could not produce a safe SELECT query.",
                    "table": table,
                    "method": "rules",
                }
            sql = _build_sql_from_query(user_query, table)
            method = "rules-fallback"

    if company_id:
        sql = inject_company_filter(sql, company_id, table)

    try:
        memory.save_context({"input": user_query}, {"output": sql})
    except Exception:
        pass

    return {
        "blocked": False,
        "intent": "SELECT",
        "sql": sql.strip(),
        "explanation": (
            f"Understood as a read query ({intent_info['source']}). "
            f"Generated SQL ({method})."
        ),
        "table": table,
        "method": method,
    }


def generate_full_response(user_query: str, columns: list, rows: list) -> dict:
    if not rows:
        return {"summary": "No records found.", "insights": [], "names": []}

    summary = f"Found {len(rows)} record(s)."
    insights = []

    q = user_query.lower()
    if "customer" in q:
        insights.append(f"{len(rows)} customers")
    elif "payment" in q:
        insights.append(f"{len(rows)} payments")
    elif "order" in q or "invoice" in q:
        insights.append(f"{len(rows)} orders/invoices")

    # Extract names from result columns
    names = _extract_names_from_rows(columns, rows)
    return {"summary": summary, "insights": insights, "names": names}


def _extract_names_from_rows(columns: list, rows: list) -> list[str]:
    """
    Pull human-readable names from query result rows.
    Handles: first_name+last_name, name, customer_name, full_name, company_name.
    Never returns literal "NULL" as part of a name.
    """
    if not rows or not columns:
        return []

    col_lower = [c.lower() for c in columns]

    def idx(name: str) -> int | None:
        try:
            return col_lower.index(name)
        except ValueError:
            return None

    def _clean(val) -> str:
        """Strip NULL tokens and whitespace from a name value."""
        s = str(val or "").strip()
        if s.upper() == "NULL" or not s:
            return ""
        # Remove embedded NULLs e.g. "NIBIN NULL"
        s = re.sub(r'\bNULL\b', '', s, flags=re.IGNORECASE).strip()
        return s

    first_idx = idx("first_name")
    last_idx  = idx("last_name")
    name_idx  = idx("full_name") or idx("customer_name") or idx("name") or idx("company_name")

    names = []
    for row in rows[:20]:  # cap at 20 for display
        if first_idx is not None:
            first = _clean(row[first_idx])
            last  = _clean(row[last_idx]) if last_idx is not None else ""
            full  = f"{first} {last}".strip()
            if full:
                names.append(full)
                continue
        if name_idx is not None:
            val = _clean(row[name_idx])
            if val:
                names.append(val)
                continue
        # Fallback: first non-id string column
        for i, col in enumerate(col_lower):
            if "id" not in col and row[i]:
                val = _clean(row[i])
                if val and not val.isdigit():
                    names.append(val)
                    break

    return [n for n in names if n]