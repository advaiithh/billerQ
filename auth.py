import sqlite3
import os
import hashlib
import secrets
from typing import Optional, Dict

DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            password_hash TEXT,
            company_id INTEGER,
            is_admin INTEGER DEFAULT 0,
            approved INTEGER DEFAULT 0
        )
        """
    )
    conn.commit()
    conn.close()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(8)
    h = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return f"{salt}${h}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        salt, h = password_hash.split("$", 1)
        return hashlib.sha256((salt + password).encode("utf-8")).hexdigest() == h
    except Exception:
        return False


def create_user(email: str, password: str, company_id: int, is_admin: bool = False, approved: bool = False):
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (email, password_hash, company_id, is_admin, approved) VALUES (?, ?, ?, ?, ?)",
            (email, hash_password(password), company_id, 1 if is_admin else 0, 1 if approved else 0)
        )
        conn.commit()
        return cur.lastrowid
    except Exception:
        return None
    finally:
        conn.close()


def get_user_by_email(email: str) -> Optional[Dict]:
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = ?", (email,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def count_users() -> int:
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    n = cur.fetchone()[0]
    conn.close()
    return n


def list_pending_users():
    init_db()
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM users WHERE approved = 0 AND is_admin = 0 ORDER BY id"
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def approve_user(user_id: int):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET approved = 1 WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()


# Simple in-memory session store (token -> user info)
SESSIONS = {}


def create_session(user: Dict, company_name: str = "") -> str:
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = {
        "id": user["id"],
        "email": user["email"],
        "company_id": user["company_id"],
        "company_name": company_name,
        "is_admin": bool(user["is_admin"]),
    }
    return token


def get_session(token: str) -> Optional[Dict]:
    return SESSIONS.get(token)


def logout_session(token: str):
    if token in SESSIONS:
        del SESSIONS[token]
