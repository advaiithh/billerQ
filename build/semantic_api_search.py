"""
Step 4: Semantic API Search Integration

Integrates the API vector store into the FastAPI application.
Provides semantic search functionality that maps natural language queries
to the best matching BillerQ API endpoints.
"""

import json
import os
import re
from pathlib import Path
from api_vector_store import APIVectorStore


# Singleton instance
_vector_store = None
_catalog_data = None


def load_vector_store(base_dir: str = None) -> APIVectorStore:
    """Load or initialize the API vector store singleton."""
    global _vector_store

    if _vector_store is not None:
        return _vector_store

    if base_dir is None:
        base_dir = Path(__file__).resolve().parent

    store_path = os.path.join(base_dir, "api_vector_store.json")

    if os.path.exists(store_path):
        _vector_store = APIVectorStore.load(store_path)
        print(f"  ✅ Loaded API vector store from {store_path}")
    else:
        # Try to build it from the enriched catalog
        catalog_path = os.path.join(base_dir, "api_catalog_enriched.json")
        if os.path.exists(catalog_path):
            from api_vector_store import build_vector_store
            _vector_store = build_vector_store(catalog_path, output_dir=str(base_dir))
            print(f"  ✅ Built API vector store from {catalog_path}")
        else:
            print("  ⚠️  No API catalog found. Semantic search will be unavailable.")
            _vector_store = APIVectorStore()

    return _vector_store


def load_catalog(base_dir: str = None) -> list[dict]:
    """Load the enriched API catalog."""
    global _catalog_data

    if _catalog_data is not None:
        return _catalog_data

    if base_dir is None:
        base_dir = Path(__file__).resolve().parent

    catalog_path = os.path.join(base_dir, "api_catalog_enriched.json")
    if os.path.exists(catalog_path):
        with open(catalog_path, "r", encoding="utf-8") as f:
            _catalog_data = json.load(f)
        return _catalog_data

    # Try unenriched
    catalog_path = os.path.join(base_dir, "api_catalog.json")
    if os.path.exists(catalog_path):
        with open(catalog_path, "r", encoding="utf-8") as f:
            _catalog_data = json.load(f)
        return _catalog_data

    return []


def search_apis(query: str, top_k: int = 5) -> list[dict]:
    """
    Search for the most relevant BillerQ API endpoints for a given query.
    Uses semantic search with keyword fallback.

    Args:
        query: Natural language query (e.g., "Who has not paid yet?")
        top_k: Number of results to return

    Returns:
        List of matching APIs with endpoint, description, category, and score
    """
    store = load_vector_store()
    if not store.api_docs:
        return []

    results = store.search(query, top_k=top_k)

    # Format results for API response
    output = []
    for r in results:
        output.append({
            "endpoint": r["endpoint"],
            "category": r.get("category", ""),
            "description": r.get("description", ""),
            "keywords": r.get("keywords", []),
            "score": r["score"],
        })

    return output


def get_api_details(endpoint: str) -> dict | None:
    """Get detailed information about a specific endpoint."""
    catalog = load_catalog()
    for entry in catalog:
        if entry["endpoint"] == endpoint:
            return entry
    return None


def find_best_api(query: str, min_score: float = 0.001) -> dict | None:
    """
    Find the single best matching API for a query.
    Returns None if no good match found (score too low).
    """
    results = search_apis(query, top_k=1)
    if results and results[0].get("score", 0) > min_score:
        return results[0]
    return None


