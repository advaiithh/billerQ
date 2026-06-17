"""
BillerQ AI Copilot v4.0 — Complete Hybrid Intelligence Backend
==============================================================
Architecture:
  - Client-Side Intent Router handles 70%+ requests locally (NO AI)
  - Backend handles: Analysis, Workflow Guidance, Complex Queries, DB Search
  - Multi-Tenant Security: company_id in every request, scoped to tenant
  - LLM Provider Abstraction: Ollama (local) ↔ Amazon Bedrock (cloud)
  - Async MySQL Database for rich customer/payment queries
  - Conversational Memory with session management
  - Query Logging for analytics and cost tracking

Run with:
    uvicorn main:app --host 0.0.0.0 --port 8001 --reload
"""

import os
import re
import json
import asyncio
from datetime import datetime
from typing import Optional, Any
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import httpx

# Custom modules
try:
    from query_logger import QueryLogEntry, log_query_async, get_query_log_store
    HAS_LOGGER = True
except ImportError:
    HAS_LOGGER = False

try:
    from database import get_db, check_db_status
    HAS_DB = True
except ImportError:
    HAS_DB = False

# ─── Load env ────────────────────────────────────────────────────────────────
load_dotenv()

app = FastAPI(title="BillerQ AI Copilot", version="4.0.0")

# Thread pool for blocking operations (boto3, etc.)
_thread_executor = ThreadPoolExecutor(max_workers=4)

# ─── CORS ────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

ADMIN_API_BASE   = os.getenv("ADMIN_API_BASE", "https://admin.billerq.com/public/api")
OLLAMA_URL       = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL     = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
LLM_PROVIDER     = os.getenv("LLM_PROVIDER", "ollama")  # "ollama" | "bedrock"

# Amazon Bedrock — updated to Claude 3.5 models
BEDROCK_REGION       = os.getenv("BEDROCK_REGION", "us-east-1")
BEDROCK_HAIKU_MODEL  = os.getenv("BEDROCK_HAIKU_MODEL", "anthropic.claude-3-5-haiku-20241022-v1:0")
BEDROCK_SONNET_MODEL = os.getenv("BEDROCK_SONNET_MODEL", "anthropic.claude-3-5-sonnet-20241022-v2:0")
BEDROCK_ACCESS_KEY   = os.getenv("BEDROCK_ACCESS_KEY", "")
BEDROCK_SECRET_KEY   = os.getenv("BEDROCK_SECRET_KEY", "")

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE MAP — BillerQ React routes
# ═══════════════════════════════════════════════════════════════════════════════

PAGE_MAP = {
    "dashboard":             "/dashboard/default",
    "customers":             "/customers/customer",
    "add_customer":          "/customers/customer-add",
    "edit_customer":         "/customers/customer-edit",
    "customer_archive":      "/customers/customer-archive",
    "stb_modem":             "/customers/stb-modem",
    "wallet":                "/customers/wallet",
    "payments":              "/payment/quick-pay",
    "invoices":              "/billing/invoice",
    "invoice_cancel":        "/billing/invoice-cancel",
    "subscriptions":         "/billing/subscription",
    "subscription_add":      "/billing/subscription-add",
    "activate_subscription": "/billing/activate-subscription",
    "recurring":             "/billing/recurring",
    "orders":                "/billing/order-add",
    "complaints":            "/complaints",
    "complaints_add":        "/complaints-add",
    "complaints_edit":       "/complaints-edit",
    "collections":           "/report/payment-collection",
    "reports":               "/report/payment-collection",
    "payment_due":           "/report/payment-due",
    "unpaid_customers":      "/report/unpaid-customer",
    "expense_report":        "/report/expense-summary",
    "income_report":         "/report/income-summary",
    "tax_report":            "/report/tax-report",
    "addon_report":          "/report/addon-summary",
    "subscription_report":   "/report/subscription-summary",
    "sms_logs":              "/report/sms-message-logs",
    "online_payment":        "/report/online-payment",
    "wallet_report":         "/report/wallet-balance",
    "settings":              "/settings/area",
    "settings_area":         "/settings/area",
    "settings_categories":   "/settings/categories",
    "settings_payment":      "/settings/payment",
    "settings_tax":          "/settings/tax-group",
    "settings_message":      "/settings/custom-message",
    "users":                 "/menu/user",
    "roles":                 "/menu/role",
}

SHORT_PAGE_ALIASES = {
    "dashboard": "dashboard", "customer": "customers", "customers": "customers",
    "payment": "payments", "payments": "payments", "invoice": "invoices",
    "invoices": "invoices", "subscription": "subscriptions",
    "subscriptions": "subscriptions", "complaint": "complaints",
    "complaints": "complaints", "collection": "collections",
    "collections": "collections", "report": "reports", "reports": "reports",
    "wallet": "wallet", "settings": "settings", "users": "users", "roles": "roles",
}

# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD METRICS
# ═══════════════════════════════════════════════════════════════════════════════

