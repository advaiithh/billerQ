#!/usr/bin/env python3
"""End-to-end test for the semantic API search system."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from semantic_api_search import (
    load_vector_store, search_apis, find_best_api, 
    categorize_query, format_search_results
)

def main():
    base_dir = Path(__file__).resolve().parent
    
    print("=" * 80)
    print("BILLERQ SEMANTIC API SEARCH - END-TO-END TEST")
    print("=" * 80)
    
    # Load the store
    load_vector_store(str(base_dir))
    
    test_queries = [
        "Who has not paid their bills yet?",
        "Show me inactive customers",
        "What is my total collection today?",
        "How many active subscriptions do I have?",
        "Pending complaints against customers",
        "Add a new customer",
        "Show revenue this month",
        "List all invoices",
        "Show payment history for a customer",
        "Import customers from Excel",
        "What is my dashboard data?",
        "List all disconnected STB devices",
        "Show me the agent collection report",
        "How many complaints are pending?",
        "Show wallet balance for all customers",
        "Activate a subscription for a customer",
        "Reverse a transaction",
        "Send a notification to customers",
        "Export the tax report",
        "Update customer status to inactive",
    ]
    
    header = f"{'Query':<50} {'Best Match API':<50} {'Score':<10}"
    print(f"\n{header}")
    print("-" * 110)
    success = 0
    for query in test_queries:
        best = find_best_api(query)
        if best:
            score_pct = best["score"] * 100
            print(f"{query:<50} {best['endpoint']:<50} {score_pct:.1f}%")
            success += 1
        else:
            print(f"{query:<50} {'NO MATCH':<50} {'0.0%':<10}")
    
    print(f"\nResults: {success}/{len(test_queries)} matched ({success/len(test_queries)*100:.0f}%)")
    
    # Show a detailed example
    print("\n" + "=" * 80)
    print("DETAILED EXAMPLE")
    print("=" * 80)
    
    example = "Who has not paid their bills yet?"
    print(f"\nQuery: '{example}'")
    results = search_apis(example, top_k=5)
    for i, r in enumerate(results, 1):
        print(f"\n  #{i} [{r['score']*100:.1f}%] {r['endpoint']}")
        print(f"      Category: {r['category']}")
        print(f"      Description: {r['description']}")
        print(f"      Keywords: {', '.join(r['keywords'][:5])}")

if __name__ == "__main__":
    main()