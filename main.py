import re
import time
from pathlib import Path

from fastapi import FastAPI, Request, Depends, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ai import (
    natural_language_to_sql,
    CHIP_PHRASES,
    _wants_names_only,
    _project_names_only,
)
from summaries import build_narrative

from config import OLLAMA_MODEL
from business_services import resolve_customer_details
from business_router import route_business_query
from memory import (
    clear_pending_disambiguation,
    get_pending_disambiguation,
    remember_result,
    remember_turn,
    resolve_followup_query,
    try_filter_from_cache,
)

from query_logging import init_query_logging_table, log_payload, log_query
from report_store import get_report, render_report_html, safe_result, store_report

import database
from database import run_query, get_companies, get_company_name, resolve_query_company_scope
from auth import (
    init_auth_tables,
    seed_admin_if_needed,
    create_user,
    authenticate_user,
    create_session_token,
    verify_session_token,
    list_pending_users,
    approve_user,
    reject_user,
)

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="BillerQ AI Assistant")

# CORS middleware for cross-origin chatbot widget calls (e.g. Live Server)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SESSION_COOKIE = "bq_session"


@app.on_event("startup")
async def startup():
    init_auth_tables()
    seed_admin_if_needed()
    init_query_logging_table()


def get_current_user(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    user = verify_session_token(token) if token else None
    return user


def require_user(request: Request):
    user = get_current_user(request)
    if not user:
        return None
    return user


def require_admin(request: Request):
    user = get_current_user(request)
    if not user or user["role"] != "admin":
        return None
    return user


class ChatRequest(BaseModel):
    message: str


class AuthRequest(BaseModel):
    email: str
    password: str
    company_id: int | None = None


class UserActionRequest(BaseModel):
    user_id: int


def _attach_report(payload: dict, user: dict, company_id: int | None) -> dict:
    if payload.get("blocked") or not payload.get("columns"):
        return payload
    safe_columns, safe_rows = safe_result(payload.get("columns") or [], payload.get("rows") or [])
    payload["columns"] = safe_columns
    payload["rows"] = safe_rows
    payload["row_count"] = len(safe_rows)
    report_id = store_report(
        title=payload.get("report_title") or payload.get("summary") or "BillerQ Report",
        summary=payload.get("summary") or "",
        columns=safe_columns,
        rows=safe_rows,
        user_id=user.get("id"),
        company_id=company_id,
    )
    payload["report_url"] = f"/report/{report_id}"
    return payload


def _build_payload_from_cached_rows(
    *,
    user_msg: str,
    effective_msg: str,
    scope_label: str,
    is_admin: bool,
    table: str,
    columns: list,
    rows: list,
    matched_by: str,
) -> dict:
    row_count = len(rows)
    narrative, extra_insights = build_narrative(
        effective_msg, None, scope_label, table, columns, rows, row_count,
    )
    summary = (
        f"Found {row_count} record(s) for {scope_label} (served from session cache, matched on {matched_by})."
        if row_count
        else f"No records found in the previous result for {matched_by}."
    )
    return {
        "success": True,
        "blocked": False,
        "intent": "SELECT",
        "sql": None,
        "explanation": (
            f"Filtered from the previous query's result in the session cache "
            f"(matched on {matched_by}). No new database call was made."
        ),
        "summary": summary,
        "narrative": narrative,
        "insights": extra_insights,
        "columns": columns,
        "rows": rows,
        "row_count": row_count,
        "company": scope_label,
        "is_admin": is_admin,
        "method": "session-cache",
        "service_used": "Session Cache",
        "route": "session_cache",
        "detail_mode": "collapsed",
        "served_from_cache": True,
    }


def _set_session(response: Response, user: dict):
    token = create_session_token(user)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        max_age=7 * 24 * 3600,
        samesite="lax",
    )


def _clear_session(response: Response):
    response.delete_cookie(SESSION_COOKIE)


