# BillerQ Semantic API Search

## How It Works

This system provides **semantic search** across all 261+ BillerQ API endpoints. It uses `sentence-transformers` (all-MiniLM-L6-v2) to convert natural language queries AND API descriptions into vector embeddings, then finds the most relevant endpoints using cosine similarity.

### Architecture Diagram

```
CommonUrl.jsx (Frontend)
      │
      ▼
api_catalog_generator.py
  ─ Extracts 261+ endpoints
  ─ Generates api_catalog.json
      │
      ▼
generate_descriptions.py
  ─ Adds category, description, keywords to each API
  ─ Uses LLM (Qwen) if available, otherwise rule-based fallback
  ─ Generates api_catalog_enriched.json
      │
      ▼
api_vector_store.py (APIVectorStore class)
  ─ Creates embeddings using sentence-transformers (384-dim)
  ─ Persists vector store to api_vector_store.json
  ─ On reload: loads metadata + regenerates embeddings in memory
      │
      ▼
semantic_api_search.py
  ─ search_apis(query) — top-k matching APIs with scores
  ─ find_best_api(query) — single best match
  ─ categorize_query(query) — analyze intent + category
      │
      ▼
main.py (FastAPI)
  ─ GET /api-search/search?q=who+has+not+paid
  ─ GET /api-search/best?q=add+customer
  ─ GET /api-search/categorize?q=show+invoices
  ─ GET /api-search/endpoint/{path}
  ─ POST /chat also returns api_search field with matches
```

## How to Run

### Step 1: Initial Setup (One Time)
```bash
pip install -r requirements.txt
```

### Step 2: Generate API Catalog + Vector Store
```bash
cd build
python run_enrich.py
```
This does everything: extracts APIs from CommonUrl.jsx → generates descriptions → creates embeddings → saves vector store + runs test.

### Step 3: Test Semantic Search
```bash
cd build
python test_semantic_search.py
```
Tests 20 natural language queries like "Who has not paid yet?" and shows the best API match.

### Step 4: Run the FastAPI Server
```bash
cd build
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Step 5: Try the API Endpoints

Open in browser or use curl:

**Search APIs:**
```
http://localhost:8000/api-search/search?q=who+has+not+paid+yet
```

**Best Match:**
```
http://localhost:8000/api-search/best?q=add+a+new+customer
```

**Categorize:**
```
http://localhost:8000/api-search/categorize?q=show+inactive+customers
```

**Endpoint Details:**
```
http://localhost:8000/api-search/endpoint/admin/get-payment-due-data
```

## How the Semantic Search Scoring Works

The search combines two scores:

1. **Embedding score (60%)** — Uses `sentence-transformers` to compute cosine similarity between the query embedding and each API's description embedding. This captures semantic meaning (e.g., "who has not paid" → "/admin/get-payment-due-data" even though the words don't match exactly).

2. **Keyword score (40%)** — Boosts results where:
   - The endpoint path contains query words (e.g., "payment" in path matches "paid" in query)
   - Keywords/categories match
   - Category-related terms boost (e.g., "payment" category matches "due", "collection")

## Improving Descriptions with LLM

If you have Ollama running with `qwen2.5:7b`, the system can use LLM to generate smarter descriptions:
```bash
cd build
python generate_descriptions.py  # Uses Ollama if available
```

Or edit `generate_descriptions.py` and set `use_llm=True` to force LLM usage.

## Files Reference

| File | Purpose |
|------|---------|
| `api_catalog_generator.py` | Extract APIs from CommonUrl.jsx |
| `generate_descriptions.py` | Add category/description/keywords |
| `api_vector_store.py` | Embedding + similarity search engine |
| `semantic_api_search.py` | High-level search functions + FastAPI router |
| `run_enrich.py` | One-command pipeline |
| `test_semantic_search.py` | 20-query e2e test |
| `api_catalog.json` | Raw extracted endpoints |
| `api_catalog_enriched.json` | Endpoints with descriptions |
| `api_vector_store.json` | Persisted vector store data |