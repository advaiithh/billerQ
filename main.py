from pathlib import Path
import re

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent

from ai import (
    natural_language_to_sql,
    generate_full_response
)
from auth import (
    init_db,
    create_user,
    get_user_by_email,
    create_session,
    get_session,
    list_pending_users,
    approve_user
)
from database import get_connection, run_query
import database
from fastapi import Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(
    title="BillerQ AI Assistant"
)


@app.on_event("startup")
def startup_event():
    # ensure auth DB exists
    init_db()

if STATIC_DIR.exists():
    app.mount(
        "/static",
        StaticFiles(directory=str(STATIC_DIR)),
        name="static"
    )


class ChatRequest(BaseModel):
    message: str


def current_user_from_request(request):
    token = request.cookies.get("session_token")
    if not token:
        return None
    return get_session(token)


def apply_company_filter(sql: str, company_id: int) -> str:
    """Naively inject company filter into simple SELECT queries for common tables."""
    sql = sql.strip()
    # Only handle simple SELECT ... FROM table [WHERE ...]
    m = re.match(r"SELECT\s+(.*?)\s+FROM\s+([a-zA-Z0-9_]+)([\s\S]*)", sql, re.IGNORECASE)
    if not m:
        return sql

    select_cols, table, rest = m.group(1), m.group(2), m.group(3)

    # tables that should be scoped by company_id
    scoped = {"customers", "orders", "payments", "customer_subscriptions", "customer_add_ons", "packages"}
    if table.lower() not in scoped:
        return sql

    # if WHERE exists, append AND company_id = X, else add WHERE company_id = X
    if re.search(r"\bWHERE\b", rest, re.IGNORECASE):
        rest = re.sub(r"\bWHERE\b", "WHERE", rest, flags=re.IGNORECASE)
        new_sql = f"SELECT {select_cols} FROM {table} {rest} AND company_id = {company_id}"
    else:
        new_sql = f"SELECT {select_cols} FROM {table} WHERE company_id = {company_id} {rest}"

    # Ensure semicolon
    if not new_sql.strip().endswith(";"):
        new_sql = new_sql.strip() + ";"

    return new_sql


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return RedirectResponse(url="/login")


@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    # Show login form with company dropdown
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM companies")
    companies = cur.fetchall()
    conn.close()
    return templates.TemplateResponse("login.html", {"request": request, "companies": companies})


@app.post("/login")
async def login_post(request: Request, company_id: int = Form(...), email: str = Form(...), password: str = Form(...)):
    user = get_user_by_email(email)
    if not user:
        return templates.TemplateResponse("login.html", {"request": request, "companies": [] , "error": "Invalid credentials"})
    # verify password
    from auth import verify_password
    if not verify_password(password, user["password_hash"]):
        return templates.TemplateResponse("login.html", {"request": request, "companies": [] , "error": "Invalid credentials"})
    if not user["approved"]:
        return templates.TemplateResponse("login.html", {"request": request, "companies": [] , "error": "Account pending approval"})

    token = create_session(user)
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie("session_token", token, httponly=True)
    return response


@app.get("/signup", response_class=HTMLResponse)
async def signup_get(request: Request):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM companies")
    companies = cur.fetchall()
    conn.close()
    return templates.TemplateResponse("signup.html", {"request": request, "companies": companies})


@app.post("/signup")
async def signup_post(request: Request, company_id: int = Form(...), email: str = Form(...), password: str = Form(...)):
    # create user as pending (approved=0)
    init_db()
    existing = get_user_by_email(email)
    if existing:
        return templates.TemplateResponse("signup.html", {"request": request, "companies": [] , "error": "Email already exists"})

    # For simplicity, create user as pending
    uid = create_user(email, password, company_id, is_admin=False, approved=False)
    return templates.TemplateResponse("signup.html", {"request": request, "companies": [], "message": "Signup submitted — awaiting admin approval"})


@app.get("/admin", response_class=HTMLResponse)
async def admin_get(request: Request):
    token = request.cookies.get("session_token")
    user = get_session(token) if token else None
    if not user or not user.get("is_admin"):
        return RedirectResponse(url="/login")
    users = list_pending_users()
    return templates.TemplateResponse("admin.html", {"request": request, "users": users})