# ---------------------------------------------------
# FRONTEND ROUTING - React Dashboard First
# ---------------------------------------------------

def _get_build_index_html() -> str:
    path = BASE_DIR / "build-cable" / "build" / "index.html"
    if not path.is_file():
        path = Path("C:/Users/Lenovo/Downloads/build-cable/build/index.html")
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return "<h3>React build index.html not found. Please place it in build-cable/build/</h3>"


@app.get("/", response_class=HTMLResponse)
@app.get("/login", response_class=HTMLResponse)
@app.get("/signup", response_class=HTMLResponse)
@app.get("/app", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    return HTMLResponse(content=_get_build_index_html())


@app.get("/legacy-chat", response_class=HTMLResponse)
async def legacy_chat(request: Request):
    if not get_current_user(request):
        return RedirectResponse(url="/", status_code=302)
    html_file = BASE_DIR / "templates" / "index.html"
    return HTMLResponse(content=html_file.read_text(encoding="utf-8"))


@app.get("/guide", response_class=HTMLResponse)
async def guide_page(request: Request):
    html_file = BASE_DIR / "templates" / "guide.html"
    return HTMLResponse(content=html_file.read_text(encoding="utf-8"))


@app.get("/report/{report_id}", response_class=HTMLResponse)
async def report_page(report_id: str, request: Request):
    user = require_user(request)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    report = get_report(report_id)
    if not report:
        return HTMLResponse(content="Report expired or not found.", status_code=404)
    if user["role"] != "admin" and report.get("company_id") != user.get("company_id"):
        return HTMLResponse(content="You do not have access to this report.", status_code=403)
    return HTMLResponse(content=render_report_html(report))


# ---------------------------------------------------
# DASHBOARD MOCK API ENDPOINTS
# ---------------------------------------------------

@app.get("/admin/get-invoice-amount")
@app.get("/get-invoice-amount")
async def get_invoice_amount():
    return {
        "success": True,
        "invoice": 25842.00,
        "due": 25842.00,
        "collection": 17.80,
        "percentage": 0.07
    }


@app.get("/admin/get-connection-data")
@app.get("/get-connection-data")
async def get_connection_data():
    return {
        "success": True,
        "cable": 7,
        "broadband": 2,
        "iptv": 0
    }


@app.get("/admin/get-customer-status-wise-count")
@app.get("/get-customer-status-wise-count")
async def get_customer_status_wise_count():
    return {
        "success": True,
        "active": 5,
        "inactive": 1,
        "total": 6
    }


@app.get("/admin/get-recent-payment")
@app.get("/get-recent-payment")
async def get_recent_payment():
    return {
        "success": True,
        "data": {
            "data": [
                {"id": 1, "name": "Ram Jacob", "amount": 3500.0, "payment_date": "2026-06-11"},
                {"id": 2, "name": "John Deo", "amount": 2400.0, "payment_date": "2026-06-10"},
                {"id": 3, "name": "Elana John", "amount": 2560.0, "payment_date": "2026-06-09"}
            ]
        }
    }


@app.get("/admin/get-recent-order")
@app.get("/get-recent-order")
async def get_recent_order():
    return {
        "success": True,
        "data": {
            "data": [
                {"id": 1, "product": "Broadband Plan - Developer", "price": "210$", "prdouctstatus": "Processing"},
                {"id": 2, "product": "Broadband Plan - Designer", "price": "210$", "prdouctstatus": "Shipped"}
            ]
        }
    }


@app.get("/admin/stb-status-count")
@app.get("/stb-status-count")
async def stb_status_count():
    return {
        "success": True,
        "active": 7,
        "inactive": 2
    }


@app.get("/admin/complaint-status-count")
async def complaint_status_count():
    return {
        "success": True,
        "open": 4,
        "resolved": 3
    }


@app.get("/admin/get-header")
async def get_header():
    return {"success": True, "header": "BillerQ Admin"}


@app.get("/admin/get-company-data")
async def get_company_data():
    return {"success": True, "data": {"name": "QLO"}}


@app.get("/admin/get-user-profile-counts")
async def get_user_profile_counts():
    return {"success": True, "counts": {"active_customers": 5, "due_payments": 2}}


# ---------------------------------------------------
# AUTH ENDPOINTS
# ---------------------------------------------------

@app.get("/companies")
async def list_companies():
    try:
        companies = get_companies()
        return {"success": True, "companies": companies}
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/auth/signup")
async def signup(body: AuthRequest):
    if not body.company_id:
        return JSONResponse(
            {"success": False, "error": "Please select a company"},
            status_code=400,
        )
    try:
        user = create_user(body.email, body.password, body.company_id)
        return {
            "success": True,
            "message": (
                "Signup successful! Your account is pending admin approval. "
                "You will be able to log in once an administrator approves your request."
            ),
            "user": {
                "email": user["email"],
                "company_name": user["company_name"],
                "status": user["status"],
            },
        }
    except ValueError as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/auth/login")
async def login(body: AuthRequest, response: Response):
    try:
        user = authenticate_user(body.email, body.password)
        _set_session(response, user)
        return {
            "success": True,
            "user": {
                "id": user["id"],
                "email": user["email"],
                "role": user["role"],
                "company_id": user["company_id"],
                "company_name": user["company_name"],
            },
        }
    except ValueError as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=401)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/auth/logout")
