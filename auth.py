import sqlite3
import hashlib
import hmac
import json
import base64
import secrets
from datetime import datetime, timedelta
from pathlib import Path

from config import SECRET_KEY, SESSION_MAX_DAYS, ADMIN_EMAIL, ADMIN_PASSWORD, ADMIN_COMPANY_ID
from database import get_company_name

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "users.db"


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 120000
    ).hex()
    return f"{salt}${digest}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
        check = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), 120000
        ).hex()
        return hmac.compare_digest(check, digest)
    except Exception:
        return False


def get_sqlite_connection():
    conn = sqlite3.connect(str(DB_FILE))
    return conn


def init_auth_tables():
    conn = get_sqlite_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bq_app_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                company_id INTEGER NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                approved_at TIMESTAMP NULL,
                approved_by INTEGER NULL
            )
        """)
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def seed_admin_if_needed():
    conn = get_sqlite_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM bq_app_users")
        count = cursor.fetchone()[0]
        if count == 0:
            cursor.execute(
                """
                INSERT INTO bq_app_users
                    (email, password_hash, company_id, role, status, approved_at)
                VALUES (?, ?, ?, 'admin', 'approved', CURRENT_TIMESTAMP)
                """,
                (ADMIN_EMAIL.lower().strip(), _hash_password(ADMIN_PASSWORD), ADMIN_COMPANY_ID),
            )
            conn.commit()
    finally:
        cursor.close()
        conn.close()


def _row_to_user(row) -> dict:
    return {
        "id": row[0],
        "email": row[1],
        "company_id": row[2],
        "role": row[3],
        "status": row[4],
        "created_at": str(row[5]) if row[5] else None,
        "approved_at": str(row[6]) if row[6] else None,
        "company_name": get_company_name(row[2]),
    }


def get_user_by_email(email: str):
    conn = get_sqlite_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT id, email, company_id, role, status, created_at, approved_at
            FROM bq_app_users
            WHERE LOWER(email) = ?
            """,
            (email.lower().strip(),),
        )
        row = cursor.fetchone()
        return _row_to_user(row) if row else None
    finally:
        cursor.close()
        conn.close()


def get_user_by_id(user_id: int):
    conn = get_sqlite_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT id, email, company_id, role, status, created_at, approved_at
            FROM bq_app_users
            WHERE id = ?
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        return _row_to_user(row) if row else None
    finally:
        cursor.close()
        conn.close()


def get_password_hash(email: str) -> str | None:
    conn = get_sqlite_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT password_hash FROM bq_app_users WHERE LOWER(email) = ?",
            (email.lower().strip(),),
        )
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        cursor.close()
        conn.close()


def create_user(email: str, password: str, company_id: int) -> dict:
    email = email.lower().strip()
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters")

    conn = get_sqlite_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO bq_app_users (email, password_hash, company_id, role, status)
            VALUES (?, ?, ?, 'user', 'pending')
            """,
            (email, _hash_password(password), company_id),
        )
        conn.commit()
        user_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError("An account with this email already exists")
    except Exception as e:
        raise
    finally:
        cursor.close()
        conn.close()

    return get_user_by_id(user_id)


def authenticate_user(email: str, password: str) -> dict:
    email = email.lower().strip()
    stored = get_password_hash(email)
    if not stored or not _verify_password(password, stored):
        raise ValueError("Invalid email or password")

    user = get_user_by_email(email)
    if not user:
        raise ValueError("Invalid email or password")

    if user["status"] == "pending":
        raise ValueError(
            "Your account is pending admin approval. Please wait until an admin approves your signup."
        )
    if user["status"] == "rejected":
        raise ValueError(
            "Your signup request was rejected. Please contact the administrator."
        )

    return user


def create_session_token(user: dict) -> str:
    payload = {
        "uid": user["id"],
        "email": user["email"],
        "company_id": user["company_id"],
        "role": user["role"],
        "exp": (datetime.utcnow() + timedelta(days=SESSION_MAX_DAYS)).isoformat(),
    }
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload).encode()
    ).decode()
    sig = hmac.new(
        SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256
    ).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_session_token(token: str) -> dict | None:
    if not token or "." not in token:
        return None
    try:
        payload_b64, sig = token.rsplit(".", 1)
        expected = hmac.new(
            SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None

        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode()))
        if datetime.fromisoformat(payload["exp"]) < datetime.utcnow():
            return None

        user = get_user_by_id(payload["uid"])
        if not user or user["status"] != "approved":
            return None
        return user
    except Exception:
        return None


def list_pending_users():
    conn = get_sqlite_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT id, email, company_id, created_at
            FROM bq_app_users
            WHERE status = 'pending'
            ORDER BY created_at ASC
        """)
        rows = cursor.fetchall()
        return [
            {
                "id": r[0],
                "email": r[1],
                "company_id": r[2],
                "company_name": get_company_name(r[2]),
                "created_at": str(r[3]) if r[3] else None,
            }
            for r in rows
        ]
    finally:
        cursor.close()
        conn.close()


def approve_user(user_id: int, admin_id: int):
    conn = get_sqlite_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE bq_app_users
            SET status = 'approved', approved_at = datetime('now'), approved_by = ?
            WHERE id = ? AND status = 'pending'
            """,
            (admin_id, user_id),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise ValueError("User not found or already processed")
    finally:
        cursor.close()
        conn.close()


def reject_user(user_id: int, admin_id: int):
    conn = get_sqlite_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE bq_app_users
            SET status = 'rejected', approved_at = datetime('now'), approved_by = ?
            WHERE id = ? AND status = 'pending'
            """,
            (admin_id, user_id),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise ValueError("User not found or already processed")
    finally:
        cursor.close()
        conn.close()
