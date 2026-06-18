#!/usr/bin/env python3
"""Run the enrichment pipeline: generate descriptions and build vector store."""
import json
import os
import sys
from pathlib import Path

# Add current dir to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_descriptions import generate_descriptions
from api_vector_store import APIVectorStore, build_vector_store

base_dir = Path(__file__).resolve().parent

# Step 1: Generate descriptions
print("=" * 60)
print("STEP 1: Generating API descriptions")
print("=" * 60)
with open(base_dir / "api_catalog.json", "r") as f:
    catalog = json.load(f)

catalog = generate_descriptions(catalog, use_llm=False)

with open(base_dir / "api_catalog_enriched.json", "w") as f:
    json.dump(catalog, f, indent=2, ensure_ascii=False)
print(f"✅ Saved {len(catalog)} enriched APIs to api_catalog_enriched.json")

# Step 2: Build vector store
print("\n" + "=" * 60)
print("STEP 2: Building Vector Store")
print("=" * 60)
store = build_vector_store(str(base_dir / "api_catalog_enriched.json"), output_dir=str(base_dir))

# Step 3: Test search
print("\n" + "=" * 60)
print("STEP 3: Testing Semantic Search")
print("=" * 60)
test_queries = [
    "Who has not paid yet?",
    "Show me inactive customers",
    "What is my collection today?",
    "How many active subscriptions?",
    "Pending complaints",
    "Add a new customer",
    "Revenue this month",
    "Show all invoices",
    "Customer payment history",
    "Export customer import report",
]

for query in test_queries:
    results = store.search(query, top_k=3)
    print(f"\n📝 '{query}'")
    for r in results:
        print(f"   [{r['score']:.3f}] {r['endpoint']} ({r['category']})")