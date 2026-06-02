from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ai import (
    natural_language_to_sql,
    generate_full_response
)

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
        # retry if no rows
        if db_result["row_count"] == 0:

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

        # AI Summary
        analysis = generate_full_response(
            user_msg,
            columns,
            rows
        )

        return {

            "success": True,

            "sql": sql,

            "explanation": explanation,

            "summary": analysis["summary"],

            "insights": analysis["insights"],

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


@app.get("/health")
async def health():

    try:

        conn = get_connection()

        conn.close()

        return {
            "status": "ok",
            "database": "connected",
            "model": "qwen2.5:7b"
        }

    except Exception as e:

        return JSONResponse(
            {
                "status": "error",
                "detail": str(e)
            },
            status_code=500
        )