from pathlib import Path
import re

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent

from ai import natural_language_to_sql, generate_full_response
from auth import (
    init_db,
    create_user,
    get_user_by_email,
    create_session,
    get_session,
    list_pending_users,
    approve_user,
    verify_password,
    logout_session,
    count_users,
)
from database import get_connection, run_query
import database

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="BillerQ AI Assistant")

COMPANY_SCOPED_TABLES = {
    "customers",
    "orders",
    "payments",
    "customer_subscriptions",
    "customer_add_ons",
    "packages",
    "complaints",
    "enquiries",
    "stbs",
    "expenses",
    "incomes",
}


@app.on_event("startup")
def startup_event():
    init_db()
    print("BillerQ routes: /login  /signup  /app  /admin  (open http://127.0.0.1:8001/login)")


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class ChatRequest(BaseModel):
    message: str


def fetch_companies():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM companies ORDER BY name")
    companies = cur.fetchall()
    conn.close()
    return companies


def company_name_by_id(company_id: int) -> str:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT name FROM companies WHERE id = %s", (company_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else f"Company #{company_id}"


def current_user_from_request(request: Request):
    token = request.cookies.get("session_token")
    if not token:
        return None
    return get_session(token)


def require_user(request: Request):
    user = current_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def apply_company_filter(sql: str, company_id: int) -> str:
    """Inject company filter into simple SELECT queries."""
    sql = sql.strip().rstrip(";")
    m = re.match(
        r"SELECT\s+(.*?)\s+FROM\s+([a-zA-Z0-9_]+)([\s\S]*)",
        sql,
        re.IGNORECASE,
    )
    if not m:
        return sql + ";"

    select_cols, table, rest = m.group(1), m.group(2), m.group(3)
    table_lower = table.lower()

    if table_lower == "companies":
        clause = f"id = {int(company_id)}"
    elif table_lower in COMPANY_SCOPED_TABLES:
        clause = f"company_id = {int(company_id)}"
    else:
        return sql + ";"

    if re.search(r"\bWHERE\b", rest, re.IGNORECASE):
        if re.search(r"\bcompany_id\b", rest, re.IGNORECASE) or (
            table_lower == "companies" and re.search(r"\bid\b", rest, re.IGNORECASE)
        ):
            return sql + ";"
        new_sql = f"SELECT {select_cols} FROM {table} {rest} AND {clause}"
    else:
        new_sql = f"SELECT {select_cols} FROM {table} WHERE {clause} {rest}"

    return new_sql.strip() + ";"


def render_login(request: Request, error: str = None, message: str = None):
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "companies": fetch_companies(),
            "error": error,
            "message": message,
        },
    )


def render_signup(request: Request, error: str = None, message: str = None):
    return templates.TemplateResponse(
        "signup.html",
        {
            "request": request,
            "companies": fetch_companies(),
            "is_first_user": count_users() == 0,
            "error": error,
            "message": message,
        },
    )


def render_admin_login(request: Request, error: str = None):
    return templates.TemplateResponse(
        "admin_login.html",
        {"request": request, "error": error},
    )


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    user = current_user_from_request(request)
    if user:
        return RedirectResponse(url="/app", status_code=302)
    return RedirectResponse(url="/login", status_code=302)


@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    if current_user_from_request(request):
        return RedirectResponse(url="/app", status_code=302)
    return render_login(request)


@app.get("/admin-login", response_class=HTMLResponse)
async def admin_login_get(request: Request):
    # if already logged in as admin, go to admin
    user = current_user_from_request(request)
    if user and user.get("is_admin"):
        return RedirectResponse(url="/admin", status_code=302)
    return render_admin_login(request)


@app.post("/login")
async def login_post(
    request: Request,
    company_id: int = Form(...),
    email: str = Form(...),
    password: str = Form(...),
):
    email = email.strip().lower()
    user = get_user_by_email(email)
    if not user or not verify_password(password, user["password_hash"]):
        return render_login(request, error="Invalid email or password.")
    if int(user["company_id"]) != int(company_id):
        return render_login(request, error="Selected company does not match your account.")
    if not user["approved"]:
        return render_login(
            request,
            error="Your account is pending admin approval. Please try again later.",
        )

    name = company_name_by_id(int(company_id))
    token = create_session(user, name)
    response = RedirectResponse(url="/app", status_code=302)
    response.set_cookie("session_token", token, httponly=True, samesite="lax")
    return response


@app.post("/admin-login")
async def admin_login_post(request: Request, email: str = Form(...), password: str = Form(...)):
    email = email.strip().lower()
    user = get_user_by_email(email)
    if not user or not verify_password(password, user["password_hash"]):
        return render_admin_login(request, error="Invalid email or password.")
    if not user.get("is_admin"):
        return render_admin_login(request, error="Account is not an administrator.")
    if not user.get("approved"):
        return render_admin_login(request, error="Admin account pending approval.")

    token = create_session(user, "")
    response = RedirectResponse(url="/admin", status_code=302)
    response.set_cookie("session_token", token, httponly=True, samesite="lax")
    return response


@app.get("/signup", response_class=HTMLResponse)
async def signup_get(request: Request):
    if current_user_from_request(request):
        return RedirectResponse(url="/app", status_code=302)
    is_first = count_users() == 0
    return templates.TemplateResponse(
        "signup.html",
        {
            "request": request,
            "companies": fetch_companies(),
            "is_first_user": is_first,
            "error": None,
            "message": None,
        },
    )


