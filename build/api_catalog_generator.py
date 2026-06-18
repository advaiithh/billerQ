#!/usr/bin/env python3
"""
Step 1: Auto-Generate API Catalog from CommonUrl.jsx

Extracts all BillerQ API endpoints from CommonUrl.jsx and creates
a structured JSON catalog with intent, description, and keywords fields
to be filled by an LLM later.
"""

import json
import re
import os
from pathlib import Path


def extract_endpoints_from_jsx(filepath: str) -> list[dict]:
    """Parse CommonUrl.jsx and extract all API endpoint definitions."""
    with open(filepath, "r", encoding="utf-8-sig") as f:
        content = f.read()

    endpoints = set()

    # Pattern 1: export const X = "/admin/something" or "/admin/somethingRole"
    # Match single-quoted or double-quoted strings
    patterns = [
        r'"(/[^"]+)"',   # double-quoted
        r"'(/[^']+)'",    # single-quoted
    ]

    for pat in patterns:
        for match in re.finditer(pat, content):
            path = match.group(1)
            # Filter for admin API endpoints (skip non-api URLs)
            if path.startswith("/admin/") or path.startswith("/"):
                # Skip generic non-api paths
                if any(skip in path for skip in ["/static/", "/templates/"]):
                    continue
                # Only keep meaningful API-like paths
                if path.count("/") >= 2 or path.startswith("/admin/"):
                    # Normalize: strip trailing whitespace
                    path = path.strip()
                    if path and len(path) > 3:
                        endpoints.add(path)

    # Pattern 2: Look for role-suffixed endpoints (without /admin/ prefix)
    # These are stored as variables ending in "Role" but resolved at runtime
    for match in re.finditer(r'export\s+const\s+\w+Role\s*=\s*["\']([^"\']+)["\']', content):
        path = match.group(1).strip()
        if path and path.startswith("/") and len(path) > 3:
            # Add with /admin/ prefix for the real endpoint
            if not path.startswith("/admin/"):
                endpoints.add(f"/admin{path}")

    # Build catalog
    catalog = []
    for endpoint in sorted(endpoints, key=lambda x: (x.count("/"), x)):
        catalog.append({
            "endpoint": endpoint,
            "category": None,
            "description": None,
            "keywords": [],
        })

    return catalog


def extract_all_roles(filepath: str) -> list[str]:
    """Extract role-based endpoint paths."""
    with open(filepath, "r", encoding="utf-8-sig") as f:
        content = f.read()

    roles = set()
    pattern = r"export\s+const\s+\w+Role\s*=\s*['\"](\/[^'\"]+)['\"]"
    for match in re.finditer(pattern, content):
        path = match.group(1).strip()
        if path and path.startswith("/") and len(path) > 3:
            roles.add(path)
    return sorted(roles)


def write_catalog(catalog: list[dict], output_path: str):
    """Write the catalog to a JSON file."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
    print(f"✅ Catalog written to {output_path}")
    print(f"   Total endpoints: {len(catalog)}")


def write_api_list_txt(catalog: list[dict], output_path: str):
    """Write just the endpoint list as a simple text file."""
    with open(output_path, "w", encoding="utf-8") as f:
        for entry in catalog:
            f.write(entry["endpoint"] + "\n")
    print(f"✅ API list written to {output_path}")


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent
    common_url_jsx = base_dir / "CommonUrl.jsx"

    if not common_url_jsx.exists():
        print(f"❌ CommonUrl.jsx not found at {common_url_jsx}")
        print("   Searching build/ directory...")
        alt_path = base_dir.parent / "build" / "CommonUrl.jsx"
        if alt_path.exists():
            common_url_jsx = alt_path
        else:
            raise FileNotFoundError(f"Cannot find CommonUrl.jsx")

    print(f"📂 Parsing {common_url_jsx}...")

    catalog = extract_endpoints_from_jsx(str(common_url_jsx))
    roles = extract_all_roles(str(common_url_jsx))

    # Remove duplicates (roles version without /admin/ prefix)
    final_catalog = []
    seen = set()
    for entry in catalog:
        ep = entry["endpoint"]
        # Normalize: if there's both /admin/foo and /foo, keep /admin/foo
        if ep not in seen:
            # Check if there's an /admin version of a non-admin path
            admin_version = f"/admin{ep}" if not ep.startswith("/admin/") else None
            if admin_version and admin_version in seen:
                continue  # Skip, the /admin/ version is already in the catalog
            seen.add(ep)
            final_catalog.append(entry)

    deduped = []
    seen2 = set()
    for entry in final_catalog:
        # Deduplicate by endpoint
        key = entry["endpoint"].rstrip("/")
        if key not in seen2:
            seen2.add(key)
            deduped.append(entry)

    print(f"📊 Raw endpoints extracted: {len(catalog)}")
    print(f"📊 After deduplication: {len(deduped)}")
    print(f"📊 Role-based endpoints found: {len(roles)}")

    write_catalog(deduped, str(base_dir / "api_catalog.json"))
    write_api_list_txt(deduped, str(base_dir / "api_list.txt"))

    # Print sample
    print("\n📋 Sample entries:")
    for entry in deduped[:5]:
        print(f"   {entry['endpoint']}")
    print(f"   ... and {len(deduped) - 5} more")