def categorize_query(query: str) -> dict:
    """
    Analyze a natural language query and determine:
    - What category of API is needed
    - Whether it's a read or write operation
    - Key entities mentioned

    Returns a dict with analysis results and matched APIs.
    """
    query_lower = query.lower()

    # Determine operation type
    is_read = any(re.search(r"\b" + w + r"\b", query_lower) for w in
                  ["show", "list", "get", "find", "display", "view", "fetch",
                   "search", "how many", "count", "what", "which", "who"])
    is_write = any(re.search(r"\b" + w + r"\b", query_lower) for w in
                   ["add", "create", "new", "insert", "register", "store"])

    # Determine primary category based on keywords
    category_hints = {
        "customer": ["customer", "subscriber", "user", "client"],
        "payment": ["payment", "pay", "paid", "unpaid", "due", "collection",
                     "revenue", "money", "wallet", "receipt"],
        "invoice": ["invoice", "bill", "order"],
        "subscription": ["subscription", "sub", "recurring", "plan"],
        "complaint": ["complaint", "issue", "problem", "complaints"],
        "report": ["report", "summary", "statistics", "stats"],
        "dashboard": ["dashboard", "overview", "snapshot"],
        "import": ["import", "export", "upload"],
    }

    primary_category = "general"
    max_score = 0
    for cat, keywords in category_hints.items():
        score = sum(1 for kw in keywords if kw in query_lower)
        if score > max_score:
            max_score = score
            primary_category = cat

    # Search for matching APIs
    apis = search_apis(query, top_k=5)

    return {
        "query": query,
        "operation": "read" if is_read else ("write" if is_write else "unknown"),
        "primary_category": primary_category,
        "matched_apis": apis,
        "total_matches": len(apis),
    }


def format_search_results(results: list[dict]) -> str:
    """Format search results as a readable string."""
    if not results:
        return "No matching APIs found."

    lines = ["Top matching APIs:"]
    for i, r in enumerate(results, 1):
        score_pct = r.get("score", 0) * 100
        lines.append(
            f"  {i}. [{score_pct:.0f}%] {r['endpoint']}\n"
            f"     {r.get('description', 'No description')}"
        )

    return "\n".join(lines)


# ─── FastAPI Integration Helper ────────────────────────

def create_semantic_search_router():
    """
    Creates APIRouter endpoints for semantic API search.
    Call this in your FastAPI app initialization.
    """
    from fastapi import APIRouter, Query

    router = APIRouter(prefix="/api-search", tags=["API Search"])

    @router.get("/search")
    async def semantic_search(
        q: str = Query(..., description="Natural language query"),
        top_k: int = Query(5, description="Number of results"),
    ):
        """
        Search for the best matching BillerQ API endpoints using semantic search.
        """
        results = search_apis(q, top_k=top_k)
        return {
            "success": True,
            "query": q,
            "results": results,
            "total": len(results),
        }

    @router.get("/categorize")
    async def categorize_query_endpoint(
        q: str = Query(..., description="Natural language query"),
    ):
        """
        Analyze a query and return category, operation type, and matched APIs.
        """
        analysis = categorize_query(q)
        return {
            "success": True,
            "analysis": analysis,
        }

    @router.get("/best")
    async def best_match(
        q: str = Query(..., description="Natural language query"),
    ):
        """
        Return the single best matching API for a query.
        """
        best = find_best_api(q)
        if best:
            return {"success": True, "api": best}
        return {"success": False, "error": "No good match found", "api": None}

    @router.get("/endpoint/{endpoint_path:path}")
    async def get_endpoint_details(endpoint_path: str):
        """
        Get detailed information about a specific endpoint.
        """
        details = get_api_details("/" + endpoint_path.lstrip("/"))
        if details:
            return {"success": True, "api": details}
        return {"success": False, "error": "Endpoint not found"}

    return router


if __name__ == "__main__":
    # Test the search
    print("Testing Semantic API Search...\n")

    # Load the store
    base_dir = Path(__file__).resolve().parent
    load_vector_store(str(base_dir))

    # Test queries
    test_queries = [
        "Who has not paid yet?",
        "Show me inactive customers",
        "What is my collection today?",
        "How many active subscriptions?",
        "Pending complaints against customers",
        "Add a new customer named John",
        "Revenue this month",
        "Show all invoices for last month",
        "Customer payment history for customer 123",
        "Export customer import report",
        "What is my total due collection?",
        "List all disconnected STBs",
    ]

    print(f"{'Query':<50} {'Best Match API':<50} {'Score':<10}")
    print("-" * 110)
    for query in test_queries:
        best = find_best_api(query)
        if best:
            print(f"{query:<50} {best['endpoint']:<50} {best['score']:.3f}")
        else:
            print(f"{query:<50} {'NO MATCH':<50} {'':<10}")