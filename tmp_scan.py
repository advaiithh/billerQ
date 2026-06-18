import re, json

# ── Scan React main bundle ───────────────────────────────────────────────────
with open(r'C:\Users\Lenovo\Documents\billerq\build\static\js\main.c2891d24.js',
          'r', encoding='utf-8') as f:
    bundle = f.read()

# All quoted strings that look like API paths
paths = set(re.findall(r'"(/[a-zA-Z0-9/_-]{4,60})"', bundle))
api_paths = sorted(p for p in paths if any(k in p for k in
    ['admin', 'api', 'customer', 'payment', 'invoice',
     'complaint', 'subscription', 'report', 'billing',
     'dashboard', 'collection', 'get-', 'set-', 'create',
     'update', 'delete', 'search', 'list']))

print("=== API-like paths in React bundle ===")
for p in api_paths:
    print(p)

# All URL strings
urls = set(re.findall(r'https?://[a-zA-Z0-9._/:-]{5,80}', bundle))
billerq_urls = sorted(u for u in urls if 'billerq' in u.lower())
print("\n=== BillerQ base URLs in bundle ===")
for u in billerq_urls:
    print(u)

# ── Scan billerq-copilot.js ──────────────────────────────────────────────────
with open(r'C:\Users\Lenovo\Documents\billerq\build\billerq-copilot.js',
          'r', encoding='utf-8') as f:
    copilot = f.read()

copilot_paths = set(re.findall(r'"(/[a-zA-Z0-9/_-]{4,60})"', copilot))
copilot_api = sorted(p for p in copilot_paths if any(k in p for k in
    ['admin', 'api', 'chat', 'search', 'session', 'health',
     'metric', 'page', 'workflow', 'analytic']))
print("\n=== Copilot widget API paths ===")
for p in copilot_api:
    print(p)

# localhost URLs
localhost_urls = set(re.findall(r'http://localhost:\d+[^\s"\']{0,50}', copilot))
print("\n=== Localhost URLs in copilot widget ===")
for u in sorted(localhost_urls):
    print(u)

# ── Scan all chunk JS files ──────────────────────────────────────────────────
import os, glob
chunk_dir = r'C:\Users\Lenovo\Documents\billerq\build\static\js'
all_paths = set()
for fp in glob.glob(os.path.join(chunk_dir, '*.js')):
    with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
        c = f.read()
    found = re.findall(r'"(/[a-zA-Z0-9/_-]{6,80})"', c)
    for p in found:
        if any(k in p for k in ['get-', 'admin/', 'api/', 'customer', 'payment',
                                  'invoice', 'complaint', 'dashboard', 'report',
                                  'billing', 'collection', 'subscription']):
            all_paths.add(p)

print("\n=== All API-like paths across ALL chunk files ===")
for p in sorted(all_paths):
    print(p)
