# BillerQ AI Assistant

AI-powered natural language interface to your MySQL business database.
Built with FastAPI + Gemini API + MySQL.

---

## Project Structure

```
billerq/
├── config.py          ← Edit this with your DB + Gemini credentials
├── main.py            ← FastAPI app (routes)
├── ai.py              ← Gemini API integration (NL → SQL)
├── database.py        ← MySQL connector + query runner
├── templates/
│   └── index.html     ← Chat frontend
├── static/            ← (place any CSS/JS assets here)
├── requirements.txt
└── run.bat            ← Double-click to start on Windows
```

---

## Setup (Windows)

### Step 1 — Install Python
Make sure Python 3.10+ is installed.
Download: https://www.python.org/downloads/

### Step 2 — Edit config.py
Open `config.py` and fill in:

```python
DB_HOST     = "localhost"
DB_PORT     = 3306
DB_USER     = "root"
DB_PASSWORD = "your_mysql_password"
DB_NAME     = "your_database_name"

GEMINI_API_KEY = "your_gemini_api_key_here"
```

Get a free Gemini API key at: https://aistudio.google.com/app/apikey

### Step 3 — Run the project
Double-click `run.bat`
OR open a terminal in this folder and run:

```
pip install -r requirements.txt
uvicorn main:app --reload
```

### Step 4 — Open the chatbot
Go to: http://localhost:8000

---

## How It Works

1. You type a question like "Show premium customers"
2. The backend sends your question + your DB schema to Gemini
3. Gemini returns a safe SELECT query
4. FastAPI executes it on MySQL
5. Gemini summarises the results in plain English
6. The chatbot displays the SQL, results table, and summary

---

## Example Queries

- Show premium customers
- Recent payments
- Latest invoices
- Active subscriptions
- Overdue invoices
- Top 5 orders by amount
- How many customers signed up this month?
- Which customer has the highest outstanding balance?

---

## Security

- Only SELECT queries are allowed — no INSERT, UPDATE, DELETE, DROP
- Gemini is given your schema (not data), so your data is safe
- No raw user SQL is ever executed directly

---

## API Endpoints

| Method | Path      | Description                        |
|--------|-----------|------------------------------------|
| GET    | /         | Chat UI                            |
| POST   | /chat     | Send message, get SQL + results    |
| GET    | /health   | Check DB connection status         |
