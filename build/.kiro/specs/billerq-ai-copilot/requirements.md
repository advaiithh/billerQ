# BillerQ AI Copilot — Requirements

## Overview

Transform BillerQ's existing NL-to-SQL chatbot prototype into a full **Business Copilot** integrated across the BillerQ platform. The copilot must answer business questions conversationally, route to the right data source intelligently, enforce multi-tenant security, and be ready for Amazon Bedrock migration.

**Current state:** User → Prompt → Qwen (LLM) → SQL → MySQL → Raw table  
**Target state:** User → Intent Router → Dashboard API (fast path) or DB Query Engine (slow path) → NL Response + View More link

### Core Principle
> The LLM must NOT fetch data. The LLM only understands, classifies, extracts, summarizes, analyzes, and formats. All data comes from Dashboard APIs or direct Database queries.

---

## Requirement 1 — Intent Router

### Description
Every user message must be classified into one of four intent types before any data is fetched. This classification determines which subsystem handles the query.

| Intent Type | Description | Example |
|---|---|---|
| `dashboard_query` | Answered by a Dashboard API call | "How many active customers?" |
| `database_query` | Requires a parameterized DB query | "Customers from Kochi with dues" |
| `analytics_query` | Requires trend data + LLM insight | "Why is collection dropping?" |
| `navigation_query` | Redirect the user to a BillerQ page | "Open complaints page" |

### User Stories

**REQ-1.1** — As the system, when a user submits a message, I must classify it into exactly one of the four intent types before proceeding.

**REQ-1.2** — As a user, when I ask a question that maps to a known dashboard metric, the system must route it as a `dashboard_query` so I receive a fast response without SQL.

**REQ-1.3** — As a user, when I ask a filtered or specific question (e.g., "customers in Kochi"), the system must route it as a `database_query`.

**REQ-1.4** — As a user, when I ask a trend or "why" question, the system must route it as an `analytics_query` so I receive an LLM-generated insight.

**REQ-1.5** — As a user, when I ask to open or navigate to a page, the system must route it as a `navigation_query` and return the correct URL.

### Acceptance Criteria

- [ ] The router classifies each message in under 200 ms.
- [ ] Classification accuracy must be ≥ 95% on a standard test set of 100 labelled queries.
- [ ] Unknown or ambiguous intents fall back to `database_query` rather than failing.
- [ ] The router never calls the database or LLM for a `navigation_query`.
- [ ] Intent type is logged with every request for monitoring and improvement.

---

## Requirement 2 — Dashboard Knowledge Layer

### Description
A metadata registry that maps plain-language business concepts to specific Dashboard API endpoints and response fields. This allows the Intent Router and response layer to serve answers without writing SQL.

### User Stories

**REQ-2.1** — As a developer, I need a structured metadata file (`dashboard_metrics.py` or equivalent) that maps metric names to their API endpoint and response field.

**REQ-2.2** — As the system, when a `dashboard_query` intent is detected, I must look up the relevant metric in the knowledge layer and call the mapped API.

**REQ-2.3** — As a developer, I must be able to add new metrics to the knowledge layer without changing the router or response logic.

### Acceptance Criteria

- [ ] The knowledge layer covers at minimum: `total_customers`, `active_customers`, `inactive_customers`, `pending_amount`, `today_collection`, `collection_yesterday`, `total_invoices`, `overdue_invoices`, `open_complaints`, `active_subscriptions`.
- [ ] Each entry specifies: `api_endpoint`, `response_field`, `unit` (e.g., currency/count), and `page_link`.
- [ ] The layer is a single importable config — not hardcoded inside routing logic.
- [ ] Adding a new metric requires editing only the config file.

---

## Requirement 3 — Fast Dashboard Responses

### Description
For `dashboard_query` intents, the system must return a natural language answer in under 500 ms by calling the Dashboard API directly — no SQL, no LLM inference required.

### User Stories

**REQ-3.1** — As a user, when I ask "How many active customers?", I must receive a response like *"You currently have 14,850 active customers."* in under 500 ms.

**REQ-3.2** — As a user, when I ask about today's collection, I must receive the amount and payment count in a single sentence.

**REQ-3.3** — As the system, dashboard responses must use pre-built response templates populated with live API data — no LLM call needed.

**REQ-3.4** — As a user, every dashboard response must include a "View More" button linking to the relevant BillerQ page.

### Acceptance Criteria

- [ ] End-to-end response time for dashboard queries ≤ 500 ms (measured at the API layer).
- [ ] Responses are grammatically correct natural language, not raw JSON or table rows.
- [ ] Each response includes a `view_more` object with `label` and `url`.
- [ ] If the Dashboard API is unavailable, the system returns a graceful error message and does not attempt an SQL fallback silently.
- [ ] Response templates cover all metrics defined in the Dashboard Knowledge Layer.

---

## Requirement 4 — Natural Language Responses

