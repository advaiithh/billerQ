# ─────────────────────────────────────────────
#  BillerQ Configuration
# ─────────────────────────────────────────────

# MySQL Database
DB_HOST     = "srv1145.hstgr.io"
DB_PORT     = 3306
DB_USER     = "u167254999_bqcustomerai"
DB_PASSWORD = "4U;iQ:3PG^v"
DB_NAME     = "u167254999_BqCustomerAi"

# Ollama
OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:7b"
OLLAMA_TIMEOUT_SEC = 4

# Auth — change these in production
SECRET_KEY       = "billerq-change-this-secret-in-production-2026"
SESSION_MAX_DAYS = 7

# Bootstrap admin (created automatically if no users exist)
ADMIN_EMAIL    = "admin@billerq.com"
ADMIN_PASSWORD = "admin123"
ADMIN_COMPANY_ID = 1
