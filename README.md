# BillerQ AI Assistant

A **read-only**, AI-assisted chat interface for exploring BillerQ billing data stored in **MySQL**. Users log in, ask questions in plain English, and receive SQL-backed tables with plain-English summaries — scoped to their company. A floating **Copilot widget** embedded in the dashboard answers KPI questions from live API data and forwards all other questions to the AI backend.

**Stack:** FastAPI · MySQL · Ollama (Qwen 2.5 7B) · React (build) · LangChain (memory buffer)

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
17. [**Chatbot Copilot widget — how it works**](#chatbot-copilot-widget--how-it-works)
18. [Caching & performance](#caching--performance)
19. [Ollama / model — how it fits in](#ollama--model--how-it-fits-in)
20. [Setup (local)](#setup-local)
21. [Hosting as a public website](#hosting-as-a-public-website)
22. [API reference](#api-reference)
23. [Example walkthroughs](#example-walkthroughs)
24. [Security model](#security-model)
25. [Troubleshooting](#troubleshooting)
26. [Configuration reference](#configuration-reference)

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

## Chatbot Copilot widget — how it works

The floating **BillerQ Copilot** button lives in `build-cable/build/index.html` and is injected into the React single-page app shell that serves **every route** (`/`, `/login`, `/signup`, `/app`). Because the same HTML file is served for all routes, careful auth-gating is needed so the chatbot only appears **after the user has signed in**.

---

### 1 — Why the widget is hidden before login

The floating button (`#bq-chatbot-btn`) is rendered with `display: none` in CSS from the very first paint. A JavaScript function `bqInitAuth()` is registered on `window.load` and calls `GET /auth/me` with the session cookie.

```
Page loads (any route: /, /login, /signup, /app)
  ↓
bqInitAuth()  →  GET /auth/me  (sends bq_session cookie)
  ↓
401 Not authenticated          → button stays hidden (display:none)
  ↓ OR
200 { success: true, user: … } → button.style.display = 'flex'  ← visible
                                → header label set to company or 'Admin · all companies'
                                → bqLoadDashboardData() called in background
```

**Result:** The copilot button is **invisible on the login and signup screens**. It only appears when a valid, approved session cookie exists — i.e. after a successful login redirect to `/app`.

---

### 2 — Opening the chat and the welcome message

Clicking the floating button calls `bqToggleChat()`, which adds/removes the `.open` class on `#bq-chatbot-box`.

- On the **first open**, a welcome message is injected into the chat body:
  - Greets the user by their email prefix
  - States which company's data is in scope (or "all companies" for admin)
- On subsequent opens (or re-opens), the existing chat history is preserved
- Dashboard data is **refreshed** every time the chat is opened via `bqLoadDashboardData()`

---

### 3 — Loading live dashboard data

`bqLoadDashboardData()` runs immediately after auth is confirmed and again on every chat open. It fetches **the same API endpoints the React dashboard uses** in parallel:

| Key stored | API endpoint | Data returned |
|------------|-------------|---------------|
| `invoice` | `GET /get-invoice-amount` | `{ invoice, due, collection, percentage }` |
| `connections` | `GET /get-connection-data` | `{ cable, broadband, iptv }` |
| `customerStatus` | `GET /get-customer-status-wise-count` | `{ active, inactive, total }` |
| `recentPayments` | `GET /get-recent-payment` | Array of `{ name, amount, payment_date }` |
| `recentOrders` | `GET /get-recent-order` | Array of `{ product, price, prdouctstatus }` |
| `stbStatus` | `GET /stb-status-count` | `{ active, inactive }` |

All results are stored in the `bqDashboardData` object in memory. The fetches use `Promise.allSettled` so a single failing endpoint never breaks the others.

---

### 4 — The two-path response system

Every message the user sends goes through **two decision layers** before a response is shown:

```
User types message → bqSendText(text)
         │
         ▼
 ┌───────────────────────────────────────────────┐
 │ Step 1: bqCheckDashboardIntent(text)          │
 │                                               │
 │ Regex-matches the user's text against         │
 │ dashboard KPI topics:                         │
 │   invoice / collection / amount               │
 │   connection / cable / broadband / iptv       │
 │   customer count (non-list question)          │
 │   stb / set-top-box                           │
 │   recent payment / recent order               │
 │   dashboard / summary / overview / snapshot   │
 │                                               │
 │ If MATCHED → return pre-built HTML from       │
 │ bqDashboardData (no network call needed)      │
 └───────────┬───────────────────────────────────┘
             │ not matched
             ▼
 ┌───────────────────────────────────────────────┐
 │ Step 2: POST /chat  { message: text }         │
 │                                               │
 │ Full BillerQ AI pipeline:                     │
 │   intent classify → SQL → run_query           │
 │   → narrative/summary → JSON response         │
 │                                               │
 │ Widget renders narrative + mini data table    │
 └───────────────────────────────────────────────┘
```

#### Path 1 — Dashboard API (fast, no AI)

When `bqCheckDashboardIntent` matches, the chatbot shows a **stat card grid** or **mini table** built directly from `bqDashboardData`. This path:
- Responds in ~400 ms (artificial typing delay for UX)
- Uses no Ollama, no SQL
- Always shows current numbers (data was fetched on open)

Example triggers:
| User types | Response source |
|---|---|
| `What is today's collection?` | `bqDashboardData.invoice` |
| `Show connection summary` | `bqDashboardData.connections` |
| `How many active customers?` | `bqDashboardData.customerStatus` |
| `Recent payments` | `bqDashboardData.recentPayments` table |
| `Show dashboard summary` | All KPIs combined in a grid |

#### Path 2 — BillerQ AI `/chat` (full pipeline)

When the intent doesn't match a dashboard KPI, the message is forwarded to `POST /chat` — the same FastAPI endpoint the full chat UI uses. The widget then renders:
- **`d.narrative`** — plain-English paragraph (or `d.summary` as fallback)
- **Mini data table** — first 5 rows × first 4 columns from `d.rows` / `d.columns`
- **Row count notice** if there are more than 5 rows
- Error / blocked messages if the AI returned those

If the server returns a 401 "Please log in" error (session expired), the widget hides itself and removes the button automatically.

---

### 5 — Dashboard intent regex patterns

`bqCheckDashboardIntent` uses these regex patterns (case-insensitive):

| Topic | Regex | Excludes |
|-------|-------|----------|
| Invoice/Collection | `/invoice|collection|amount|due|revenue|billing/` | — |
| Connections | `/connection|cable|broadband|iptv/` | `/show all|list|display/` (those go to AI) |
| Customer count | `/how many customer|customer count|customer status/` | `/show|list/` |
| STB | `/stb|set.top.box/` | — |
| Recent payments | `/recent payment|latest payment/` | — |
| Recent orders | `/recent order|latest order/` | — |
| Full summary | `/dashboard|summary|overview|snapshot/` | — |

If the message passes all exclusions and data exists in `bqDashboardData`, an HTML string is returned. If the API data for that topic was not loaded (fetch failed), `null` is returned and the message falls through to `/chat`.

---

### 6 — HTML rendering helpers

| Function | Output |
|----------|--------|
| `bqStatGrid(title, stats[])` | 2-column CSS grid of stat cards with label + value + optional sub-label |
| `bqMiniTable(title, cols, rows, note)` | Compact scrollable table with column headers |
| `bqFullSummary()` | Combined grid: invoice total + collection + customers + connections + STBs |
| `bqFmt(number)` | `toLocaleString('en-IN', {minimumFractionDigits:2})` — Indian number format |
| `bqEsc(string)` | HTML-escapes `&`, `<`, `>` — used for AI text output |
| `bqAddRaw(html, isUser)` | Appends a bubble with raw HTML (dashboard cards) |
| `bqAddMsg(text, isUser, data)` | Appends a bubble with escaped text + optional mini table (AI results) |

---

### 7 — Quick-action chips

Six chips are shown at the bottom of the widget. Each calls `bqSendText(text)` with a pre-written message:

| Chip label | Message sent | Goes to |
|---|---|---|
| Dashboard summary | `Show dashboard summary` | Dashboard API (full KPI grid) |
| Pending payments | `Who has pending payments?` | AI `/chat` |
| Broadband | `Show active broadband subscribers` | AI `/chat` |
| All customers | `Show all customers` | AI `/chat` (chip fast-path) |
| Inactive customers | `Inactive customers` | AI `/chat` (chip fast-path) |
| Recent payments | `Recent payments` | Dashboard API (payment table) |

---

### 8 — Complete data flow diagram

```
 Browser (any page)
     │
     │  window.load
     ▼
 bqInitAuth()
     │  GET /auth/me  (cookie: bq_session)
     │
     ├── 401 Not auth ──────→  button hidden (login/signup page)
     │
     └── 200 OK (user data)
           │
           ├── Show #bq-chatbot-btn (display: flex)
           ├── Set header label  (company name or 'Admin · all companies')
           └── bqLoadDashboardData()  ← runs in background
                 │
                 │  6 parallel fetches (Promise.allSettled)
                 ├── GET /get-invoice-amount        → bqDashboardData.invoice
                 ├── GET /get-connection-data       → bqDashboardData.connections
                 ├── GET /get-customer-status-wise-count → bqDashboardData.customerStatus
                 ├── GET /get-recent-payment        → bqDashboardData.recentPayments
                 ├── GET /get-recent-order          → bqDashboardData.recentOrders
                 └── GET /stb-status-count          → bqDashboardData.stbStatus

 User clicks button → bqToggleChat()
     │
     ├── First open: inject welcome message, refresh dashboard data
     └── Subsequent: history preserved, refresh data

 User sends message → bqSendText(text)
     │
     ├── bqCheckDashboardIntent(text)
     │     │
     │     ├── MATCH (KPI question)
     │     │     └── bqAddRaw(bqStatGrid / bqMiniTable / bqFullSummary)
     │     │         ← No network call, instant response
     │     │
     │     └── NO MATCH
     │           └── POST /chat  { message: text }
     │                 │  FastAPI pipeline:
     │                 │    1. require_user() — session check
     │                 │    2. resolve_query_company_scope()
     │                 │    3. classify_intent() in ai.py
     │                 │    4. route_business_query() OR natural_language_to_sql()
     │                 │    5. run_query() on MySQL
     │                 │    6. build_narrative()
     │                 │    7. Return JSON payload
     │                 │
     │                 └── Widget renders:
     │                       narrative / summary text
     │                       mini table (first 5 rows × 4 cols)
     │                       row count notice if >5 rows
     │
     └── Session expired (401) → hide widget + button
```

---

### 9 — Where the code lives

| Element | File | Lines |
|---------|------|-------|
| Widget HTML + CSS + JS | `build-cable/build/index.html` | Everything after `<div id="root">` |
| Auth-gate (`bqInitAuth`) | `build-cable/build/index.html` | `window.addEventListener('load', bqInitAuth)` |
| Dashboard API loader (`bqLoadDashboardData`) | `build-cable/build/index.html` | Fetches 6 endpoints in parallel |
| Intent matcher (`bqCheckDashboardIntent`) | `build-cable/build/index.html` | Regex switches on `bqDashboardData` |
| AI backend (`/chat`) | `main.py` lines 468–740 | Full NL→SQL pipeline |
| Dashboard API endpoints | `main.py` lines 243–337 | `GET /get-invoice-amount`, etc. |
| AI intent + SQL | `ai.py` | `classify_intent`, `natural_language_to_sql` |

---

## License

Internal BillerQ project — adjust as needed for your organisation.