### Description
All responses — whether from the dashboard layer, database layer, or analytics engine — must be returned as conversational natural language. Users must never see raw JSON, SQL results, or table rows.

### User Stories

**REQ-4.1** — As a user, I must receive responses written in plain English (or the user's preferred language) regardless of data source.

**REQ-4.2** — As a user, when the result involves a currency value, it must be formatted with the ₹ symbol and appropriate units (e.g., ₹2.4 Lakhs).

**REQ-4.3** — As a user, when the result involves a count, it must read naturally (e.g., "124 customers" not "124").

**REQ-4.4** — As a user, when comparative data is available (today vs yesterday, this month vs last month), the response must include the percentage change.

### Acceptance Criteria

- [ ] No raw JSON, SQL result sets, or table data is ever returned to the user.
- [ ] Currency values use ₹ symbol with Lakh/Crore formatting where appropriate.
- [ ] Percentage comparisons are included whenever historical data is available.
- [ ] Responses are ≤ 3 sentences for simple queries, with detail available via the "View More" link.
- [ ] LLM is used for formatting only in `analytics_query` and complex `database_query` results; dashboard responses use templates.

---

## Requirement 5 — View More Navigation

### Description
Every response must optionally include a "View More" action that links the user to the relevant page in the BillerQ platform. Navigation links may include query parameters to pre-filter the destination page.

### User Stories

**REQ-5.1** — As a user, every response about a specific domain (customers, payments, collections, etc.) must include a visible "View More" or contextual label button.

**REQ-5.2** — As a user, when I ask about pending payments, the "View More" link must open `/payments?status=pending` — not just `/payments`.

**REQ-5.3** — As a developer, I need a `PAGE_MAP` config that maps domain concepts to URL paths, so navigation is centrally managed.

**REQ-5.4** — As a user, clicking "View More" must open the page in the same application — not a new tab (unless configured otherwise).

### Acceptance Criteria

- [ ] The `PAGE_MAP` covers: `customers`, `payments`, `complaints`, `subscriptions`, `collections`, `invoices`, `dashboard`.
- [ ] Filter parameters are appended as query strings where applicable (e.g., `?status=pending`, `?area=kochi`).
- [ ] Every API response includes a `navigation` object with `label`, `url`, and optional `params`.
- [ ] If no relevant page exists for a query, the `navigation` field is omitted — not set to null or a generic link.

---

## Requirement 6 — Multi-Tenant Security

### Description
BillerQ is a multi-tenant SaaS platform. Every data query — whether Dashboard API or direct DB — must be scoped to the authenticated user's `company_id`. Users must never be able to access another company's data.

### User Stories

**REQ-6.1** — As the system, every API call and database query must include the authenticated user's `company_id` as a filter.

**REQ-6.2** — As a company admin, I must only see data belonging to my company, even if I ask generic questions like "show all customers".

**REQ-6.3** — As the system, the `company_id` must be extracted from the authenticated session/JWT token — never from user input.

**REQ-6.4** — As the system, if `company_id` cannot be determined from the session, the request must be rejected with a 401 error.

### Acceptance Criteria

- [ ] All database queries include a `WHERE company_id = :current_company_id` clause (parameterized, never interpolated).
- [ ] All Dashboard API calls pass `company_id` as a header or query parameter.
- [ ] `company_id` is never accepted from the request body or chat message text.
- [ ] Attempting to query without a valid session returns HTTP 401.
- [ ] Security is enforced at the backend layer — the frontend cannot bypass it.
- [ ] Penetration test: querying with one company's token returns zero rows from another company's data.

---

## Requirement 7 — Conversational Memory

### Description
The copilot must maintain session-level context so users can have multi-turn conversations without repeating themselves. The system must remember the current entity, active filters, and previous question context within a session.

### User Stories

**REQ-7.1** — As a user, when I ask "Show Suresh" and then "Show his payments", the system must understand "his" refers to Suresh without me repeating the name.

**REQ-7.2** — As a user, when I apply a filter (e.g., "customers in Kochi") and follow up with "show their invoices", the location filter must carry forward.

**REQ-7.3** — As a user, my conversation context must persist for the duration of my session and reset when I log out or start a new chat.

**REQ-7.4** — As the system, memory must store: last mentioned customer, last applied filters, last intent type, and last referenced entity type.

### Acceptance Criteria

- [ ] Memory correctly resolves pronouns ("he", "she", "they", "his", "her") to the last mentioned entity.
- [ ] Filters from a previous turn are applied to follow-up queries unless the user explicitly changes them.
- [ ] Memory is session-scoped — isolated per user session, not shared across users.
- [ ] Memory resets cleanly on session end or explicit "start over" / "clear" command.
- [ ] Memory does not persist across sessions (no cross-session memory by default in Phase 1).
- [ ] Memory stores a maximum of the last 10 turns to avoid context bloat.

---

## Requirement 8 — Smart Search

### Description
Users must be able to find customers and records using natural language descriptions rather than exact IDs or names. Phase 1 delivers fuzzy text search; Phase 2 introduces vector-based semantic search.

### User Stories

**REQ-8.1** — As a user, I must be able to find a customer by typing "John from Kochi" instead of needing their customer ID.

**REQ-8.2** — As a user, partial name matches must return relevant results (e.g., "Suresh K" matches "Suresh Kumar").

**REQ-8.3** — As a developer (Phase 2), I need a vector search implementation using FAISS or Chroma to support semantic customer lookup.

**REQ-8.4** — As a user, search results must respect the `company_id` filter — I can only find customers from my own company.

### Acceptance Criteria

- [ ] Phase 1: Full-text / fuzzy search on customer name, area, phone number returns results in ≤ 1 second.
- [ ] Search is case-insensitive and handles partial matches.
- [ ] All search results are filtered by `company_id`.
- [ ] Phase 2 (future): Vector search returns semantically similar customers even with spelling variations.
- [ ] Search results are presented as a natural language list, not a raw table.

---

## Requirement 9 — Analytics Engine

### Description
For `analytics_query` intents, the system must fetch trend data from the database, pass it to the LLM for analysis, and return a business insight in natural language. This is the only flow where the LLM processes data directly.

### User Stories

**REQ-9.1** — As a user, when I ask "Why is collection dropping?", I must receive a specific business insight (e.g., which region, which segment, by what percentage) — not a generic answer.

**REQ-9.2** — As a user, analytics responses must cite the data they are based on (e.g., "Based on the last 30 days…").

**REQ-9.3** — As the system, the analytics engine must query trend data first, then pass only the data (not the raw DB connection) to the LLM for interpretation.

**REQ-9.4** — As a user, analytics responses must include a "View Analytics" link to the relevant report page.

### Acceptance Criteria

- [ ] Analytics queries fetch data from DB first; LLM receives only the result set, not DB credentials or raw queries.
- [ ] Insights include: percentage change, affected segment/region, time period analyzed.
- [ ] Response includes a `navigation` link to the relevant analytics or report page.
- [ ] Analytics response time ≤ 5 seconds (acceptable given LLM processing).
- [ ] If trend data is insufficient (< 2 data points), the system responds with "Not enough data to analyze trends yet."

---

## Requirement 10 — Amazon Bedrock Migration Readiness

### Description
The system architecture must be designed so that the LLM provider (currently Ollama/Qwen 2.5 7B) can be swapped for Amazon Bedrock (Claude Sonnet or Nova Pro) with minimal code changes — ideally by changing a single config value.

### User Stories

**REQ-10.1** — As a developer, I must be able to switch from Ollama to Amazon Bedrock by changing a config flag, without modifying intent routing, dashboard layer, DB layer, or memory logic.

**REQ-10.2** — As a developer, all LLM calls must go through a single abstraction layer (`llm_provider.py` or equivalent) so the provider is swappable.

**REQ-10.3** — As an architect, the Intent Router, Dashboard Layer, Database Layer, and Memory must have zero direct dependency on the LLM provider library.

**REQ-10.4** — As a developer, the system must support both providers simultaneously during a transition period (feature flag).

### Acceptance Criteria

- [ ] A `LLMProvider` abstraction class/interface exists with at minimum: `classify(prompt)`, `analyze(data, question)`, `format(data, template)` methods.
- [ ] `OllamaProvider` and `BedrockProvider` both implement the same interface.
- [ ] Switching providers requires changing only `LLM_PROVIDER=bedrock` in the environment config.
- [ ] No LLM-provider-specific imports exist outside of `llm_provider.py`.
- [ ] The Bedrock provider supports Claude Sonnet 3.5 and Nova Pro as selectable models via config.
- [ ] All existing functionality (intent classification, analytics, NL formatting) works identically on both providers.

---

## Non-Functional Requirements

| NFR | Requirement |
|---|---|
| **Performance** | Dashboard query responses ≤ 500 ms; DB query responses ≤ 2 s; Analytics ≤ 5 s |
| **Security** | All queries scoped by `company_id`; parameterized queries only; JWT-based auth |
| **Scalability** | Dashboard layer must be stateless and horizontally scalable |
| **Reliability** | Graceful degradation — if Dashboard API fails, surface a clear error, do not silently query DB |
| **Observability** | Log intent type, data source used, response time, and company_id for every request |
| **Maintainability** | Adding a new dashboard metric or page link must require editing only a config file |
| **Compatibility** | Must work with existing BillerQ React frontend without changes to the UI framework |

---

## Out of Scope (Phase 1)

- Cross-session persistent memory
- Voice input
- Multi-language support (Hindi, Malayalam, etc.) — future phase
- Vector search (FAISS/Chroma) — Phase 2
- Proactive alerts / push notifications
- Fine-tuning the LLM on BillerQ data