async def logout(response: Response):
    _clear_session(response)
    return {"success": True}


@app.get("/auth/me")
async def me(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"success": False, "error": "Not authenticated"}, status_code=401)
    return {
        "success": True,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "role": user["role"],
            "company_id": user["company_id"],
            "company_name": user["company_name"],
        },
    }


@app.get("/admin/pending")
async def admin_pending(request: Request):
    admin = require_admin(request)
    if not admin:
        return JSONResponse({"success": False, "error": "Admin access required"}, status_code=403)
    try:
        pending = list_pending_users()
        return {"success": True, "pending": pending}
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/admin/approve")
async def admin_approve(body: UserActionRequest, request: Request):
    admin = require_admin(request)
    if not admin:
        return JSONResponse({"success": False, "error": "Admin access required"}, status_code=403)
    try:
        approve_user(body.user_id, admin["id"])
        return {"success": True, "message": "User approved successfully"}
    except ValueError as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/admin/reject")
async def admin_reject(body: UserActionRequest, request: Request):
    admin = require_admin(request)
    if not admin:
        return JSONResponse({"success": False, "error": "Admin access required"}, status_code=403)
    try:
        reject_user(body.user_id, admin["id"])
        return {"success": True, "message": "User rejected"}
    except ValueError as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# ---------------------------------------------------
# CHAT API ENDPOINT
# ---------------------------------------------------

