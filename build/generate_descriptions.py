#!/usr/bin/env python3
"""
Step 2: LLM Description Generator for BillerQ APIs

Uses Qwen (via Ollama) to automatically generate:
- category (e.g., customer, payment, invoice)
- description (business purpose)
- keywords (search terms)

Processes 50 APIs at a time in batches to avoid overwhelming the LLM.
"""

import json
import time
import re
import requests
import os
from pathlib import Path

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:7b"
BATCH_SIZE = 50
DELAY_BETWEEN_BATCHES = 2  # seconds

# Known categories for consistent categorization
CATEGORIES = [
    "customer", "payment", "invoice", "subscription", "package",
    "addon", "stb", "complaint", "enquiry", "lead", "vendor",
    "expense", "income", "report", "account", "provider",
    "area", "tax", "role", "import", "notification",
    "message", "dashboard", "company", "config", "auth",
    "enquiry", "lead", "followup", "problem_type",
]

CATEGORY_KEYWORDS = {
    "customer": ["customer", "subscriber", "user"],
    "payment": ["payment", "pay", "collect", "wallet", "receipt", "reverse"],
    "invoice": ["invoice", "order", "bill", "receipt"],
    "subscription": ["subscription", "sub", "recurring", "activate"],
    "package": ["package", "plan"],
    "addon": ["add-on", "addon", "additional"],
    "stb": ["stb", "device", "set-top", "box"],
    "complaint": ["complaint", "issue", "problem"],
    "vendor": ["vendor", "supplier"],
    "expense": ["expense", "spend"],
    "income": ["income", "revenue"],
    "report": ["report", "summary", "stats", "count"],
    "account": ["account", "ledger"],
    "provider": ["provider", "lco"],
    "area": ["area", "region", "zone"],
    "tax": ["tax", "gst", "rate"],
    "role": ["role", "permission"],
    "import": ["import", "upload", "bulk"],
    "notification": ["notification", "notify", "alert"],
    "message": ["message", "sms", "whatsapp", "email"],
    "dashboard": ["dashboard", "overview", "home"],
    "company": ["company", "org", "business"],
    "config": ["config", "setting", "header", "channel"],
    "auth": ["login", "logout", "auth", "session", "token"],
    "lead": ["lead"],
    "enquiry": ["enquiry"],
    "followup": ["followup", "follow-up"],
    "problem_type": ["problem-type", "problem type"],
}


def extract_path_parts(endpoint: str) -> list[str]:
    """Extract meaningful parts from an API path."""
    parts = endpoint.strip("/").split("/")
    # Skip 'admin' prefix
    return [p for p in parts if p not in ("admin",) and not p.startswith("{")]


def guess_category(endpoint: str) -> str:
    """Guess category based on path keywords (fallback if LLM unavailable)."""
    endpoint_lower = endpoint.lower()
    best_category = "general"
    best_score = 0

    for category, keywords in CATEGORY_KEYWORDS.items():
        score = 0
        for kw in keywords:
            if kw in endpoint_lower:
                score += 1
                # Bonus for exact match at path start
                if endpoint_lower.startswith(f"/admin/{kw}") or f"/{kw}-" in endpoint_lower or f"-{kw}-" in endpoint_lower or f"/{kw}/" in endpoint_lower or endpoint_lower.endswith(kw):
                    score += 2
        if score > best_score:
            best_score = score
            best_category = category

    return best_category


def guess_description(endpoint: str) -> str:
    """Generate a basic description from the endpoint path."""
    parts = extract_path_parts(endpoint)
    verbs = {
        "get": "Retrieves",
        "show": "Retrieves",
        "view": "Retrieves",
        "add": "Creates a new",
        "store": "Creates a new",
        "create": "Creates a new",
        "update": "Updates an existing",
        "edit": "Retrieves data for editing",
        "delete": "Deletes a",
        "remove": "Deletes a",
        "change": "Changes",
        "toggle": "Toggles",
        "activate": "Activates a",
        "deactivate": "Deactivates a",
        "reconnect": "Reconnects a",
        "disconnect": "Disconnects a",
        "reactivate": "Reactives a",
        "approve": "Approves",
        "reject": "Rejects",
        "assign": "Assigns",
        "import": "Imports",
        "convert": "Converts",
    }

    action = None
    for part in parts:
        verb = part.replace("-", " ").replace("_", " ")
        if verb in verbs:
            action = verbs[verb]
            break

    if not action:
        if any(p in endpoint.lower() for p in ["list", "all", "show", "get"]):
            action = "Retrieves"
        elif any(p in endpoint.lower() for p in ["add", "create", "store", "new"]):
            action = "Creates a new"
        elif any(p in endpoint.lower() for p in ["update", "edit", "change", "modify"]):
            action = "Updates"
        elif any(p in endpoint.lower() for p in ["delete", "remove", "cancel"]):
            action = "Deletes"
        else:
            action = "Retrieves"

    # Extract the main subject from endpoint
    subject_parts = [p.replace("-", " ") for p in parts if p not in ("admin", "get", "show", "add", "store", "update", "edit", "delete", "remove", "change", "toggle", "activate", "deactivate", "reconnect", "disconnect", "reactivate", "approve", "reject", "assign", "import", "{id}", "{customerId}")]
    subject = " ".join(subject_parts) if subject_parts else "data"

    return f"{action} {subject} in the BillerQ system."


