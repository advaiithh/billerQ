import time
from typing import Any

from database import get_connection


def init_query_logging_table() -> None:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS bq_ai_query_logs (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NULL,
                company_id BIGINT UNSIGNED NULL,
                user_query TEXT NOT NULL,
                effective_query TEXT NULL,
                intent VARCHAR(80) NULL,
                service_used VARCHAR(120) NULL,
                sql_used TEXT NULL,
                response_time_ms INT NULL,
                row_count INT NULL,
                success TINYINT(1) NOT NULL DEFAULT 1,
                error_message TEXT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_company_created (company_id, created_at),
                INDEX idx_user_created (user_id, created_at),
                INDEX idx_intent (intent)
            )
            """
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def log_query(
    *,
    user: dict,
    user_query: str,
    effective_query: str,
    intent: str | None,
    service_used: str | None,
    sql_used: str | None,
    started_at: float,
    row_count: int | None = None,
    success: bool = True,
    error_message: str | None = None,
) -> None:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO bq_ai_query_logs
                (user_id, company_id, user_query, effective_query, intent, service_used,
                 sql_used, response_time_ms, row_count, success, error_message)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user.get("id"),
                user.get("company_id"),
                user_query,
                effective_query,
                intent,
                service_used,
                sql_used,
                int((time.perf_counter() - started_at) * 1000),
                row_count,
                1 if success else 0,
                error_message,
            ),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass


def log_payload(
    *,
    user: dict,
    user_query: str,
    effective_query: str,
    payload: dict[str, Any],
    started_at: float,
    success: bool = True,
    error_message: str | None = None,
) -> None:
    log_query(
        user=user,
        user_query=user_query,
        effective_query=effective_query,
        intent=payload.get("intent"),
        service_used=payload.get("service_used") or payload.get("method"),
        sql_used=payload.get("sql"),
        started_at=started_at,
        row_count=payload.get("row_count"),
        success=success,
        error_message=error_message,
    )
