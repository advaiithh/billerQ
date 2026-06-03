from pathlib import Path

from fastapi import FastAPI, Request, Depends, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ai import natural_language_to_sql
from config import OLLAMA_MODEL

import database
from database import run_query, get_connection, get_companies, get_company_name, resolve_query_company_scope
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

app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "static")),
    name="static",
)

SESSION_COOKIE = "bq_session"


@app.on_event("startup")
async def startup():
    init_auth_tables()
    seed_admin_if_needed()


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


@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    if get_current_user(request):
        return RedirectResponse(url="/app", status_code=302)
    html_file = BASE_DIR / "templates" / "login.html"
    return HTMLResponse(content=html_file.read_text(encoding="utf-8"))


@app.get("/app", response_class=HTMLResponse)
async def app_page(request: Request):
    if not get_current_user(request):
        return RedirectResponse(url="/", status_code=302)
    html_file = BASE_DIR / "templates" / "index.html"
    return HTMLResponse(content=html_file.read_text(encoding="utf-8"))


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


@app.post("/chat")
async def chat(body: ChatRequest, request: Request):
    user = require_user(request)
    if not user:
        return JSONResponse(
            {"success": False, "error": "Please log in to continue"},
            status_code=401,
        )

    user_msg = body.message.strip()
    is_admin = user["role"] == "admin"

    company_id, scope_label = resolve_query_company_scope(user_msg, user)

    if not user_msg:
        return JSONResponse({"success": False, "error": "Empty message"}, status_code=400)

    try:
        ai_result = natural_language_to_sql(user_msg, company_id=company_id)
        sql = ai_result["sql"]
        explanation = ai_result["explanation"]
        method = ai_result.get("method", "rules")

        db_result = run_query(sql)

        if (
            db_result["row_count"] == 0
            and method == "rules"
            and any(w in user_msg.lower() for w in ["show", "get", "find", "list"])
        ):
            retry_ai = natural_language_to_sql(
                f"{user_msg} (include all matching statuses, use correct column names)",
                company_id=company_id,
            )
            retry_sql = retry_ai["sql"]
            if retry_sql != sql:
                retry_result = run_query(retry_sql)
                if retry_result["row_count"] > 0:
                    sql = retry_sql
                    db_result = retry_result
                    explanation = retry_ai["explanation"]

        row_count = db_result["row_count"]

        if row_count > 0:
            summary = f"Found {row_count} record(s) for {scope_label}."
            insights = []
            q = user_msg.lower()
            if "customer" in q and row_count > 1:
                insights.append(f"{row_count} customer records for {scope_label}")
            elif "payment" in q and row_count > 1:
                insights.append(f"{row_count} payment records for {scope_label}")
            elif ("order" in q or "invoice" in q) and row_count > 1:
                insights.append(f"{row_count} invoice/order records for {scope_label}")
        else:
            summary = f"No records found for {scope_label} matching your query."
            insights = []

        return {
            "success": True,
            "sql": sql,
            "explanation": explanation,
            "summary": summary,
            "insights": insights,
            "columns": db_result["columns"],
            "rows": db_result["rows"],
            "row_count": row_count,
            "company": scope_label,
            "is_admin": is_admin,
        }

    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/cache/clear")
async def clear_cache(request: Request):
    admin = require_admin(request)
    if not admin:
        return JSONResponse({"success": False, "error": "Admin access required"}, status_code=403)
    try:
        database._SCHEMA_CACHE = None
        database._SCHEMA_CACHE_TIME = 0
        database._COLUMNS_CACHE = None
        database._COLUMNS_CACHE_TIME = 0
        database._BUSINESS_CONTEXT_CACHE = None
        database._BUSINESS_CONTEXT_CACHE_TIME = 0
        database._COMPANIES_LIST_CACHE = None
        database._COMPANIES_LIST_CACHE_TIME = 0
        return {"success": True, "message": "Cache cleared successfully"}
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.get("/health")
async def health():
    try:
        conn = get_connection()
        conn.close()
        return {"status": "ok", "database": "connected", "model": OLLAMA_MODEL}
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)
