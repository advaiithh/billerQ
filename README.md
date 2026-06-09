# BillerQ AI Assistant

A **read-only**, AI-assisted chat interface for exploring BillerQ billing data stored in **MySQL**. Users log in, ask questions in plain English, and receive SQL-backed tables with plain-English summaries — scoped to their company.

**Stack:** FastAPI · MySQL · Ollama (Qwen 2.5 7B) · Jinja2 · LangChain (memory buffer)

---

## Table of contents

1. [What this project does](#what-this-project-does)
2. [High-level architecture](#high-level-architecture)
3. [Project structure (every file)](#project-structure-every-file)
4. [Complete system overview (how everything works)](#complete-system-overview-how-everything-works)
5. [Signup, login, approval & user blocking](#signup-login-approval--user-blocking)
6. [User account lifecycle (states)](#user-account-lifecycle-states)
7. [Admin approval workflow](#admin-approval-workflow)
8. [Sessions, roles & company access](#sessions-roles--company-access)
9. [Chat blocking (read-only enforcement)](#chat-blocking-read-only-enforcement)
10. [How a chat message is processed](#how-a-chat-message-is-processed)
11. [Intent classification (understanding the prompt)](#intent-classification-understanding-the-prompt)
12. [Natural language → SQL](#natural-language--sql)
13. [Company data scoping](#company-data-scoping)
14. [Running queries safely](#running-queries-safely)
15. [Summaries & plain-English narratives](#summaries--plain-english-narratives)
16. [Frontend (what users see)](#frontend-what-users-see)
17. [Caching & performance](#caching--performance)
18. [Ollama / model — how it fits in](#ollama--model--how-it-fits-in)
19. [Setup (local)](#setup-local)
20. [Hosting as a public website](#hosting-as-a-public-website)
21. [API reference](#api-reference)
22. [Example walkthroughs](#example-walkthroughs)
23. [Security model](#security-model)
24. [Troubleshooting](#troubleshooting)
25. [Configuration reference](#configuration-reference)

---

## What this project does

| Capability | Description |
|------------|-------------|
| **Natural language queries** | "Show inactive customers", "Overdue invoices", etc. |
| **Intent awareness** | Greetings, help, add/update/delete, and data questions are handled differently |
| **Read-only** | Only `SELECT` runs; writes are blocked before SQL is built |
| **Multi-company** | Each user belongs to one company; data is filtered by `company_id` |
| **Admin workflow** | New signups need admin approval before login |
| **Summaries** | Text under the table explains totals, statuses, and amounts without reading every row |
| **Quick chips** | One-click buttons for the most common reports (fast, rule-based) |

**What it is not:** a CRM, a customer editor, or a general chatbot. It **views and reports** existing billing data only.

---

## High-level architecture

```
┌──────────────┐
│   Browser    │  login.html  →  index.html (chat)
└──────┬───────┘
       │ HTTP (cookies: bq_session)
       ▼
┌──────────────────────────────────────────────────────────┐
│  main.py (FastAPI)                                        │
│  • Auth routes (/auth/*)                                  │
│  • Admin routes (/admin/*)                                │
│  • POST /chat → orchestrates ai + database + summaries    │
└──────┬─────────────────────────────┬───────────────────────┘
       │                             │
       ▼                             ▼
┌─────────────┐              ┌──────────────┐
│   ai.py     │              │ database.py  │
│ • intent    │              │ • MySQL      │
│ • NL→SQL    │              │ • validate   │
│ • Ollama    │              │ • company    │
└──────┬──────┘              │   filter     │
       │                     └──────┬───────┘
       │  (optional)                │
       ▼                              ▼
┌─────────────┐              ┌──────────────┐
│   Ollama    │              │    MySQL     │
│ qwen2.5:7b  │              │  BillerQ DB  │
│  :11434     │              │  (remote)    │
└─────────────┘              └──────────────┘

Also used:
  auth.py      → users in bq_app_users (MySQL)
  summaries.py → plain-English text from results
  config.py    → credentials & settings
```

---

## Project structure (every file)

| File | Responsibility |
|------|----------------|
| **`main.py`** | FastAPI app: routes, session checks, `/chat` pipeline, health |
| **`ai.py`** | Intent classification, table detection, rule-based SQL, Ollama SQL generation |
| **`database.py`** | MySQL connection, schema cache, business context, `validate_sql`, `run_query`, `inject_company_filter` |
| **`auth.py`** | `bq_app_users` table, signup/login, HMAC sessions, approve/reject |
| **`summaries.py`** | Builds narrative paragraphs + insight bullets from query results |
| **`config.py`** | DB host, Ollama URL/model, `SECRET_KEY`, bootstrap admin |
| **`memory.py`** | LangChain `ConversationBufferMemory` (stores Q/SQL pairs; not yet fed back into prompts) |
| **`templates/login.html`** | Login + Sign Up tabs, company dropdown, calls `/auth/*` |
| **`templates/index.html`** | Chat UI, chips, admin panel, renders SQL/table/summary |
| **`run.bat`** | Windows launcher: install deps, free ports, start uvicorn |
| **`requirements.txt`** | Python dependencies |
| **`test_fixes.py`** | Manual sanity script for SQL generation |

Legacy / unused in main flow: `templates/admin.html`, `templates/signup.html`, `users.db` (old SQLite auth).

---

## Complete system overview (how everything works)

BillerQ has **three layers** that work together:

```
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 1 — ACCESS CONTROL (who can use the app)                 │
│  Signup → pending → admin approves/rejects → login → session      │
└───────────────────────────────┬─────────────────────────────────┘
                                │ only approved users pass
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 2 — DATA ISOLATION (what company data they see)            │
│  Regular user: always their company_id                            │
│  Admin: all companies, or one company if named in the query     │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 3 — CHAT / AI (what questions are allowed)                 │
│  Intent check → SELECT only → SQL + table + summary             │
│  Greetings / add / update / delete → blocked with message       │
└─────────────────────────────────────────────────────────────────┘
```

### First-time deployment flow

```
Server starts (uvicorn main:app)
    ↓
startup(): init_auth_tables()     → creates bq_app_users in MySQL if missing
startup(): seed_admin_if_needed() → if table empty, inserts bootstrap admin
    ↓
Admin logs in with ADMIN_EMAIL / ADMIN_PASSWORD from config.py
    ↓
Admin approves team signups from the app
    ↓
Approved users log in and query their company data
```

### Daily user flow

```
Open site → /login → log in → /app → ask question or click chip → see table + summary
```

---

## Signup, login, approval & user blocking

This section explains **account-level** control: who can register, who can log in, and how admins manage access.

### Sign up (new user registration)

**Where:** `templates/login.html` → **Sign Up** tab  
**API:** `POST /auth/signup`

#### Step-by-step (what happens in code)

| Step | What happens |
|------|----------------|
| 1 | Page loads → `GET /companies` fetches active companies from MySQL (`companies` table, `status='active'`, not deleted) |
| 2 | User selects **company**, enters **email** + **password** (min 6 chars) |
| 3 | Browser sends `POST /auth/signup` with `{ email, password, company_id }` |
| 4 | `auth.create_user()` hashes password (PBKDF2-SHA256), inserts row into `bq_app_users` |
| 5 | New row defaults: `role='user'`, **`status='pending'`** |
| 6 | Success message shown: *"pending admin approval"* — user is **not** logged in automatically |
| 7 | UI switches to Login tab after ~2.5 seconds |

#### Signup validation & errors

| Check | Error if fails |
|-------|----------------|
| Company selected | `"Please select a company"` |
| Password length ≥ 6 | `"Password must be at least 6 characters"` |
| Email not already used | `"An account with this email already exists"` |
| MySQL insert | 500 error |

#### Important: signup does NOT grant access

A signed-up user is **blocked from the app** until an admin approves them. They exist in the database with `status='pending'` but cannot get a valid session.

---

### Login

**Where:** `templates/login.html` → **Login** tab  
**API:** `POST /auth/login`

| Step | What happens |
|------|----------------|
| 1 | User enters email + password |
| 2 | `auth.authenticate_user()` looks up email, verifies password hash |
| 3 | **Status check** — see table below |
| 4 | If approved: `create_session_token()` → cookie `bq_session` set (7 days, HTTP-only) |
| 5 | Browser redirects to `/app` |

#### Login blocked by user status

| `status` | Can log in? | Message shown |
|----------|-------------|---------------|
| **`pending`** | No | *"Your account is pending admin approval. Please wait until an admin approves your signup."* |
| **`rejected`** | No | *"Your signup request was rejected. Please contact the administrator."* |
| **`approved`** | Yes | Redirect to `/app` |

Wrong email/password always returns: *"Invalid email or password"* (same message for both — does not reveal if email exists).

---

### Bootstrap admin (first user ever)

On **first server startup** when `bq_app_users` is **empty**:

```
seed_admin_if_needed() inserts ONE admin:
  email      = ADMIN_EMAIL     (config.py, default admin@billerq.com)
  password   = ADMIN_PASSWORD  (config.py, default admin123)
  company_id = ADMIN_COMPANY_ID (config.py, default 1)
  role       = admin
  status     = approved  ← can log in immediately, no approval needed
```

After this, **all new signups** (including future admins) go through `pending` unless you manually change the DB. Only the auto-seeded first admin skips approval.

---

## User account lifecycle (states)

Every app user is always in exactly one state:

```
                    ┌──────────────┐
         Sign up    │   PENDING    │  Cannot log in
        ──────────▶ │              │  Cannot use /chat
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              │ Admin      │            │ Admin
              │ Approve    │            │ Reject
              ▼            │            ▼
       ┌──────────────┐    │     ┌──────────────┐
       │  APPROVED    │    │     │  REJECTED    │
       │  Can log in  │    │     │  Cannot log  │
       │  Can use chat│    │     │  in ever     │
       └──────────────┘    │     └──────────────┘
                           │
                    (stays pending until
                     admin acts)
```

### Database record (`bq_app_users`)

| Column | Purpose |
|--------|---------|
| `id` | Primary key |
| `email` | Unique login (stored lowercase) |
| `password_hash` | `salt$digest` — PBKDF2-SHA256, 120,000 iterations |
| `company_id` | FK to `companies.id` — **locks user to one company** |
| `role` | `admin` or `user` |
| `status` | `pending` \| `approved` \| `rejected` |
| `created_at` | Signup timestamp |
| `approved_at` | When admin approved/rejected (NULL while pending) |
| `approved_by` | Admin user `id` who approved/rejected |

Table is created on startup in the **same MySQL database** as BillerQ business data (`auth.init_auth_tables()`).

---

## Admin approval workflow

Only users with `role='admin'` **and** `status='approved'` can approve or reject signups.

### Where admin manages users

**UI:** `/app` (chat page) → header button **"Pending Signups"** → panel slides open  
**Not** a separate `/admin` page in the current main flow — it's built into `index.html`.

### Step-by-step: approving a user

| Step | Action | API / code |
|------|--------|------------|
| 1 | Admin logs in at `/login` | `POST /auth/login` |
| 2 | Header shows **Pending Signups** (admins only) | `GET /auth/me` returns `role: admin` |
| 3 | Admin clicks **Pending Signups** | `GET /admin/pending` |
| 4 | List shows: email, company name, request date | `auth.list_pending_users()` — `status='pending'` only |
| 5 | Admin clicks **Approve** | `POST /admin/approve` `{ user_id }` |
| 6 | DB update: `status='approved'`, `approved_at=NOW()`, `approved_by=admin_id` | `auth.approve_user()` |
| 7 | User can now log in | `authenticate_user()` passes status check |

### Step-by-step: rejecting (blocking) a user

| Step | Action | API / code |
|------|--------|------------|
| 1–4 | Same as approve — admin opens pending list | |
| 5 | Admin clicks **Reject** → confirm dialog | `POST /admin/reject` `{ user_id }` |
| 6 | DB update: `status='rejected'`, `approved_at`, `approved_by` | `auth.reject_user()` |
| 7 | User **permanently blocked** from login with rejection message | |

Rejected users are **not deleted** — their row stays for audit. They cannot log in unless an admin manually changes `status` in the database.

### Admin API protection

| Endpoint | Non-admin response |
|----------|-------------------|
| `GET /admin/pending` | `403 Admin access required` |
| `POST /admin/approve` | `403 Admin access required` |
| `POST /admin/reject` | `403 Admin access required` |

`require_admin()` checks: valid session **and** `user.role == 'admin'`.

### Pending list on page load

When an admin opens `/app`, `loadPending()` runs automatically so the admin can see if requests are waiting (panel opens on click).

---

## Sessions, roles & company access

### Session cookie (`bq_session`)

Created on successful login only (approved users):

```
Token = base64(JSON payload) + "." + HMAC-SHA256 signature

Payload contains:
  uid, email, company_id, role, exp (expiry datetime)
```

| Property | Value |
|----------|-------|
| Cookie name | `bq_session` |
| HTTP-only | Yes (JavaScript cannot read it) |
| SameSite | `lax` |
| Max age | 7 days (`SESSION_MAX_DAYS`) |

### Session verification (`verify_session_token`)

On every protected request:

1. Split token → verify HMAC with `SECRET_KEY`
2. Check expiry
3. Reload user from DB by `uid`
4. **Reject if `status != 'approved'`** — even a stolen old token fails if user was rejected

### Logout

`POST /auth/logout` → deletes `bq_session` cookie → redirect to login.

### Route protection

| Route | Unauthenticated visitor |
|-------|-------------------------|
| `/`, `/login`, `/signup` | Login page (redirect to `/app` if already logged in) |
| `/app` | Redirect to `/` (login) |
| `/chat` | `401 Please log in to continue` |
| `/auth/me` | `401 Not authenticated` |

### Roles & data visibility

| Role | Chat data scope | Admin panel |
|------|-----------------|-------------|
| **user** | Only their `company_id` — customers, invoices, payments, etc. | Hidden |
| **admin** | All companies by default; filter if company name in query | Pending Signups visible |

**Company dropdown at signup** determines which company's data the user will see after approval. It does **not** change at login — stored in `bq_app_users.company_id` forever (unless DB is edited).

---

## Chat blocking (read-only enforcement)

Separate from **user account blocking** (pending/rejected). This blocks **dangerous chat requests** from logged-in users.

### Two types of "blocking"

| Type | Who | When | User sees |
|------|-----|------|-----------|
| **Account block** | Pending/rejected users | At login | Error on login form |
| **Intent block** | Any logged-in user | At `/chat` | Yellow box: INSERT/UPDATE/DELETE not allowed |
| **Conversational** | Any logged-in user | Greetings like `hi` | Green box: friendly reply, no SQL |

### Chat intent blocking flow

```
User sends message to POST /chat
    ↓
classify_intent() in ai.py
    ↓
┌─────────┬──────────┬──────────┬─────────┐
│ OTHER   │ INSERT   │ UPDATE   │ DELETE  │  → blocked: true, sql: null
│ (hi)    │ (add…)   │ (edit…)  │ (remove)│
└─────────┴──────────┴──────────┴─────────┘
    ↓ only SELECT continues
natural_language_to_sql() → build SQL
    ↓
validate_sql() → only SELECT allowed
    ↓
run_query() on MySQL
```

### Blocked message examples

| User says | Intent | Response |
|-----------|--------|----------|
| `hi` | OTHER | Green: *"Hi! I'm the BillerQ assistant…"* |
| `add customer named Usha` | INSERT | Yellow: *"read-only — cannot add records"* |
| `update customer email` | UPDATE | Yellow: *"cannot update"* |
| `delete invoice 5` | DELETE | Yellow: *"cannot delete"* |
| `show inactive customers` | SELECT | Normal table + summary |

### Why both intent block AND SQL validator?

1. **Intent layer** — stops write *requests* early (better UX, no useless SQL)
2. **`validate_sql()`** — safety net if Ollama returns `INSERT`/`UPDATE` anyway

---

## How a chat message is processed

Full pipeline inside `POST /chat` (`main.py`) — **only for approved, logged-in users**:

```
1. require_user()           — cookie valid? else 401
2. resolve_query_company_scope() — which company_id to filter?
3. natural_language_to_sql()   — intent + SQL (ai.py)
4. If blocked/conversational   — return message, no SQL
5. run_query(sql)              — database.py
6. Optional retry              — if 0 rows + list-style query, retry with AI hint
7. build_narrative()           — summaries.py
8. Return JSON to frontend
```

---

## How a chat message is processed

Full pipeline inside `POST /chat` (`main.py`):

```
1. require_user()           — cookie valid? else 401
2. resolve_query_company_scope() — which company_id to filter?
3. natural_language_to_sql()   — intent + SQL (ai.py)
4. If blocked/conversational   — return message, no SQL
5. run_query(sql)              — database.py
6. Optional retry              — if 0 rows + list-style query, retry with AI hint
7. build_narrative()           — summaries.py
8. Return JSON to frontend
```

---

## Intent classification (understanding the prompt)

**Problem solved:** Without this, messages like `hi` or `add customer named Usha` would incorrectly run `SELECT * FROM customers`.

### Step 1 — Rule-based classifier (`ai._classify_intent_rules`)

Checks in order:

1. Empty → `OTHER`
2. Conversational (`hi`, `hello`, `thanks`, `help`, …) → `OTHER`
3. Chip phrases (`show all customers`, …) → `SELECT`
4. DDL (`CREATE TABLE`, …) → `DDL`
5. Write keywords (`add`, `create`, `insert`, …) → `INSERT`
6. Update keywords → `UPDATE`
7. Delete keywords → `DELETE`
8. Read patterns (`show`, `list`, `how many`, …) → `SELECT`
9. Billing data keywords present → `SELECT`
10. Otherwise → `OTHER` (not a data question)

### Step 2 — Ollama classifier (optional)

For ambiguous messages, Qwen is asked for **one word**: `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `DDL`, or `OTHER`.

- Timeout: `OLLAMA_TIMEOUT_SEC` (15s)
- If Ollama is down, rules decide

### Outcomes

| Intent | User sees | SQL runs? |
|--------|-----------|-----------|
| `SELECT` | Table + summary | Yes |
| `OTHER` | Green friendly message (`hi`, help) | No |
| `INSERT` | Yellow blocked — read-only | No |
| `UPDATE` | Yellow blocked | No |
| `DELETE` | Yellow blocked | No |
| `DDL` | Yellow blocked | No |

---

## Natural language → SQL

Only runs when intent = `SELECT`.

### A. Pick the table (`_find_best_table`)

Keyword map in `ai.TABLE_MAPPINGS` — examples:

| User says | Table |
|-----------|-------|
| customer, subscriber | `customers` |
| invoice, bill, order | `orders` |
| payment | `payments` |
| subscription | `customer_subscriptions` |
| package, product | `packages` |
| complaint | `complaints` |

Longest keyword match wins.

### B. Rules path (fast) — `_use_rules_only`

Used for:

- Exact **chip** phrases
- Short queries (≤8–10 words) with clear data keywords
- Status words: active, inactive, overdue, pending, paid, top, recent, …

`_build_sql_from_query()` builds SQL templates:

| Pattern | Example SQL logic |
|---------|-------------------|
| inactive | `WHERE status = 'inactive'` (checked before `active`) |
| overdue + orders | `due_date < NOW() AND payment_status != 'paid'` |
| top N | `ORDER BY order_total DESC LIMIT N` |
| recent/latest | `ORDER BY created_at DESC` |
| count / how many | `SELECT COUNT(*)` |
| default | `SELECT *` with soft-delete filter |

Uses live schema via `table_has_column()` for correct column names (`order_total` on orders, not `amount`).

### C. Ollama path (complex questions) — `_try_ollama_sql`

When rules are not used, the prompt sent to Qwen includes:

1. Full **database schema** (`SHOW TABLES` + `DESCRIBE`)
2. **Business context** — sample status values from DB
3. **Column mappings** — e.g. orders use `order_total`
4. **Company scope rules** — mandatory `company_id` filter for regular users
5. User question + likely table

Model returns SQL; app extracts `SELECT ...` from the response.

### D. Post-processing

- `inject_company_filter()` — adds `company_id = X` and `deleted_at IS NULL`
- `validate_sql()` — blocks non-SELECT
- `run_query()` — executes on MySQL

### Method labels in responses

| `method` | Meaning |
|----------|---------|
| `rules` | Chip or keyword template |
| `ai` | Ollama generated SQL |
| `rules-fallback` | Ollama failed, used rules |

---

## Company data scoping

### Regular user

Every query is scoped to `user.company_id` via `inject_company_filter()`.

Tables with `company_id` column: customers, orders, payments, customer_subscriptions, packages, complaints, enquiries, stbs, expenses, incomes, etc.

For `companies` table: `WHERE id = {company_id}`.

### Admin user

`database.resolve_query_company_scope()`:

- Default: **all companies** (no `company_id` filter)
- If query mentions a company name → filter to that company
- Phrases like "all companies" → explicitly no filter

### Soft deletes

Where `deleted_at` exists: `deleted_at IS NULL` is appended automatically.

---

## Running queries safely

`database.validate_sql()` enforces:

- Must start with `SELECT`
- Blocks: `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `CREATE`, `GRANT`, `REVOKE`

Even if Ollama returns bad SQL, execution is blocked.

**Defence in depth:**

1. Intent layer blocks write *requests*
2. SQL validator blocks write *statements*
3. MySQL user can be read-only in production (recommended)

---

## Summaries & plain-English narratives

`summary` = one-line count ("Found 10 records for Amazon.")

`narrative` = paragraph under the table (**"In plain English"** section) — built by `summaries.py` without calling Ollama (fast).

### How narratives are built

1. Optionally runs **one aggregate query** (`fetch_table_stats`) for context
2. Analyzes returned rows (status counts, sum of amounts)
3. Produces human text by query type

| Query type | Narrative example |
|------------|-------------------|
| Inactive customers | "10 inactive shown — out of 150 total, 120 active, 30 inactive" |
| Overdue invoices | Count + **₹** outstanding total |
| Active subscriptions | Active vs inactive totals |
| Payments | Count + sum of amounts + status mix |
| Generic | Row count + status breakdown if available |

`insights` = short bullet points (e.g. "% inactive", "unpaid balance").

---

## Frontend (what users see)

### `login.html`

- Tabs: **Login** | **Sign Up**
- Sign up: company dropdown from `GET /companies`
- Login: email + password
- Note about default admin credentials (dev)

### `index.html`

- Header: company name, email, admin **Pending Signups**, Logout
- Chat messages: user bubble (green) + bot bubble (dark)
- Bot response sections:
  1. **Summary** (green box)
  2. **Generated SQL** (blue monospace) — audit what ran
  3. **Results** table
  4. **In plain English** (narrative)
  5. **Key points** (insights)
- **Chips** — 8 quick queries
- Blocked writes: yellow box + intent tag
- Greetings: green chat box, no SQL

---

## Caching & performance

| Cache | TTL | Location |
|-------|-----|----------|
| Table schema | 1 hour | `database._SCHEMA_CACHE` |
| Column map | 1 hour | `database._COLUMNS_CACHE` |
| Business context | 1 hour | `database._BUSINESS_CONTEXT_CACHE` |
| Companies list | 1 hour | `database._COMPANIES_LIST_CACHE` |

Admin can clear via `POST /cache/clear`.

**Speed tips built in:**

- Chips always use rules (no Ollama wait)
- Intent uses rules first; Ollama only when needed
- Summaries use SQL aggregates, not a second LLM call
- Retry to Ollama only when rules return 0 rows on list queries

---

## Ollama / model — how it fits in

Ollama is a **local model server**. BillerQ talks to it over HTTP.

```
config.OLLAMA_URL = "http://localhost:11434/api/generate"
config.OLLAMA_MODEL = "qwen2.5:7b"
```

### When Ollama is used

1. **Intent classification** — ambiguous messages
2. **SQL generation** — non-chip, complex questions

### When Ollama is NOT used

- Chip buttons
- Short clear queries (rules)
- Greetings / blocked intents
- Summaries

### Must Ollama stay running?

| Scenario | Ollama required? |
|----------|------------------|
| Local dev, full features | **Yes** (install + `ollama pull qwen2.5:7b`) |
| Chips + simple queries only | No |
| Production VPS | Yes, as a **background service** on same or another server |

If Ollama is stopped: app still runs; complex questions fall back to basic rules.

---

## LLM provider — Ollama or Amazon Bedrock

All LLM calls (intent classification + SQL generation) go through a single
provider-agnostic helper, `llm_client.generate()`. The backend is selected at
runtime, so the rest of the codebase never changes when you switch models.

```
config.LLM_PROVIDER = "ollama"   # local Qwen via Ollama (default)
config.LLM_PROVIDER = "bedrock"  # Amazon Bedrock (recommended for production)
```

Set it with the `BILLERQ_LLM_PROVIDER` environment variable.

### Tiered models (cost control)

`generate()` takes a `tier` so cheap work doesn't pay for an expensive model:

| Tier | Used for | Default Bedrock model |
|------|----------|------------------------|
| `fast` | intent / entity / summary (every prompt) | Claude 3.5 Haiku |
| `smart` | SQL generation, reports, insights | Claude 3.5 Sonnet |

The cheapest alternative is **Amazon Nova Lite/Micro** for the `fast` tier.
Embeddings (future semantic search): **Amazon Titan Text Embeddings V2**.

### Bedrock configuration (env vars)

| Variable | Default | Purpose |
|----------|---------|---------|
| `BILLERQ_LLM_PROVIDER` | `ollama` | `ollama` or `bedrock` |
| `AWS_REGION` | `us-east-1` | Region where Bedrock models are enabled |
| `BEDROCK_MODEL_FAST` | `us.anthropic.claude-3-5-haiku-20241022-v1:0` | fast-tier model id |
| `BEDROCK_MODEL_SMART` | `us.anthropic.claude-3-5-sonnet-20241022-v2:0` | smart-tier model id |
| `BEDROCK_TIMEOUT_SEC` | `30` | per-call read timeout |

> Confirm the exact model IDs enabled in **your** region under
> Bedrock → Model access. Many Claude models require a cross-region
> **inference profile** id (the `us.` / `eu.` / `apac.` prefix).

### AWS credentials

`boto3` resolves credentials automatically — **never hardcode AWS keys**:

- On AWS (EC2/ECS/Lambda): attach an **IAM role** with `bedrock:InvokeModel`
  and `bedrock:Converse` permissions.
- Locally: `aws configure` or export `AWS_ACCESS_KEY_ID` /
  `AWS_SECRET_ACCESS_KEY` / `AWS_REGION`.

### Switch to Bedrock (quick start)

```bash
pip install -r requirements.txt          # installs boto3
export AWS_REGION=us-east-1               # your region
export BILLERQ_LLM_PROVIDER=bedrock
# (ensure AWS credentials are available to boto3)
```

Token usage is logged per Bedrock call (logger `billerq.llm`) so you can track
cost. If a Bedrock call fails, the app degrades gracefully to the rules engine,
exactly like the Ollama fallback.

---

## Setup (local)

### Requirements

- Python 3.10+
- MySQL (BillerQ database — can be remote)
- Ollama (recommended)

### Steps

```bash
# 1. Clone / open project
cd billerq

# 2. Install Ollama + model
ollama pull qwen2.5:7b

# 3. Edit config.py (see Configuration reference)

# 4. Install & run
pip install -r requirements.txt
# Windows: double-click run.bat
# Or:
uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# 5. Browser
http://127.0.0.1:8000/login
```

---

## Hosting as a public website

You need these running:

| Service | Port | Always on? |
|---------|------|------------|
| BillerQ (uvicorn) | 8000 (behind Nginx) | Yes |
| Ollama | 11434 | Yes (if using AI) |
| MySQL | 3306 | Yes (usually remote) |

### Single VPS (recommended)

1. Linux VPS, **8 GB+ RAM** for Qwen 7B
2. `systemctl enable ollama && systemctl start ollama`
3. Run uvicorn with systemd/supervisor (no `--reload`)
4. Nginx reverse proxy + HTTPS
5. `OLLAMA_URL = "http://127.0.0.1:11434/api/generate"`

### Split deployment

- Small web server: FastAPI only
- GPU/big server: Ollama only
- Set `OLLAMA_URL` to internal IP; firewall to app server only

### Production checklist

- [ ] Change `SECRET_KEY`, `ADMIN_PASSWORD`
- [ ] HTTPS
- [ ] Read-only MySQL user for app
- [ ] Never commit secrets
- [ ] Ollama as systemd service
- [ ] Remove `--reload` in production

---

## API reference

### Pages

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/`, `/login`, `/signup` | No | Login page |
| GET | `/app` | Yes | Chat UI |

### Auth

| Method | Path | Body | Description |
|--------|------|------|-------------|
| GET | `/companies` | — | Active companies for signup |
| POST | `/auth/signup` | `{email, password, company_id}` | Register (pending) |
| POST | `/auth/login` | `{email, password}` | Login, sets cookie |
| POST | `/auth/logout` | — | Clear session |
| GET | `/auth/me` | — | Current user |

### Admin

| Method | Path | Body | Description |
|--------|------|------|-------------|
| GET | `/admin/pending` | — | Pending signups |
| POST | `/admin/approve` | `{user_id}` | Approve |
| POST | `/admin/reject` | `{user_id}` | Reject |

### Chat

| Method | Path | Body | Description |
|--------|------|------|-------------|
| POST | `/chat` | `{message}` | NL query pipeline |
| POST | `/cache/clear` | — | Clear schema caches (admin) |
| GET | `/health` | — | DB + model name |

### Chat response fields

| Field | Description |
|-------|-------------|
| `success` | Request OK |
| `blocked` | No SQL (greeting or write blocked) |
| `conversational` | Friendly chat response |
| `intent` | SELECT, OTHER, INSERT, … |
| `sql` | Generated query (null if blocked) |
| `summary` | One-line count |
| `narrative` | Plain-English paragraph |
| `insights` | Bullet points |
| `columns`, `rows`, `row_count` | Table data |
| `company` | Scope label |
| `method` | rules / ai / rules-fallback |

---

## Example walkthroughs

### Scenario A — First deploy (admin sets up the system)

```
1. Developer runs run.bat / uvicorn
2. startup() creates bq_app_users table
3. seed_admin_if_needed() — table empty → inserts admin@billerq.com (approved, role=admin)
4. Admin opens http://127.0.0.1:8000/login
5. Logs in: admin@billerq.com / admin123 (from config.py)
6. Lands on /app — header shows "All Companies · Admin"
7. Admin is ready to approve team members
```

### Scenario B — Employee signs up and gets approved

```
1. Employee opens /login → Sign Up tab
2. Selects company "Amazon" (company_id=28), email user@amazon.com, password
3. POST /auth/signup → row inserted: status=pending, role=user
4. Green message: "pending admin approval" → switched to Login tab
5. Employee tries to log in → BLOCKED: "pending admin approval"
6. Admin logs in → Pending Signups → sees user@amazon.com · Amazon
7. Admin clicks Approve → status=approved
8. Employee logs in → cookie set → /app
9. Employee asks "inactive customers" → SQL filtered: company_id=28 only
10. Sees only Amazon data, not other companies
```

### Scenario C — Admin rejects a signup

```
1. Unknown person signs up with company X
2. Admin opens Pending Signups → Reject → confirms
3. status=rejected in database
4. Person tries login → "Your signup request was rejected"
5. Person cannot access /app or /chat ever (unless DB manually fixed)
```

### Scenario D — Approved user tries to add data via chat

```
1. User logged in, company_id=28
2. Types: "add customer named Usha"
3. Intent: INSERT → blocked before SQL
4. Yellow box: read-only assistant, use main BillerQ admin panel
5. No row created in customers table
```

### Example 1 — `hi`

```
User: "hi"
→ Intent: OTHER (conversational)
→ Response: "Hi! I'm the BillerQ assistant..."
→ SQL: none
```

### Example 2 — `add customer named Usha`

```
User: "add one more customer named usha"
→ Intent: INSERT (rules detect "add" + "customer" + "named")
→ Response: "This assistant is read-only — cannot add records..."
→ SQL: none
```

### Example 3 — Chip: Inactive customers

```
User: clicks "Inactive customers"
→ Intent: SELECT
→ Table: customers
→ Method: rules
→ SQL: SELECT * FROM customers WHERE status='inactive' AND company_id=X AND deleted_at IS NULL
→ Narrative: "10 inactive shown — out of 150 total, 120 active, 30 inactive"
```

### Example 4 — Complex question (Ollama)

```
User: "customers in Mumbai with pending payments last month"
→ Intent: SELECT (Ollama may confirm)
→ Method: ai
→ Ollama builds JOIN/filter SQL from schema
→ Company filter injected
→ Results + narrative
```

---

## Security model

| Layer | Mechanism |
|-------|-----------|
| **Signup gate** | New users start `pending` — zero app access until admin approves |
| **Rejection** | Rejected users cannot log in; session verify also checks `status=approved` |
| **Authentication** | HMAC session cookie, PBKDF2 passwords (120k iterations) |
| **Authorization** | Admin vs user roles; admin-only `/admin/*` endpoints return 403 |
| **Route guard** | `/app` and `/chat` require valid approved session |
| **Intent gate** | Blocks write *requests* (add/update/delete) before SQL |
| **SQL validator** | Blocks write *statements* even if LLM misbehaves |
| **Company isolation** | `company_id` injected into queries for regular users |
| **LLM exposure** | Schema + sample enum values only — not full data dumps in prompts |
| **HTTPS** | Required in production (reverse proxy) |

### Who can do what (summary)

| Action | Guest | Pending user | Rejected user | Approved user | Admin |
|--------|-------|--------------|---------------|---------------|-------|
| View login page | Yes | Yes | Yes | Yes | Yes |
| Sign up | Yes | — | — | — | — |
| Log in | No | No | No | Yes | Yes |
| Use /chat | No | No | No | Yes (own company) | Yes (all cos.) |
| Approve signups | No | No | No | No | Yes |
| Add data via chat | — | — | — | **Blocked** | **Blocked** |

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| No login page on :8000 | Old server process | Run `run.bat` (may use :8002) or restart PC |
| `hi` shows customer table | Old code / cache | Restart server, Ctrl+F5 browser |
| Generic/wrong SQL | Ollama off | Start Ollama, `ollama pull qwen2.5:7b` |
| Slow responses | Ollama cold start | Use chips; keep Ollama running |
| Pending login | Not approved yet | Admin → Pending Signups → Approve |
| "Signup rejected" on login | Admin rejected account | Contact admin; or update `status` in `bq_app_users` |
| No Pending Signups button | Logged in as regular user | Only `role=admin` sees it |
| 401 on /chat | Session expired / not logged in | Log in again at `/login` |
| Wrong company data | Admin sees all | Normal for admin; users are scoped |
| Duplicate `company_id` in SQL | Filter injected twice | Cosmetic; results still correct |

---

## Configuration reference

All settings in `config.py`:

```python
# MySQL
DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

# Ollama
OLLAMA_URL          # default http://localhost:11434/api/generate
OLLAMA_MODEL        # default qwen2.5:7b
OLLAMA_TIMEOUT_SEC  # default 15

# Auth
SECRET_KEY          # HMAC signing — change in production
SESSION_MAX_DAYS    # cookie lifetime

# Bootstrap admin (only if bq_app_users is empty)
ADMIN_EMAIL
ADMIN_PASSWORD
ADMIN_COMPANY_ID
```

---

## Quick reference — data tables BillerQ understands

| Business concept | MySQL table |
|------------------|-------------|
| Customers / subscribers | `customers` |
| Invoices / orders | `orders` |
| Payments | `payments` |
| Subscriptions | `customer_subscriptions` |
| Packages / products | `packages` |
| Companies / LCOs | `companies` |
| Complaints | `complaints` |
| Leads / enquiries | `enquiries` |
| Vendors | `vendors` |
| Add-ons | `customer_add_ons` |
| STBs / devices | `stbs` |
| Expenses / incomes | `expenses`, `incomes` |

---

## License

Internal BillerQ project — adjust as needed for your organisation.
