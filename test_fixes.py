from database import get_connection, run_query
from ai import natural_language_to_sql

conn = get_connection()
cur = conn.cursor()

cur.execute(
    "SELECT company_id, COUNT(*) FROM orders GROUP BY company_id ORDER BY COUNT(*) DESC LIMIT 3"
)
print("Top companies by orders:", cur.fetchall())

cur.execute(
    "SELECT company_id, COUNT(*) FROM customers WHERE status = 'inactive' "
    "GROUP BY company_id ORDER BY COUNT(*) DESC LIMIT 3"
)
print("Top companies by inactive customers:", cur.fetchall())

cur.close()
conn.close()

# Test with a company that has data
cid = 1
for q in ["Top 5 orders by amount", "Inactive customers", "Show all customers"]:
    r = natural_language_to_sql(q, company_id=cid)
    res = run_query(r["sql"])
    print(f"\n{q}: {res['row_count']} rows")
    print(r["sql"])
