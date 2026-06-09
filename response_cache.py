"""
BillerQ Persistent Response Cache
==================================
Layer 1 — SQLite-backed, survives page reloads and server restarts.
Layer 2 — In-memory SQL cache, avoids re-calling Ollama for the same question.

Cache keys:   SHA-256( normalize(question) + "|" + str(company_id) )
TTL strategy:
  - "today" / "now" queries  →  2 minutes  (data changes frequently)
  - dashboard / count queries →  5 minutes
  - list / report queries     →  10 minutes
  - schema / context          →  1 hour (already in database.py)

Invalidation:
  - Per-company flush via invalidate_company(company_id)
  - Full flush via clear_all()
  - Automatic expiry on every get()
"""

import hashlib
import json
import sqlite3
import time
import re
from pathlib import Path

# ── paths ──────────────────────────────────────────────────────────────────────
_BASE_DIR = Path(__file__).resolve().parent
_CACHE_DB  = _BASE_DIR / "response_cache.db"

# ── TTL constants (seconds) ────────────────────────────────────────────────────
_TTL_REALTIME  =   120   # "today", "now", "right now"
_TTL_SHORT     =   300   # dashboard, counts, summaries
_TTL_MEDIUM    =   600   # list queries (customers, payments …)
_TTL_LONG      =  1800   # static-ish data (packages, areas …)

# ── in-memory SQL cache (Layer 2) ─────────────────────────────────────────────
_SQL_CACHE: dict[str, tuple[float, str]] = {}   # key → (expires_at, sql)
_SQL_TTL   = 600   # 10 minutes


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _normalize(text: str) -> str:
    """Lower-case, collapse whitespace, strip punctuation for stable keys."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text)


def _make_key(question: str, company_id: int | None) -> str:
    raw = _normalize(question) + "|" + str(company_id)
    return hashlib.sha256(raw.encode()).hexdigest()


def _choose_ttl(question: str) -> int:
    q = question.lower()
    if any(w in q for w in ("today", "now", "right now", "current", "live", "this hour")):
        return _TTL_REALTIME
    if any(w in q for w in ("dashboard", "snapshot", "overview", "how many", "count", "total", "summary")):
        return _TTL_SHORT
    if any(w in q for w in ("package", "plan", "area", "region", "vendor")):
        return _TTL_LONG
    return _TTL_MEDIUM


# ══════════════════════════════════════════════════════════════════════════════
# SQLITE INIT
# ══════════════════════════════════════════════════════════════════════════════

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_CACHE_DB), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_cache_db() -> None:
    """Create the cache table if it doesn't exist."""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS response_cache (
            cache_key   TEXT PRIMARY KEY,
            company_id  INTEGER,
            question    TEXT,
            payload     TEXT,
            created_at  REAL,
            expires_at  REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_company ON response_cache(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_expires ON response_cache(expires_at)")
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 1 — RESPONSE CACHE (SQLite)
# ══════════════════════════════════════════════════════════════════════════════

def get_cached_response(question: str, company_id: int | None) -> dict | None:
    """Return a cached full response payload, or None if missing/expired."""
    key = _make_key(question, company_id)
    now = time.time()
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT payload, expires_at FROM response_cache WHERE cache_key = ?",
            (key,)
        ).fetchone()
        conn.close()
        if row and row["expires_at"] > now:
            payload = json.loads(row["payload"])
            payload["_from_cache"] = True
            return payload
    except Exception:
        pass
    return None


def set_cached_response(question: str, company_id: int | None, payload: dict) -> None:
    """Persist a response payload to cache."""
    # Don't cache errors, blocked replies, or disambiguation prompts
    if not payload.get("success") or payload.get("blocked") or payload.get("needs_disambiguation"):
        return
    if payload.get("row_count", 0) == 0:
        return   # Don't cache empty results — data may just not exist yet

    key  = _make_key(question, company_id)
    ttl  = _choose_ttl(question)
    now  = time.time()

    # Strip report_url — it's ephemeral (in-memory store, different server run)
    safe_payload = {k: v for k, v in payload.items() if k != "report_url"}

    try:
        conn = _get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO response_cache
                (cache_key, company_id, question, payload, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (key, company_id, question, json.dumps(safe_payload, default=str), now, now + ttl))
        conn.commit()
        conn.close()
    except Exception:
        pass


def invalidate_company(company_id: int | None) -> int:
    """Delete all cached entries for a company. Returns rows deleted."""
    try:
        conn = _get_conn()
        cur = conn.execute(
            "DELETE FROM response_cache WHERE company_id = ? OR company_id IS NULL",
            (company_id,)
        )
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        return deleted
    except Exception:
        return 0


def clear_all() -> int:
    """Wipe the entire cache. Returns rows deleted."""
    try:
        conn = _get_conn()
        cur = conn.execute("DELETE FROM response_cache")
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        return deleted
    except Exception:
        return 0


def purge_expired() -> int:
    """Remove expired rows. Call this periodically (e.g. on startup)."""
    try:
        conn = _get_conn()
        cur = conn.execute(
            "DELETE FROM response_cache WHERE expires_at <= ?", (time.time(),)
        )
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        return deleted
    except Exception:
        return 0


def cache_stats() -> dict:
    """Return basic stats for the admin panel."""
    try:
        conn = _get_conn()
        total = conn.execute("SELECT COUNT(*) FROM response_cache").fetchone()[0]
        live  = conn.execute(
            "SELECT COUNT(*) FROM response_cache WHERE expires_at > ?", (time.time(),)
        ).fetchone()[0]
        conn.close()
        return {"total": total, "live": live, "expired": total - live}
    except Exception:
        return {"total": 0, "live": 0, "expired": 0}


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 2 — SQL CACHE (in-memory)
# ══════════════════════════════════════════════════════════════════════════════

def get_cached_sql(question: str, company_id: int | None) -> str | None:
    """Return a previously generated SQL string, or None if missing/expired."""
    key = _make_key(question, company_id)
    entry = _SQL_CACHE.get(key)
    if entry and entry[0] > time.time():
        return entry[1]
    return None


def set_cached_sql(question: str, company_id: int | None, sql: str) -> None:
    """Store a generated SQL string in memory."""
    if not sql:
        return
    key = _make_key(question, company_id)
    _SQL_CACHE[key] = (time.time() + _SQL_TTL, sql)


def clear_sql_cache() -> None:
    _SQL_CACHE.clear()
