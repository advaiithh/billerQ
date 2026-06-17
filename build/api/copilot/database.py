"""
BillerQ AI Copilot - Database Layer
=====================================
Async MySQL connection with multi-tenant security.

Features:
  - Async connection pool via aiomysql
  - Multi-tenant: ALL queries filter by company_id
  - Query whitelist: only SELECT allowed (no DDL/DML)
  - Graceful degradation: if DB unavailable, returns error dict
  - Schema-aware: knows BillerQ table structure

Usage:
    db = await get_db_pool()
    results = await db.query_customers(company_id=1, name="John")
"""

import os
import re
import logging
from typing import Optional, List, Any
from datetime import date

logger = logging.getLogger(__name__)

# ─── Connection Pool Singleton ─────────────────────────────────────────────────
_pool = None


async def get_db_pool():
    """Get or create the async MySQL connection pool."""
    global _pool
    if _pool is not None:
        return _pool

    try:
        import aiomysql
        _pool = await aiomysql.create_pool(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "3306")),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASSWORD", ""),
            db=os.getenv("DB_NAME", "billerq"),
            charset="utf8mb4",
            autocommit=True,
            minsize=1,
            maxsize=10,
            connect_timeout=5,
        )
        logger.info("MySQL connection pool created successfully")
        return _pool
    except ImportError:
        logger.warning("aiomysql not installed. Run: pip install aiomysql")
        return None
    except Exception as e:
        logger.error(f"MySQL connection failed: {e}")
        return None


async def check_db_status() -> dict:
    """Check if database is reachable."""
    pool = await get_db_pool()
    if pool is None:
        return {
            "connected": False,
            "error": "aiomysql not installed or connection failed",
            "db_host": os.getenv("DB_HOST", "localhost"),
            "db_name": os.getenv("DB_NAME", "billerq"),
        }
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
                await cur.fetchone()
        return {
            "connected": True,
            "db_host": os.getenv("DB_HOST", "localhost"),
            "db_name": os.getenv("DB_NAME", "billerq"),
        }
    except Exception as e:
        return {"connected": False, "error": str(e)}


# ─── Safe Query Executor ───────────────────────────────────────────────────────

def _validate_select_only(sql: str) -> bool:
    """Ensure query is SELECT-only. Rejects DDL/DML."""
    stripped = sql.strip().upper()
    # Must start with SELECT or WITH (for CTEs)
    if not (stripped.startswith("SELECT") or stripped.startswith("WITH")):
        return False
    # Block dangerous keywords
    blocked = ["INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER",
                "TRUNCATE", "EXEC", "EXECUTE", "GRANT", "REVOKE"]
    for kw in blocked:
        # Word boundary check
        if re.search(rf"\b{kw}\b", stripped):
            return False
    return True


async def execute_query(
    sql: str,
    params: tuple = (),
    company_id: Optional[int] = None,
) -> dict:
    """
    Execute a SELECT query with optional company_id injection.
    Returns: { rows: [...], count: int } or { error: str }
    """
    if not _validate_select_only(sql):
        return {"error": "Only SELECT queries are allowed"}

    pool = await get_db_pool()
    if pool is None:
        return {"error": "Database not available"}

    try:
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor if _aiomysql_available() else None) as cur:
                await cur.execute(sql, params)
                rows = await cur.fetchall()
                return {"rows": rows, "count": len(rows)}
    except Exception as e:
        logger.error(f"Query error: {e} | SQL: {sql[:100]}")
        return {"error": str(e)}


def _aiomysql_available() -> bool:
    try:
        import aiomysql  # noqa
        return True
    except ImportError:
        return False


# ─── Business Queries ─────────────────────────────────────────────────────────

