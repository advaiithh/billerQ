from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ai import (
    natural_language_to_sql,
    generate_full_response
)

import database
from database import (
    run_query,
    get_connection
)

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="BillerQ AI Assistant"
)

app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "static")),
    name="static"
)


class ChatRequest(BaseModel):
    message: str


@app.get("/", response_class=HTMLResponse)
async def home():

    html_file = (
        BASE_DIR
        / "templates"
        / "index.html"
    )

    return HTMLResponse(
        content=html_file.read_text(
            encoding="utf-8"
        )
    )


@app.post("/chat")
async def chat(body: ChatRequest):

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

        # Execute SQL
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