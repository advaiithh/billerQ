import mysql.connector

conn = mysql.connector.connect(
    host="billerq.com",
    user=" srv1145.hstgr.io",
    password="4U;iQ:3PG^v",
    database="u167254999_BqCustomerAi"
)

cursor = conn.cursor()

cursor.execute("SELECT id, name FROM companies")

companies = cursor.fetchall()

for company_id, company_name in companies:
    print(f"{company_id}: {company_name}")

cursor.close()
conn.close()