DASHBOARD_METRICS = {
    "total_customers":     {"api": "/admin/get-customer",        "field": "total",               "label": "Total customers",          "page": "customers",   "unit": "count"},
    "active_customers":    {"api": "/admin/get-customer",        "field": "active",              "label": "Active customers",         "page": "customers",   "unit": "count"},
    "inactive_customers":  {"api": "/admin/get-customer",        "field": "inactive",            "label": "Inactive customers",       "page": "customers",   "unit": "count"},
    "today_collection":    {"api": "/admin/dashboard",           "field": "today_collection",    "label": "Today's collection",       "page": "collections", "unit": "currency"},
    "pending_amount":      {"api": "/admin/dashboard",           "field": "pending_amount",      "label": "Pending amount",           "page": "payments",    "unit": "currency"},
    "open_complaints":     {"api": "/admin/dashboard",           "field": "open_complaints",     "label": "Open complaints",          "page": "complaints",  "unit": "count"},
    "active_subscriptions":{"api": "/admin/dashboard",           "field": "active_subscriptions","label": "Active subscriptions",     "page": "subscriptions","unit": "count"},
    "today_payments":      {"api": "/admin/dashboard",           "field": "today_payments",      "label": "Today's payments",         "page": "payments",    "unit": "count"},
    "monthly_collection":  {"api": "/admin/dashboard",           "field": "monthly_collection",  "label": "Monthly collection",       "page": "collections", "unit": "currency"},
    "total_outstanding":   {"api": "/admin/get-payment-due-data","field": "total",               "label": "Total outstanding amount", "page": "payment_due", "unit": "currency"},
    "overdue_customers":   {"api": "/admin/overdue-list",        "field": "total",               "label": "Overdue customers",        "page": "payment_due", "unit": "count"},
}

METRIC_MAP = {
    "active customer": "active_customers",    "inactive customer": "inactive_customers",
    "total customer": "total_customers",      "how many customer": "total_customers",
    "active customers": "active_customers",   "inactive customers": "inactive_customers",
    "total customers": "total_customers",     "how many customers": "total_customers",
    "collection today": "today_collection",   "today collection": "today_collection",
    "today's collection": "today_collection", "how much collection": "today_collection",
    "pending amount": "pending_amount",       "pending payment": "pending_amount",
    "pending payments": "pending_amount",     "open complaint": "open_complaints",
    "open complaints": "open_complaints",     "active subscription": "active_subscriptions",
    "active subscriptions": "active_subscriptions",
    "monthly collection": "monthly_collection",
    "outstanding amount": "total_outstanding", "total outstanding": "total_outstanding",
    "overdue": "overdue_customers",           "overdue customers": "overdue_customers",
    "today payment": "today_payments",        "today payments": "today_payments",
    "today's payments": "today_payments",
}

# ═══════════════════════════════════════════════════════════════════════════════
# WORKFLOW KNOWLEDGE BASE (SOPs)
# ═══════════════════════════════════════════════════════════════════════════════

WORKFLOW_SOPS = {
    "assign_technician": {
        "title": "Assign a Technician to a Complaint",
        "steps": [
            "1. Go to the **Complaints** section from the sidebar.",
            "2. Find the complaint (use the search if needed).",
            "3. Click on the complaint to open its details.",
            "4. Click the **Assign Technician** button or dropdown.",
            "5. Select the technician from the list.",
            "6. Click **Save** or **Confirm** to assign.",
            "7. The customer will be notified automatically.",
        ],
        "page": "complaints",
    },
    "generate_invoice": {
        "title": "Generate an Invoice",
        "steps": [
            "1. Go to **Billing → Invoices** from the sidebar.",
            "2. Click **Add Invoice** or **Generate Invoice**.",
            "3. Select the customer from the dropdown.",
            "4. Add invoice items (description, quantity, rate).",
            "5. Apply discounts or taxes if applicable.",
            "6. Review the invoice preview.",
            "7. Click **Save** — you can print or email it directly.",
        ],
        "page": "invoices",
    },
    "close_complaint": {
        "title": "Close a Complaint",
        "steps": [
            "1. Go to **Complaints** from the sidebar.",
            "2. Open the resolved complaint.",
            "3. Update status to **Resolved**.",
            "4. Add resolution notes.",
            "5. Click **Save** — customer will be notified automatically.",
        ],
        "page": "complaints",
    },
    "add_customer": {
        "title": "Add a New Customer",
        "steps": [
            "1. Go to **Customers** → **Add Customer**.",
            "2. Fill in: name, phone, address, area.",
            "3. Select subscription plan and STB/Modem details.",
            "4. Set payment terms.",
            "5. Click **Save** to create the customer.",
        ],
        "page": "add_customer",
    },
    "process_payment": {
        "title": "Process a Payment",
        "steps": [
            "1. Go to **Payments → Quick Pay**.",
            "2. Search for the customer by name or subscriber ID.",
            "3. Enter the payment amount.",
            "4. Select payment method (Cash, UPI, Card, etc.).",
            "5. Add reference number if applicable.",
            "6. Click **Submit** — receipt is auto-generated.",
        ],
        "page": "payments",
    },
    "create_subscription": {
        "title": "Create a Subscription",
        "steps": [
            "1. Go to **Billing → Subscriptions → Add Subscription**.",
            "2. Select the customer.",
            "3. Choose plan and billing cycle.",
            "4. Set start date and auto-renewal preferences.",
            "5. Click **Save** to activate.",
        ],
        "page": "subscription_add",
    },
    "activate_customer": {
        "title": "Activate a Customer",
        "steps": [
            "1. Go to **Billing → Activate Subscription**.",
            "2. Search for the customer.",
            "3. Select the subscription to activate.",
            "4. Confirm the activation date.",
            "5. Click **Activate** — customer status updates immediately.",
        ],
        "page": "activate_subscription",
    },
    "generate_report": {
        "title": "Generate a Collection Report",
        "steps": [
            "1. Go to **Reports → Payment Collection**.",
            "2. Select the date range (from/to).",
            "3. Filter by area or agent if needed.",
            "4. Click **Generate** or **Filter**.",
            "5. Export as Excel or PDF using the export button.",
        ],
        "page": "collections",
    },
    "add_complaint": {
        "title": "Log a New Complaint",
        "steps": [
            "1. Go to **Complaints → Add Complaint**.",
            "2. Search and select the customer.",
            "3. Select complaint category and priority.",
            "4. Describe the issue in the details field.",
            "5. Assign to a technician if available.",
            "6. Click **Save** to log the complaint.",
        ],
        "page": "complaints_add",
    },
}