@app.post("/signup")
async def signup_post(
    request: Request,
    company_id: int = Form(...),
    email: str = Form(...),
    password: str = Form(...),
):
    email = email.strip().lower()
    is_first = count_users() == 0

    if get_user_by_email(email):
        return render_signup(request, error="An account with this email already exists.")

    if len(password) < 6:
        return render_signup(request, error="Password must be at least 6 characters.")

    if is_first:
        uid = create_user(
            email, password, company_id, is_admin=True, approved=True
        )
        if not uid:
            return render_signup(request, error="Could not create account. Try again.")
        return render_signup(
            request,
            message="Administrator account created. You can log in now and approve other signups.",
        )

    uid = create_user(
        email, password, company_id, is_admin=False, approved=False
    )
    if not uid:
        return render_signup(request, error="Could not create account. Try again.")
    return render_signup(
        request,
        message="Signup submitted. An administrator must approve your account before you can log in.",
    )


@app.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("session_token")
    if token:
        logout_session(token)
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("session_token")
    return response


@app.get("/app", response_class=HTMLResponse)
async def app_home(request: Request):
    user = current_user_from_request(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "user": user},
    )


@app.get("/admin", response_class=HTMLResponse)
async def admin_get(request: Request):
    user = current_user_from_request(request)
    if not user or not user.get("is_admin"):
        return RedirectResponse(url="/login", status_code=302)

    pending = list_pending_users()
    for u in pending:
        u["company_name"] = company_name_by_id(int(u["company_id"]))

    companies = fetch_companies()

    return templates.TemplateResponse(
        "admin.html",
        {"request": request, "users": pending, "admin": user, "companies": companies},
    )


@app.post("/admin/approve")
async def admin_approve(request: Request, user_id: int = Form(...)):
    user = current_user_from_request(request)
    if not user or not user.get("is_admin"):
        return RedirectResponse(url="/login", status_code=302)
    approve_user(int(user_id))
    return RedirectResponse(url="/admin", status_code=302)


@app.get("/me")
async def me(request: Request):
    user = current_user_from_request(request)
    if not user:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "user": {
            "id": user.get("id"),
            "email": user.get("email"),
            "company_id": user.get("company_id"),
            "company_name": user.get("company_name"),
            "is_admin": user.get("is_admin"),
        },
    }


@app.post("/chat")
async def chat(body: ChatRequest, request: Request):
    user = current_user_from_request(request)
    if not user:
        return JSONResponse(
            {"success": False, "error": "Please log in to continue."},
            status_code=401,
        )

    user_msg = body.message.strip()
    if not user_msg:
        return JSONResponse(
            {"success": False, "error": "Empty message"},
            status_code=400,
        )

    company_id = int(user["company_id"])

    try:
        ai_result = natural_language_to_sql(user_msg)
        sql = apply_company_filter(ai_result["sql"], company_id)
        explanation = ai_result["explanation"]

        db_result = run_query(sql)

        if db_result["row_count"] == 0 and any(
            word in user_msg.lower()
            for word in ["show", "get", "find", "list"]
        ):
            retry_prompt = f"""
            The SQL returned 0 rows.

            Original user request:
            {user_msg}

            SQL used:
            {sql}

            Try again using similar database values.
            """
            retry_ai = natural_language_to_sql(retry_prompt)
            retry_sql = apply_company_filter(retry_ai["sql"], company_id)
            retry_result = run_query(retry_sql)
            if retry_result["row_count"] > 0:
                sql = retry_sql
                db_result = retry_result

        columns = db_result["columns"]
        rows = db_result["rows"]
        row_count = db_result["row_count"]

        if row_count > 0:
            summary = f"Found {row_count} record(s) for your company."
            insights = []
            if "customer" in user_msg.lower() and row_count > 1:
                insights.append(f"{row_count} customers retrieved")
            elif "payment" in user_msg.lower() and row_count > 1:
                insights.append(f"{row_count} payment records retrieved")
        else:
            summary = "No records found matching your query."
            insights = []

        return {
            "success": True,
            "sql": sql,
            "explanation": explanation,
            "summary": summary,
            "insights": insights,
            "columns": columns,
            "rows": rows,
            "row_count": row_count,
        }

    except Exception as e:
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


@app.post("/analyze")
async def analyze(body: ChatRequest, request: Request):
    require_user(request)
    try:
        user_msg = body.message.strip()
        if not user_msg:
            return JSONResponse(
                {"success": False, "error": "Empty message"},
                status_code=400,
            )
        return {
            "success": True,
            "message": "Use /chat endpoint for complete analysis",
        }
    except Exception as e:
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


@app.post("/cache/clear")
async def clear_cache(request: Request):
    require_user(request)
    try:
        database._SCHEMA_CACHE = None
        database._SCHEMA_CACHE_TIME = 0
        database._BUSINESS_CONTEXT_CACHE = None
        database._BUSINESS_CONTEXT_CACHE_TIME = 0
        return {"success": True, "message": "Cache cleared successfully"}
    except Exception as e:
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


@app.get("/health")
async def health():
    try:
        conn = get_connection()
        conn.close()
        return {
            "status": "ok",
            "database": "connected",
            "model": "qwen2.5:7b ",
        }
    except Exception as e:
        return JSONResponse(
            {"status": "error", "detail": str(e)},
            status_code=500,
        )