@app.post("/chat")
async def chat(body: ChatRequest, request: Request):
    started_at = time.perf_counter()
    user = require_user(request)
    if not user:
        return JSONResponse(
            {"success": False, "error": "Please log in to continue"},
            status_code=401,
        )

    user_msg = body.message.strip()
    is_admin = user["role"] == "admin"

    if not user_msg:
        return JSONResponse({"success": False, "error": "Empty message"}, status_code=400)

    session_id = request.cookies.get(SESSION_COOKIE) or str(user["id"])
    effective_msg, used_memory = resolve_followup_query(session_id, user_msg)
    company_id, scope_label = resolve_query_company_scope(effective_msg, user)

    try:
        pending = get_pending_disambiguation(session_id)
        user_identifier = re.search(r"[\w.\-+]+@[\w.\-]+\.\w+|\+?\d[\d\s.\-]{5,}\d", user_msg)
        if pending and user_identifier:
            pending_company_id = pending.get("company_id", company_id)
            routed = resolve_customer_details(
                pending_company_id,
                scope_label,
                pending,
                user_identifier.group(0),
            )
            if routed:
                payload = {
                    "success": True,
                    "blocked": False,
                    "sql": None,
                    "explanation": "Matched your phone/email reply to the previous customer search.",
                    "company": scope_label,
                    "is_admin": is_admin,
                    **routed,
                }
                _attach_report(payload, user, pending_company_id)
                if not payload.get("needs_disambiguation"):
                    clear_pending_disambiguation(session_id)
                remember_turn(session_id, user_msg, effective_msg, payload)
                log_payload(
                    user=user,
                    user_query=user_msg,
                    effective_query=effective_msg,
                    payload=payload,
                    started_at=started_at,
                )
                return payload

        cached = try_filter_from_cache(session_id, user_msg)
        if cached:
            payload = _build_payload_from_cached_rows(
                user_msg=user_msg,
                effective_msg=effective_msg,
                scope_label=scope_label,
                is_admin=is_admin,
                table=cached["table"],
                columns=cached["columns"],
                rows=cached["rows"],
                matched_by=cached["matched_by"],
            )
            _attach_report(payload, user, company_id)
            remember_turn(session_id, user_msg, effective_msg, payload)
            log_payload(
                user=user,
                user_query=user_msg,
                effective_query=effective_msg,
                payload=payload,
                started_at=started_at,
            )
            return payload

        routed = route_business_query(effective_msg, company_id, scope_label)
        if routed:
            explanation = (
                "Dashboard-first routing selected an existing business service before SQL generation."
            )
            if used_memory:
                explanation += f" Context applied from the previous turn: {effective_msg}"
            payload = {
                "success": True,
                "blocked": False,
                "sql": None,
                "explanation": explanation,
                "company": scope_label,
                "is_admin": is_admin,
                **routed,
            }
            if payload.get("needs_disambiguation") and payload.get("disambiguation"):
                payload["disambiguation"]["company_id"] = company_id
            _attach_report(payload, user, company_id)
            remember_turn(session_id, user_msg, effective_msg, payload)
            log_payload(
                user=user,
                user_query=user_msg,
                effective_query=effective_msg,
                payload=payload,
                started_at=started_at,
            )
            return payload

        ai_result = natural_language_to_sql(effective_msg, company_id=company_id)

        if ai_result.get("blocked"):
            payload = {
                "success": True,
                "blocked": True,
                "conversational": ai_result.get("conversational", False),
                "intent": ai_result.get("intent"),
                "sql": None,
                "explanation": ai_result.get("explanation", ""),
                "summary": ai_result.get("message", ""),
                "narrative": ai_result.get("message", ""),
                "insights": [],
                "columns": [],
                "rows": [],
                "row_count": 0,
                "company": scope_label,
                "is_admin": is_admin,
            }
            _attach_report(payload, user, company_id)
            remember_turn(session_id, user_msg, effective_msg, payload)
            log_payload(
                user=user,
                user_query=user_msg,
                effective_query=effective_msg,
                payload=payload,
                started_at=started_at,
            )
            return payload

        sql = ai_result["sql"]
        explanation = ai_result["explanation"]
        if used_memory:
            explanation += f" Context applied from the previous turn: {effective_msg}"
        method = ai_result.get("method", "rules")
        table = ai_result.get("table", "customers")

        names_only = _wants_names_only(effective_msg)
        if names_only and sql.upper().lstrip().startswith("SELECT"):
            sql = _project_names_only(sql, table)

        db_result = run_query(sql)

        q_lower = effective_msg.lower().strip()
        if (
            db_result["row_count"] == 0
            and method in ("rules", "rules-fallback")
            and q_lower not in CHIP_PHRASES
            and any(w in q_lower for w in ["show", "get", "find", "list"])
        ):
            retry_ai = natural_language_to_sql(
                f"{effective_msg} (include all matching statuses, use correct column names)",
                company_id=company_id,
            )
            if not retry_ai.get("blocked") and retry_ai.get("sql") and retry_ai["sql"] != sql:
                retry_sql = retry_ai["sql"]
                if names_only:
                    retry_sql = _project_names_only(retry_sql, table)
                retry_result = run_query(retry_sql)
                if retry_result["row_count"] > 0:
                    sql = retry_sql
                    db_result = retry_result
                    explanation = retry_ai["explanation"]
                    table = retry_ai.get("table", table)

        row_count = db_result["row_count"]
        narrative, extra_insights = build_narrative(
            effective_msg,
            company_id,
            scope_label,
            table,
            db_result["columns"],
            db_result["rows"],
            row_count,
        )

        names_list: list[str] = []
        if names_only and row_count > 0:
            seen: set[str] = set()
            for r in db_result["rows"]:
                if not r:
                    continue
                value = str(r[0]).strip()
                if not value or value.lower() in ("null", "none"):
                    continue
                key = value.lower()
                if key in seen:
                    continue
                seen.add(key)
                names_list.append(value)

        if names_only and names_list:
            display = names_list[:50]
            extra = max(len(names_list) - len(display), 0)
            bullet_lines = "\n".join(f"- {name}" for name in display)
            if extra:
                bullet_lines += f"\n- …and {extra} more"
            narrative = (
                f"Here are the **{len(names_list)} name(s)** for {scope_label}:\n\n"
                f"{bullet_lines}"
            )
            summary = f"Found {len(names_list)} name(s) for {scope_label}."
            extra_insights = [
                "Showing names only. Open the Detailed Report to see more columns."
            ]
        else:
            summary = (
                f"Found {row_count} record(s) for {scope_label}."
                if row_count
                else f"No records found for {scope_label}."
            )

        payload = {
            "success": True,
            "blocked": False,
            "intent": "SELECT",
            "sql": sql,
            "explanation": explanation,
            "summary": summary,
            "narrative": narrative,
            "insights": extra_insights,
            "columns": db_result["columns"],
            "rows": db_result["rows"],
            "row_count": row_count,
            "company": scope_label,
            "is_admin": is_admin,
            "method": method,
            "service_used": "Database Query",
            "route": "database_query",
            "detail_mode": "collapsed",
            "names_only": names_only,
            "names_list": names_list[:50] if names_only else [],
        }

        if row_count > 0 and db_result.get("columns"):
            remember_result(
                session_id,
                table=table,
                columns=db_result["columns"],
                rows=db_result["rows"],
                user_query=user_msg,
            )

        _attach_report(payload, user, company_id)
        remember_turn(session_id, user_msg, effective_msg, payload)
        log_payload(
            user=user,
            user_query=user_msg,
            effective_query=effective_msg,
            payload=payload,
            started_at=started_at,
        )
        return payload

    except Exception as e:
        log_query(
            user=user,
            user_query=user_msg,
            effective_query=effective_msg,
            intent=None,
            service_used=None,
            sql_used=None,
            started_at=started_at,
            success=False,
            error_message=str(e),
        )
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/cache/clear")
async def clear_cache(request: Request):
    admin = require_admin(request)
    if not admin:
        return JSONResponse({"success": False, "error": "Admin access required"}, status_code=403)
    try:
        database._MOCK_DATA = {}
        return {"success": True, "message": "Mock database cache cleared"}
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.get("/health")
async def health():
    return {"status": "ok", "database": "local-json-mocked", "model": OLLAMA_MODEL}


# ---------------------------------------------------
# FALLBACK: Serve static build assets
# ---------------------------------------------------
build_dir = BASE_DIR / "build-cable" / "build"
if not build_dir.is_dir():
    build_dir = Path("C:/Users/Lenovo/Downloads/build-cable/build")

if build_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(build_dir), html=True), name="build")