# ═══════════════════════════════════════════════════════════════════════════════
# LLM PROVIDER ABSTRACTION
# ═══════════════════════════════════════════════════════════════════════════════

class LLMProvider:
    """Abstract base — swap Ollama ↔ Bedrock via LLM_PROVIDER env var."""
    async def generate(self, prompt: str, system: str = "") -> str:
        raise NotImplementedError

    async def generate_complex(self, prompt: str, system: str = "") -> str:
        """Complex analysis — override in providers that support it."""
        return await self.generate(prompt, system)


class OllamaProvider(LLMProvider):
    async def generate(self, prompt: str, system: str = "") -> str:
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": full_prompt, "stream": False},
            )
            resp.raise_for_status()
            return resp.json().get("response", "").strip()


class BedrockProvider(LLMProvider):
    """
    Amazon Bedrock provider — Claude 3.5 Haiku (fast) + Sonnet (complex).
    boto3 calls are blocking so we run them in a thread pool.
    """

    async def generate(self, prompt: str, system: str = "") -> str:
        return await self._call_bedrock_async(prompt, system, BEDROCK_HAIKU_MODEL)

    async def generate_complex(self, prompt: str, system: str = "") -> str:
        return await self._call_bedrock_async(prompt, system, BEDROCK_SONNET_MODEL)

    async def _call_bedrock_async(self, prompt: str, system: str, model_id: str) -> str:
        """Run blocking boto3 call in thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _thread_executor,
            self._call_bedrock_sync,
            prompt, system, model_id
        )

    def _call_bedrock_sync(self, prompt: str, system: str, model_id: str) -> str:
        """Synchronous Bedrock invocation (runs in thread pool)."""
        try:
            import boto3
            import botocore.exceptions

            session = boto3.Session(
                aws_access_key_id=BEDROCK_ACCESS_KEY or None,
                aws_secret_access_key=BEDROCK_SECRET_KEY or None,
                region_name=BEDROCK_REGION,
            )
            client = session.client("bedrock-runtime")

            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1000,
                "system": system,
                "messages": [{"role": "user", "content": prompt}],
            })

            response = client.invoke_model(
                modelId=model_id,
                contentType="application/json",
                accept="application/json",
                body=body,
            )

            result = json.loads(response["body"].read().decode())
            return result.get("content", [{}])[0].get("text", "").strip()

        except ImportError:
            return "Bedrock SDK not installed. Run: pip install boto3"
        except Exception as e:
            return f"Bedrock error: {str(e)}"


def get_llm_provider() -> LLMProvider:
    if LLM_PROVIDER == "bedrock":
        return BedrockProvider()
    return OllamaProvider()


# ═══════════════════════════════════════════════════════════════════════════════
# AUTH & HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def extract_company_id(token: str) -> Optional[int]:
    """Extract company_id from JWT payload."""
    if not token:
        return None
    try:
        parts = token.split(".")
        if len(parts) == 3:
            payload_b64 = parts[1]
            payload_b64 += "=" * (4 - len(payload_b64) % 4)
            import base64
            payload_bytes = base64.urlsafe_b64decode(payload_b64)
            payload = json.loads(payload_bytes)
            return payload.get("company_id") or payload.get("companyId")
    except Exception:
        pass
    return None


def format_currency(value) -> str:
    try:
        v = float(value)
        if v >= 10_000_000:
            return f"₹{v/10_000_000:.2f} Cr"
        elif v >= 100_000:
            return f"₹{v/100_000:.2f} Lakh"
        elif v >= 1000:
            return f"₹{v:,.0f}"
        else:
            return f"₹{v:.2f}"
    except Exception:
        return f"₹{value}"


def format_number(value) -> str:
    try:
        return f"{int(value):,}"
    except Exception:
        return str(value)


# ═══════════════════════════════════════════════════════════════════════════════
# SESSION MEMORY
# ═══════════════════════════════════════════════════════════════════════════════

session_store: dict = {}


def get_session(session_id: str) -> list:
    return session_store.get(session_id, [])


def save_session(session_id: str, history: list):
    session_store[session_id] = history[-20:]


# ═══════════════════════════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class ChatRequest(BaseModel):
    message: str
    session_id: str
    context: Optional[dict] = None
    company_id: Optional[int] = None   # Can also be passed in body
    scraped_data: Optional[dict] = None  # DOM-scraped live data from the widget


class NavigationPayload(BaseModel):
    label: str
    url: str


class ChatResponse(BaseModel):
    message: str
    intent: str
    navigation: Optional[NavigationPayload] = None
    company_id: Optional[int] = None
    source: str = "ai"
    data: Optional[dict] = None       # Rich structured data (e.g. customer results)


class CustomerSearchRequest(BaseModel):
    query: str
    company_id: int
    search_type: str = "auto"         # "auto" | "name" | "phone" | "subscriber_id" | "area"


# ═══════════════════════════════════════════════════════════════════════════════
# API HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

async def call_admin_api(endpoint: str, token: str, company_id: Optional[int] = None) -> dict:
    """Call BillerQ admin API with bearer token and optional company_id."""
    url = f"{ADMIN_API_BASE}{endpoint}"
    headers = {"Authorization": f"Bearer {token}"}
    if company_id:
        headers["X-Company-Id"] = str(company_id)
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def call_llm(prompt: str, system: str = "") -> str:
    provider = get_llm_provider()
    return await provider.generate(prompt, system)


async def call_llm_complex(prompt: str, system: str = "") -> str:
    provider = get_llm_provider()
    return await provider.generate_complex(prompt, system)


# ═══════════════════════════════════════════════════════════════════════════════
# INTENT DETECTION HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def detect_workflow_topic(message: str) -> Optional[str]:
    msg = message.lower()
    patterns = {
        "assign_technician":  ["assign", "assign technician", "allocate technician", "assign engineer"],
        "generate_invoice":   ["create invoice", "generate invoice", "make invoice", "new invoice", "how to invoice"],
        "close_complaint":    ["close complaint", "resolve complaint", "mark resolved", "complaint resolved"],
        "add_customer":       ["add customer", "new customer", "create customer", "register customer"],
        "process_payment":    ["process payment", "make payment", "record payment", "accept payment", "collect payment", "quick pay"],
        "create_subscription":["create subscription", "add subscription", "new subscription"],
        "activate_customer":  ["activate customer", "activate subscription", "activate account"],
        "generate_report":    ["generate report", "create report", "export report", "download report"],
        "add_complaint":      ["add complaint", "log complaint", "new complaint", "raise complaint", "file complaint"],
    }
    for topic, triggers in patterns.items():
        for trigger in triggers:
            if trigger in msg:
                return topic
    return None


def detect_customer_search(message: str) -> Optional[dict]:
    """
    Detect if message is asking to find/search a specific customer.
    Returns search params or None.
    """
    msg = message.lower().strip()
    search_triggers = [
        "find customer", "search customer", "look up", "lookup",
        "find subscriber", "search subscriber", "who is", "details of",
        "customer details", "show customer", "check customer",
        "find for", "search for",
    ]
    is_search = any(t in msg for t in search_triggers)

    # Also detect phone number patterns (10+ digits)
    phone_match = re.search(r'\b(\d{10,12})\b', message)
    # Subscriber ID pattern (e.g. SUB123, BQ-001, etc.)
    sub_match = re.search(r'\b([A-Za-z]{2,4}[-_]?\d{3,8})\b', message)

    if phone_match:
        return {"type": "phone", "query": phone_match.group(1)}
    if sub_match and (is_search or "subscriber" in msg):
        return {"type": "subscriber_id", "query": sub_match.group(1)}
    if is_search:
        # Extract the search term after trigger words
        for trigger in search_triggers:
            if trigger in msg:
                after = msg[msg.index(trigger) + len(trigger):].strip()
                after = re.sub(r'^(for|named?|called?|with|:)\s*', '', after).strip()
                if after and len(after) > 1:
                    query_type = "phone" if after.isdigit() else "name"
                    return {"type": query_type, "query": after}
    return None


def detect_dashboard_query(message: str) -> Optional[str]:
    """Detect if message asks for a dashboard metric."""
    msg = message.lower()
    for phrase, key in METRIC_MAP.items():
        if phrase in msg:
            return key
    return None


def detect_navigation(message: str) -> Optional[dict]:
    """Detect navigation request and return page key."""
    msg = message.lower().strip()
    nav_triggers = ["open", "go to", "navigate", "take me to", "show me", "redirect", "go ", "show page"]
    is_nav = any(kw in msg for kw in nav_triggers)

    if not is_nav:
        # Check for direct alias ("customers", "invoices", etc.)
        for alias in SHORT_PAGE_ALIASES:
            if msg == alias or msg == f"show {alias}" or msg == f"open {alias}":
                is_nav = True
                break

    if is_nav:
        # Check specific compound pages first
        specific = {
            "add customer": "add_customer", "new customer": "add_customer",
            "add complaint": "complaints_add", "new complaint": "complaints_add",
            "add subscription": "subscription_add", "new subscription": "subscription_add",
            "payment collection": "collections", "payment due": "payment_due",
            "unpaid customer": "unpaid_customers", "expense report": "expense_report",
            "income report": "income_report", "tax report": "tax_report",
            "sms log": "sms_logs", "online payment": "online_payment",
            "wallet balance": "wallet_report", "wallet report": "wallet_report",
        }
        for phrase, key in specific.items():
            if phrase in msg:
                return {"page_key": key, "url": PAGE_MAP[key]}

        for alias, page_key in SHORT_PAGE_ALIASES.items():
            if alias in msg:
                return {"page_key": page_key, "url": PAGE_MAP[page_key]}
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# RESPONSE FORMATTERS
# ═══════════════════════════════════════════════════════════════════════════════

def format_workflow_response(topic: str, sop: dict) -> str:
    steps = "\n".join(sop["steps"])
    return (
        f"📋 **{sop['title']}**\n\n"
        f"Here are the steps:\n\n"
        f"{steps}\n\n"
        f"💡 Want me to open the {sop['page'].replace('_', ' ')} page?"
    )


def format_metric_response(metric_key: str, value, metric_info: dict) -> str:
    unit = metric_info["unit"]
    formatted = format_currency(value) if unit == "currency" else format_number(value)
    label = metric_info["label"]

    icons = {
        "total_customers": "👥", "active_customers": "✅", "inactive_customers": "🔴",
        "today_collection": "💰", "pending_amount": "⏳", "open_complaints": "🔧",
        "active_subscriptions": "📋", "today_payments": "💵",
        "monthly_collection": "📊", "total_outstanding": "💳", "overdue_customers": "⚠️",
    }
    icon = icons.get(metric_key, "📊")
    return f"{icon} **{label}:** {formatted}"


def format_customer_results(results: list, query: str) -> str:
    if not results:
        return f"🔍 No customers found matching **{query}**.\n\nTry searching by:\n• Phone number\n• Subscriber ID (e.g. SUB123)\n• Area name"

    lines = [f"🔍 Found **{len(results)}** customer(s) matching **{query}**:\n"]
    for c in results[:5]:  # Show max 5 in chat
        name = c.get("name") or c.get("full_name", "Unknown")
        phone = c.get("phone") or c.get("mobile", "—")
        status = c.get("status", "unknown")
        area = c.get("area", "—")
        sub_id = c.get("subscriber_id", "—")
        status_icon = "✅" if status == "active" else "🔴"

        lines.append(f"{status_icon} **{name}** (ID: {sub_id})")
        lines.append(f"   📱 {phone} · 📍 {area}")

    if len(results) > 5:
        lines.append(f"\n...and {len(results) - 5} more. View all in Customer Management.")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# ANALYTICS ENDPOINT HELPER
# ═══════════════════════════════════════════════════════════════════════════════

def _log_query(session_id: str, query: str, intent: str, response: str,
               company_id: Optional[int], start_time: datetime):
    if not HAS_LOGGER:
        return
    try:
        elapsed = (datetime.now() - start_time).total_seconds() * 1000
        entry = QueryLogEntry(
            session_id=session_id, user_query=query, intent=intent,
            response=response, service_used="backend",
            response_time_ms=elapsed, company_id=company_id,
        )
        asyncio.ensure_future(log_query_async(entry))
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN CHAT ENDPOINT
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    authorization: Optional[str] = Header(None),
    x_company_id: Optional[str] = Header(None),
):
    message = request.message.strip()
    session_id = request.session_id
    ui_context = request.context or {}

    if not message:
        return ChatResponse(message="Please type a message to get started.", intent="empty")

    # ── Auth & Company ID Resolution ─────────────────────────────────────────
    token = None
    company_id = None

    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]
        company_id = extract_company_id(token)

    # Header takes precedence over JWT
    if x_company_id and x_company_id.isdigit():
        company_id = int(x_company_id)

    # Body company_id as fallback (from widget context)
    if company_id is None and request.company_id:
        company_id = request.company_id

    # Extract from UI context if still missing
    if company_id is None and ui_context.get("user", {}).get("companyId"):
        try:
            company_id = int(ui_context["user"]["companyId"])
        except (ValueError, TypeError):
            pass

    # Extract API URL from context (per-tenant)
    tenant_api_base = ui_context.get("user", {}).get("apiUrl") or ADMIN_API_BASE

    history = get_session(session_id)
    start_time = datetime.now()
    msg_lower = message.lower().strip()

    # ── 1. WORKFLOW GUIDANCE ─────────────────────────────────────────────────
    workflow_topic = detect_workflow_topic(message)
    if workflow_topic and workflow_topic in WORKFLOW_SOPS:
        sop = WORKFLOW_SOPS[workflow_topic]
        response_text = format_workflow_response(workflow_topic, sop)
        nav = NavigationPayload(
            label=f"Open {sop['page'].replace('_', ' ').title()}",
            url=PAGE_MAP.get(sop["page"], "/dashboard/default"),
        )
        history.extend([
            {"role": "user", "content": message},
            {"role": "assistant", "content": response_text},
        ])
        save_session(session_id, history)
        _log_query(session_id, message, "workflow_guidance", response_text, company_id, start_time)
        return ChatResponse(
            message=response_text, intent="workflow_guidance",
            navigation=nav, company_id=company_id, source="knowledge_base",
        )

    # ── 2. CUSTOMER SEARCH ────────────────────────────────────────────────────
    search_params = detect_customer_search(message)
    if search_params and company_id:
        results = []
        search_source = "api"

        # Try admin API first
        try:
            api_params: dict = {}
            if search_params["type"] == "phone":
                api_params["mobile"] = search_params["query"]
            elif search_params["type"] == "name":
                api_params["name"] = search_params["query"]
            elif search_params["type"] == "subscriber_id":
                api_params["subscriber_id"] = search_params["query"]
            elif search_params["type"] == "area":
                api_params["area"] = search_params["query"]

            if token and api_params:
                url = f"{tenant_api_base}/admin/get-customer"
                headers = {"Authorization": f"Bearer {token}", "X-Company-Id": str(company_id)}
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(url, headers=headers, params=api_params)
                    if resp.status_code == 200:
                        data = resp.json()
                        results = data.get("data", data.get("customers", []))
        except Exception:
            pass

        # Fallback to DB if API gave nothing
        if not results and HAS_DB:
            try:
                db = get_db()
                db_result = await db.search_customers(
                    company_id=company_id,
                    name=search_params["query"] if search_params["type"] == "name" else None,
                    phone=search_params["query"] if search_params["type"] == "phone" else None,
                    subscriber_id=search_params["query"] if search_params["type"] == "subscriber_id" else None,
                )
                if "error" not in db_result:
                    results = db_result.get("results", [])
                    search_source = "database"
            except Exception:
                pass

        response_text = format_customer_results(results, search_params["query"])
        nav = NavigationPayload(label="View All Customers", url=PAGE_MAP["customers"])

        history.extend([
            {"role": "user", "content": message},
            {"role": "assistant", "content": response_text},
        ])
        save_session(session_id, history)
        _log_query(session_id, message, "customer_search", response_text, company_id, start_time)
        return ChatResponse(
            message=response_text, intent="customer_search",
            navigation=nav, company_id=company_id, source=search_source,
            data={"results": results[:10], "total": len(results)},
        )

    # ── 3. NAVIGATION ─────────────────────────────────────────────────────────
    nav_result = detect_navigation(message)
    if nav_result:
        page_key = nav_result["page_key"]
        url = nav_result["url"]
        page_name = page_key.replace("_", " ").title()
        response_text = f"Opening the **{page_name}** page..."
        nav = NavigationPayload(label=f"Go to {page_name}", url=url)
        history.extend([
            {"role": "user", "content": message},
            {"role": "assistant", "content": response_text},
        ])
        save_session(session_id, history)
        _log_query(session_id, message, "navigation", response_text, company_id, start_time)
        return ChatResponse(
            message=response_text, intent="navigation",
            navigation=nav, company_id=company_id, source="local",
        )

    # ── 4. DASHBOARD METRIC QUERY ─────────────────────────────────────────────
    metric_key = detect_dashboard_query(message)
    if metric_key and token:
        metric = DASHBOARD_METRICS[metric_key]
        try:
            data = await call_admin_api(metric["api"], token, company_id)
            value = data.get(metric["field"])
            if value is None and isinstance(data.get("data"), dict):
                value = data["data"].get(metric["field"])

            if value is not None:
                response_text = format_metric_response(metric_key, value, metric)
                nav = NavigationPayload(
                    label=f"View {metric['label']}",
                    url=PAGE_MAP.get(metric["page"], "/dashboard/default"),
                )
                history.extend([
                    {"role": "user", "content": message},
                    {"role": "assistant", "content": response_text},
                ])
                save_session(session_id, history)
                _log_query(session_id, message, "dashboard_query", response_text, company_id, start_time)
                return ChatResponse(
                    message=response_text, intent="dashboard_query",
                    navigation=nav, company_id=company_id, source="api",
                )
        except Exception:
            pass  # Fall through to AI

    elif metric_key and not token:
        response_text = "I can see you're asking about dashboard metrics. Please make sure you're logged in so I can fetch real-time data for you."
        return ChatResponse(
            message=response_text, intent="dashboard_query",
            navigation=NavigationPayload(label="View Dashboard", url="/dashboard/default"),
            company_id=company_id, source="local",
        )

    # ── 5. DASHBOARD SUMMARY ──────────────────────────────────────────────────
    if any(kw in msg_lower for kw in ["dashboard summary", "overview", "summary", "how's business", "business summary", "everything"]):
        if token:
            summary_parts = []
            metrics_to_fetch = ["today_collection", "active_customers", "pending_amount", "open_complaints"]

            async def fetch_metric(mk):
                m = DASHBOARD_METRICS[mk]
                try:
                    d = await call_admin_api(m["api"], token, company_id)
                    v = d.get(m["field"]) or (d.get("data") or {}).get(m["field"])
                    return mk, v
                except Exception:
                    return mk, None

            results = await asyncio.gather(*[fetch_metric(mk) for mk in metrics_to_fetch])
            for mk, val in results:
                if val is not None:
                    summary_parts.append(format_metric_response(mk, val, DASHBOARD_METRICS[mk]))

            if summary_parts:
                response_text = "📊 **Dashboard Summary**\n\n" + "\n".join(summary_parts)
                response_text += "\n\n💡 Ask me about any specific metric for more details!"
            else:
                response_text = "I couldn't fetch the dashboard data right now. Check your connection and try again."

            nav = NavigationPayload(label="View Dashboard", url="/dashboard/default")
            history.extend([{"role": "user", "content": message}, {"role": "assistant", "content": response_text}])
            save_session(session_id, history)
            _log_query(session_id, message, "dashboard_summary", response_text, company_id, start_time)
            return ChatResponse(
                message=response_text, intent="dashboard_summary",
                navigation=nav, company_id=company_id, source="api",
            )

    # ── 6. ANALYSIS (requires AI, but uses DOM data first) ──────────────────────
    analysis_keywords = [
        "why", "reason", "trend", "compare", "analysis", "insight",
        "summarize", "explain", "growth", "decline",
        "performance", "forecast", "predict", "pattern", "analyse",
        "which area", "best area", "worst area", "most complaints",
    ]
    is_analysis = any(kw in msg_lower for kw in analysis_keywords)

    if is_analysis:
        context_str = "\n".join(f"{m['role']}: {m['content']}" for m in history[-6:])

        # Build data context from DOM-scraped values (no API call needed)
        scraped = request.scraped_data or ui_context.get("scraped_data") or ui_context.get("scraped") or {}
        data_lines = []
        data_labels = {
            "active_customers": "Active customers",
            "inactive_customers": "Inactive customers",
            "total_customers": "Total customers",
            "today_collection": "Today's collection (INR)",
            "monthly_collection": "Monthly collection (INR)",
            "invoice_amount": "Invoice amount (INR)",
            "due_invoice": "Due invoice amount (INR)",
            "open_complaints": "Open complaints",
            "closed_complaints": "Closed complaints",
            "active_subscriptions": "Active subscriptions",
            "revenue_pct": "Revenue collected %",
            "recurring_invoices": "Recurring invoices",
            "payment_count": "Payments count",
            "collection_total": "Collection total (INR)",
        }
        for key, label in data_labels.items():
            if key in scraped and scraped[key] is not None:
                data_lines.append(f"  {label}: {scraped[key]}")

        scraped_summary = "\n".join(data_lines) if data_lines else "No data available from UI."
        user_name = ui_context.get("user", {}).get("name", "User")
        current_page = ui_context.get("current_page") or ui_context.get("currentPage", "")

        system_prompt = f"""You are BillerQ AI Copilot, an expert business intelligence assistant for a billing/collection SaaS platform.