def generate_keywords(endpoint: str) -> list[str]:
    """Generate search keywords from the endpoint path."""
    parts = extract_path_parts(endpoint)
    keywords = set()

    for part in parts:
        # Split on hyphens and underscores
        for sub in re.split(r"[-_/]", part):
            if sub and len(sub) > 1:
                keywords.add(sub.lower())

    # Add the category
    category = guess_category(endpoint)
    keywords.add(category)

    # Remove common noise
    noise = {"admin", "get", "show", "add", "store", "update", "edit", "delete", "remove",
             "change", "toggle", "activate", "deactivate", "reconnect", "disconnect",
             "reactivate", "approve", "reject", "assign", "import", "post", "view"}
    keywords = {k for k in keywords if k not in noise}

    return sorted(keywords)


def describe_via_llm(endpoints: list[str]) -> list[dict]:
    """
    Send a batch of endpoints to the LLM for description generation.
    """
    endpoints_json = json.dumps([{"endpoint": ep} for ep in endpoints], indent=2)

    prompt = f"""You are analyzing BillerQ APIs — a cable TV & ISP billing system.

For each endpoint:
1. Identify the business purpose (what data does it return/manipulate?)
2. Assign a category from: {', '.join(CATEGORIES)}
3. Generate 3-7 relevant search keywords

Return ONLY a JSON array. No markdown, no explanation.

Endpoints to analyze:
{endpoints_json}"""

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 2048},
            },
            timeout=30,
        )
        response.raise_for_status()
        result = response.json().get("response", "").strip()

        # Extract JSON from response (handle possible markdown wrapping)
        json_match = re.search(r"\[.*\]", result, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        # Try parsing the whole result
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            print(f"  ⚠️  LLM returned invalid JSON. Using fallback.")
            return []

    except Exception as e:
        print(f"  ⚠️  LLM call failed: {e}. Using fallback.")
        return []


def generate_descriptions(catalog: list[dict], use_llm: bool = True) -> list[dict]:
    """
    Generate descriptions for all APIs in the catalog.
    If use_llm=True and Ollama is available, uses LLM for smart descriptions.
    Otherwise uses rule-based fallback.
    """
    total = len(catalog)
    print(f"📝 Generating descriptions for {total} APIs...")

    # Check if Ollama is available
    llm_available = False
    if use_llm:
        try:
            resp = requests.get("http://localhost:11434/api/tags", timeout=3)
            llm_available = resp.status_code == 200
            if llm_available:
                print("  ✅ Ollama is available — using LLM for descriptions")
            else:
                print("  ⚠️  Ollama not responding — using rule-based fallback")
        except Exception:
            print("  ⚠️  Ollama not available — using rule-based fallback")

    completed = 0
    if llm_available:
        # Process in batches
        for i in range(0, total, BATCH_SIZE):
            batch = catalog[i:i + BATCH_SIZE]
            batch_endpoints = [entry["endpoint"] for entry in batch]
            print(f"  🔄 Batch {i // BATCH_SIZE + 1}/{(total - 1) // BATCH_SIZE + 1} ({len(batch)} APIs)...")

            llm_results = describe_via_llm(batch_endpoints)

            # Map LLM results back to catalog entries
            llm_map = {}
            for item in llm_results:
                ep = item.get("endpoint", "")
                llm_map[ep] = item

            for entry in batch:
                ep = entry["endpoint"]
                if ep in llm_map:
                    entry["category"] = llm_map[ep].get("category", guess_category(ep))
                    entry["description"] = llm_map[ep].get("description", guess_description(ep))
                    entry["keywords"] = llm_map[ep].get("keywords", generate_keywords(ep))
                else:
                    entry["category"] = guess_category(ep)
                    entry["description"] = guess_description(ep)
                    entry["keywords"] = generate_keywords(ep)
                completed += 1

            print(f"    → {completed}/{total} complete")

            if i + BATCH_SIZE < total:
                time.sleep(DELAY_BETWEEN_BATCHES)
    else:
        # Rule-based fallback for all
        for entry in catalog:
            entry["category"] = guess_category(entry["endpoint"])
            entry["description"] = guess_description(entry["endpoint"])
            entry["keywords"] = generate_keywords(entry["endpoint"])
            completed += 1

        print(f"  ✅ Rule-based descriptions generated for all {total} APIs")

    return catalog


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent
    catalog_path = base_dir / "api_catalog.json"

    if not catalog_path.exists():
        print("❌ api_catalog.json not found. Run api_catalog_generator.py first.")
        exit(1)

    with open(catalog_path, "r", encoding="utf-8") as f:
        catalog = json.load(f)

    print(f"📂 Loaded {len(catalog)} APIs from catalog")

    # Generate descriptions
    catalog = generate_descriptions(catalog, use_llm=True)

    # Save updated catalog
    output_path = base_dir / "api_catalog_enriched.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Enriched catalog saved to {output_path}")

    # Print statistics
    categories = {}
    for entry in catalog:
        cat = entry.get("category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1

    print(f"\n📊 Category distribution:")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"   {cat}: {count}")

    # Print samples
    print(f"\n📋 Sample entries:")
    for entry in catalog[:5]:
        print(f"   {entry['endpoint']}")
        print(f"      Category: {entry['category']}")
        print(f"      Description: {entry['description']}")
        print(f"      Keywords: {entry['keywords']}")