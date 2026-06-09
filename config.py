# ─────────────────────────────────────────────
#  BillerQ Configuration
# ─────────────────────────────────────────────

import os

# MySQL Database
DB_HOST     = "srv1145.hstgr.io"
DB_PORT     = 3306
DB_USER     = "u167254999_bqcustomerai"
DB_PASSWORD = "4U;iQ:3PG^v"
DB_NAME     = "u167254999_BqCustomerAi"

# ─────────────────────────────────────────────
#  LLM provider
# ─────────────────────────────────────────────
# Which backend powers intent detection / SQL generation / summaries.
#   "ollama"  -> local Qwen via Ollama (default, good for local dev)
#   "bedrock" -> Amazon Bedrock (recommended for production)
LLM_PROVIDER = os.getenv("BILLERQ_LLM_PROVIDER", "ollama").strip().lower()

# Ollama
OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:7b"
OLLAMA_TIMEOUT_SEC = 15

# ─────────────────────────────────────────────
#  Amazon Bedrock (used when LLM_PROVIDER == "bedrock")
# ─────────────────────────────────────────────
# Credentials are resolved by boto3 (IAM role, env vars, or ~/.aws). Never
# hardcode AWS keys here. Override model IDs/region with env vars below.
AWS_REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))

# Tiered models: cheap "fast" tier for intent/entity/summary (runs on every
# prompt), stronger "smart" tier reserved for SQL generation and reports.
# Confirm the exact IDs enabled in YOUR region under Bedrock > Model access.
BEDROCK_MODEL_FAST  = os.getenv(
    "BEDROCK_MODEL_FAST", "us.anthropic.claude-3-5-haiku-20241022-v1:0"
)
BEDROCK_MODEL_SMART = os.getenv(
    "BEDROCK_MODEL_SMART", "us.anthropic.claude-3-5-sonnet-20241022-v2:0"
)
BEDROCK_TIMEOUT_SEC = int(os.getenv("BEDROCK_TIMEOUT_SEC", "30"))

# Auth — change these in production
SECRET_KEY       = "billerq-change-this-secret-in-production-2026"
SESSION_MAX_DAYS = 7

# Bootstrap admin (created automatically if no users exist)
ADMIN_EMAIL    = "admin@billerq.com"
ADMIN_PASSWORD = "admin123"
ADMIN_COMPANY_ID = 1