Your users are cable TV and broadband operators in India.

You have direct access to the user's live dashboard data (scraped from their screen):
{scraped_summary}

Current page: {current_page}
User: {user_name}

Rules:
- Use the live data above to give specific, numeric answers
- Format money as Indian Rupees (e.g. Rs. 74,534 or 6.00 Lakh)
- Always show the relevant numbers from the data first, then give insight
- End with one specific actionable recommendation
- Do NOT say 'I don't have access to data' — the data is above
- Keep response under 5 lines"""

        user_prompt = f"""Recent conversation:
{context_str}

User question: {message}

Using the live data provided, give a specific insight with numbers. End with one action item."""

        try:
            llm_response = await call_llm_complex(user_prompt, system_prompt)
            response_text = llm_response
        except Exception:
            response_text = (
                "For detailed analysis, check the **Reports** section — "
                "you'll find collection reports, payment summaries, and area-wise analytics there."
            )

        nav = NavigationPayload(label="View Reports →", url="/report/payment-collection")
        history.extend([{"role": "user", "content": message}, {"role": "assistant", "content": response_text}])
        save_session(session_id, history)
        _log_query(session_id, message, "analysis", response_text, company_id, start_time)
        return ChatResponse(
            message=response_text, intent="analysis",
            navigation=nav, company_id=company_id, source="ai",
        )

    # ── 7. GENERAL QUERY (AI fallback with DOM context) ───────────────────────
    context_str = "\n".join(f"{m['role']}: {m['content']}" for m in history[-6:])

    # Inject scraped DOM data into general query prompt too
    scraped = request.scraped_data or ui_context.get("scraped_data") or ui_context.get("scraped") or {}
    data_lines = [f"  {k}: {v}" for k, v in scraped.items() if v is not None][:15]
    scraped_summary = "\n".join(data_lines) if data_lines else "Not available."
    current_page = ui_context.get("current_page") or ui_context.get("currentPage", "")

    system_prompt = f"""You are BillerQ AI Copilot, an intelligent assistant for the BillerQ billing platform.