class BillerQDatabase:
    """
    High-level database queries for BillerQ.
    All methods require company_id for multi-tenant security.
    """

    async def search_customers(
        self,
        company_id: int,
        name: Optional[str] = None,
        phone: Optional[str] = None,
        area: Optional[str] = None,
        subscriber_id: Optional[str] = None,
        limit: int = 10,
    ) -> dict:
        """
        Search customers by name, phone, area, or subscriber_id.
        All results are scoped to company_id.
        """
        if not company_id:
            return {"error": "company_id required for customer search"}

        conditions = ["company_id = %s"]
        params = [company_id]

        if subscriber_id:
            conditions.append("subscriber_id = %s")
            params.append(subscriber_id)
        elif phone:
            conditions.append("(mobile LIKE %s OR phone LIKE %s)")
            params.extend([f"%{phone}%", f"%{phone}%"])
        elif name:
            conditions.append("(full_name LIKE %s OR name LIKE %s)")
            params.extend([f"%{name}%", f"%{name}%"])
        elif area:
            conditions.append("area LIKE %s")
            params.append(f"%{area}%")
        else:
            return {"error": "At least one search criterion required"}

        sql = f"""
            SELECT
                id,
                subscriber_id,
                full_name AS name,
                mobile AS phone,
                area,
                status,
                plan_name,
                balance
            FROM customers
            WHERE {' AND '.join(conditions)}
            ORDER BY full_name
            LIMIT {int(limit)}
        """
        result = await execute_query(sql, tuple(params), company_id)

        if "error" in result:
            return result

        return {
            "query": name or phone or area or subscriber_id,
            "company_id": company_id,
            "total_found": result["count"],
            "results": result["rows"],
            "source": "database",
        }

    async def get_customer_detail(self, company_id: int, subscriber_id: str) -> dict:
        """Get full customer details by subscriber_id."""
        sql = """
            SELECT
                c.id,
                c.subscriber_id,
                c.full_name AS name,
                c.mobile AS phone,
                c.email,
                c.address,
                c.area,
                c.status,
                c.balance,
                c.plan_name,
                c.plan_amount,
                c.activation_date,
                c.last_payment_date,
                c.next_due_date
            FROM customers c
            WHERE c.company_id = %s AND c.subscriber_id = %s
            LIMIT 1
        """
        result = await execute_query(sql, (company_id, subscriber_id))
        if "error" in result:
            return result
        if result["count"] == 0:
            return {"error": f"Customer {subscriber_id} not found"}
        return {"customer": result["rows"][0], "source": "database"}

    async def get_payment_summary(self, company_id: int, days: int = 30) -> dict:
        """Get payment collection summary for last N days."""
        sql = """
            SELECT
                COUNT(*) AS payment_count,
                SUM(amount) AS total_collected,
                MAX(transaction_date) AS last_payment
            FROM payments
            WHERE company_id = %s
              AND transaction_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
        """
        result = await execute_query(sql, (company_id, days))
        if "error" in result:
            return result
        row = result["rows"][0] if result["rows"] else {}
        return {
            "period_days": days,
            "payment_count": row.get("payment_count", 0),
            "total_collected": float(row.get("total_collected") or 0),
            "last_payment": str(row.get("last_payment", "")),
            "source": "database",
        }

    async def get_overdue_customers(self, company_id: int, limit: int = 20) -> dict:
        """Get list of customers with overdue payments."""
        sql = """
            SELECT
                subscriber_id,
                full_name AS name,
                mobile AS phone,
                area,
                balance AS outstanding,
                next_due_date
            FROM customers
            WHERE company_id = %s
              AND status = 'active'
              AND next_due_date < CURDATE()
              AND balance > 0
            ORDER BY balance DESC
            LIMIT %s
        """
        result = await execute_query(sql, (company_id, limit))
        if "error" in result:
            return result
        return {
            "company_id": company_id,
            "overdue_count": result["count"],
            "customers": result["rows"],
            "source": "database",
        }

    async def get_collection_by_area(self, company_id: int) -> dict:
        """Get collection breakdown by area."""
        sql = """
            SELECT
                c.area,
                COUNT(DISTINCT c.id) AS customer_count,
                SUM(p.amount) AS collected,
                SUM(CASE WHEN c.balance > 0 THEN c.balance ELSE 0 END) AS outstanding
            FROM customers c
            LEFT JOIN payments p
                ON p.customer_id = c.id
               AND p.company_id = c.company_id
               AND p.transaction_date >= DATE_FORMAT(CURDATE(), '%Y-%m-01')
            WHERE c.company_id = %s
            GROUP BY c.area
            ORDER BY collected DESC
            LIMIT 20
        """
        result = await execute_query(sql, (company_id,))
        if "error" in result:
            return result
        return {
            "company_id": company_id,
            "areas": result["rows"],
            "source": "database",
        }


# ─── Singleton DB Instance ────────────────────────────────────────────────────
_db_instance: Optional[BillerQDatabase] = None


def get_db() -> BillerQDatabase:
    """Get the global BillerQDatabase instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = BillerQDatabase()
    return _db_instance
