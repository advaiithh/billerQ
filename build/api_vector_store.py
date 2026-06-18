#!/usr/bin/env python3
"""
Step 3: ChromaDB Vector Store for BillerQ APIs

Creates embeddings for all API endpoints using sentence-transformers
and stores them in ChromaDB for semantic search.

Can also use Ollama for embeddings as an alternative.
"""

import json
import os
import re
from pathlib import Path


# We'll create a lightweight vector store using simple numpy operations
# since ChromaDB/sentence-transformers may not be installed yet.
# This can be swapped for ChromaDB later.

class APIVectorStore:
    """
    In-memory vector store for API endpoints with cosine similarity search.
    Uses TF-IDF-like keyword vectors when sentence-transformers isn't available,
    or proper embeddings when it is.
    """
    
    def __init__(self, persist_dir: str = None):
        self.api_docs = []
        self.persist_dir = persist_dir
        self.embedder = None
        self._init_embedder()
    
    def _init_embedder(self):
        """Try to initialize sentence-transformers, fall back to Ollama or None."""
        try:
            from sentence_transformers import SentenceTransformer
            self.embedder = SentenceTransformer("all-MiniLM-L6-v2")
            self.embedding_dim = 384
            print("  ✅ Using sentence-transformers (all-MiniLM-L6-v2)")
            return
        except ImportError:
            print("  📝 sentence-transformers not available, trying Ollama...")
        
        # Try Ollama embeddings
        try:
            import requests
            resp = requests.get("http://localhost:11434/api/tags", timeout=2)
            if resp.status_code == 200:
                self.embedder = "ollama"
                self.embedding_dim = 1024  # approximate for qwen
                print("  ✅ Using Ollama embeddings")
                return
        except Exception:
            pass
        
        print("  ⚠️  No embedding model available — will use keyword matching")
        self.embedder = None
        self.embedding_dim = 0
    
    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        if self.embedder is None:
            return None
        
        if hasattr(self.embedder, 'encode'):
            return self.embedder.encode(texts).tolist()
        
        if self.embedder == "ollama":
            import requests
            embeddings = []
            for text in texts:
                try:
                    resp = requests.post(
                        "http://localhost:11434/api/embeddings",
                        json={
                            "model": "qwen2.5:7b",
                            "prompt": text[:512],  # Truncate
                        },
                        timeout=5,
                    )
                    if resp.status_code == 200:
                        emb = resp.json().get("embedding", [])
                        if emb:
                            embeddings.append(emb)
                            continue
                except Exception:
                    pass
                embeddings.append(None)
            return embeddings
        
        return None
    
    def add_apis(self, catalog: list[dict]):
        """Add API catalog entries to the vector store."""
        print(f"📦 Adding {len(catalog)} APIs to vector store...")
        
        # Build search documents from API metadata
        docs = []
        for entry in catalog:
            # Combine all searchable text
            search_text = (
                f"{entry['endpoint']} "
                f"{entry.get('category', '')} "
                f"{entry.get('description', '')} "
                f"{' '.join(entry.get('keywords', []))}"
            )
            # Extract path segments for keyword enrichment
            path_parts = entry['endpoint'].strip('/').replace('-', ' ').replace('_', ' ').split('/')
            search_text += " " + " ".join(path_parts[1:])  # skip 'admin'
            
            docs.append({
                "endpoint": entry["endpoint"],
                "category": entry.get("category", ""),
                "description": entry.get("description", ""),
                "keywords": entry.get("keywords", []),
                "search_text": search_text.lower(),
            })
        
        self.api_docs = docs
        print(f"  ✅ Added {len(docs)} APIs to vector store")
        
        # Generate embeddings if available
        texts = [d["search_text"] for d in docs]
        embeddings = self._embed_texts(texts)
        if embeddings:
            for i, emb in enumerate(embeddings):
                self.api_docs[i]["embedding"] = emb
            print(f"  ✅ Generated embeddings for {len([e for e in embeddings if e])} APIs")
    
    def _cosine_similarity(self, v1: list[float], v2: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        import math
        dot = sum(a * b for a, b in zip(v1, v2))
        n1 = math.sqrt(sum(a * a for a in v1))
        n2 = math.sqrt(sum(b * b for b in v2))
        if n1 == 0 or n2 == 0:
            return 0
        return dot / (n1 * n2)
    
    def _keyword_score(self, query: str, doc: dict) -> float:
        """Compute a keyword-based relevance score."""
        query_lower = query.lower()
        score = 0.0
        
        # Exact endpoint match (highest score)
        if query_lower == doc["endpoint"].lower():
            return 100.0
        
        # Endpoint contains query
        if query_lower in doc["endpoint"].lower():
            score += 20.0
        
        # Query contains endpoint path segments
        path_segments = doc["endpoint"].strip("/").lower().split("/")
        for seg in path_segments:
            if seg and seg != "admin" and seg in query_lower:
                score += 5.0
        
        # Keyword matches
        for kw in doc["keywords"]:
            if kw.lower() in query_lower:
                score += 3.0
        
        # Category match
        if doc.get("category", "").lower() in query_lower:
            score += 2.0
        
        # Description word overlap
        desc_words = set(doc.get("description", "").lower().split())
        query_words = set(query_lower.split())
        overlap = len(desc_words & query_words)
        score += overlap * 1.0
        
        # Boost if category-related keywords appear
        category_boost = {
            "customer": ["customer", "subscriber", "user", "client", "who"],
            "payment": ["payment", "pay", "paid", "unpaid", "due", "collection", "money"],
            "invoice": ["invoice", "bill", "order", "receipt"],
            "subscription": ["subscription", "sub", "active", "recurring", "plan"],
            "complaint": ["complaint", "issue", "problem", "support"],
            "report": ["report", "summary", "count", "statistics", "how many"],
            "dashboard": ["dashboard", "overview", "metrics", "summary", "snapshot"],
        }
        
        cat = doc.get("category", "")
        if cat in category_boost:
            for kw in category_boost[cat]:
                if kw in query_lower:
                    score += 1.5
        
        return score
    
    def search(self, query: str, top_k: int = 10) -> list[dict]:
        """
        Search for the most relevant APIs given a natural language query.
        Returns top_k results ranked by relevance.
        """
        if not self.api_docs:
            return []
        
        query_lower = query.lower()
        scored = []
        
        # Try embedding search first
        query_embedding = None
        if self.api_docs and "embedding" in self.api_docs[0] and self.api_docs[0]["embedding"] is not None:
            query_embeddings = self._embed_texts([query])
            if query_embeddings and query_embeddings[0]:
                query_embedding = query_embeddings[0]
        
        for doc in self.api_docs:
            keyword_score = self._keyword_score(query, doc)
            
            if query_embedding and doc.get("embedding"):
                emb_score = self._cosine_similarity(query_embedding, doc["embedding"])
                # Combine scores (60% embedding, 40% keyword)
                final_score = 0.6 * emb_score + 0.4 * (keyword_score / 100.0)
            else:
                final_score = keyword_score / 100.0
            
            scored.append({
                "endpoint": doc["endpoint"],
                "category": doc.get("category", ""),
                "description": doc.get("description", ""),
                "keywords": doc.get("keywords", []),
                "score": round(final_score, 4),
                "keyword_score": round(keyword_score, 2),
            })
        
        # Sort by score descending
        scored.sort(key=lambda x: x["score"], reverse=True)
        
        # Return top_k with scores > threshold
        results = [r for r in scored[:top_k] if r["score"] > 0.01]
        
        return results
    
    def save(self, filepath: str = None):
        """Persist the vector store to disk."""
        if filepath is None and self.persist_dir:
            filepath = os.path.join(self.persist_dir, "api_vector_store.json")
        
        if not filepath:
            return
        
        # Strip embeddings before saving (they're large)
        save_data = []
        for doc in self.api_docs:
            save_data.append({
                "endpoint": doc["endpoint"],
                "category": doc.get("category", ""),
                "description": doc.get("description", ""),
                "keywords": doc.get("keywords", []),
                "search_text": doc.get("search_text", ""),
            })
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(save_data, f, indent=2, ensure_ascii=False)
        print(f"  💾 Vector store saved to {filepath}")
    
    @classmethod
    def load(cls, filepath: str) -> "APIVectorStore":
        """Load a previously saved vector store and regenerate embeddings."""
        store = cls()
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        store.api_docs = data
        print(f"  📂 Loaded {len(data)} APIs from {filepath}")
        
        # Regenerate embeddings since they're stripped during save
        texts = [d.get("search_text", d.get("description", "")) for d in data]
        embeddings = store._embed_texts(texts)
        if embeddings:
            for i, emb in enumerate(embeddings):
                if emb:
                    store.api_docs[i]["embedding"] = emb
            valid_count = len([e for e in embeddings if e])
            if valid_count:
                print(f"  ✅ Regenerated embeddings for {valid_count} APIs")
        else:
            print(f"  ℹ️  Embeddings not available, using keyword-only search")
        
        return store


def build_vector_store(catalog_path: str, output_dir: str = None) -> APIVectorStore:
    """Build the vector store from an enriched catalog JSON file."""
    with open(catalog_path, "r", encoding="utf-8") as f:
        catalog = json.load(f)
    
    store = APIVectorStore(persist_dir=output_dir)
    store.add_apis(catalog)
    
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        store.save(os.path.join(output_dir, "api_vector_store.json"))
    
    return store


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent
    catalog_path = base_dir / "api_catalog_enriched.json"
    
    if not catalog_path.exists():
        # Try the unenriched catalog
        catalog_path = base_dir / "api_catalog.json"
        if not catalog_path.exists():
            print("❌ No catalog found. Run api_catalog_generator.py first.")
            exit(1)
    
    print(f"📂 Loading catalog from {catalog_path}")
    store = build_vector_store(str(catalog_path), output_dir=str(base_dir))
    
    # Test search
    print("\n🔍 Testing semantic search...")
    test_queries = [
        "Who has not paid yet?",
        "Show me inactive customers",
        "How many active subscriptions?",
        "Revenue this month",
        "Pending complaints",
        "Add a new customer",
    ]
    
    for query in test_queries:
        results = store.search(query, top_k=3)
        print(f"\n📝 Query: '{query}'")
        for r in results:
            print(f"   [{r['score']:.3f}] {r['endpoint']} ({r['category']})")
            print(f"        {r['description'][:80]}")