Your users are cable TV and broadband operators in India.

Live data from the user's current screen ({current_page}):
{scraped_summary}

You can help with:
- Dashboard metrics (active customers, today's collection, pending payments, etc.)
- Navigation (opening any page in the app)
- Workflows (step-by-step guides for common tasks)
- Customer search (by name, phone, or subscriber ID)
- Business analysis and insights

Rules:
- Use the live data above when answering metric questions
- Be concise (2-4 sentences)
- Use Indian Rupee (Rs.) for money
- Recommend specific pages or actions
- Be helpful and direct"""

    user_prompt = f"""Recent conversation:
{context_str}

User question: {message}

Answer directly and helpfully using the live data if relevant."""

    try:
        llm_response = await call_llm(user_prompt, system_prompt)
        response_text = llm_response
    except Exception:
        response_text = (
            "I'm here to help! You can ask me about:\n"
            "• **Dashboard metrics** — 'How many active customers?'\n"
            "• **Navigation** — 'Open complaints page'\n"
            "• **Customer search** — 'Find customer John' or a phone number\n"
            "• **Workflows** — 'How to assign a technician?'\n"
            "• **Analysis** — 'Why is collection dropping?'\n\n"
            "What would you like to know?"
        )

    nav = NavigationPayload(label="View Dashboard", url="/dashboard/default")
    history.extend([{"role": "user", "content": message}, {"role": "assistant", "content": response_text}])
    save_session(session_id, history)
    _log_query(session_id, message, "general", response_text, company_id, start_time)
    return ChatResponse(
        message=response_text, intent="general",
        navigation=nav, company_id=company_id, source="ai",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# CUSTOMER SEARCH ENDPOINT (dedicated)
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/search/customer")
async def search_customer(
    request: CustomerSearchRequest,
    authorization: Optional[str] = Header(None),
):
    """
    Dedicated customer search endpoint.
    Tries admin API first, falls back to DB.
    Requires company_id for multi-tenant security.
    """
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]

    query = request.query.strip()
    company_id = request.company_id
    search_type = request.search_type

    # Detect type if auto
    if search_type == "auto":
        if re.match(r'^\d{10,12}$', query):
            search_type = "phone"
        elif re.match(r'^[A-Za-z]{2,4}[-_]?\d{3,8}$', query):
            search_type = "subscriber_id"
        else:
            search_type = "name"

    results = []
    source = "api"

    # Try admin API
    if token:
        try:
            api_params = {search_type: query} if search_type != "auto" else {"name": query}
            url = f"{ADMIN_API_BASE}/admin/get-customer"
            headers = {"Authorization": f"Bearer {token}", "X-Company-Id": str(company_id)}
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=headers, params=api_params)
                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get("data", data.get("customers", []))
        except Exception:
            pass

    # Fallback to DB
    if not results and HAS_DB:
        try:
            db = get_db()
            db_kwargs = {"company_id": company_id}
            if search_type == "phone":
                db_kwargs["phone"] = query
            elif search_type == "subscriber_id":
                db_kwargs["subscriber_id"] = query
            elif search_type == "area":
                db_kwargs["area"] = query
            else:
                db_kwargs["name"] = query

            db_result = await db.search_customers(**db_kwargs)
            if "error" not in db_result:
                results = db_result.get("results", [])
                source = "database"
        except Exception:
            pass

    return {
        "query": query,
        "search_type": search_type,
        "company_id": company_id,
        "total_found": len(results),
        "results": results[:20],
        "source": source,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# UTILITY ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    db_status = {}
    if HAS_DB:
        db_status = await check_db_status()

    return {
        "status": "ok",
        "service": "billerq-copilot",
        "version": "4.0.0",
        "llm_provider": LLM_PROVIDER,
        "model": BEDROCK_HAIKU_MODEL if LLM_PROVIDER == "bedrock" else OLLAMA_MODEL,
        "architecture": "hybrid",
        "features": {
            "client_handles": ["dashboard_query", "navigation", "search"],
            "backend_handles": ["workflow_guidance", "analysis", "customer_search", "dashboard_summary", "general"],
            "database": db_status.get("connected", False),
            "multi_tenant": True,
            "smart_search": True,
        },
        "database": db_status,
    }


@app.get("/db/status")
async def db_status():
    """Check database connectivity."""
    if not HAS_DB:
        return {"available": False, "error": "database module not loaded (aiomysql may not be installed)"}
    status = await check_db_status()
    return status


@app.delete("/session/{session_id}")
async def clear_session(session_id: str):
    session_store.pop(session_id, None)
    return {"cleared": True}


@app.get("/metrics")
async def list_metrics():
    return {
        "metrics": [
            {"key": k, "label": m["label"], "page": m["page"], "unit": m["unit"]}
            for k, m in DASHBOARD_METRICS.items()
        ]
    }


@app.get("/page-map")
async def get_page_map():
    return {"pages": PAGE_MAP}


@app.get("/workflows")
async def list_workflows():
    return {
        "workflows": [
            {"key": k, "title": v["title"], "page": v["page"]}
            for k, v in WORKFLOW_SOPS.items()
        ]
    }


@app.post("/workflow/{topic}")
async def get_workflow(topic: str):
    sop = WORKFLOW_SOPS.get(topic)
    if not sop:
        raise HTTPException(status_code=404, detail=f"Workflow '{topic}' not found")
    return {
        "topic": topic, "title": sop["title"],
        "steps": sop["steps"], "page": sop["page"],
        "page_url": PAGE_MAP.get(sop["page"], "/dashboard/default"),
    }


@app.get("/analytics")
async def get_analytics(
    company_id: Optional[int] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Get usage statistics for query analytics."""
    if not HAS_LOGGER:
        return {"error": "Logger not available"}
    store = get_query_log_store()
    return {
        "stats": store.get_usage_stats(company_id=company_id),
        "cost_estimate": store.get_cost_estimate(company_id=company_id),
        "recent_queries": store.get_recent_logs(limit=20, company_id=company_id),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════════════════════════════════════

@app.on_event("startup")
async def startup():
    print(f"[BillerQ Copilot] v4.0 starting...")
    print(f"[BillerQ Copilot] LLM Provider: {LLM_PROVIDER}")
    if LLM_PROVIDER == "bedrock":
        print(f"   Haiku:  {BEDROCK_HAIKU_MODEL}")
        print(f"   Sonnet: {BEDROCK_SONNET_MODEL}")
    else:
        print(f"   Ollama Model: {OLLAMA_MODEL}")
    print(f"[BillerQ Copilot] Admin API: {ADMIN_API_BASE}")
    print(f"[BillerQ Copilot] Running at http://localhost:8001")
    print(f"[BillerQ Copilot] Health:    http://localhost:8001/health")
    print(f"[BillerQ Copilot] DB Status: http://localhost:8001/db/status")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("COPILOT_PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port)