@app.post("/admin/approve")
async def admin_approve(request: Request, user_id: int = Form(...)):
    token = request.cookies.get("session_token")
    user = get_session(token) if token else None
    if not user or not user.get("is_admin"):
        return RedirectResponse(url="/login")
    approve_user(int(user_id))
    return RedirectResponse(url="/admin")


@app.post("/chat")
async def chat(body: ChatRequest, request: Request):
    # auth: get session from cookie
    token = request.cookies.get("session_token")
    user = get_session(token) if token else None

    user_msg = body.message.strip()

    if not user_msg:

        return JSONResponse(
            {
                "success": False,
                "error": "Empty message"
            },
            status_code=400
        )

    try:

        # AI → SQL
        ai_result = natural_language_to_sql(
            user_msg
        )

        sql = ai_result["sql"]

        explanation = ai_result["explanation"]

        # Apply company scoping if user is logged in
        if user and user.get("company_id"):
            try:
                sql = apply_company_filter(sql, int(user.get("company_id")))
            except Exception:
                pass

        db_result = run_query(sql)
        
        # SKIP EXPENSIVE RETRY - only retry if result is empty and user asked for specific data
        if db_result["row_count"] == 0 and any(word in user_msg.lower() for word in ["show", "get", "find", "list"]):

            retry_prompt = f"""
            The SQL returned 0 rows.

            Original user request:
            {user_msg}

            SQL used:
            {sql}

            Try again using similar database values.
            """

            retry_ai = natural_language_to_sql(
                retry_prompt
            )

            retry_sql = retry_ai["sql"]

            retry_result = run_query(retry_sql)

            if retry_result["row_count"] > 0:

                sql = retry_sql
                db_result = retry_result

        columns = db_result["columns"]

        rows = db_result["rows"]

        row_count = db_result["row_count"]

        # SKIP expensive AI summary - generate simple summary instead
        if row_count > 0:
            summary = f"Found {row_count} record(s) matching your query."
            insights = []
            
            # Quick heuristics for insights
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

            "row_count": row_count
        }

    except Exception as e:

        return JSONResponse(
            {
                "success": False,
                "error": str(e)
            },
            status_code=500
        )


@app.post("/analyze")
async def analyze(body: ChatRequest):
    """Generate AI analysis for previously fetched results"""
    try:
        from ai import generate_full_response
        
        user_msg = body.message.strip()
        
        if not user_msg:
            return JSONResponse(
                {
                    "success": False,
                    "error": "Empty message"
                },
                status_code=400
            )
        
        # This endpoint is for getting AI-powered analysis
        # Client would pass raw results to analyze
        return {
            "success": True,
            "message": "Use /chat endpoint for complete analysis"
        }
    
    except Exception as e:
        return JSONResponse(
            {
                "success": False,
                "error": str(e)
            },
            status_code=500
        )


@app.post("/cache/clear")
async def clear_cache():
    """Clear database schema and context caches"""
    try:
        database._SCHEMA_CACHE = None
        database._SCHEMA_CACHE_TIME = 0
        database._BUSINESS_CONTEXT_CACHE = None
        database._BUSINESS_CONTEXT_CACHE_TIME = 0
        
        return {
            "success": True,
            "message": "Cache cleared successfully"
        }
    except Exception as e:
        return JSONResponse(
            {
                "success": False,
                "error": str(e)
            },
            status_code=500
        )


@app.get("/health")
async def health():

    try:

        conn = get_connection()

        conn.close()

        return {
            "status": "ok",
            "database": "connected",
            "model": "qwen2.5:7b "
        }

    except Exception as e:

        return JSONResponse(
            {
                "status": "error",
                "detail": str(e)
            },
            status_code=500
        )


    @app.get("/me")
    async def me(request: Request):
        """Return authentication status for the current visitor (uses session cookie)."""
        token = request.cookies.get("session_token")
        user = get_session(token) if token else None
        if not user:
            return {"authenticated": False}
        return {"authenticated": True, "user": {"id": user.get("id"), "email": user.get("email"), "company_id": user.get("company_id"), "is_admin": user.get("is_admin")}}